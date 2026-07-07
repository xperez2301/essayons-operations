from eoms_modules.driver_center_service import build_driver_workspace
from eoms_modules.fulfillment_service import SHIPPED_STATUS, build_fulfillment_workspace
from eoms_modules.inventory_service import build_inventory_workspace
from eoms_modules.receiving_service import build_receiving_workspace
from eoms_modules.recovery_center_service import clean, summarize_recovery_workspace_from_records
from eoms_modules.reporting_service import (
    fulfillment_metrics,
    inventory_metrics,
    receiving_metrics,
    recovery_metrics,
    safe_percent,
    status_class,
)


def status_label(status, healthy_values=None, warning_values=None):
    value = clean(status).upper()
    healthy_values = healthy_values or {"HEALTHY", "READY", "RUNNING", "OK", "COMPLETED"}
    warning_values = warning_values or {"DEGRADED", "WARNING", "ATTENTION", "BLOCKED", "FAILED"}

    if value in healthy_values:
        return "Healthy"
    if value in warning_values:
        return "Warning"
    if value in {"OFFLINE", "ERROR", "NO WORKERS", ""}:
        return "Offline"
    return "Warning"


def health_card(name, status, detail, href):
    return {
        "name": name,
        "status": status,
        "status_class": status_class(status),
        "detail": detail,
        "href": href,
    }


def stage(name, status, count, warning=False, href=""):
    return {
        "name": name,
        "status": status,
        "status_class": status_class(status),
        "count": count,
        "warning": bool(warning),
        "href": href,
    }


def automation_health(automation_status=None):
    automation_status = automation_status or {}
    raw_status = (
        automation_status.get("worker_health")
        or automation_status.get("status")
        or automation_status.get("worker_state")
        or ""
    )
    return status_label(raw_status)


def roadmap_snapshot(roadmap_workspace=None):
    roadmap_workspace = roadmap_workspace or {}
    era_ii = next(
        (
            era for era in roadmap_workspace.get("era_completion", [])
            if era.get("id") == "era-ii"
        ),
        {},
    )
    current = roadmap_workspace.get("current_build") or {}

    return {
        "current_build": clean(current.get("id")) or "Not set",
        "current_title": clean(current.get("title")) or "No current build",
        "completed_builds": roadmap_workspace.get("completed_builds", 0),
        "remaining_builds": roadmap_workspace.get("remaining_builds", 0),
        "era_ii_completed": era_ii.get("completed", 0),
        "era_ii_total": era_ii.get("total", 0),
        "era_ii_remaining": era_ii.get("remaining", 0),
        "era_ii_progress": era_ii.get("percent", 0),
        "overall_progress": roadmap_workspace.get("overall_completion", 0),
    }


def executive_kpis(recovery, receiving, inventory, fulfillment, automation, roadmap):
    return [
        {"label": "Active Recovery Routes", "value": recovery["recovery_routes"], "detail": "routes in recovery scope", "href": "/recovery"},
        {"label": "Recovered Stops", "value": recovery["recovered_stops"], "detail": "completed recovery stops", "href": "/recovery"},
        {"label": "Exception Stops", "value": recovery["exception_stops"], "detail": "driver exception stops", "href": "/driver"},
        {"label": "Pending Receipts", "value": receiving["pending_receipts"], "detail": "loads waiting receiving", "href": "/receiving"},
        {"label": "Inventory Components", "value": inventory["inventory_components"], "detail": "components on hand", "href": "/inventory"},
        {"label": "Open Fulfillment Orders", "value": fulfillment["open_orders"], "detail": "outbound orders open", "href": "/fulfillment"},
        {"label": "Shipped Orders", "value": fulfillment["shipped_orders"], "detail": "orders shipped", "href": "/fulfillment"},
        {"label": "Automation Health", "value": automation, "detail": "worker and queue status", "href": "/automation-center"},
        {"label": "Roadmap Progress", "value": f"{roadmap['era_ii_progress']}%", "detail": "Era II completion", "href": "/roadmap"},
    ]


