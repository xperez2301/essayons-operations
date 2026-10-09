"""Driver Portal blueprint.

FT6 step 1 of the app.py blueprint split: these six routes were previously
thin wrappers living directly in app.py, all delegating the actual business
logic to eoms_modules.driver_center_service (unchanged). This file only
relocates the Flask routing/glue code; no business logic changed.

Shared globals (STORES_FILE, ROUTES_FILE, read_json/write_json,
synchronized_data_write, session helpers, audit) are imported from app at
module load time. app.py imports this blueprint only after all of those
names are already defined, so this import is safe despite the circular
app <-> routes.driver_portal relationship.
"""

from pathlib import Path

from flask import abort, send_file, make_response, Blueprint, jsonify, render_template, request, session

from app import (
    STORES_FILE,
    ROUTES_FILE,
    read_json,
    write_json,
    synchronized_data_write,
    clean,
    current_role,
    current_user,
    audit,
)
from eoms_modules.driver_center_service import (
    accept_driver_route,
    advance_next_driver_stop,
    build_driver_workspace,
    complete_driver_stop,
    decline_driver_route,
    save_driver_exception,
    save_driver_stop_counts,
    update_route_recovery_progress,
)

driver_portal_bp = Blueprint("driver_portal", __name__)


def _current_driver_names():
    if current_role() == "Driver":
        user = current_user() or {}
        return [user.get("username"), user.get("display_name")]
    return []


@driver_portal_bp.route("/driver")
def driver_portal():
    stores = read_json(STORES_FILE)
    routes = read_json(ROUTES_FILE)
    names = {clean(name) for name in _current_driver_names() if clean(name)}
    if current_role() == "Driver" and not names:
        abort(403)
    visible_routes = [route for route in routes if not names or clean(route.get("driver")) in names]
    route_id = request.args.get("route_id")
    if route_id and not any(clean(route.get("id")) == route_id for route in visible_routes):
        abort(404)
    selected_routes = [route for route in visible_routes if clean(route.get("id")) == route_id] if route_id else visible_routes
    workspace = build_driver_workspace(
        routes=selected_routes,
        stores=stores,
        driver_names=_current_driver_names(),
    )
    all_work = build_driver_workspace(routes=visible_routes, stores=stores, driver_names=names)
    workspace["available_routes"] = all_work["routes"]
    from eoms_modules.driver_stop_selection import service_history
    for stop in workspace["stops"]:
        stop["service_history"] = service_history(stop, stores)
    if workspace.get("selected_stop_detail") and workspace.get("selected_stop"):
        workspace["selected_stop_detail"]["service_history"] = service_history(workspace["selected_stop"], stores)
    if not session.get("driver_stop_csrf"):
        import secrets
        session["driver_stop_csrf"] = secrets.token_urlsafe(32)
    response = make_response(render_template("driver_center.html", workspace=workspace))
    response.headers["Cache-Control"] = "no-store"
    return response


@driver_portal_bp.route("/driver/bol/<store_id>")
def driver_bol(store_id):
    from app import BOL_DIR, render_saved_bol
    names = {clean(name) for name in _current_driver_names() if clean(name)}
    if current_role() == "Driver" and not names:
        abort(403)
    routes = read_json(ROUTES_FILE)
    allowed = any(
        (not names or clean(route.get("driver")) in names)
        and store_id in (route.get("store_ids") or [])
        for route in routes
    )
    if not allowed:
        abort(404)
    record = next((row for row in read_json(STORES_FILE) if row.get("id") == store_id), None)
    if not record:
        abort(404)
    path = Path(record.get("pdf_path") or record.get("printable_path") or "")
    if not path.is_file() or not path.resolve().is_relative_to(Path(BOL_DIR).resolve()):
        abort(404)
    if path.suffix.lower() == ".pdf":
        return send_file(path, mimetype="application/pdf", as_attachment=False)
    if path.suffix.lower() != ".html":
        abort(404)
    return render_saved_bol(record, path, auto_print=False)


