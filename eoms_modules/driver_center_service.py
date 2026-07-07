from copy import deepcopy
from datetime import datetime, timezone

from eoms_modules.recovery_center_service import (
    COMPONENT_NAMES,
    STORE_COMPONENT_FIELDS,
    calculate_estimated_weight,
    clean,
    empty_component_counts,
    is_completed_stop,
    normalize_quantity,
    status_class,
    summarize_recovery_workspace_from_records,
)


ACTIVE_DRIVER_STATUSES = {
    "assigned",
    "dispatched",
    "in progress",
    "accepted",
}

DRIVER_EXCEPTION_TYPES = (
    "No Pickup",
    "No Recovery",
    "Partial Recovery",
    "Store Closed",
    "Rack Missing",
    "Damaged Components",
    "Access Issue",
    "Safety Issue",
    "Other",
)

COMPONENT_ENTRY_LABELS = {
    '84" Corner Post': '84" Corner Posts',
    '40" DRB': '40" DRB',
    '48" DRB': '48" DRB',
    "Wood Shelf": "Wood Shelves",
}


def normalize_driver_names(driver_names=None):
    if driver_names is None:
        return set()

    if isinstance(driver_names, str):
        driver_names = [driver_names]

    return {
        clean(name)
        for name in driver_names
        if clean(name)
    }


def is_active_route(route_summary):
    statuses = [clean(route_summary.get("status")).lower()]
    route = route_summary.get("route") or {}
    statuses.append(clean(route.get("status")).lower())

    for stop in route.get("recovery_stops") or []:
        statuses.append(clean(stop.get("status")).lower())

    statuses = [status for status in statuses if status]
    if not statuses:
        return True

    return any(status in ACTIVE_DRIVER_STATUSES for status in statuses)


def matches_driver(route_summary, driver_names):
    if not driver_names:
        return True

    return clean(route_summary.get("driver")) in driver_names


def active_stops_for_route(route):
    stops = []

    for stop in route.get("recovery_stops") or []:
        status = clean(stop.get("status")).lower()
        if status in ACTIVE_DRIVER_STATUSES:
            stops.append(deepcopy(stop))

    return stops


def total_stop_components(stops):
    totals = empty_component_counts()

    for stop in stops or []:
        counts = stop.get("driver_counts") or {}
        for component in COMPONENT_NAMES:
            try:
                totals[component] += int(float(counts.get(component, 0) or 0))
            except (TypeError, ValueError):
                totals[component] += 0

    return totals


def store_lookup_keys(record):
    keys = []

    for field in ("id", "bol"):
        value = clean(record.get(field))
        if value:
            keys.append((field, value))

    store_name = clean(record.get("store_name") or record.get("store"))
    if store_name:
        keys.append(("store", store_name))

    return keys


def build_store_lookup(stores=None):
    lookup = {}

    for store in stores or []:
        if not isinstance(store, dict):
            continue

        for key in store_lookup_keys(store):
            lookup[key] = deepcopy(store)

    return lookup


def find_store_for_stop(stop, store_lookup):
    if not isinstance(stop, dict):
        return {}

    candidates = [
        ("id", clean(stop.get("id"))),
        ("bol", clean(stop.get("bol"))),
        ("store", clean(stop.get("store") or stop.get("store_name"))),
    ]

    for key in candidates:
        if key[1] and key in store_lookup:
            return deepcopy(store_lookup[key])

    return {}


def display_or_default(value, default="Not set"):
    value = clean(value)
    return value if value else default


def stop_address(store_record):
    return (
        clean(store_record.get("full_address"))
        or ", ".join(
            part for part in [
                clean(store_record.get("address") or store_record.get("origin_address")),
                clean(store_record.get("city")),
                clean(store_record.get("state")),
                clean(store_record.get("zip")),
            ]
            if part
        )
    )


def stop_contact(store_record):
    contact_parts = [
        clean(store_record.get("contact") or store_record.get("origin_contact")),
        clean(store_record.get("contact_phone")),
        clean(store_record.get("contact_email")),
    ]
    return " | ".join(part for part in contact_parts if part)


def component_entries_for_stop(stop):
    counts = stop.get("driver_counts") or {}
    entries = []

    for component in COMPONENT_NAMES:
        try:
            value = int(float(counts.get(component, 0) or 0))
        except (TypeError, ValueError):
            value = 0

        entries.append({
            "component": component,
            "field_name": STORE_COMPONENT_FIELDS[component],
            "label": COMPONENT_ENTRY_LABELS[component],
            "value": value,
        })

    return entries


