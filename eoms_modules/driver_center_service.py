from copy import deepcopy

from eoms_modules.recovery_center_service import (
    COMPONENT_NAMES,
    calculate_estimated_weight,
    clean,
    empty_component_counts,
    is_completed_stop,
    status_class,
    summarize_recovery_workspace_from_records,
)


ACTIVE_DRIVER_STATUSES = {
    "assigned",
    "dispatched",
    "in progress",
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
        "component_entries": component_entries_for_stop(stop),
    }


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
