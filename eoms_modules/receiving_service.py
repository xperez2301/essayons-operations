from copy import deepcopy
from datetime import datetime, timezone

from eoms_modules.recovery_center_service import (
    COMPONENT_NAMES,
    STORE_COMPONENT_FIELDS,
    calculate_estimated_weight,
    clean,
    driver_counts_from_store,
    empty_component_counts,
    normalize_quantity,
)


RECEIVABLE_STATUSES = {"recovered", "exception"}
RECEIVED_STATUS = "Received"
DISPATCHER_CLOSED_STATUS = "Closed"
DAMAGE_CATEGORIES = (
    "Good Inventory",
    "Damaged Inventory",
    "Returned to EZ Rack",
    "Awaiting Repair",
)


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today_iso():
    return datetime.now(timezone.utc).date().isoformat()


def is_receivable_store(store):
    if not isinstance(store, dict):
        return False
    if clean(store.get("receiving_status")) == RECEIVED_STATUS:
        return True
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
        counts = warehouse_verified_counts_from_store(store)
        if not any(counts.values()):
            counts = driver_counts_from_store(store)
        for component in COMPONENT_NAMES:
            totals[component] += counts[component]

    return totals


def default_damage_counts():
    return {
        category: empty_component_counts()
        for category in DAMAGE_CATEGORIES
    }


def normalize_component_payload(data=None, fallback=None):
    data = data if isinstance(data, dict) else {}
    fallback = fallback if isinstance(fallback, dict) else {}
    counts = empty_component_counts()

    for component, field_name in STORE_COMPONENT_FIELDS.items():
        counts[component] = normalize_quantity(
            data.get(field_name, data.get(component, fallback.get(component, 0))),
            component,
        )

    return counts


def normalize_damage_payload(data=None):
    data = data if isinstance(data, dict) else {}
    normalized = default_damage_counts()

    for category in DAMAGE_CATEGORIES:
        normalized[category] = normalize_component_payload(data.get(category) or {})

    return normalized


def normalize_photo_refs(value):
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


def warehouse_verified_counts_from_store(store):
    if not isinstance(store, dict):
        return empty_component_counts()

    counts = store.get("warehouse_verified_counts")
    if isinstance(counts, dict):
        return normalize_component_payload(counts)

    return empty_component_counts()


def damage_counts_from_store(store):
    if not isinstance(store, dict):
        return default_damage_counts()

    return normalize_damage_payload(store.get("damage_counts"))


def total_damaged_components(store):
    damage_counts = damage_counts_from_store(store)
    return sum(
        damage_counts[category][component]
        for category in DAMAGE_CATEGORIES
        if category != "Good Inventory"
        for component in COMPONENT_NAMES
    )


def quantity_difference(driver_counts, warehouse_counts):
    return {
        component: warehouse_counts.get(component, 0) - driver_counts.get(component, 0)
        for component in COMPONENT_NAMES
    }


def normalize_optional_quantity(value, label):
    if value in (None, ""):
        return None
    return normalize_quantity(value, label)


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
    verified_counts = warehouse_verified_counts_from_store(store)
    receiving_status = clean(store.get("receiving_status")) or "Pending"
    recovery_status = clean(store.get("status")) or "Unknown"
    verified_racks = store.get("warehouse_verified_racks")
    verified_pieces = store.get("warehouse_verified_pieces")

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
        "warehouse_verified_racks": verified_racks if verified_racks not in (None, "") else "",
        "warehouse_verified_pieces": verified_pieces if verified_pieces not in (None, "") else "",
        "warehouse_verified_counts": verified_counts,
        "quantity_difference": quantity_difference(counts, verified_counts),
        "damage_counts": damage_counts_from_store(store),
        "damaged_material": clean(store.get("damaged_material")),
        "damage_notes": clean(store.get("damage_notes")),
        "warehouse_photos": store.get("warehouse_photos") if isinstance(store.get("warehouse_photos"), list) else [],
        "dispatcher_closeout_status": clean(store.get("dispatcher_closeout_status")) or "Pending",
        "dispatcher_closed_by": clean(store.get("dispatcher_closed_by")),
        "dispatcher_closed_at": clean(store.get("dispatcher_closed_at")),
        "dispatcher_closeout_notes": clean(store.get("dispatcher_closeout_notes")),
        "notes": clean(store.get("notes")),
        "driver_submitted_racks": store.get("collected_racks", ""),
        "driver_submitted_pieces": store.get("collected_pieces", ""),
        "driver_count_revisions": store.get("driver_count_revisions") if isinstance(store.get("driver_count_revisions"), list) else [],
        "no_pickup_manager_name": clean(store.get("no_pickup_manager_name")),
        "no_pickup_photos": store.get("no_pickup_photos") if isinstance(store.get("no_pickup_photos"), list) else [],
        "driver_exception_type": clean(store.get("driver_exception_type")),
        "driver_exception_notes": clean(store.get("driver_exception_notes")),
        "component_counts": counts,
        "recovered_weight": calculate_estimated_weight(counts),
        "verified_weight": calculate_estimated_weight(verified_counts),
        "damaged_component_total": total_damaged_components(store),
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


def prepare_dispatcher_closeout(loads):
    return [
        load for load in loads
        if load["receiving_status"] == RECEIVED_STATUS
        and load["dispatcher_closeout_status"] != DISPATCHER_CLOSED_STATUS
    ]


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
        "closeout_queue": prepare_dispatcher_closeout(loads),
        "damage_categories": DAMAGE_CATEGORIES,
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


def receive_load(
    stores,
    store_id,
    received_by="",
    warehouse_notes="",
    verified_racks=None,
    verified_pieces=None,
    verified_counts=None,
    damage_counts=None,
    damaged_material="",
    damage_notes="",
    warehouse_photos=None,
):
    store = validate_receiving_action(stores, store_id)

    if is_received_store(store):
        store["already_received"] = True
        return store

    driver_counts = driver_counts_from_store(store)
    verified_counts = normalize_component_payload(verified_counts, driver_counts)
    damage_counts = normalize_damage_payload(damage_counts)
    verified_racks = normalize_optional_quantity(
        verified_racks if verified_racks not in (None, "") else store.get("collected_racks"),
        "Verified rack count",
    )
    verified_pieces = normalize_optional_quantity(
        verified_pieces if verified_pieces not in (None, "") else store.get("collected_pieces"),
        "Verified piece count",
    )

    store["receiving_status"] = RECEIVED_STATUS
    store["received_by"] = clean(received_by) or "system"
    store["received_at"] = utc_now_iso()
    store["warehouse_notes"] = clean(warehouse_notes)
    store["warehouse_verified_racks"] = verified_racks if verified_racks is not None else 0
    store["warehouse_verified_pieces"] = verified_pieces if verified_pieces is not None else 0
    store["warehouse_verified_counts"] = verified_counts
    store["damage_counts"] = damage_counts
    store["damaged_material"] = clean(damaged_material)
    store["damage_notes"] = clean(damage_notes)
    store["warehouse_photos"] = normalize_photo_refs(warehouse_photos)
    store["dispatcher_closeout_status"] = "Pending"
    store["already_received"] = False
    return store
