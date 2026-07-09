"""Route / Dispatch core blueprint.

FT6 blueprint split: relocates Flask routing/glue code out of app.py for
the route-building, assignment, dispatch, and completion lifecycle. This
logic has no existing eoms_modules service file - it's the same pure
helper functions (build_route_order, calculate_route_metrics, etc., all
already covered by test_core_business_logic.py) called directly, exactly
as they were inline in app.py. No behavior changed; verified line-by-line
against the original functions before removal from app.py.

/api/store-closeout/<store_id> intentionally stays in app.py for now (it's
a separate, already fully-tested closeout mechanism from
/api/dispatcher/closeout in routes/dispatcher_closeout.py); moving it is a
small future cleanup, not required for this extraction.
"""

import os
from datetime import datetime
from uuid import uuid4

import requests
from flask import Blueprint, jsonify, render_template, request, session

from app import (
    STORES_FILE,
    ROUTES_FILE,
    SETTINGS_FILE,
    HUBS,
    MAX_PAYLOAD,
    PIECES_PER_RACK,
    RATE_PER_PIECE,
    DRIVER_PAY_PER_PIECE,
    read_json,
    write_json,
    synchronized_data_write,
    filter_stores_for_user,
    filter_routes_for_user,
    active_map_stores,
    map_settings_payload,
    sms_status_payload,
    date_value,
    today_iso,
    geocode_address_azure,
    full_address_for_item,
    build_route_order,
    calculate_route_metrics,
    completion_summary_for_stores,
    move_pdf,
    users_payload,
    current_user,
    current_role,
    dispatch_required,
    audit,
    clean,
    num,
)
from eoms_modules.permission_service import permissions
from eoms_modules.recovery_center_service import delete_route_if_allowed

route_dispatch_bp = Blueprint("route_dispatch", __name__)


@route_dispatch_bp.route("/api/dispatch-map-debug")
def api_dispatch_map_debug():
    stores = read_json(STORES_FILE)
    return jsonify({
        "total_stores": len(stores),
        "unassigned": len([s for s in stores if s.get("status") == "Unassigned"]),
        "need_review": len([s for s in stores if s.get("status") == "Need Review"]),
        "assigned": len([s for s in stores if s.get("status") == "Assigned"]),
        "completed": len([s for s in stores if s.get("status") == "Completed"]),
        "map_eligible": [
            {
                "bol": s.get("bol"),
                "status": s.get("status"),
                "lat": s.get("lat"),
                "lng": s.get("lng"),
                "city": s.get("city"),
                "store_name": s.get("store_name"),
                "racks": s.get("expected_racks"),
                "address": s.get("address"),
                "full_address": s.get("full_address"),
                "geocode_status": s.get("geocode_status")
            }
            for s in stores if s.get("status") == "Unassigned"
        ]
    })


@route_dispatch_bp.route("/api/geocode-stores", methods=["POST"])
def api_geocode_stores():
    stores = read_json(STORES_FILE)
    updated = 0
    failed = 0
    failures = []

    for store in stores:
        address = store.get("address") or store.get("origin_address") or ""
        city = store.get("city") or store.get("origin_city") or ""
        state = store.get("state") or store.get("origin_state") or "TX"
        zip_code = store.get("zip") or store.get("origin_zip") or ""

        bol = store.get("bol") or ""
        origin = store.get("origin") or ""
        store_name = store.get("store_name") or ""
        full_address = full_address_for_item(address, city, state, zip_code)

        if not address or not city:
            failed += 1
            reason = "Missing address or city"
            store["lat"] = None
            store["lng"] = None
            store["full_address"] = full_address
            store["geocode_status"] = reason
            failures.append({"bol": bol, "origin": origin, "store": store_name, "address": full_address, "reason": reason})
            continue

        lat, lng, note = geocode_address_azure(full_address)

        if lat is not None and lng is not None:
            store["lat"] = lat
            store["lng"] = lng
            store["full_address"] = full_address
            store["geocode_status"] = f"Azure Maps geocoded: {note}"
            updated += 1
        else:
            failed += 1
            store["lat"] = None
            store["lng"] = None
            store["full_address"] = full_address
            store["geocode_status"] = f"Failed: {note}"
            failures.append({"bol": bol, "origin": origin, "store": store_name, "address": full_address, "reason": note})

    write_json(STORES_FILE, stores)
    audit("Geocode Stores", {"updated": updated, "failed": failed, "failures": failures[:25]})

    return jsonify({"ok": True, "updated": updated, "failed": failed, "failures": failures[:50]})


