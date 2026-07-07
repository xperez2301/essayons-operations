from copy import deepcopy
from datetime import datetime, timezone


PIECES_PER_RACK = 19
DEFAULT_RACK_WEIGHT = 200

COMPONENT_NAMES = (
    '84" Corner Post',
    '40" DRB',
    '48" DRB',
    "Wood Shelf",
)

COMPONENT_WEIGHTS = {
    '84" Corner Post': 5.20,
    '40" DRB': 2.90,
    '48" DRB': 3.40,
    "Wood Shelf": 16.50,
}

STORE_COMPONENT_FIELDS = {
    '84" Corner Post': "corner_posts",
    '40" DRB': "drb40",
    '48" DRB': "drb48",
    "Wood Shelf": "wood_shelf",
}

COMPLETED_STOP_STATUSES = {
    "completed",
    "complete",
    "recovered",
}

DEFAULT_ROUTE_STATUS = "Planned"
DEFAULT_STOP_STATUS = "Pending"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean(value):
    return "" if value is None else str(value).strip()


def normalize_quantity(value, field_name="quantity"):
    if value in (None, ""):
        return 0

    try:
        quantity = int(float(value))
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a whole number.")

    if quantity < 0:
        raise ValueError(f"{field_name} cannot be negative.")

    return quantity


def empty_component_counts():
    return {
        component: 0
        for component in COMPONENT_NAMES
    }


def normalize_driver_counts(driver_counts=None):
    normalized = empty_component_counts()

    if driver_counts is None:
        return normalized

    if not isinstance(driver_counts, dict):
        raise ValueError("Driver counts must be provided as a dictionary.")

    for component in COMPONENT_NAMES:
        normalized[component] = normalize_quantity(
            driver_counts.get(component, 0),
            component,
        )

    return normalized


def normalize_stop_status(status):
    return clean(status) or DEFAULT_STOP_STATUS


def normalize_route_status(status):
    return clean(status) or DEFAULT_ROUTE_STATUS


def create_recovery_stop(
    store="",
    origin="",
    bol="",
    driver_counts=None,
    notes="",
    status=DEFAULT_STOP_STATUS,
    city="",
    state="",
    due_date="",
):
    return {
        "store": clean(store),
        "origin": clean(origin),
        "bol": clean(bol),
        "city": clean(city),
        "state": clean(state),
        "due_date": clean(due_date),
        "driver_counts": normalize_driver_counts(driver_counts),
        "notes": clean(notes),
        "status": normalize_stop_status(status),
        "created_at": utc_now_iso(),
    }


def is_completed_stop(stop):
    if not isinstance(stop, dict):
        return False

    return clean(stop.get("status")).lower() in COMPLETED_STOP_STATUSES


def calculate_component_totals(stops, completed_only=False):
    totals = empty_component_counts()

    for stop in stops or []:
        if not isinstance(stop, dict):
            continue

        if completed_only and not is_completed_stop(stop):
            continue

        counts = normalize_driver_counts(stop.get("driver_counts"))
        for component in COMPONENT_NAMES:
            totals[component] += counts[component]

    return totals


def calculate_running_totals(stops):
    return calculate_component_totals(stops, completed_only=True)


def calculate_estimated_component_totals(stops):
    return calculate_component_totals(stops, completed_only=False)


def calculate_estimated_weight(component_totals):
    totals = normalize_driver_counts(component_totals)
    weight = sum(
        totals[component] * COMPONENT_WEIGHTS[component]
        for component in COMPONENT_NAMES
    )
    return round(weight, 2)


def calculate_recovery_status(stops):
    stops = [
        stop for stop in (stops or [])
        if isinstance(stop, dict)
    ]

    if not stops:
        return DEFAULT_ROUTE_STATUS

    completed_count = sum(1 for stop in stops if is_completed_stop(stop))

    if completed_count == 0:
        return "Planned"

    if completed_count == len(stops):
        return "Completed"

    return "In Progress"