def build_stop_detail(stop=None, store_lookup=None):
    if not isinstance(stop, dict):
        return None

    store_lookup = store_lookup or {}
    store_record = find_store_for_stop(stop, store_lookup)

    return {
        "store_id": clean(store_record.get("id") or stop.get("id")),
        "store": display_or_default(stop.get("store") or store_record.get("store_name") or store_record.get("store"), "Unassigned"),
        "bol": display_or_default(stop.get("bol") or store_record.get("bol")),
        "origin": display_or_default(stop.get("origin") or store_record.get("origin"), "Unknown"),
        "address": display_or_default(stop_address(store_record), "No address on file"),
        "contact": display_or_default(stop_contact(store_record), "No contact on file"),
        "city_state": display_or_default(
            ", ".join(part for part in [clean(stop.get("city") or store_record.get("city")), clean(stop.get("state") or store_record.get("state"))] if part),
            "Unknown",
        ),
        "status": display_or_default(stop.get("status"), "Assigned"),
        "due_date": display_or_default(stop.get("due_date") or store_record.get("due_date")),
        "notes": clean(stop.get("notes") or store_record.get("notes") or store_record.get("variance_review") or ""),
        "collected_racks": store_record.get("collected_racks", ""),
        "collected_pieces": store_record.get("collected_pieces", ""),
        "no_pickup_manager_name": clean(store_record.get("no_pickup_manager_name") or stop.get("no_pickup_manager_name")),
        "no_pickup_photos": store_record.get("no_pickup_photos") if isinstance(store_record.get("no_pickup_photos"), list) else [],
        "counts_saved_at": clean(store_record.get("driver_counts_saved_at")),
        "completed_by": clean(store_record.get("completed_by")),
        "completed_at": clean(store_record.get("completed_at")),
        "is_recovered": clean(stop.get("status") or store_record.get("status")).lower() == "recovered",
        "is_exception": clean(stop.get("status") or store_record.get("status")).lower() == "exception",
        "driver_exception_type": clean(store_record.get("driver_exception_type") or stop.get("driver_exception_type")),
        "driver_exception_notes": clean(store_record.get("driver_exception_notes") or stop.get("driver_exception_notes")),
        "driver_exception_reported_at": clean(store_record.get("driver_exception_reported_at") or stop.get("driver_exception_reported_at")),
        "driver_exception_reported_by": clean(store_record.get("driver_exception_reported_by") or stop.get("driver_exception_reported_by")),
        "exception_types": DRIVER_EXCEPTION_TYPES,
        "component_entries": component_entries_for_stop(stop),
    }


def normalize_driver_count_payload(data):
    data = data if isinstance(data, dict) else {}
    counts = {}

    for component, field_name in STORE_COMPONENT_FIELDS.items():
        counts[field_name] = normalize_quantity(data.get(field_name, 0), component)

    return counts


def normalize_optional_driver_quantity(value, label):
    if value in (None, ""):
        return ""
    return normalize_quantity(value, label)


def route_identifier(route):
    return clean(route.get("id") or route.get("route_id") or route.get("route_number"))


def route_matches(route, route_id):
    route_id = clean(route_id)
    if not route_id or not isinstance(route, dict):
        return False
    return route_id in {
        clean(route.get("id")),
        clean(route.get("route_id")),
        clean(route.get("route_number")),
    }


def store_matches_driver(store, driver_names):
    if not driver_names:
        return True

    return clean(store.get("assigned_driver")) in driver_names


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_reference_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        candidates = value
    else:
        candidates = str(value).replace("\r", "\n").replace(",", "\n").split("\n")
    return [
        clean(candidate)
        for candidate in candidates
        if clean(candidate)
    ]


def route_matches_driver(route, driver_names):
    if not driver_names:
        return True
    return clean(route.get("driver")) in driver_names


def store_ids_for_route(route):
    ids = [
        clean(store_id)
        for store_id in route.get("store_ids") or []
        if clean(store_id)
    ]
    if ids:
        return ids
    return [
        clean(stop.get("id"))
        for stop in route.get("stops") or []
        if isinstance(stop, dict) and clean(stop.get("id"))
    ]


