from datetime import datetime
from uuid import uuid4


OPEN_EXCEPTION_STATUSES = {"", "Open", "Acknowledged"}


def clean(value):
    return str(value or "").strip()


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def ensure_operational_domain(store):
    operational = store.get("operational")
    if not isinstance(operational, dict):
        operational = {}
        store["operational"] = operational

    if not isinstance(operational.get("exceptions"), list):
        operational["exceptions"] = []

    if not isinstance(operational.get("history"), list):
        operational["history"] = []

    if not isinstance(operational.get("worker_state"), dict):
        operational["worker_state"] = {}

    if not isinstance(operational.get("automation"), dict):
        operational["automation"] = {}

    if not isinstance(operational.get("flags"), dict):
        operational["flags"] = {}

    if not isinstance(operational.get("metrics"), dict):
        operational["metrics"] = {}

    return operational


def normalize_operational_record(store):
    ensure_operational_domain(store)
    return store


def operational_exceptions(store):
    return ensure_operational_domain(store)["exceptions"]


def get_open_exceptions(store, exception_type=""):
    exception_type = clean(exception_type)
    results = []

    for exception in operational_exceptions(store):
        if not isinstance(exception, dict):
            continue

        status = clean(exception.get("status"))
        if status not in OPEN_EXCEPTION_STATUSES:
            continue

        if exception_type and clean(exception.get("type")) != exception_type:
            continue

        results.append(exception)

    return results


def has_open_exception(store, exception_type):
    return bool(get_open_exceptions(store, exception_type))


def add_operational_history(store, action, details=None, actor="system"):
    operational = ensure_operational_domain(store)
    event = {
        "id": str(uuid4()),
        "action": clean(action),
        "actor": clean(actor) or "system",
        "created_at": now_iso(),
        "details": details or {},
    }
    operational["history"].append(event)
    return event


def ensure_operational_exception(
    store,
    exception_type,
    queue="Operational Queue",
    source_worker="System",
    severity="Warning",
    message="",
    payload=None,
):
    operational = ensure_operational_domain(store)
    exception_type = clean(exception_type)
    now = now_iso()

    for exception in operational["exceptions"]:
        if not isinstance(exception, dict):
            continue

        same_type = clean(exception.get("type")) == exception_type
        open_status = clean(exception.get("status")) in OPEN_EXCEPTION_STATUSES

        if same_type and open_status:
            exception["status"] = clean(exception.get("status")) or "Open"
            exception["queue"] = queue
            exception["source_worker"] = source_worker
            exception["severity"] = severity
            exception["message"] = message or exception.get("message", "")
            exception["last_seen_at"] = now
            exception["payload"] = payload or exception.get("payload", {})
            store["updated_at"] = now

            add_operational_history(
                store,
                "Exception Updated",
                {
                    "type": exception_type,
                    "queue": queue,
                    "source_worker": source_worker,
                    "severity": severity,
                },
            )
            return exception

    exception = {
        "id": str(uuid4()),
        "type": exception_type,
        "queue": queue,
        "status": "Open",
        "severity": severity,
        "source_worker": source_worker,
        "message": message,
        "detected_at": now,
        "last_seen_at": now,
        "acknowledged_at": "",
        "acknowledged_by": "",
        "resolved_at": "",
        "resolved_by": "",
        "resolution": "",
        "payload": payload or {},
    }

    operational["exceptions"].append(exception)
    store["updated_at"] = now

    add_operational_history(
        store,
        "Exception Created",
        {
            "type": exception_type,
            "queue": queue,
            "source_worker": source_worker,
            "severity": severity,
        },
    )

    return exception


def acknowledge_operational_exception(
    store,
    exception_type,
    acknowledged_by="system",
):
    now = now_iso()
    changed = 0

    for exception in get_open_exceptions(store, exception_type):
        if clean(exception.get("status")) == "Open":
            exception["status"] = "Acknowledged"
            exception["acknowledged_at"] = now
            exception["acknowledged_by"] = clean(acknowledged_by) or "system"
            changed += 1

    if changed:
        store["updated_at"] = now
        add_operational_history(
            store,
            "Exception Acknowledged",
            {
                "type": clean(exception_type),
                "count": changed,
                "acknowledged_by": clean(acknowledged_by) or "system",
            },
        )

    return changed


def resolve_operational_exception(
    store,
    exception_type,
    resolved_by="system",
    resolution="",
):
    now = now_iso()
    changed = 0

    for exception in get_open_exceptions(store, exception_type):
        exception["status"] = "Resolved"
        exception["resolved_at"] = now
        exception["resolved_by"] = clean(resolved_by) or "system"
        exception["resolution"] = clean(resolution)
        changed += 1

    if changed:
        store["updated_at"] = now
        add_operational_history(
            store,
            "Exception Resolved",
            {
                "type": clean(exception_type),
                "count": changed,
                "resolved_by": clean(resolved_by) or "system",
                "resolution": clean(resolution),
            },
        )

    return changed


def stores_with_open_exception(stores, exception_type=""):
    return [
        store
        for store in stores
        if get_open_exceptions(store, exception_type)
    ]