def refresh_route_totals(route):
    if not isinstance(route, dict):
        raise ValueError("Recovery route must be a dictionary.")

    stops = route.get("recovery_stops")
    if not isinstance(stops, list):
        stops = []
        route["recovery_stops"] = stops

    running_totals = calculate_running_totals(stops)
    estimated_component_totals = calculate_estimated_component_totals(stops)

    route["running_totals"] = running_totals
    route["estimated_component_totals"] = estimated_component_totals
    route["estimated_weight"] = calculate_estimated_weight(estimated_component_totals)
    route["warehouse_expected_totals"] = deepcopy(running_totals)
    route["recovery_status"] = calculate_recovery_status(stops)

    if clean(route.get("status")) in ("", DEFAULT_ROUTE_STATUS, "In Progress", "Completed"):
        route["status"] = route["recovery_status"]

    return route


def create_recovery_route(
    truck="",
    driver="",
    dispatcher="",
    status=DEFAULT_ROUTE_STATUS,
    recovery_stops=None,
    warehouse_eta="",
):
    route = {
        "truck": clean(truck),
        "driver": clean(driver),
        "dispatcher": clean(dispatcher),
        "status": normalize_route_status(status),
        "recovery_stops": [],
        "running_totals": empty_component_counts(),
        "estimated_component_totals": empty_component_counts(),
        "estimated_weight": 0,
        "warehouse_eta": clean(warehouse_eta),
        "warehouse_expected_totals": empty_component_counts(),
        "recovery_status": normalize_route_status(status),
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }

    if recovery_stops:
        if not isinstance(recovery_stops, list):
            raise ValueError("Recovery stops must be provided as a list.")

        route["recovery_stops"] = [
            normalize_recovery_stop(stop)
            for stop in recovery_stops
        ]

    return refresh_route_totals(route)


def normalize_recovery_stop(stop):
    if not isinstance(stop, dict):
        raise ValueError("Recovery stop must be a dictionary.")

    return create_recovery_stop(
        store=stop.get("store") or stop.get("store_name"),
        origin=stop.get("origin"),
        bol=stop.get("bol"),
        driver_counts=stop.get("driver_counts"),
        notes=stop.get("notes"),
        status=stop.get("status") or DEFAULT_STOP_STATUS,
        city=stop.get("city"),
        state=stop.get("state"),
        due_date=stop.get("due_date"),
    )


def add_recovery_stop(route, stop):
    if not isinstance(route, dict):
        raise ValueError("Recovery route must be a dictionary.")

    stops = route.setdefault("recovery_stops", [])
    if not isinstance(stops, list):
        raise ValueError("Recovery route stops must be a list.")

    stops.append(normalize_recovery_stop(stop))
    route["updated_at"] = utc_now_iso()
    return refresh_route_totals(route)


def complete_recovery_stop(route, bol, driver_counts=None, notes=None):
    if not isinstance(route, dict):
        raise ValueError("Recovery route must be a dictionary.")

    bol = clean(bol)
    if not bol:
        raise ValueError("BOL is required to complete a recovery stop.")

    for stop in route.get("recovery_stops", []):
        if clean(stop.get("bol")) != bol:
            continue

        if driver_counts is not None:
            stop["driver_counts"] = normalize_driver_counts(driver_counts)

        if notes is not None:
            stop["notes"] = clean(notes)

        stop["status"] = "Completed"
        stop["completed_at"] = utc_now_iso()
        route["updated_at"] = utc_now_iso()
        return refresh_route_totals(route)

    raise ValueError("Recovery stop was not found for the provided BOL.")


def normalize_recovery_route(route):
    if not isinstance(route, dict):
        raise ValueError("Recovery route must be a dictionary.")

    normalized = create_recovery_route(
        truck=route.get("truck"),
        driver=route.get("driver"),
        dispatcher=route.get("dispatcher"),
        status=route.get("status") or DEFAULT_ROUTE_STATUS,
        recovery_stops=route.get("recovery_stops") or [],
        warehouse_eta=route.get("warehouse_eta"),
    )

    for key in ("route_id", "route_number", "created_at", "updated_at"):
        if clean(route.get(key)):
            normalized[key] = clean(route.get(key))

    return refresh_route_totals(normalized)