@route_dispatch_bp.route("/dispatch-map")
@dispatch_required
def dispatch_map():
    stores = active_map_stores(filter_stores_for_user(read_json(STORES_FILE)))
    status_filter = clean(request.args.get("status"))
    if status_filter:
        stores = [s for s in stores if clean(s.get("status") or "Unassigned") == status_filter]
    settings_data = read_json(SETTINGS_FILE)
    maps_key = clean(settings_data.get("azure_maps_key"))
    return render_template(
        "dispatch_map.html", stores=stores, hubs=HUBS,
        max_payload=MAX_PAYLOAD, azure_maps_key=maps_key,
        map_settings=map_settings_payload(),
        sms_status=sms_status_payload(settings_data),
        can_view_financials=permissions.can_view_financials(current_user())
    )


@route_dispatch_bp.route("/route-builder")
def route_builder():
    routes = filter_routes_for_user(read_json(ROUTES_FILE))
    status_filter = clean(request.args.get("status"))
    if status_filter:
        routes = [r for r in routes if clean(r.get("status") or "Assigned") == status_filter]
    return render_template("route_builder.html", routes=routes)


@route_dispatch_bp.route("/api/dispatch-board-live")
def api_dispatch_board_live():
    stores = filter_stores_for_user(read_json(STORES_FILE))
    active_statuses = {"Need Review", "Unassigned", "Assigned", "Dispatched"}
    active = [s for s in stores if s.get("status", "Unassigned") in active_statuses]
    completed_today = [
        s for s in stores
        if s.get("status") == "Completed" and date_value(s.get("completed_at")) == today_iso()
    ]
    board_stores = active + completed_today
    racks = round(sum(num(s.get("expected_racks")) for s in active), 1)
    weight = round(sum(num(s.get("weight")) for s in active), 1)
    pieces = round(racks * PIECES_PER_RACK, 1)
    return jsonify({
        "ok": True,
        "stores": board_stores,
        "metrics": {
            "stores": len(active),
            "racks": racks,
            "pieces": pieces,
            "weight": weight,
            "revenue": round(pieces * RATE_PER_PIECE, 2),
            "driver_pay": round(pieces * DRIVER_PAY_PER_PIECE, 2),
            "max_payload": MAX_PAYLOAD,
            "remaining_capacity": round(MAX_PAYLOAD - weight, 1),
        }
    })


