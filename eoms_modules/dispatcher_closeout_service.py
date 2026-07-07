from copy import deepcopy
from datetime import datetime, timezone

from eoms_modules.receiving_service import (
    DISPATCHER_CLOSED_STATUS,
    RECEIVED_STATUS,
    build_recovery_load,
    damage_counts_from_store,
    route_lookup,
    total_damaged_components,
    warehouse_verified_counts_from_store,
)
from eoms_modules.recovery_center_service import (
    COMPONENT_NAMES,
    PIECES_PER_RACK,
    calculate_estimated_weight,
    clean,
    driver_counts_from_store,
)


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_ready_for_dispatcher_closeout(store):
    if not isinstance(store, dict):
        return False
    return (
        clean(store.get("receiving_status")) == RECEIVED_STATUS
        and clean(store.get("dispatcher_closeout_status")) != DISPATCHER_CLOSED_STATUS
    )


def closeout_difference(store):
    driver_counts = driver_counts_from_store(store)
    verified_counts = warehouse_verified_counts_from_store(store)
    return {
        component: verified_counts.get(component, 0) - driver_counts.get(component, 0)
        for component in driver_counts
    }


def find_store_for_closeout(stores, store_id):
    store_id = clean(store_id)
    if not store_id:
        raise ValueError("A store id is required.")

    for store in stores or []:
        if not isinstance(store, dict):
            continue
        if clean(store.get("id")) == store_id or clean(store.get("bol")) == store_id:
            return store

    raise LookupError("BOL was not found for dispatcher close-out.")


def validate_closeout(stores, store_id):
    if not isinstance(stores, list):
        raise ValueError("Stores must be provided as a list.")

    store = find_store_for_closeout(stores, store_id)
    if not is_ready_for_dispatcher_closeout(store):
        if clean(store.get("dispatcher_closeout_status")) == DISPATCHER_CLOSED_STATUS:
            return store
        raise ValueError("Warehouse receiving must be complete before dispatcher close-out.")
    if not isinstance(store.get("warehouse_verified_counts"), dict):
        raise ValueError("Warehouse verified component quantities are required before close-out.")
    return store


def append_audit_event(store, event, operator="", timestamp="", details=None):
    events = store.setdefault("audit_history", [])
    if not isinstance(events, list):
        events = []
        store["audit_history"] = events

    timestamp = clean(timestamp) or utc_now_iso()
    operator = clean(operator) or "system"
    if any(
        isinstance(item, dict)
        and clean(item.get("event")) == event
        and clean(item.get("timestamp")) == timestamp
        for item in events
    ):
        return

    payload = {
        "event": event,
        "timestamp": timestamp,
        "operator": operator,
        "action": event,
    }
    if isinstance(details, dict):
        payload.update(details)
    events.append(payload)


def ensure_operational_audit_history(store):
    if clean(store.get("completed_at")):
        append_audit_event(
            store,
            "Driver Completion",
            operator=store.get("completed_by") or store.get("driver_counts_saved_by") or store.get("assigned_driver"),
            timestamp=store.get("completed_at"),
            details={
                "driver_counts": driver_counts_from_store(store),
                "notes": clean(store.get("notes")),
                "driver_exception_type": clean(store.get("driver_exception_type")),
            },
        )

    if clean(store.get("received_at")):
        append_audit_event(
            store,
            "Warehouse Verification",
            operator=store.get("received_by"),
            timestamp=store.get("received_at"),
            details={
                "warehouse_verified_counts": warehouse_verified_counts_from_store(store),
                "warehouse_verified_racks": store.get("warehouse_verified_racks"),
                "warehouse_verified_pieces": store.get("warehouse_verified_pieces"),
                "damage_counts": damage_counts_from_store(store),
                "warehouse_notes": clean(store.get("warehouse_notes")),
            },
        )