@driver_portal_bp.route("/api/driver/accept-route", methods=["POST"])
@synchronized_data_write(STORES_FILE, ROUTES_FILE)
def api_driver_accept_route():
    data = request.get_json(force=True) or {}
    stores = read_json(STORES_FILE)
    routes = read_json(ROUTES_FILE)
    driver_names = _current_driver_names()

    try:
        route, updated_stores = accept_driver_route(
            routes,
            stores,
            data.get("route_id"),
            driver_names=driver_names,
            accepted_by=session.get("username", "system"),
        )
    except PermissionError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 403
    except LookupError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 404

    write_json(STORES_FILE, stores)
    write_json(ROUTES_FILE, routes)
    audit("Driver Route Accepted", {
        "route_id": route.get("id"),
        "route_number": route.get("route_number"),
        "stores": len(updated_stores),
    })
    return jsonify({"ok": True, "route": route, "updated_stores": len(updated_stores)})


@driver_portal_bp.route("/api/driver/decline-route", methods=["POST"])
@synchronized_data_write(STORES_FILE, ROUTES_FILE)
def api_driver_decline_route():
    data = request.get_json(force=True) or {}
    stores = read_json(STORES_FILE)
    routes = read_json(ROUTES_FILE)
    driver_names = _current_driver_names()

    try:
        route, restored_stores = decline_driver_route(
            routes,
            stores,
            data.get("route_id"),
            reason=data.get("reason"),
            driver_names=driver_names,
            declined_by=session.get("username", "system"),
        )
    except PermissionError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 403
    except LookupError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 404

    write_json(STORES_FILE, stores)
    write_json(ROUTES_FILE, routes)
    audit("Driver Route Declined", {
        "route_id": route.get("id"),
        "route_number": route.get("route_number"),
        "stores": len(restored_stores),
        "reason": clean(data.get("reason")),
    })
    return jsonify({"ok": True, "route": route, "restored_stores": len(restored_stores)})


@driver_portal_bp.route("/api/driver/save-counts", methods=["POST"])
@synchronized_data_write(STORES_FILE)
def api_driver_save_counts():
    data = request.get_json(force=True) or {}
    stores = read_json(STORES_FILE)
    driver_names = _current_driver_names()

    try:
        updated = save_driver_stop_counts(
            stores,
            data.get("store_id"),
            data,
            driver_names=driver_names,
            saved_by=session.get("username", "system"),
        )
    except PermissionError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 403
    except LookupError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    write_json(STORES_FILE, stores)
    routes = read_json(ROUTES_FILE)
    workspace = build_driver_workspace(
        routes=routes,
        stores=stores,
        driver_names=driver_names,
    )
    audit("Driver Count Save", {"store_id": updated.get("id"), "bol": updated.get("bol")})

    return jsonify({
        "ok": True,
        "store": updated,
        "summary": workspace.get("summary", {}),
        "component_totals": workspace.get("component_totals", {}),
    })


@driver_portal_bp.route("/api/driver/save-exception", methods=["POST"])
@synchronized_data_write(STORES_FILE)
def api_driver_save_exception():
    data = request.get_json(force=True) or {}
    stores = read_json(STORES_FILE)
    driver_names = _current_driver_names()

    try:
        updated = save_driver_exception(
            stores,
            data.get("store_id"),
            data,
            driver_names=driver_names,
            reported_by=session.get("username", "system"),
        )
    except PermissionError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 403
    except LookupError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    write_json(STORES_FILE, stores)
    routes = read_json(ROUTES_FILE)
    workspace = build_driver_workspace(
        routes=routes,
        stores=stores,
        driver_names=driver_names,
    )
    audit("Driver Exception Save", {
        "store_id": updated.get("id"),
        "bol": updated.get("bol"),
        "exception": updated.get("driver_exception_type"),
    })

    return jsonify({
        "ok": True,
        "store": updated,
        "summary": workspace.get("summary", {}),
        "component_totals": workspace.get("component_totals", {}),
    })