@route_dispatch_bp.route("/api/send-route-sms", methods=["POST"])
@dispatch_required
@synchronized_data_write(ROUTES_FILE)
def api_send_route_sms():
    data = request.get_json(force=True)
    route_id = data.get("route_id")
    routes = read_json(ROUTES_FILE)
    route = next((r for r in routes if r.get("id") == route_id or r.get("route_number") == route_id), None)
    if not route:
        return jsonify({"ok": False, "message": "Route not found."}), 404

    phone = clean(route.get("driver_phone"))
    if not phone and clean(route.get("driver")):
        driver_name = clean(route.get("driver"))
        for user in users_payload().get("users", []):
            names = {clean(user.get("username")), clean(user.get("display_name"))}
            if (user.get("role") or "").lower() == "driver" and driver_name in names:
                phone = clean(user.get("phone"))
                if phone:
                    route["driver_phone"] = phone
                break
    if not phone:
        return jsonify({"ok": False, "message": "Add the driver phone number first."})

    stops = route.get("stops", []) or []
    body_lines = [
        "Essayons BAX",
        "",
        f"You have {len(stops)} BOL{'s' if len(stops) != 1 else ''} assigned today.",
        "",
    ]

    for idx, stop in enumerate(stops, start=1):
        store_name = clean(stop.get("store_name") or stop.get("origin_name") or "Unknown Store")
        bol = clean(stop.get("bol"))
        body_lines.append(f"{idx}. {store_name}")
        if bol:
            body_lines.append(f"   BOL {bol}")
        body_lines.append("")

    body_lines.append("Please log into the EOMS Driver Portal to accept and complete your assignments.")
    body = "\n".join(body_lines).strip()

    telnyx_settings = read_json(SETTINGS_FILE)
    api_key = clean(os.environ.get("TELNYX_API_KEY")) or clean(telnyx_settings.get("telnyx_api_key"))
    from_number = clean(os.environ.get("TELNYX_FROM_NUMBER")) or clean(telnyx_settings.get("telnyx_from_number"))
    if not api_key or not from_number:
        return jsonify({"ok": False, "message": "Telnyx is not configured locally. Copy Message or set TELNYX_API_KEY and TELNYX_FROM_NUMBER.", "body": body})

    try:
        resp = requests.post(
            "https://api.telnyx.com/v2/messages",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"from": from_number, "to": phone, "text": body},
            timeout=15,
        )
        if resp.status_code >= 300:
            return jsonify({"ok": False, "message": f"Telnyx error {resp.status_code}: {resp.text[:180]}", "body": body})
        route["last_sms_sent_at"] = datetime.now().isoformat(timespec="seconds")
        write_json(ROUTES_FILE, routes)
        audit("Send Driver BOL SMS", {"route_id": route.get("id"), "bols": len(stops), "to": phone})
        return jsonify({"ok": True, "message": "Driver BOL SMS sent.", "body": body})
    except Exception as exc:
        return jsonify({"ok": False, "message": "SMS send failed: " + str(exc)[:180], "body": body})


@route_dispatch_bp.route("/api/routes")
def api_routes():
    routes = read_json(ROUTES_FILE)
    return jsonify({"ok": True, "routes": routes})


@route_dispatch_bp.route("/api/route/<route_id>")
def api_route_detail(route_id):
    routes = read_json(ROUTES_FILE)
    for route in routes:
        if route.get("id") == route_id or route.get("route_number") == route_id:
            if current_role() == "Driver":
                user = current_user() or {}
                driver_names = {clean(user.get("username")), clean(user.get("display_name"))}
                if clean(route.get("driver")) not in driver_names:
                    return jsonify({"ok": False, "message": "Route not assigned to you."}), 403
            return jsonify({"ok": True, "route": route})
    return jsonify({"ok": False, "message": "Route not found."}), 404


@route_dispatch_bp.route("/api/preview-route", methods=["POST"])
@dispatch_required
def api_preview_route():
    data = request.get_json(force=True)
    store_ids = data.get("store_ids", [])
    mode = data.get("mode", "optimized")
    requested_hub = clean(data.get("hub"))

    allowed_ids = {s.get("id") for s in filter_stores_for_user(read_json(STORES_FILE))}
    if any(store_id not in allowed_ids for store_id in store_ids):
        return jsonify({"ok": False, "message": "One or more stores are outside your assigned cities."}), 403

    hub_name, ordered, metrics = build_route_order(store_ids, mode, requested_hub)

    if not ordered:
        return jsonify({"ok": False, "message": "No unassigned stores selected."})
    if not hub_name:
        return jsonify({"ok": False, "message": (metrics or {}).get("message") or "Hub Required", "hub_required": True})

    return jsonify({
        "ok": True,
        "hub": hub_name,
        "mode": mode,
        "stores": ordered,
        "metrics": metrics
    })