def closeout_store(stores, store_id, closed_by="", notes=""):
    store = validate_closeout(stores, store_id)
    if clean(store.get("dispatcher_closeout_status")) == DISPATCHER_CLOSED_STATUS:
        result = deepcopy(store)
        result["already_closed"] = True
        return result

    now = utc_now_iso()
    verified_counts = warehouse_verified_counts_from_store(store)
    previous_status = clean(store.get("status"))
    ensure_operational_audit_history(store)

    store["dispatcher_closeout_status"] = DISPATCHER_CLOSED_STATUS
    store["dispatcher_closed_by"] = clean(closed_by) or "system"
    store["dispatcher_closed_at"] = now
    store["dispatcher_closeout_notes"] = clean(notes)
    store["inventory_updated_at"] = now
    store["inventory_updated_by"] = clean(closed_by) or "system"
    store["inventory_source"] = "Warehouse Verification"
    if previous_status.lower() in {"recovered", "exception"}:
        store["recovery_result_status"] = previous_status
    store["status"] = "Completed"
    store["closed_source"] = "EOMS"
    store["closed_at"] = now
    store["driver_estimated_earnings"] = round(float(store.get("warehouse_verified_pieces") or 0) * 0.05, 2)

    expected_racks = float(store.get("expected_racks") or 0)
    verified_racks = float(store.get("warehouse_verified_racks") or 0)
    store["variance"] = verified_racks - expected_racks
    expected_pieces = float(store.get("expected_pieces") or (expected_racks * PIECES_PER_RACK) or 0)
    store["pieces_variance"] = float(store.get("warehouse_verified_pieces") or 0) - expected_pieces
    store["variance_review"] = abs(float(store.get("variance") or 0)) >= 2

    append_audit_event(
        store,
        "Dispatcher Approval",
        operator=closed_by,
        timestamp=now,
        details={
            "notes": clean(notes),
            "driver_counts": driver_counts_from_store(store),
            "warehouse_verified_counts": verified_counts,
            "difference": closeout_difference(store),
            "inventory_weight": calculate_estimated_weight(verified_counts),
        },
    )

    return store


def refresh_route_closeout(routes, stores, store_id):
    updated = []
    store_id = clean(store_id)
    stores_by_id = {
        clean(store.get("id")): store
        for store in stores or []
        if isinstance(store, dict) and clean(store.get("id"))
    }

    for route in routes or []:
        if not isinstance(route, dict):
            continue
        route_store_ids = [clean(item) for item in route.get("store_ids") or []]
        if store_id not in route_store_ids:
            continue
        route_stores = [stores_by_id[item] for item in route_store_ids if item in stores_by_id]
        closed = [
            store for store in route_stores
            if clean(store.get("dispatcher_closeout_status")) == DISPATCHER_CLOSED_STATUS
        ]
        route["dispatcher_closeout_progress"] = {
            "closed_stops": len(closed),
            "total_stops": len(route_stores),
            "updated_at": utc_now_iso(),
        }
        if route_stores and len(closed) == len(route_stores):
            route["status"] = "Completed"
            route["closed_at"] = utc_now_iso()
        updated.append(route)

    return updated


def build_closeout_queue(stores=None, routes=None):
    route_info = route_lookup(routes or [])
    queue = []

    for store in stores or []:
        if not isinstance(store, dict):
            continue
        if (
            clean(store.get("receiving_status")) == RECEIVED_STATUS
            and clean(store.get("dispatcher_closeout_status")) != DISPATCHER_CLOSED_STATUS
        ):
            load = build_recovery_load(store, route_info.get(clean(store.get("id"))))
            load["difference"] = closeout_difference(store)
            load["damage_counts"] = damage_counts_from_store(store)
            load["damaged_component_total"] = total_damaged_components(store)
            queue.append(load)

    return sorted(queue, key=lambda load: clean(load.get("received_at")) or clean(load.get("completed_time")))


def build_closeout_workspace(stores=None, routes=None, selected_index=0):
    queue = build_closeout_queue(stores, routes)
    selected_load = None
    if queue:
        selected_index = max(0, min(int(selected_index or 0), len(queue) - 1))
        selected_load = queue[selected_index]

    total_difference = 0
    damage_total = 0
    for load in queue:
        total_difference += sum(abs(int(value or 0)) for value in (load.get("difference") or {}).values())
        damage_total += int(load.get("damaged_component_total") or 0)

    return {
        "component_names": COMPONENT_NAMES,
        "queue": queue,
        "selected_load": selected_load,
        "summary": {
            "awaiting_approval": len(queue),
            "variance_items": total_difference,
            "damage_items": damage_total,
        },
    }