def update_route_stores_status(stores, route, status, driver_status=""):
    route_store_ids = set(store_ids_for_route(route))
    updated = []
    for store in stores or []:
        if not isinstance(store, dict) or clean(store.get("id")) not in route_store_ids:
            continue
        store["status"] = status
        if driver_status:
            store["driver_status"] = driver_status
        updated.append(store)
    return updated


def accept_driver_route(routes, stores, route_id, driver_names=None, accepted_by=""):
    driver_names = normalize_driver_names(driver_names)
    for route in routes or []:
        if not route_matches(route, route_id):
            continue
        if not route_matches_driver(route, driver_names):
            raise PermissionError("This route is not assigned to you.")
        route["driver_status"] = "Accepted"
        route["driver_accepted_at"] = utc_now_iso()
        route["driver_accepted_by"] = clean(accepted_by) or "system"
        if clean(route.get("status")).lower() == "assigned":
            route["status"] = "Dispatched"
        updated_stores = update_route_stores_status(stores, route, "Dispatched", "Accepted")
        return route, updated_stores
    raise LookupError("Driver route was not found.")


def decline_driver_route(routes, stores, route_id, reason="", driver_names=None, declined_by=""):
    driver_names = normalize_driver_names(driver_names)
    for index, route in enumerate(routes or []):
        if not route_matches(route, route_id):
            continue
        if not route_matches_driver(route, driver_names):
            raise PermissionError("This route is not assigned to you.")
        route_store_ids = set(store_ids_for_route(route))
        restored = []
        for store in stores or []:
            if not isinstance(store, dict) or clean(store.get("id")) not in route_store_ids:
                continue
            store["status"] = "Unassigned"
            store["assigned_driver"] = ""
            store["driver_phone"] = ""
            store["truck"] = ""
            store["helper"] = ""
            store["truck_status"] = ""
            store["route_id"] = ""
            store["driver_status"] = "Declined"
            store["driver_decline_reason"] = clean(reason)
            store["driver_declined_at"] = utc_now_iso()
            restored.append(store)
        declined_route = routes.pop(index)
        declined_route["driver_status"] = "Declined"
        declined_route["driver_decline_reason"] = clean(reason)
        declined_route["driver_declined_at"] = utc_now_iso()
        declined_route["driver_declined_by"] = clean(declined_by) or "system"
        return declined_route, restored
    raise LookupError("Driver route was not found.")


def count_snapshot(store):
    snapshot = {
        field_name: normalize_quantity(store.get(field_name, 0), component)
        for component, field_name in STORE_COMPONENT_FIELDS.items()
    }
    snapshot["collected_racks"] = store.get("collected_racks", "")
    snapshot["collected_pieces"] = store.get("collected_pieces", "")
    return snapshot


def append_driver_revision(store, previous_counts, new_counts, operator="", reason=""):
    revisions = store.setdefault("driver_count_revisions", [])
    if not isinstance(revisions, list):
        revisions = []
        store["driver_count_revisions"] = revisions
    revisions.append({
        "timestamp": utc_now_iso(),
        "operator": clean(operator) or "system",
        "reason": clean(reason),
        "previous_counts": previous_counts,
        "new_counts": new_counts,
        "previous_notes": clean(store.get("notes")),
    })


def save_driver_stop_counts(stores, store_id, data, driver_names=None, saved_by=""):
    if not isinstance(stores, list):
        raise ValueError("Stores must be provided as a list.")

    store_id = clean(store_id or (data or {}).get("store_id"))
    if not store_id:
        raise ValueError("A store id is required.")

    driver_names = normalize_driver_names(driver_names)
    counts = normalize_driver_count_payload(data)
    notes = clean((data or {}).get("notes"))
    revision_reason = clean((data or {}).get("revision_reason"))
    collected_racks = normalize_optional_driver_quantity((data or {}).get("collected_racks"), "Rack count")
    collected_pieces = normalize_optional_driver_quantity((data or {}).get("collected_pieces"), "Piece count")
    no_pickup_manager_name = clean((data or {}).get("no_pickup_manager_name"))
    no_pickup_photos = normalize_reference_list((data or {}).get("no_pickup_photos"))

    for store in stores:
        if not isinstance(store, dict):
            continue

        if clean(store.get("id")) != store_id:
            continue

        if not store_matches_driver(store, driver_names):
            raise PermissionError("This stop is not assigned to you.")

        if clean(store.get("receiving_status")).lower() == "received" or clean(store.get("received_at")):
            raise ValueError("Driver counts cannot be revised after Receiving begins.")

        previous_counts = count_snapshot(store)
        has_previous_submission = bool(clean(store.get("driver_counts_saved_at")))
        if has_previous_submission:
            append_driver_revision(store, previous_counts, counts, saved_by, revision_reason)

        for field_name, value in counts.items():
            store[field_name] = value

        if collected_racks != "":
            store["collected_racks"] = collected_racks
        if collected_pieces != "":
            store["collected_pieces"] = collected_pieces
        if no_pickup_manager_name:
            store["no_pickup_manager_name"] = no_pickup_manager_name
        if no_pickup_photos:
            store["no_pickup_photos"] = no_pickup_photos
        store["notes"] = notes
        store["driver_counts_saved_at"] = utc_now_iso()
        store["driver_counts_saved_by"] = clean(saved_by) or "system"
        return store

    raise LookupError("Driver stop was not found.")