@route_dispatch_bp.route("/api/assign-route", methods=["POST"])
@dispatch_required
@synchronized_data_write(STORES_FILE, ROUTES_FILE)
def api_assign_route():
    data = request.get_json(force=True)
    driver = clean(data.get("driver"))
    driver_phone = clean(data.get("driver_phone"))
    store_ids = data.get("store_ids", [])
    mode = data.get("mode", "optimized")
    requested_hub = clean(data.get("hub"))

    allowed_ids = {s.get("id") for s in filter_stores_for_user(read_json(STORES_FILE))}
    if any(store_id not in allowed_ids for store_id in store_ids):
        return jsonify({"ok": False, "message": "One or more stores are outside your assigned cities."}), 403

    hub_name, ordered, metrics = build_route_order(store_ids, mode, requested_hub)

    if not ordered:
        return jsonify({"ok": False, "message": "No unassigned stores selected."})
    if not hub_name:
        return jsonify({"ok": False, "message": (metrics or {}).get("message") or "Hub Required", "hub_required": True})

    if metrics["status"] == "OVER LIMIT":
        return jsonify({"ok": False, "message": "Route is over 25,001 lbs. Remove stores before assigning."})

    assigned_ids = [s["id"] for s in ordered]
    route_id = str(uuid4())
    stores = read_json(STORES_FILE)

    for store in stores:
        if store["id"] in assigned_ids:
            store["status"] = "Assigned"
            store["assigned_driver"] = driver
            store["driver_phone"] = driver_phone
            store["route_id"] = route_id
            store["driver_status"] = "Pending"
            store["driver_work_status"] = "Waiting"
            store["receiving_status"] = ""
            store["dispatcher_closeout_status"] = ""
            if store.get("pdf_path"):
                store["pdf_path"] = move_pdf(store["pdf_path"], "Assigned")

    assigned_store_lookup = {
        clean(store.get("id")): store
        for store in stores
        if clean(store.get("id")) in set(assigned_ids)
    }
    ordered = [dict(assigned_store_lookup.get(clean(store.get("id")), store)) for store in ordered]

    routes = read_json(ROUTES_FILE)
    route_number = f"RT-{len(routes) + 1:05d}"

    route = {
        "id": route_id,
        "route_number": route_number,
        "driver": driver,
        "driver_phone": driver_phone,
        "hub": hub_name,
        "mode": mode,
        "mode_label": "Selection Order" if mode == "selection" else "Optimized Nearest Stop",
        "store_ids": assigned_ids,
        "stops": ordered,
        "metrics": metrics,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "Assigned",
        "driver_status": "Pending",
    }

    routes.append(route)
    write_json(STORES_FILE, stores)
    write_json(ROUTES_FILE, routes)
    audit("Assign Route", {"route_number": route_number, "driver": driver, "stores": len(ordered), "mode": mode})

    return jsonify({"ok": True, "route": route, "assigned": ordered, "metrics": metrics})


@route_dispatch_bp.route("/api/dispatch-route", methods=["POST"])
@dispatch_required
@synchronized_data_write(STORES_FILE, ROUTES_FILE)
def api_dispatch_route():
    data = request.get_json(force=True)
    route_id = clean(data.get("route_id"))
    routes = read_json(ROUTES_FILE)
    visible_route_ids = {
        clean(r.get("id")) for r in filter_routes_for_user(routes)
    } | {
        clean(r.get("route_number")) for r in filter_routes_for_user(routes)
    }
    if route_id not in visible_route_ids:
        return jsonify({"ok": False, "message": "Route not found or outside your assigned cities."}), 404

    route = next((r for r in routes if clean(r.get("id")) == route_id or clean(r.get("route_number")) == route_id), None)
    if not route:
        return jsonify({"ok": False, "message": "Route not found."}), 404
    if not clean(route.get("driver")):
        return jsonify({"ok": False, "message": "Assign a driver before dispatch."})
    if num((route.get("metrics") or {}).get("weight")) > MAX_PAYLOAD:
        return jsonify({"ok": False, "message": "Route exceeds the 25,001 lb payload limit."})

    route["status"] = "Dispatched"
    route["dispatched_at"] = datetime.now().isoformat(timespec="seconds")
    route_store_ids = set(route.get("store_ids", []))
    stores = read_json(STORES_FILE)
    for store in stores:
        if store.get("id") in route_store_ids:
            if clean(store.get("status")).lower() not in {"recovered", "exception", "completed"}:
                store["status"] = "Assigned"
                store["driver_work_status"] = clean(store.get("driver_work_status")) or "Waiting"
            store["dispatched_at"] = route["dispatched_at"]
            if store.get("pdf_path"):
                store["pdf_path"] = move_pdf(store["pdf_path"], "Dispatched")

    write_json(ROUTES_FILE, routes)
    write_json(STORES_FILE, stores)
    audit("Dispatch Route", {"route_id": route.get("id"), "route_number": route.get("route_number"), "driver": route.get("driver")})
    return jsonify({"ok": True, "route": route, "message": "Route dispatched."})


