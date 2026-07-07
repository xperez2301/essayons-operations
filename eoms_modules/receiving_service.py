from copy import deepcopy
from datetime import datetime, timezone

from eoms_modules.recovery_center_service import (
    COMPONENT_NAMES,
    STORE_COMPONENT_FIELDS,
    calculate_estimated_weight,
    clean,
    driver_counts_from_store,
    empty_component_counts,
)


RECEIVABLE_STATUSES = {"recovered", "exception"}
RECEIVED_STATUS = "Received"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today_iso():
    return datetime.now(timezone.utc).date().isoformat()


def is_receivable_store(store):
    if not isinstance(store, dict):
        return False
    return clean(store.get("status")).lower() in RECEIVABLE_STATUSES


def is_received_store(store):
    if not isinstance(store, dict):
        return False
    return clean(store.get("receiving_status")) == RECEIVED_STATUS


def store_completed_time(store):
    return clean(store.get("completed_at") or store.get("recovered_at") or store.get("updated_at"))


def route_lookup(routes):
    lookup = {}

    for route in routes or []:
        if not isinstance(route, dict):
            continue

        route_label = clean(route.get("route_number") or route.get("id")) or "Unassigned Route"
        route_driver = clean(route.get("driver")) or "Unassigned"

        for store_id in route.get("store_ids") or []:
            if clean(store_id):
                lookup[clean(store_id)] = {
                    "route": route_label,
                    "driver": route_driver,
                }

        for stop in route.get("stops") or []:
            if isinstance(stop, dict) and clean(stop.get("id")):
                lookup[clean(stop.get("id"))] = {
                    "route": route_label,
                    "driver": route_driver,
                }

    return lookup


def component_totals_for_stores(stores):
    totals = empty_component_counts()

    for store in stores or []:
        counts = driver_counts_from_store(store)
        for component in COMPONENT_NAMES:
            totals[component] += counts[component]

    return totals


def receiving_status_class(status):
    status = clean(status).lower()
    if status == "received":
        return "success"
    if status == "pending":
        return "warning"
    if status == "exception":
        return "danger"
    return "neutral"


def build_recovery_load(store, route_info=None):
    route_info = route_info or {}
    counts = driver_counts_from_store(store)
    receiving_status = clean(store.get("receiving_status")) or "Pending"
    recovery_status = clean(store.get("status")) or "Unknown"

    return {
        "store_id": clean(store.get("id")),
        "store": clean(store.get("store_name") or store.get("store")) or "Unassigned",
        "bol": clean(store.get("bol")) or "Not set",
        "origin": clean(store.get("origin")) or "Unknown",
        "route": clean(route_info.get("route")) or "Unassigned Route",
        "driver": clean(route_info.get("driver") or store.get("assigned_driver")) or "Unassigned",
        "completed_time": store_completed_time(store) or "Not set",
        "recovery_status": recovery_status,
        "recovery_status_class": receiving_status_class(recovery_status),
        "receiving_status": receiving_status,
        "receiving_status_class": receiving_status_class(receiving_status),
        "received_by": clean(store.get("received_by")) or "Not received",
        "received_at": clean(store.get("received_at")) or "",
        "warehouse_notes": clean(store.get("warehouse_notes")),
        "notes": clean(store.get("notes")),
        "driver_exception_type": clean(store.get("driver_exception_type")),
        "driver_exception_notes": clean(store.get("driver_exception_notes")),
        "component_counts": counts,
        "recovered_weight": calculate_estimated_weight(counts),
    }


def prepare_recovery_loads(stores=None, routes=None):
    routes_by_store = route_lookup(routes or [])
    loads = []

    for store in stores or []:
        if not is_receivable_store(store):
            continue

        store_id = clean(store.get("id"))
        loads.append(build_recovery_load(store, routes_by_store.get(store_id)))

    return sorted(loads, key=lambda load: load["completed_time"], reverse=True)


def prepare_receiving_history(loads):
    received = [
        load for load in loads
        if load["receiving_status"] == RECEIVED_STATUS
    ]
    return sorted(received, key=lambda load: load["received_at"], reverse=True)


def calculate_workspace_summary(stores, loads):
    pending_loads = [
        load for load in loads
        if load["receiving_status"] != RECEIVED_STATUS
    ]
    received_stores = [
        store for store in stores or []
        if is_received_store(store)
    ]
    received_today = [
        store for store in received_stores
        if clean(store.get("received_at")).startswith(today_iso())
    ]
    component_totals = component_totals_for_stores(received_stores)

    active_routes = {
        load["route"] for load in pending_loads
        if load["route"] != "Unassigned Route"
    }

    return {
        "active_recovery_routes": len(active_routes),
        "pending_receipts": len(pending_loads),
        "received_today": len(received_today),
        "total_components_received": sum(component_totals.values()),
        "estimated_weight_received": calculate_estimated_weight(component_totals),
        "component_totals": component_totals,
    }


def build_receiving_workspace(stores=None, routes=None, selected_index=0):
    stores = stores if isinstance(stores, list) else []
    routes = routes if isinstance(routes, list) else []
    loads = prepare_recovery_loads(stores, routes)
    pending_loads = [load for load in loads if load["receiving_status"] != RECEIVED_STATUS]

    selected_load = None
    if pending_loads:
        selected_index = max(0, min(int(selected_index or 0), len(pending_loads) - 1))
        selected_load = pending_loads[selected_index]
    elif loads:
        selected_index = max(0, min(int(selected_index or 0), len(loads) - 1))
        selected_load = loads[selected_index]

    return {
        "component_names": COMPONENT_NAMES,
        "summary": calculate_workspace_summary(stores, loads),
        "loads": loads,
        "pending_loads": pending_loads,
        "selected_load": selected_load,
        "history": prepare_receiving_history(loads),
    }


def validate_receiving_action(stores, store_id):
    if not isinstance(stores, list):
        raise ValueError("Stores must be provided as a list.")

    store_id = clean(store_id)
    if not store_id:
        raise ValueError("A store id is required.")

    for store in stores:
        if not isinstance(store, dict):
            continue

        if clean(store.get("id")) != store_id:
            continue

        if not is_receivable_store(store):
            raise ValueError("Only Recovered or Exception loads can be received.")

        return store

    raise LookupError("Recovery load was not found.")


def receive_load(stores, store_id, received_by="", warehouse_notes=""):
    store = validate_receiving_action(stores, store_id)

    if is_received_store(store):
        store["already_received"] = True
        return store

    store["receiving_status"] = RECEIVED_STATUS
    store["received_by"] = clean(received_by) or "system"
    store["received_at"] = utc_now_iso()
    store["warehouse_notes"] = clean(warehouse_notes)
    store["already_received"] = False
    return store
