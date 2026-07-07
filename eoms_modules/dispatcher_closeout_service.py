from datetime import datetime, timezone

from eoms_modules.receiving_service import (
    DISPATCHER_CLOSED_STATUS,
    RECEIVED_STATUS,
    warehouse_verified_counts_from_store,
)
from eoms_modules.recovery_center_service import (
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


def validate_closeout(stores, store_id):
    if not isinstance(stores, list):
        raise ValueError("Stores must be provided as a list.")

    store_id = clean(store_id)
    if not store_id:
        raise ValueError("A store id is required.")

    for store in stores:
        if not isinstance(store, dict):
            continue
        if clean(store.get("id")) != store_id and clean(store.get("bol")) != store_id:
            continue
        if not is_ready_for_dispatcher_closeout(store):
            if clean(store.get("dispatcher_closeout_status")) == DISPATCHER_CLOSED_STATUS:
                raise ValueError("This BOL has already been closed out by Dispatch.")
            raise ValueError("Warehouse receiving must be complete before dispatcher close-out.")
        if not isinstance(store.get("warehouse_verified_counts"), dict):
            raise ValueError("Warehouse verified component quantities are required before close-out.")
        return store

    raise LookupError("BOL was not found for dispatcher close-out.")


def closeout_store(stores, store_id, closed_by="", notes=""):
    store = validate_closeout(stores, store_id)
    now = utc_now_iso()
    verified_counts = warehouse_verified_counts_from_store(store)
    previous_status = clean(store.get("status"))

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

    events = store.setdefault("audit_history", [])
    if not isinstance(events, list):
        events = []
        store["audit_history"] = events
    events.append({
        "event": "Dispatcher Close-Out",
        "timestamp": now,
        "operator": clean(closed_by) or "system",
        "notes": clean(notes),
        "driver_counts": driver_counts_from_store(store),
        "warehouse_verified_counts": verified_counts,
        "difference": closeout_difference(store),
        "inventory_weight": calculate_estimated_weight(verified_counts),
    })

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