def save_driver_exception(stores, store_id, data, driver_names=None, reported_by=""):
    if not isinstance(stores, list):
        raise ValueError("Stores must be provided as a list.")

    store_id = clean(store_id or (data or {}).get("store_id"))
    if not store_id:
        raise ValueError("A store id is required.")

    exception_type = clean((data or {}).get("driver_exception_type"))
    exception_notes = clean((data or {}).get("driver_exception_notes") or (data or {}).get("notes"))
    no_pickup_manager_name = clean((data or {}).get("no_pickup_manager_name"))
    no_pickup_photos = normalize_reference_list((data or {}).get("no_pickup_photos"))

    if not exception_type:
        raise ValueError("Select a driver exception type.")

    if exception_type not in DRIVER_EXCEPTION_TYPES:
        raise ValueError("Select a valid driver exception type.")

    if not exception_notes:
        raise ValueError("Notes are required when reporting a driver exception.")

    if exception_type in {"No Pickup", "No Recovery"} and not no_pickup_manager_name:
        raise ValueError("Manager name is required for No Pickup.")

    driver_names = normalize_driver_names(driver_names)

    for store in stores:
        if not isinstance(store, dict):
            continue

        if clean(store.get("id")) != store_id:
            continue

        if not store_matches_driver(store, driver_names):
            raise PermissionError("This stop is not assigned to you.")

        store["driver_exception_type"] = exception_type
        store["driver_exception_notes"] = exception_notes
        store["driver_exception_reported_at"] = utc_now_iso()
        store["driver_exception_reported_by"] = clean(reported_by) or "system"
        if exception_type in {"No Pickup", "No Recovery"}:
            store["collected_racks"] = 0
            store["collected_pieces"] = 0
            for field_name in STORE_COMPONENT_FIELDS.values():
                store[field_name] = 0
            store["no_pickup_manager_name"] = no_pickup_manager_name
            store["no_pickup_photos"] = no_pickup_photos
            store["driver_counts_saved_at"] = store.get("driver_counts_saved_at") or utc_now_iso()
            store["driver_counts_saved_by"] = clean(reported_by) or "system"
        store["notes"] = exception_notes
        return store

    raise LookupError("Driver stop was not found.")


def is_driver_stop_saved(store):
    if not isinstance(store, dict):
        return False

    return bool(clean(store.get("driver_counts_saved_at")))


def complete_driver_stop(stores, store_id, driver_names=None, completed_by=""):
    if not isinstance(stores, list):
        raise ValueError("Stores must be provided as a list.")

    store_id = clean(store_id)
    if not store_id:
        raise ValueError("A store id is required.")

    driver_names = normalize_driver_names(driver_names)

    for store in stores:
        if not isinstance(store, dict):
            continue

        if clean(store.get("id")) != store_id:
            continue

        if not store_matches_driver(store, driver_names):
            raise PermissionError("This stop is not assigned to you.")

        if not is_driver_stop_saved(store):
            raise ValueError("Save recovery counts and notes before completing this stop.")

        if clean(store.get("status")).lower() in {"recovered", "exception"}:
            store["already_completed"] = True
            return store

        if clean(store.get("driver_exception_type")):
            store["status"] = "Exception"
        else:
            store["status"] = "Recovered"
        store["completed_by"] = clean(completed_by) or "system"
        store["completed_at"] = utc_now_iso()
        store["already_completed"] = False
        return store

    raise LookupError("Driver stop was not found.")


