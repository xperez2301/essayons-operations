AUTOMATIC = "AUTOMATIC"
APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
BLOCKED = "BLOCKED"

DEFAULT_POLICY_MODE = APPROVAL_REQUIRED


POLICIES = {
    "worker_status_check": {
        "mode": AUTOMATIC,
        "description": "Read-only worker status check.",
    },
    "queue_health_check": {
        "mode": AUTOMATIC,
        "description": "Read-only Automation Queue health check.",
    },
    "scheduler_health_check": {
        "mode": AUTOMATIC,
        "description": "Read-only Scheduler health check.",
    },
    "database_validation_read_only": {
        "mode": AUTOMATIC,
        "description": "Read-only database validation report.",
    },
    "exception_scan_report": {
        "mode": AUTOMATIC,
        "description": "Read-only operational exception scan report.",
    },
    "rms_auto_grab": {
        "mode": APPROVAL_REQUIRED,
        "description": "RMS Auto Grab can modify operational records and requires operator approval.",
    },
    "rms_import": {
        "mode": APPROVAL_REQUIRED,
        "description": "RMS imports can create or update records and require operator approval.",
    },
    "notifications": {
        "mode": APPROVAL_REQUIRED,
        "description": "Outbound notifications require operator approval.",
    },
    "driver_messages": {
        "mode": APPROVAL_REQUIRED,
        "description": "Driver communications require operator approval.",
    },
    "customer_messages": {
        "mode": APPROVAL_REQUIRED,
        "description": "Customer communications require operator approval.",
    },
    "dispatch_assignment": {
        "mode": BLOCKED,
        "description": "Dispatch assignment automation is blocked.",
    },
    "route_changes": {
        "mode": BLOCKED,
        "description": "Route change automation is blocked.",
    },
    "financial_updates": {
        "mode": BLOCKED,
        "description": "Financial update automation is blocked.",
    },
    "delete_operations": {
        "mode": BLOCKED,
        "description": "Delete operation automation is blocked.",
    },
    "record_repairs": {
        "mode": BLOCKED,
        "description": "Record repair automation is blocked.",
    },
}


def normalize_job_type(job_type):
    return "" if job_type is None else str(job_type).strip().lower()


def normalize_mode(mode):
    normalized = "" if mode is None else str(mode).strip().upper()
    if normalized in {AUTOMATIC, APPROVAL_REQUIRED, BLOCKED}:
        return normalized
    return DEFAULT_POLICY_MODE


def get_job_policy(job_type):
    job_type = normalize_job_type(job_type)
    policy = dict(POLICIES.get(job_type, {}))
    policy["job_type"] = job_type
    policy["mode"] = normalize_mode(policy.get("mode"))
    policy.setdefault("description", "Unknown automation job type requires operator approval.")
    return policy


def is_job_allowed(job_type):
    return get_job_policy(job_type)["mode"] != BLOCKED


def requires_approval(job_type):
    return get_job_policy(job_type)["mode"] == APPROVAL_REQUIRED


def is_blocked(job_type):
    return get_job_policy(job_type)["mode"] == BLOCKED


def is_automatic(job_type):
    return get_job_policy(job_type)["mode"] == AUTOMATIC


def get_all_policies():
    return {
        job_type: get_job_policy(job_type)
        for job_type in sorted(POLICIES)
    }
