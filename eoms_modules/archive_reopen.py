"""Reopen an archived BOL without deleting its document or audit trail."""
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo
from eoms_modules.driver_center_service import store_ids_for_route


def reopen_archived_bol(stores, routes, store_id, operator):
    store = next((row for row in stores if str(row.get("id")) == str(store_id)), None)
    if not store:
        raise LookupError("BOL not found.")
    if store.get("archive_reopened_at") and store.get("status") in {"Unassigned", "Need Review"} and not store.get("completed_at"):
        return store, False
    archived = store.get("status") == "Completed" or store.get("archive_status_updated_at") or store.get("rms_status") in {"Missing from RMS", "Closed in RMS"}
    if not archived:
        raise ValueError("This BOL is not archived.")
    if store.get("status") in {"Assigned", "Dispatched", "In Progress", "Accepted"}:
        raise ValueError("This BOL is already assigned to an active route.")
    now = datetime.now(ZoneInfo("America/Chicago")).isoformat(timespec="seconds")
    snapshot = deepcopy({key:value for key,value in store.items() if key != "audit_history"})
    prefixes = ("driver_", "warehouse_", "received_", "receiving_", "dispatcher_", "inventory_", "completed_", "closed_", "archive_status_")
    reset_keys = {"assigned_driver", "route_id", "truck", "helper", "truck_status", "collected_racks", "collected_pieces", "variance", "pieces_variance", "variance_review", "recovery_result_status", "no_pickup_manager_name", "no_pickup_photos", "notes"}
    for key in list(store):
        if key.startswith(prefixes) or key in reset_keys:
            store.pop(key, None)
    store.update(status="Need Review" if store.get("review_reasons") else "Unassigned",updated_at=now,archive_reopened_at=now,archive_reopened_by=operator)
    history = store.get("audit_history")
    if not isinstance(history, list):
        history = [];store["audit_history"] = history
    history.append({"event":"BOL Returned to Pickups","timestamp":now,"operator":operator,"previous_record":snapshot})
    for route in routes:
        ids = store_ids_for_route(route)
        if store_id not in ids and route.get("id") != snapshot.get("route_id"):
            continue
        route.setdefault("reopened_bols", []).append({"id":store_id,"bol":store.get("bol"),"timestamp":now})
        route["store_ids"] = [id for id in ids if id != store_id]
        for key in ("stops", "recovery_stops"):
            if isinstance(route.get(key), list):
                route[key] = [stop for stop in route[key] if ((stop.get("store_id") or stop.get("id")) if isinstance(stop,dict) else stop) != store_id]
        remaining = [row for row in stores if row.get("id") in route["store_ids"]]
        metrics = route.get("metrics")
        if isinstance(metrics,dict):
            metrics.update(store_count=len(remaining),weight=sum(float(row.get("weight") or 0) for row in remaining),racks=sum(float(row.get("expected_racks") or 0) for row in remaining),pieces=sum(float(row.get("expected_pieces") or 0) for row in remaining))
        if not remaining:
            route["status"] = "Cancelled"
    return store, True