@driver_portal_bp.route("/api/driver/complete-stop", methods=["POST"])
@synchronized_data_write(STORES_FILE, ROUTES_FILE)
def api_driver_complete_stop():
    data = request.get_json(force=True) or {}
    stores = read_json(STORES_FILE)
    routes = read_json(ROUTES_FILE)
    driver_names = _current_driver_names()

    try:
        updated = complete_driver_stop(
            stores,
            data.get("store_id"),
            driver_names=driver_names,
            completed_by=session.get("username", "system"),
        )
        already_completed = bool(updated.pop("already_completed", False))
        updated_routes = update_route_recovery_progress(routes, stores, updated.get("id"))
        promoted = advance_next_driver_stop(routes, stores, updated.get("id"))
    except PermissionError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 403
    except LookupError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    write_json(STORES_FILE, stores)
    write_json(ROUTES_FILE, routes)
    workspace = build_driver_workspace(
        routes=routes,
        stores=stores,
        driver_names=driver_names,
    )
    audit("Driver Stop Recovered", {"store_id": updated.get("id"), "bol": updated.get("bol")})

    return jsonify({
        "ok": True,
        "already_completed": already_completed,
        "store": updated,
        "next_stop": promoted,
        "updated_routes": len(updated_routes),
        "summary": workspace.get("summary", {}),
        "component_totals": workspace.get("component_totals", {}),
    })


@driver_portal_bp.route("/api/driver/complete", methods=["POST"])
@synchronized_data_write(STORES_FILE, ROUTES_FILE)
def api_driver_complete():
    data = request.get_json(force=True) or {}
    stores = read_json(STORES_FILE)
    routes = read_json(ROUTES_FILE)
    driver_names = _current_driver_names()

    try:
        saved = save_driver_stop_counts(
            stores,
            data.get("store_id"),
            data,
            driver_names=driver_names,
            saved_by=session.get("username", "system"),
        )
        updated = complete_driver_stop(
            stores,
            saved.get("id"),
            driver_names=driver_names,
            completed_by=session.get("username", "system"),
        )
        already_completed = bool(updated.pop("already_completed", False))
        updated_routes = update_route_recovery_progress(routes, stores, updated.get("id"))
        promoted = advance_next_driver_stop(routes, stores, updated.get("id"))
    except PermissionError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 403
    except LookupError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    write_json(STORES_FILE, stores)
    write_json(ROUTES_FILE, routes)
    audit("Driver Complete For Receiving", {"store_id": updated.get("id"), "bol": updated.get("bol")})
    return jsonify({
        "ok": True,
        "already_completed": already_completed,
        "store": updated,
        "next_stop": promoted,
        "updated_routes": len(updated_routes),
    })


@driver_portal_bp.post("/api/driver/select-stop")
@synchronized_data_write(STORES_FILE, ROUTES_FILE)
def api_driver_select_stop():
    import secrets
    from eoms_modules.driver_stop_selection import select_driver_stop
    if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), session.get("driver_stop_csrf", "!")):
        return jsonify(ok=False, message="Refresh the driver portal and try again."), 403
    names = _current_driver_names()
    if current_role() == "Driver" and not any(clean(name) for name in names):
        abort(403)
    payload = request.get_json(silent=True) or {}
    stores = read_json(STORES_FILE)
    routes = read_json(ROUTES_FILE)
    try:
        chosen = select_driver_stop(routes, stores, payload.get("route_id"), payload.get("store_id"), names)
    except PermissionError as exc:
        return jsonify(ok=False, message=str(exc)), 403
    except LookupError as exc:
        return jsonify(ok=False, message=str(exc)), 404
    except ValueError as exc:
        return jsonify(ok=False, message=str(exc)), 400
    write_json(STORES_FILE, stores)
    write_json(ROUTES_FILE, routes)
    audit("Driver Selected Pickup", {"route_id": payload.get("route_id"), "store_id": chosen.get("id"), "driver": session.get("username")})
    return jsonify(ok=True)
