from eoms_modules.fulfillment_service import (
    SHIPPED_STATUS,
    build_fulfillment_workspace,
    fulfillment_orders,
)
from eoms_modules.inventory_service import (
    adjustment_entries,
    build_inventory_workspace,
)
from eoms_modules.receiving_service import build_receiving_workspace
from eoms_modules.recovery_center_service import (
    calculate_estimated_weight,
    clean,
    driver_counts_from_store,
    empty_component_counts,
    summarize_recovery_workspace_from_records,
)


def safe_percent(part, whole):
    if not whole:
        return 0
    return round((part / whole) * 100)


def status_class(status):
    status = clean(status).lower()
    if status == "healthy":
        return "success"
    if status == "warning":
        return "warning"
    if status == "offline":
        return "danger"
    return "neutral"


COMPLETED_STORE_STATUSES = {"completed", "recovered", "exception"}
COMPLETED_ROUTE_STATUSES = {"completed", "recovered", "exception", "closed"}


def is_completed_store(store):
    if not isinstance(store, dict):
        return False
    if clean(store.get("status")).lower() in COMPLETED_STORE_STATUSES:
        return True
    if clean(store.get("receiving_status")).lower() == "received":
        return True
    return any(
        isinstance(order, dict) and clean(order.get("status")) == SHIPPED_STATUS
        for order in store.get("fulfillment_orders") or []
    )


def is_completed_route(route):
    if not isinstance(route, dict):
        return False
    status = clean(route.get("status")).lower()
    if status in COMPLETED_ROUTE_STATUSES:
        return True
    return bool(clean(route.get("completed_at") or route.get("closed_at")))


def completed_reporting_stores(stores=None):
    return [
        store for store in stores or []
        if is_completed_store(store)
    ]


def completed_reporting_routes(routes=None):
    return [
        route for route in routes or []
        if is_completed_route(route)
    ]


def recovery_metrics(stores=None, routes=None, recovery_workspace=None):
    stores = stores if isinstance(stores, list) else []
    routes = routes if isinstance(routes, list) else []

    recovered_stores = [
        store for store in stores
        if clean(store.get("status")).lower() == "recovered"
    ]
    exception_stores = [
        store for store in stores
        if clean(store.get("status")).lower() == "exception"
    ]
    recovered_totals = empty_component_counts()

    for store in recovered_stores + exception_stores:
        counts = driver_counts_from_store(store)
        for component in recovered_totals:
            recovered_totals[component] += counts[component]

    completed_count = len(recovered_stores) + len(exception_stores)

    return {
        "recovery_routes": len(completed_reporting_routes(routes)),
        "recovered_stops": len(recovered_stores),
        "exception_stops": len(exception_stores),
        "total_recovery_stops": completed_count,
        "completed_recovery_stops": completed_count,
        "recovery_rate": safe_percent(completed_count, completed_count),
        "estimated_recovery_weight": calculate_estimated_weight(recovered_totals),
    }


def receiving_metrics(receiving_workspace=None):
    receiving_workspace = receiving_workspace or build_receiving_workspace()
    summary = receiving_workspace.get("summary", {})

    return {
        "pending_receipts": summary.get("pending_receipts", 0),
        "received_today": summary.get("received_today", 0),
        "received_loads": len(receiving_workspace.get("history") or []),
        "received_weight": summary.get("estimated_weight_received", 0),
    }


def inventory_metrics(stores=None, inventory_workspace=None):
    stores = stores if isinstance(stores, list) else []
    inventory_workspace = inventory_workspace or build_inventory_workspace(stores)
    summary = inventory_workspace.get("summary", {})

    return {
        "inventory_components": summary.get("total_components", 0),
        "available_inventory": summary.get("available_inventory", 0),
        "reserved_inventory": summary.get("reserved_inventory", 0),
        "inventory_adjustments": len(adjustment_entries(stores)),
        "inventory_weight": summary.get("inventory_weight", 0),
    }


