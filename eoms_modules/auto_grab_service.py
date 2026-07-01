from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class AutoGrabService:
    """
    Owns Auto Grab operational state.

    Future responsibilities:
    - RMS browser automation
    - Scheduler
    - Queue processing
    - Import execution
    - Run history
    """

    def __init__(self):
        self.enabled = False
        self.state = "Idle"

        self.started_at = None
        self.finished_at = None

        self.last_success = None
        self.last_failure = None

        self.jobs_processed = 0
        self.failed_jobs = 0

    def start_run(self):
        self.state = "Running"
        self.started_at = datetime.now(timezone.utc).isoformat()

    def finish_run(self):
        self.state = "Idle"
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.last_success = self.finished_at

    def fail_run(self, error: str):
        self.state = "Failed"
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.last_failure = error
        self.failed_jobs += 1

    def record_job_processed(self):
        self.jobs_processed += 1

    def record_job_failed(self):
        self.failed_jobs += 1

    def get_health(self) -> dict[str, Any]:
        return {
            "name": "Auto Grab",
            "status": (
                "ok"
                if self.state == "Idle"
                else "warning"
                if self.state == "Running"
                else "error"
            ),
            "message": f"Auto Grab is currently {self.state}.",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "details": {
                "enabled": self.enabled,
                "state": self.state,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "last_success": self.last_success,
                "last_failure": self.last_failure,
                "jobs_processed": self.jobs_processed,
                "failed_jobs": self.failed_jobs,
            },
        }