def status_class(status):
    status = clean(status).lower()

    if status in {"completed", "complete", "recovered"}:
        return "success"

    if status in {"in progress", "running", "active"}:
        return "warning"

    if status in {"blocked", "failed", "cancelled"}:
        return "danger"

    return "neutral"


def recovery_route_label(route, index=0):
    label = clean(route.get("route_number") or route.get("route_id"))
    if label:
        return label

    truck = clean(route.get("truck"))
    if truck:
        return f"Recovery {truck}"

    return f"Recovery Route {index + 1}"


def summarize_recovery_route(route, index=0):
    route = refresh_route_totals(deepcopy(route))
    stops = route.get("recovery_stops") or []
    completed_stops = sum(1 for stop in stops if is_completed_stop(stop))

    return {
        "label": recovery_route_label(route, index),
        "truck": clean(route.get("truck")) or "Unassigned",
        "driver": clean(route.get("driver")) or "Unassigned",
        "dispatcher": clean(route.get("dispatcher")) or "Unassigned",
        "status": route.get("recovery_status") or route.get("status") or DEFAULT_ROUTE_STATUS,
        "status_class": status_class(route.get("recovery_status") or route.get("status")),
        "stop_count": len(stops),
        "completed_stops": completed_stops,
        "estimated_weight": route.get("estimated_weight", 0),
        "warehouse_eta": clean(route.get("warehouse_eta")) or "Not set",
        "route": route,
    }


def summarize_recovery_workspace(routes=None, selected_index=0):
    if routes is None:
        routes = []

    if not isinstance(routes, list):
        raise ValueError("Recovery workspace routes must be provided as a list.")

    normalized_routes = [
        normalize_recovery_route(route)
        for route in routes
    ]
    route_summaries = [
        summarize_recovery_route(route, index)
        for index, route in enumerate(normalized_routes)
    ]

    selected_route = None
    selected_summary = None
    if route_summaries:
        selected_index = max(0, min(int(selected_index or 0), len(route_summaries) - 1))
        selected_summary = route_summaries[selected_index]
        selected_route = selected_summary["route"]

    total_stops = sum(summary["stop_count"] for summary in route_summaries)
    completed_stops = sum(summary["completed_stops"] for summary in route_summaries)
    running_totals = empty_component_counts()
    estimated_component_totals = empty_component_counts()

    for route in normalized_routes:
        for component in COMPONENT_NAMES:
            running_totals[component] += route["running_totals"][component]
            estimated_component_totals[component] += route["estimated_component_totals"][component]

    return {
        "component_names": COMPONENT_NAMES,
        "routes": route_summaries,
        "selected_route": selected_route,
        "selected_summary": selected_summary,
        "running_totals": running_totals,
        "estimated_component_totals": estimated_component_totals,
        "estimated_weight": calculate_estimated_weight(estimated_component_totals),
        "summary": {
            "route_count": len(route_summaries),
            "active_routes": sum(1 for summary in route_summaries if summary["status"] != "Completed"),
            "total_stops": total_stops,
            "completed_stops": completed_stops,
            "estimated_weight": calculate_estimated_weight(estimated_component_totals),
        },
    }


def driver_counts_from_store(store):
    if not isinstance(store, dict):
        return empty_component_counts()

    return {
        component: normalize_quantity(store.get(field_name, 0), component)
        for component, field_name in STORE_COMPONENT_FIELDS.items()
    }


def recovery_stop_from_store(store):
    if not isinstance(store, dict):
        raise ValueError("Store record must be a dictionary.")

    return create_recovery_stop(
        store=store.get("store_name") or store.get("store"),
        origin=store.get("origin"),
        bol=store.get("bol"),
        driver_counts=driver_counts_from_store(store),
        notes=store.get("notes") or store.get("variance_review") or store.get("hub_reason"),
        status=store.get("status") or DEFAULT_STOP_STATUS,
        city=store.get("city"),
        state=store.get("state"),
        due_date=store.get("due_date"),
    )