def operational_pipeline(recovery, driver_workspace, receiving, inventory, fulfillment, reporting_ready):
    driver_summary = driver_workspace.get("summary", {})
    active_driver_stops = driver_summary.get("stop_count", 0)
    driver_warnings = recovery["exception_stops"] > 0
    inventory_warnings = inventory["inventory_components"] == 0
    fulfillment_warnings = fulfillment["open_orders"] > 0

    return [
        stage("RMS", "Healthy" if recovery["total_recovery_stops"] else "Warning", recovery["total_recovery_stops"], not recovery["total_recovery_stops"], "/all-bols"),
        stage("Recovery", "Warning" if recovery["exception_stops"] else "Healthy", recovery["recovered_stops"], recovery["exception_stops"], "/recovery"),
        stage("Driver", "Warning" if driver_warnings else "Healthy", active_driver_stops, driver_warnings, "/driver"),
        stage("Receiving", "Warning" if receiving["pending_receipts"] else "Healthy", receiving["pending_receipts"], receiving["pending_receipts"], "/receiving"),
        stage("Inventory", "Warning" if inventory_warnings else "Healthy", inventory["inventory_components"], inventory_warnings, "/inventory"),
        stage("Fulfillment", "Warning" if fulfillment_warnings else "Healthy", fulfillment["open_orders"], fulfillment_warnings, "/fulfillment"),
        stage("Reporting", "Healthy" if reporting_ready else "Warning", 1 if reporting_ready else 0, not reporting_ready, "/reporting"),
    ]


def domain_health(
    recovery,
    driver_workspace,
    receiving,
    inventory,
    fulfillment,
    reporting_ready,
    automation,
    roadmap,
):
    driver_summary = driver_workspace.get("summary", {})

    return [
        health_card("Recovery", "Warning" if recovery["exception_stops"] else "Healthy", f"{recovery['recovery_routes']} routes", "/recovery"),
        health_card("Driver", "Warning" if recovery["exception_stops"] else "Healthy", f"{driver_summary.get('stop_count', 0)} active stops", "/driver"),
        health_card("Receiving", "Warning" if receiving["pending_receipts"] else "Healthy", f"{receiving['pending_receipts']} pending receipts", "/receiving"),
        health_card("Inventory", "Warning" if inventory["inventory_components"] == 0 else "Healthy", f"{inventory['inventory_components']} components", "/inventory"),
        health_card("Fulfillment", "Warning" if fulfillment["open_orders"] else "Healthy", f"{fulfillment['open_orders']} open orders", "/fulfillment"),
        health_card("Reporting", "Healthy" if reporting_ready else "Warning", "Read-only workspace online" if reporting_ready else "No reporting data", "/reporting"),
        health_card("Automation", automation, "Worker and queue health", "/automation-center"),
        health_card("Roadmap", "Healthy" if roadmap["current_build"] != "Not set" else "Warning", f"{roadmap['current_build']} current", "/roadmap"),
    ]


def exception_alerts(recovery_workspace, receiving_workspace, inventory_workspace, fulfillment_workspace, automation_jobs=None):
    alerts = []

    for item in (recovery_workspace.get("exceptions") or [])[:6]:
        alerts.append({
            "type": "Driver Exception",
            "status": "Warning",
            "detail": f"{item.get('store', 'Stop')} / {item.get('type', 'Exception')}",
            "when": item.get("reported_at") or "Not set",
            "href": "/driver",
        })

    for load in (receiving_workspace.get("pending_loads") or [])[:6]:
        alerts.append({
            "type": "Pending Receipt",
            "status": "Warning",
            "detail": f"{load.get('store', 'Load')} / {load.get('bol', 'No BOL')}",
            "when": load.get("completed_time") or "Not set",
            "href": "/receiving",
        })

    for row in inventory_workspace.get("inventory") or []:
        if row.get("available", 0) <= 0:
            alerts.append({
                "type": "Low Inventory",
                "status": "Warning",
                "detail": f"{row.get('component', 'Component')} has {row.get('available', 0)} available",
                "when": row.get("last_updated") or "Not updated",
                "href": "/inventory",
            })

    for order in (fulfillment_workspace.get("orders") or [])[:8]:
        if clean(order.get("status")) != SHIPPED_STATUS:
            alerts.append({
                "type": "Open Order",
                "status": "Warning",
                "detail": f"{order.get('order_number', 'Order')} / {order.get('customer', 'Customer')}",
                "when": order.get("reserved_at") or "Not set",
                "href": "/fulfillment",
            })

    for job in automation_jobs or []:
        if clean(job.get("status")).upper() in {"BLOCKED", "FAILED"}:
            alerts.append({
                "type": "Automation Job",
                "status": "Warning",
                "detail": f"{job.get('worker', 'Worker')} / {job.get('action', 'job')} {job.get('status', '')}",
                "when": job.get("finished_at") or job.get("created_at") or "Not set",
                "href": "/automation-center",
            })

    return sorted(alerts, key=lambda alert: alert["when"], reverse=True)[:12]


