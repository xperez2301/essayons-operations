from eoms_modules.automation_policy_service import (
    AUTOMATIC,
    APPROVAL_REQUIRED,
    BLOCKED,
    get_job_policy,
)
from eoms_modules.automation_scheduler_service import get_scheduler_state


DEFAULT_MAX_RETRIES = 3

JOB_TYPE_ALIASES = {
    "worker_status": "worker_status_check",
    "worker_status_check": "worker_status_check",
    "queue_health": "queue_health_check",
    "queue_health_check": "queue_health_check",
    "scheduler_health": "scheduler_health_check",
    "scheduler_health_check": "scheduler_health_check",
    "database_validation": "database_validation_read_only",
    "database_validation_read_only": "database_validation_read_only",
    "exception_scan": "exception_scan_report",
    "exception_scan_report": "exception_scan_report",
    "rms_auto_grab": "rms_auto_grab",
    "rms_import": "rms_import",
}


def clean(value):
    return "" if value is None else str(value).strip()


def decision(allowed, reason, policy=None, job_type="", details=None):
    return {
        "allowed": bool(allowed),
        "reason": reason,
        "job_type": job_type,
        "policy": policy or {},
        "details": details or {},
    }


def job_payload(job):
    if not isinstance(job, dict):
        return {}

    payload = job.get("payload")
    return payload if isinstance(payload, dict) else {}


def normalize_job_type(job):
    payload = job_payload(job)
    raw_job_type = clean(payload.get("job_type") or job.get("job_type") if isinstance(job, dict) else "")

    if not raw_job_type and isinstance(job, dict):
        action = clean(job.get("action")).lower()
        worker = clean(job.get("worker")).lower()

        if action == "worker_status":
            raw_job_type = "worker_status"
        elif action == "run" and worker == "rms worker":
            raw_job_type = "rms_auto_grab"
        else:
            raw_job_type = action

    normalized = raw_job_type.lower()
    return JOB_TYPE_ALIASES.get(normalized, normalized)


def automation_state(store):
    if not isinstance(store, dict):
        return {}

    operational = store.get("operational")
    if not isinstance(operational, dict):
        return {}

    automation = operational.get("automation")
    return automation if isinstance(automation, dict) else {}


def kill_switch_enabled(store):
    automation = automation_state(store)
    return bool(
        automation.get("kill_switch")
        or automation.get("kill_switch_enabled")
        or automation.get("automation_paused")
        or automation.get("stop_automation")
    )


def retry_count(job):
    if not isinstance(job, dict):
        return 0

    payload = job_payload(job)
    for key in ("retry_count", "retries", "attempts"):
        value = job.get(key, payload.get(key))
        if value in (None, ""):
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return DEFAULT_MAX_RETRIES

    return 0


def duplicate_running_job(job, current_jobs=None):
    if not isinstance(job, dict) or not current_jobs:
        return None

    worker = clean(job.get("worker"))
    action = clean(job.get("action"))
    job_id = clean(job.get("id"))

    for candidate in current_jobs:
        if not isinstance(candidate, dict):
            continue
        if clean(candidate.get("id")) == job_id:
            continue
        if clean(candidate.get("status")).upper() != "RUNNING":
            continue
        if clean(candidate.get("worker")) == worker and clean(candidate.get("action")) == action:
            return candidate

    return None


def evaluate_execution_policy(job, store, current_jobs=None, max_retries=DEFAULT_MAX_RETRIES):
    if not isinstance(job, dict):
        return decision(False, "Invalid automation job.", details={"max_retries": max_retries})

    job_type = normalize_job_type(job)
    payload = job_payload(job)
    policy = get_job_policy(job_type)
    mode = policy.get("mode")

    status = clean(job.get("status")).upper()
    if status and status not in {"QUEUED", "VALIDATING"}:
        return decision(False, "Only queued or validating jobs can be considered for automatic execution.", policy, job_type)

    scheduler_state = get_scheduler_state(store if isinstance(store, dict) else {})
    is_scheduler_job = clean(payload.get("source")).lower() == "scheduler"
    if is_scheduler_job and not scheduler_state.get("enabled"):
        return decision(False, "Scheduler is paused.", policy, job_type, {"scheduler_state": scheduler_state})

    if kill_switch_enabled(store):
        return decision(False, "Automation kill switch is enabled.", policy, job_type)

    if mode == BLOCKED:
        return decision(False, "Job is blocked by automation policy.", policy, job_type)

    if mode == APPROVAL_REQUIRED:
        if payload.get("operator_approved") is True:
            return decision(
                True,
                "Approved by operator.",
                policy,
                job_type,
                {
                    "scheduler_state": scheduler_state,
                    "approved_by": clean(payload.get("approved_by")) or "operator",
                },
            )
        return decision(False, "Job requires operator approval.", policy, job_type)

    if mode != AUTOMATIC:
        return decision(False, "Unknown policy mode is not automatic.", policy, job_type)

    retries = retry_count(job)
    if retries >= max_retries:
        return decision(
            False,
            "Retry limit reached.",
            policy,
            job_type,
            {"retry_count": retries, "max_retries": max_retries},
        )

    duplicate = duplicate_running_job(job, current_jobs)
    if duplicate:
        return decision(
            False,
            "Duplicate running job already exists.",
            policy,
            job_type,
            {"running_job_id": duplicate.get("id")},
        )

    return decision(True, "Approved by automation policy.", policy, job_type)


def get_execution_decision(job, store, current_jobs=None, max_retries=DEFAULT_MAX_RETRIES):
    return evaluate_execution_policy(job, store, current_jobs=current_jobs, max_retries=max_retries)


def can_execute_job(job, store, current_jobs=None, max_retries=DEFAULT_MAX_RETRIES):
    return get_execution_decision(
        job,
        store,
        current_jobs=current_jobs,
        max_retries=max_retries,
    )