def recovery_route_from_route_record(route, stores_by_id=None, index=0):
    if not isinstance(route, dict):
        raise ValueError("Route record must be a dictionary.")

    stores_by_id = stores_by_id or {}
    route_stops = []

    for stop in route.get("stops") or []:
        if not isinstance(stop, dict):
            continue

        store_record = stores_by_id.get(clean(stop.get("id"))) or {}
        merged = deepcopy(stop)
        merged.update({
            key: value
            for key, value in store_record.items()
            if value not in (None, "")
        })
        route_stops.append(recovery_stop_from_store(merged))

    if not route_stops:
        for store_id in route.get("store_ids") or []:
            store_record = stores_by_id.get(clean(store_id))
            if store_record:
                route_stops.append(recovery_stop_from_store(store_record))

    recovery_route = create_recovery_route(
        truck=route.get("truck"),
        driver=route.get("driver"),
        dispatcher=route.get("dispatcher") or route.get("created_by"),
        status=route.get("status") or DEFAULT_ROUTE_STATUS,
        recovery_stops=route_stops,
        warehouse_eta=route.get("warehouse_eta") or route.get("completed_at"),
    )

    recovery_route["route_id"] = clean(route.get("id")) or f"route-{index + 1}"
    recovery_route["route_number"] = clean(route.get("route_number")) or f"REC-{index + 1:04d}"
    recovery_route["source"] = "routes"
    return refresh_route_totals(recovery_route)


def route_group_key(store):
    driver = clean(store.get("assigned_driver")) or "Unassigned"
    truck = clean(store.get("truck")) or "Unassigned"
    area = clean(store.get("dispatch_group") or store.get("hub") or store.get("city")) or "Unassigned"
    return driver, truck, area


def should_include_store_in_recovery(store):
    if not isinstance(store, dict):
        return False

    status = clean(store.get("status")).lower()
    if status in {"assigned", "dispatched", "completed"}:
        return True

    return bool(clean(store.get("assigned_driver")) or clean(store.get("truck")))


def recovery_routes_from_store_records(stores):
    groups = {}

    for store in stores or []:
        if not should_include_store_in_recovery(store):
            continue

        groups.setdefault(route_group_key(store), []).append(deepcopy(store))

    recovery_routes = []
    for index, ((driver, truck, area), group_stores) in enumerate(sorted(groups.items())):
        stops = [recovery_stop_from_store(store) for store in group_stores]
        route = create_recovery_route(
            truck=truck,
            driver=driver,
            dispatcher="Unassigned",
            status=calculate_recovery_status(stops),
            recovery_stops=stops,
            warehouse_eta="",
        )
        route["route_id"] = f"store-group-{index + 1}"
        route["route_number"] = f"REC-{index + 1:04d}"
        route["source"] = "stores"
        route["dispatch_group"] = area
        recovery_routes.append(refresh_route_totals(route))

    return recovery_routes


def summarize_recovery_workspace_from_records(routes=None, stores=None, selected_index=0):
    routes = routes if isinstance(routes, list) else []
    stores = stores if isinstance(stores, list) else []
    stores_by_id = {
        clean(store.get("id")): deepcopy(store)
        for store in stores
        if isinstance(store, dict) and clean(store.get("id"))
    }

    route_records_available = bool(routes)
    recovery_routes = [
        recovery_route_from_route_record(route, stores_by_id, index)
        for index, route in enumerate(routes)
        if isinstance(route, dict)
    ]

    source = "routes"
    if not recovery_routes:
        recovery_routes = recovery_routes_from_store_records(stores)
        source = "stores"

    workspace = summarize_recovery_workspace(recovery_routes, selected_index)
    workspace["source"] = source if route_records_available or recovery_routes else "stores"
    workspace["has_live_data"] = bool(recovery_routes)
    return workspace