@route_dispatch_bp.route("/api/update-route-driver", methods=["POST"])
@synchronized_data_write(STORES_FILE, ROUTES_FILE)
def api_update_route_driver():
    data = request.get_json(force=True)
    route_id = data.get("route_id")
    driver = clean(data.get("driver"))
    driver_phone = clean(data.get("driver_phone"))
    truck = clean(data.get("truck"))
    helper = clean(data.get("helper"))
    truck_status = clean(data.get("truck_status"))

    routes = read_json(ROUTES_FILE)
    stores = read_json(STORES_FILE)

    updated = None
    for route in routes:
        if route.get("id") == route_id or route.get("route_number") == route_id:
            route["driver"] = driver
            route["driver_phone"] = driver_phone
            route["truck"] = truck
            route["helper"] = helper
            route["truck_status"] = truck_status
            route["updated_at"] = datetime.now().isoformat(timespec="seconds")
            updated = route

            route_store_ids = set(route.get("store_ids", []))
            for store in stores:
                if store.get("id") in route_store_ids:
                    store["assigned_driver"] = driver
                    store["driver_phone"] = driver_phone
                    store["truck"] = truck
                    store["helper"] = helper
                    store["truck_status"] = truck_status
                    store["status"] = "Assigned"
                    if store.get("pdf_path"):
                        store["pdf_path"] = move_pdf(store["pdf_path"], "Assigned")
            break

    if not updated:
        return jsonify({"ok": False, "message": "Route not found."})

    write_json(ROUTES_FILE, routes)
    write_json(STORES_FILE, stores)
    audit("Update Route Driver", {"route_id": route_id, "driver": driver, "driver_phone": driver_phone, "truck": truck, "helper": helper, "truck_status": truck_status})

    return jsonify({"ok": True, "route": updated})


@route_dispatch_bp.route("/api/complete-route", methods=["POST"])
@synchronized_data_write(STORES_FILE, ROUTES_FILE)
def api_complete_route():
    data = request.get_json(force=True)
    route_id = data.get("route_id")

    routes = read_json(ROUTES_FILE)
    stores = read_json(STORES_FILE)

    route = None
    for r in routes:
        if r.get("id") == route_id or r.get("route_number") == route_id:
            r["status"] = "Completed"
            r["completed_at"] = datetime.now().isoformat(timespec="seconds")
            route = r
            break

    if not route:
        return jsonify({"ok": False, "message": "Route not found."})

    route_store_ids = set(route.get("store_ids", []))
    route_stores = [s for s in stores if s.get("id") in route_store_ids]
    missing_closeout = [
        s for s in route_stores
        if clean(s.get("dispatcher_closeout_status")) != "Closed"
    ]

    if missing_closeout:
        return jsonify({
            "ok": False,
            "code": "CLOSEOUT_REQUIRED",
            "message": f"{len(missing_closeout)} stop(s) require warehouse verification and dispatcher close-out before route completion.",
            "missing": [{"bol": s.get("bol"), "store": s.get("store_name"), "city": s.get("city")} for s in missing_closeout[:10]],
        })

    for store in stores:
        if store.get("id") in route_store_ids:
            if clean(store.get("dispatcher_closeout_status")) != "Closed":
                continue
            store["status"] = "Completed"
            store["completed_at"] = route.get("completed_at")
            if clean(store.get("rms_status")) in {"Missing from RMS", "Closed in RMS"}:
                store["closed_source"] = "Both"
            else:
                store["closed_source"] = "EOMS"
            if store.get("pdf_path"):
                store["pdf_path"] = move_pdf(store["pdf_path"], "Completed")

    route["completion_summary"] = completion_summary_for_stores([s for s in stores if s.get("id") in route_store_ids])

    write_json(ROUTES_FILE, routes)
    write_json(STORES_FILE, stores)
    audit("Complete Route", {"route_id": route_id, "route_number": route.get("route_number")})

    return jsonify({"ok": True, "route": route})


