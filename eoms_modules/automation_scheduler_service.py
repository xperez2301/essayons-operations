from copy import deepcopy
from datetime import datetime, timedelta, timezone


DEFAULT_INTERVAL_SECONDS = 900

DEFAULT_SCHEDULER_STATE = {
    "enabled": False,
    "running": False,
    "interval_seconds": DEFAULT_INTERVAL_SECONDS,
    "last_run": "",
    "next_run": "",
    "health": "PAUSED",
}


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean(value):
    return "" if value is None else str(value).strip()


def ensure_operational_domain(store):
    if not isinstance(store, dict):
        raise ValueError("Scheduler state requires a store dictionary.")

    operational = store.get("operational")
    if not isinstance(operational, dict):
        operational = {}
        store["operational"] = operational

    automation = operational.get("automation")
    if not isinstance(automation, dict):
        automation = {}
        operational["automation"] = automation

    return automation


def normalize_scheduler_state(state):
    normalized = deepcopy(DEFAULT_SCHEDULER_STATE)

    if isinstance(state, dict):
        normalized.update({
            "enabled": bool(state.get("enabled", normalized["enabled"])),
            "running": bool(state.get("running", normalized["running"])),
            "interval_seconds": int(state.get("interval_seconds") or normalized["interval_seconds"]),
            "last_run": clean(state.get("last_run")),
            "next_run": clean(state.get("next_run")),
            "health": clean(state.get("health")) or normalized["health"],
        })

    if normalized["interval_seconds"] < 1:
        normalized["interval_seconds"] = DEFAULT_INTERVAL_SECONDS

    if not normalized["enabled"]:
        normalized["running"] = False
        normalized["health"] = "PAUSED"
    elif normalized["running"]:
        normalized["health"] = "RUNNING"
    elif normalized["health"] == "PAUSED":
        normalized["health"] = "READY"

    return normalized


def ensure_scheduler_state(store):
    automation = ensure_operational_domain(store)
    state = normalize_scheduler_state(automation.get("scheduler"))
    automation["scheduler"] = state
    return state


def get_scheduler_state(store):
    return dict(ensure_scheduler_state(store))


def pause_scheduler(store):
    return update_scheduler_state(
        store,
        enabled=False,
        running=False,
        next_run="",
        health="PAUSED",
    )


def resume_scheduler(store):
    state = ensure_scheduler_state(store)
    interval_seconds = int(state.get("interval_seconds") or DEFAULT_INTERVAL_SECONDS)
    next_run = datetime.now(timezone.utc) + timedelta(seconds=interval_seconds)

    return update_scheduler_state(
        store,
        enabled=True,
        running=False,
        next_run=next_run.isoformat(),
        health="READY",
    )


def update_scheduler_state(
    store,
    enabled=None,
    running=None,
    interval_seconds=None,
    last_run=None,
    next_run=None,
    health=None,
):
    state = ensure_scheduler_state(store)

    if enabled is not None:
        state["enabled"] = bool(enabled)

    if running is not None:
        state["running"] = bool(running)

    if interval_seconds is not None:
        interval_seconds = int(interval_seconds)
        if interval_seconds < 1:
            raise ValueError("interval_seconds must be greater than zero.")
        state["interval_seconds"] = interval_seconds

    if last_run is not None:
        state["last_run"] = clean(last_run)

    if next_run is not None:
        state["next_run"] = clean(next_run)

    if health is not None:
        state["health"] = clean(health) or state.get("health") or "UNKNOWN"

    normalized = normalize_scheduler_state(state)
    ensure_operational_domain(store)["scheduler"] = normalized
    return normalized
