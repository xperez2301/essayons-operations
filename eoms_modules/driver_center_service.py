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
    "recovered",
}

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
        "counts_saved_at": clean(store_record.get("driver_counts_saved_at")),
        "completed_by": clean(store_record.get("completed_by")),
        "completed_at": clean(store_record.get("completed_at")),
        "is_recovered": clean(stop.get("status") or store_record.get("status")).lower() == "recovered",
        "component_entries": component_entries_for_stop(stop),
    }


def normalize_driver_count_payload(data):
    data = data if isinstance(data, dict) else {}
    counts = {}

    for component, field_name in STORE_COMPONENT_FIELDS.items():
        counts[field_name] = normalize_quantity(data.get(field_name, 0), component)

    return counts


def store_matches_driver(store, driver_names):
    if not driver_names:
        return True

    return clean(store.get("assigned_driver")) in driver_names


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_driver_stop_counts(stores, store_id, data, driver_names=None, saved_by=""):
    if not isinstance(stores, list):
        raise ValueError("Stores must be provided as a list.")

    store_id = clean(store_id or (data or {}).get("store_id"))
    if not store_id:
        raise ValueError("A store id is required.")

    driver_names = normalize_driver_names(driver_names)
    counts = normalize_driver_count_payload(data)
    notes = clean((data or {}).get("notes"))

    for store in stores:
        if not isinstance(store, dict):
            continue

        if clean(store.get("id")) != store_id:
            continue

        if not store_matches_driver(store, driver_names):
            raise PermissionError("This stop is not assigned to you.")

        for field_name, value in counts.items():
            store[field_name] = value

        store["notes"] = notes
        store["driver_counts_saved_at"] = utc_now_iso()
        store["driver_counts_saved_by"] = clean(saved_by) or "system"
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

        if clean(store.get("status")).lower() == "recovered":
            store["already_completed"] = True
            return store

        store["status"] = "Recovered"
        store["completed_by"] = clean(completed_by) or "system"
        store["completed_at"] = utc_now_iso()
        store["already_completed"] = False
        return store

    raise LookupError("Driver stop was not found.")


def is_recovered_store(store):
    return clean(store.get("status")).lower() in {"recovered", "completed"}


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

        route["recovery_progress"] = {
            "total_stops": total_stops,
            "recovered_stops": recovered_stops,
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
        "label": route_summary.get("label") or "Assigned Route",
        "truck": route_summary.get("truck") or "Unassigned",
        "driver": route_summary.get("driver") or "Unassigned",
        "status": route_summary.get("status") or "Assigned",
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