@route_dispatch_bp.route("/route-view/<route_id>")
def route_view(route_id):
    routes = read_json(ROUTES_FILE)
    route = None
    for r in routes:
        if r.get("id") == route_id or r.get("route_number") == route_id:
            route = r
            break

    if not route:
        return "Route not found", 404

    if current_role() == "Driver":
        user = current_user() or {}
        driver_names = {clean(user.get("username")), clean(user.get("display_name"))}
        if clean(route.get("driver")) not in driver_names:
            return render_template("access_denied.html"), 403

    return render_template("route_view.html", route=route)


@route_dispatch_bp.route("/route-print/<route_id>")
def route_print(route_id):
    routes = read_json(ROUTES_FILE)
    route = None
    for r in routes:
        if r.get("id") == route_id or r.get("route_number") == route_id:
            route = r
            break

    if not route:
        return "Route not found", 404

    if current_role() == "Driver":
        user = current_user() or {}
        driver_names = {clean(user.get("username")), clean(user.get("display_name"))}
        if clean(route.get("driver")) not in driver_names:
            return render_template("access_denied.html"), 403

    return render_template("route_print.html", route=route)


@route_dispatch_bp.route("/api/unassign-route", methods=["POST"])
@dispatch_required
@synchronized_data_write(STORES_FILE, ROUTES_FILE)
def api_unassign_route():
    data = request.get_json(force=True)
    route_id = data.get("route_id")

    routes = read_json(ROUTES_FILE)
    stores = read_json(STORES_FILE)

    target_route = None
    remaining_routes = []

    for route in routes:
        if route.get("id") == route_id or route.get("route_number") == route_id:
            target_route = route
        else:
            remaining_routes.append(route)

    if not target_route:
        return jsonify({"ok": False, "message": "Route not found."})

    route_store_ids = set(target_route.get("store_ids", []))

    restored = 0
    for store in stores:
        if store.get("id") in route_store_ids:
            store["status"] = "Unassigned"
            store["assigned_driver"] = ""
            store["driver_phone"] = ""
            store["truck"] = ""
            store["helper"] = ""
            store["truck_status"] = ""
            store["route_id"] = ""
            store["driver_status"] = ""
            store["driver_work_status"] = ""
            store["receiving_status"] = ""
            store["dispatcher_closeout_status"] = ""
            if store.get("pdf_path"):
                store["pdf_path"] = move_pdf(store["pdf_path"], "Imported")
            restored += 1

    write_json(STORES_FILE, stores)
    write_json(ROUTES_FILE, remaining_routes)
    audit("Unassign Entire Route", {"route_id": route_id, "restored": restored})

    return jsonify({"ok": True, "message": f"Route unassigned. {restored} stores returned to Dispatch Map."})