def fulfillment_metrics(stores=None, fulfillment_workspace=None):
    stores = stores if isinstance(stores, list) else []
    fulfillment_workspace = fulfillment_workspace or build_fulfillment_workspace(stores)
    orders = fulfillment_workspace.get("orders") or []
    summary = fulfillment_workspace.get("summary", {})
    shipped_orders = [
        order for order in orders
        if clean(order.get("status")) == SHIPPED_STATUS
    ]

    return {
        "open_orders": 0,
        "reserved_orders": 0,
        "shipped_orders": len(shipped_orders),
        "reservation_rate": 0,
        "outbound_weight": summary.get("outbound_weight", 0),
        "components_reserved": 0,
    }


def build_recovery_timeline(stores=None):
    events = []

    for store in stores or []:
        if not isinstance(store, dict):
            continue

        status = clean(store.get("status"))
        if status.lower() not in {"recovered", "exception"}:
            continue

        events.append({
            "type": "Recovery",
            "status": status,
            "label": clean(store.get("store_name") or store.get("store")) or "Recovered Stop",
            "detail": clean(store.get("bol")) or "No BOL",
            "timestamp": clean(store.get("completed_at") or store.get("recovered_at") or store.get("updated_at")) or "Not set",
            "status_class": "danger" if status.lower() == "exception" else "success",
        })

    return events


def build_receipt_timeline(receiving_workspace=None):
    events = []

    for load in (receiving_workspace or {}).get("history") or []:
        events.append({
            "type": "Receipt",
            "status": "Received",
            "label": load.get("store", "Received Load"),
            "detail": load.get("bol", "No BOL"),
            "timestamp": load.get("received_at") or "Not set",
            "status_class": "success",
        })

    return events


def build_adjustment_timeline(stores=None):
    events = []

    for entry in adjustment_entries(stores):
        events.append({
            "type": "Inventory Adjustment",
            "status": entry.get("amount", 0),
            "label": entry.get("component", "Inventory"),
            "detail": entry.get("reason", "Adjustment"),
            "timestamp": entry.get("adjusted_at") or "Not set",
            "status_class": "warning",
        })

    return events


def build_shipment_timeline(stores=None):
    events = []

    for order in fulfillment_orders(stores):
        if clean(order.get("status")) != SHIPPED_STATUS:
            continue

        events.append({
            "type": "Shipment",
            "status": SHIPPED_STATUS,
            "label": order.get("order_number", "Shipment"),
            "detail": order.get("customer", "Customer"),
            "timestamp": order.get("shipped_at") or "Not set",
            "status_class": "success",
        })

    return events


def build_operational_timeline(stores=None, receiving_workspace=None):
    events = []
    events.extend(build_recovery_timeline(stores))
    events.extend(build_receipt_timeline(receiving_workspace))
    events.extend(build_adjustment_timeline(stores))
    events.extend(build_shipment_timeline(stores))
    return sorted(events, key=lambda event: event["timestamp"], reverse=True)


def health_card(name, status, detail):
    return {
        "name": name,
        "status": status,
        "status_class": status_class(status),
        "detail": detail,
    }