def is_recovered_store(store):
    return clean(store.get("status")).lower() in {"recovered", "completed", "exception"}


def update_route_recovery_progress(routes, stores, store_id):
    if not isinstance(routes, list):
        raise ValueError("Routes must be provided as a list.")

    stores_by_id = {
        clean(store.get("id")): store
        for store in stores or []
        if isinstance(store, dict) and clean(store.get("id"))
    }
    store_id = clean(store_id)
    updated_routes = []

    for route in routes:
        if not isinstance(route, dict):
            continue

        route_store_ids = [clean(route_store_id) for route_store_id in route.get("store_ids") or []]
        if not route_store_ids:
            route_store_ids = [
                clean(stop.get("id"))
                for stop in route.get("stops") or []
                if isinstance(stop, dict) and clean(stop.get("id"))
            ]
        if store_id not in route_store_ids:
            continue

        route_stores = [
            stores_by_id[route_store_id]
            for route_store_id in route_store_ids
            if route_store_id in stores_by_id
        ]
        total_stops = len(route_stores)
        recovered_stops = sum(1 for store in route_stores if is_recovered_store(store))
        exception_stops = sum(1 for store in route_stores if clean(store.get("status")).lower() == "exception")

        route["recovery_progress"] = {
            "total_stops": total_stops,
            "recovered_stops": recovered_stops,
            "exception_stops": exception_stops,
            "remaining_stops": max(total_stops - recovered_stops, 0),
            "updated_at": utc_now_iso(),
        }
        updated_routes.append(route)

    return updated_routes


def summarize_driver_route(route_summary):
    route = deepcopy(route_summary.get("route") or {})
    stops = active_stops_for_route(route)
    component_totals = total_stop_components(stops)
    completed_stops = sum(1 for stop in stops if is_completed_stop(stop))

    return {
        "route_id": route_identifier(route),
        "label": route_summary.get("label") or "Assigned Route",
        "truck": route_summary.get("truck") or "Unassigned",
        "driver": route_summary.get("driver") or "Unassigned",
        "status": route_summary.get("status") or "Assigned",
        "driver_status": clean(route.get("driver_status")) or "Pending",
        "status_class": status_class(route_summary.get("status")),
        "stop_count": len(stops),
        "completed_stops": completed_stops,
        "component_totals": component_totals,
        "estimated_weight": calculate_estimated_weight(component_totals),
        "stops": stops,
    }


def build_driver_workspace(routes=None, stores=None, driver_names=None, selected_index=0):
    driver_names = normalize_driver_names(driver_names)
    stores = stores if isinstance(stores, list) else []
    store_lookup = build_store_lookup(stores)
    recovery_workspace = summarize_recovery_workspace_from_records(routes, stores)

    assigned_routes = []
    for route_summary in recovery_workspace.get("routes") or []:
        if not is_active_route(route_summary):
            continue

        if not matches_driver(route_summary, driver_names):
            continue

        driver_route = summarize_driver_route(route_summary)
        if driver_route["stop_count"] > 0:
            assigned_routes.append(driver_route)

    selected_route = None
    selected_stop = None
    selected_stop_detail = None
    if assigned_routes:
        selected_index = max(0, min(int(selected_index or 0), len(assigned_routes) - 1))
        selected_route = assigned_routes[selected_index]
        if selected_route["stops"]:
            selected_stop = selected_route["stops"][0]
            selected_stop_detail = build_stop_detail(selected_stop, store_lookup)

    component_totals = empty_component_counts()
    for route in assigned_routes:
        for component in COMPONENT_NAMES:
            component_totals[component] += route["component_totals"][component]

    stop_count = sum(route["stop_count"] for route in assigned_routes)
    completed_stops = sum(route["completed_stops"] for route in assigned_routes)

    return {
        "component_names": COMPONENT_NAMES,
        "exception_types": DRIVER_EXCEPTION_TYPES,
        "driver_names": sorted(driver_names),
        "routes": assigned_routes,
        "selected_route": selected_route,
        "selected_stop": selected_stop,
        "selected_stop_detail": selected_stop_detail,
        "component_totals": component_totals,
        "estimated_weight": calculate_estimated_weight(component_totals),
        "summary": {
            "route_count": len(assigned_routes),
            "stop_count": stop_count,
            "completed_stops": completed_stops,
            "estimated_weight": calculate_estimated_weight(component_totals),
        },
    }
