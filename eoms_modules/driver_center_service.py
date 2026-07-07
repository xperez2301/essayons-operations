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
    status = clean(route_summary.get("status")).lower()
    if not status:
        return True
    return status in ACTIVE_DRIVER_STATUSES


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
    if assigned_routes:
        selected_index = max(0, min(int(selected_index or 0), len(assigned_routes) - 1))
        selected_route = assigned_routes[selected_index]
        if selected_route["stops"]:
            selected_stop = selected_route["stops"][0]

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
        "component_totals": component_totals,
        "estimated_weight": calculate_estimated_weight(component_totals),
        "summary": {
            "route_count": len(assigned_routes),
            "stop_count": stop_count,
            "completed_stops": completed_stops,
            "estimated_weight": calculate_estimated_weight(component_totals),
        },
    }