@route_dispatch_bp.route("/api/delete-route", methods=["POST"])
@dispatch_required
@synchronized_data_write(STORES_FILE, ROUTES_FILE)
def api_delete_route():
    data = request.get_json(force=True) or {}
    route_id = clean(data.get("route_id"))

    routes = read_json(ROUTES_FILE)
    stores = read_json(STORES_FILE)

    try:
        result = delete_route_if_allowed(routes, stores, route_id)
    except LookupError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    write_json(STORES_FILE, stores)
    write_json(ROUTES_FILE, routes)
    audit("Delete Recovery Route", {
        "route_id": result.get("route_id"),
        "route_number": result.get("route_number"),
        "cleared_stores": len(result.get("cleared_stores") or []),
    })

    return jsonify({
        "ok": True,
        "message": "Route deleted.",
        "route_id": result.get("route_id"),
        "cleared_stores": result.get("cleared_stores") or [],
    })


@route_dispatch_bp.route("/api/store-status", methods=["POST"])
@synchronized_data_write(STORES_FILE)
def api_store_status():
    data = request.get_json(force=True)
    store_id = data.get("store_id")
    new_status = clean(data.get("status"))

    allowed = {"Need Review", "Unassigned", "Assigned", "Dispatched", "Recovered", "Exception", "Completed"}
    if new_status not in allowed:
        return jsonify({"ok": False, "message": "Invalid status."})

    stores = read_json(STORES_FILE)
    updated = None

    for store in stores:
        if store.get("id") == store_id:
            store["status"] = new_status
            store["updated_at"] = datetime.now().isoformat(timespec="seconds")

            if new_status == "Unassigned":
                store["assigned_driver"] = ""
                if store.get("pdf_path"):
                    store["pdf_path"] = move_pdf(store["pdf_path"], "Imported")
            elif new_status == "Completed":
                if clean(store.get("rms_status")) in {"Missing from RMS", "Closed in RMS"}:
                    store["closed_source"] = "Both"
                else:
                    store["closed_source"] = "EOMS"
                if store.get("pdf_path"):
                    store["pdf_path"] = move_pdf(store["pdf_path"], "Completed")
            elif new_status == "Assigned":
                if store.get("pdf_path"):
                    store["pdf_path"] = move_pdf(store["pdf_path"], "Assigned")

            updated = store
            break

    if not updated:
        return jsonify({"ok": False, "message": "Store not found."})

    write_json(STORES_FILE, stores)
    audit("Update Store Status", {"store_id": store_id, "status": new_status})

    return jsonify({"ok": True, "store": updated})


@route_dispatch_bp.route("/api/unassign-store", methods=["POST"])
@synchronized_data_write(STORES_FILE, ROUTES_FILE)
def api_unassign_store():
    data = request.get_json(force=True)
    store_id = data.get("store_id")
    stores = read_json(STORES_FILE)
    restored = None
    for store in stores:
        if store.get("id") == store_id:
            store["status"] = "Unassigned"
            store["assigned_driver"] = ""
            store["driver_phone"] = ""
            store["truck"] = ""
            store["helper"] = ""
            store["truck_status"] = ""
            store["route_id"] = ""
            store["driver_status"] = ""
            store["driver_work_status"] = ""
            store["receiving_status"] = ""
            store["dispatcher_closeout_status"] = ""
            if store.get("pdf_path"):
                store["pdf_path"] = move_pdf(store["pdf_path"], "Imported")
            restored = store
            break

    routes = read_json(ROUTES_FILE)
    cleaned_routes = []
    for route in routes:
        route["store_ids"] = [sid for sid in route.get("store_ids", []) if sid != store_id]
        route["stops"] = [s for s in route.get("stops", []) if s.get("id") != store_id]
        if route.get("stops"):
            route["metrics"] = calculate_route_metrics(route["stops"], route.get("hub") or "San Antonio")
            cleaned_routes.append(route)

    write_json(STORES_FILE, stores)
    write_json(ROUTES_FILE, cleaned_routes)
    audit("Unassign Store", {"store_id": store_id})
    return jsonify({"ok": True, "store": restored})