def recent_activity(stores, receiving_workspace, inventory_workspace, fulfillment_workspace, automation_jobs=None):
    events = []

    for store in stores or []:
        if not isinstance(store, dict):
            continue
        status = clean(store.get("status"))
        if status.lower() in {"recovered", "exception"}:
            events.append({
                "type": "Exception" if status.lower() == "exception" else "Recovery",
                "label": clean(store.get("store_name") or store.get("store")) or "Recovered stop",
                "detail": clean(store.get("bol")) or "No BOL",
                "timestamp": clean(store.get("completed_at") or store.get("driver_exception_reported_at") or store.get("updated_at")) or "Not set",
                "status": status,
                "status_class": "danger" if status.lower() == "exception" else "success",
            })

    for load in receiving_workspace.get("history") or []:
        events.append({
            "type": "Receipt",
            "label": load.get("store", "Received load"),
            "detail": load.get("bol", "No BOL"),
            "timestamp": load.get("received_at") or "Not set",
            "status": "Received",
            "status_class": "success",
        })

    for event in inventory_workspace.get("history") or []:
        events.append({
            "type": "Inventory Adjustment",
            "label": event.get("component", "Inventory"),
            "detail": event.get("reason", "Adjustment"),
            "timestamp": event.get("date") or "Not set",
            "status": event.get("amount", 0),
            "status_class": "warning",
        })

    for event in fulfillment_workspace.get("history") or []:
        if event.get("type") != "Shipment":
            continue
        events.append({
            "type": "Shipment",
            "label": event.get("order_number", "Shipment"),
            "detail": event.get("customer", "Customer"),
            "timestamp": event.get("date") or "Not set",
            "status": event.get("status", "Shipped"),
            "status_class": "success",
        })

    for job in automation_jobs or []:
        events.append({
            "type": "Automation",
            "label": job.get("worker", "Worker"),
            "detail": job.get("action", "job"),
            "timestamp": job.get("finished_at") or job.get("created_at") or "Not set",
            "status": job.get("status", "Unknown"),
            "status_class": "danger" if clean(job.get("status")).upper() in {"FAILED", "BLOCKED"} else "success",
        })

    return sorted(events, key=lambda event: event["timestamp"], reverse=True)[:14]


def build_command_center_workspace(
    stores=None,
    routes=None,
    roadmap_workspace=None,
    automation_status=None,
    automation_jobs=None,
):
    stores = stores if isinstance(stores, list) else []
    routes = routes if isinstance(routes, list) else []
    automation_jobs = automation_jobs if isinstance(automation_jobs, list) else []

    recovery_workspace = summarize_recovery_workspace_from_records(routes, stores)
    driver_workspace = build_driver_workspace(routes, stores)
    receiving_workspace = build_receiving_workspace(stores, routes)
    inventory_workspace = build_inventory_workspace(stores)
    fulfillment_workspace = build_fulfillment_workspace(stores)

    recovery = recovery_metrics(stores, routes, recovery_workspace)
    receiving = receiving_metrics(receiving_workspace)
    inventory = inventory_metrics(stores, inventory_workspace)
    fulfillment = fulfillment_metrics(stores, fulfillment_workspace)
    automation = automation_health(automation_status)
    roadmap = roadmap_snapshot(roadmap_workspace)
    reporting_ready = bool(stores or routes or roadmap_workspace)

    system_status = "Warning" if automation == "Warning" else "Healthy"

    return {
        "kpis": executive_kpis(recovery, receiving, inventory, fulfillment, automation, roadmap),
        "pipeline": operational_pipeline(recovery, driver_workspace, receiving, inventory, fulfillment, reporting_ready),
        "domain_health": domain_health(recovery, driver_workspace, receiving, inventory, fulfillment, reporting_ready, automation, roadmap),
        "alerts": exception_alerts(recovery_workspace, receiving_workspace, inventory_workspace, fulfillment_workspace, automation_jobs),
        "roadmap": roadmap,
        "recent_activity": recent_activity(stores, receiving_workspace, inventory_workspace, fulfillment_workspace, automation_jobs),
        "read_only": True,
        "system_health": {
            "status": system_status,
            "status_class": status_class(system_status),
            "automation": automation,
            "pipeline_warnings": sum(1 for item in operational_pipeline(recovery, driver_workspace, receiving, inventory, fulfillment, reporting_ready) if item["warning"]),
            "roadmap_progress": roadmap["era_ii_progress"],
            "operational_progress": safe_percent(recovery["recovered_stops"], recovery["total_recovery_stops"]),
        },
    }