def build_domain_health(
    recovery_workspace=None,
    receiving_workspace=None,
    inventory_workspace=None,
    fulfillment_workspace=None,
    roadmap_workspace=None,
    automation_status=None,
):
    recovery_summary = (recovery_workspace or {}).get("summary", {})
    receiving_summary = (receiving_workspace or {}).get("summary", {})
    inventory_summary = (inventory_workspace or {}).get("summary", {})
    fulfillment_summary = (fulfillment_workspace or {}).get("summary", {})
    roadmap_current = (roadmap_workspace or {}).get("current_build") or {}
    automation_status = automation_status or {}

    automation_health = clean(automation_status.get("status") or automation_status.get("worker_health"))
    if automation_health.upper() in {"HEALTHY", "READY"}:
        automation_label = "Healthy"
    elif automation_health:
        automation_label = "Warning"
    else:
        automation_label = "Offline"

    return [
        health_card(
            "Recovery",
            "Healthy" if recovery_summary.get("route_count", 0) else "Warning",
            f"{recovery_summary.get('route_count', 0)} routes",
        ),
        health_card(
            "Driver",
            "Healthy" if recovery_summary.get("completed_stops", 0) else "Warning",
            f"{recovery_summary.get('completed_stops', 0)} completed stops",
        ),
        health_card(
            "Receiving",
            "Warning" if receiving_summary.get("pending_receipts", 0) else "Healthy",
            f"{receiving_summary.get('pending_receipts', 0)} pending receipts",
        ),
        health_card(
            "Inventory",
            "Healthy" if inventory_summary.get("total_components", 0) else "Warning",
            f"{inventory_summary.get('total_components', 0)} components",
        ),
        health_card(
            "Fulfillment",
            "Healthy" if fulfillment_summary.get("open_orders", 0) or fulfillment_summary.get("orders_shipped", 0) else "Warning",
            f"{fulfillment_summary.get('open_orders', 0)} open orders",
        ),
        health_card(
            "Roadmap",
            "Healthy" if roadmap_current else "Warning",
            clean(roadmap_current.get("id")) or "No current build",
        ),
        health_card(
            "Automation",
            automation_label,
            automation_health or "Status unavailable",
        ),
    ]


def build_executive_kpis(recovery, receiving, inventory, fulfillment):
    return [
        {"label": "Recovery Routes", "value": recovery["recovery_routes"], "detail": "active recovery domain"},
        {"label": "Recovered Stops", "value": recovery["recovered_stops"], "detail": "completed recoveries"},
        {"label": "Exception Stops", "value": recovery["exception_stops"], "detail": "driver exceptions"},
        {"label": "Received Loads", "value": receiving["received_loads"], "detail": "warehouse receipts"},
        {"label": "Inventory Components", "value": inventory["inventory_components"], "detail": "stock on hand"},
        {"label": "Open Orders", "value": fulfillment["open_orders"], "detail": "outbound work"},
        {"label": "Shipped Orders", "value": fulfillment["shipped_orders"], "detail": "completed shipments"},
        {"label": "Estimated Recovery Weight", "value": f"{recovery['estimated_recovery_weight']} lbs", "detail": "recovered material"},
        {"label": "Estimated Inventory Weight", "value": f"{inventory['inventory_weight']} lbs", "detail": "warehouse stock"},
        {"label": "Estimated Outbound Weight", "value": f"{fulfillment['outbound_weight']} lbs", "detail": "reserved and shipped"},
    ]


def build_reporting_workspace(
    stores=None,
    routes=None,
    roadmap_workspace=None,
    automation_status=None,
):
    stores = stores if isinstance(stores, list) else []
    routes = routes if isinstance(routes, list) else []

    reporting_stores = completed_reporting_stores(stores)
    reporting_routes = completed_reporting_routes(routes)

    recovery_workspace = summarize_recovery_workspace_from_records(reporting_routes, reporting_stores)
    receiving_workspace = build_receiving_workspace(reporting_stores, reporting_routes)
    inventory_workspace = build_inventory_workspace(reporting_stores)
    fulfillment_workspace = build_fulfillment_workspace(reporting_stores)

    recovery = recovery_metrics(reporting_stores, reporting_routes, recovery_workspace)
    receiving = receiving_metrics(receiving_workspace)
    inventory = inventory_metrics(reporting_stores, inventory_workspace)
    fulfillment = fulfillment_metrics(reporting_stores, fulfillment_workspace)

    return {
        "kpis": build_executive_kpis(recovery, receiving, inventory, fulfillment),
        "recovery": recovery,
        "receiving": receiving,
        "inventory": inventory,
        "fulfillment": fulfillment,
        "timeline": build_operational_timeline(reporting_stores, receiving_workspace),
        "domain_health": build_domain_health(
            recovery_workspace=recovery_workspace,
            receiving_workspace=receiving_workspace,
            inventory_workspace=inventory_workspace,
            fulfillment_workspace=fulfillment_workspace,
            roadmap_workspace=roadmap_workspace,
            automation_status=automation_status,
        ),
    }
