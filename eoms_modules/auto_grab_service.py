from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class AutoGrabService:
    """
    Owns Auto Grab operational state and orchestrates RMS automation
    through RMSAdapter and BrowserService.
    """

    def __init__(self, browser_service=None):
        self.browser_service = browser_service
        self.rms = None

        self.enabled = False
        self.state = "Idle"

        self.started_at = None
        self.finished_at = None

        self.last_success = None
        self.last_failure = None

        self.jobs_processed = 0
        self.failed_jobs = 0

    # -----------------------------
    # DEPENDENCY INJECTION
    # -----------------------------
    def set_browser_service(self, browser_service):
        self.browser_service = browser_service

    def set_rms_adapter(self, rms_adapter):
        self.rms = rms_adapter

    # -----------------------------
    # RUN CONTROL
    # -----------------------------
    def start_run(self):
        self.state = "Running"
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.finished_at = None

    def finish_run(self):
        self.state = "Idle"
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.last_success = self.finished_at

    def fail_run(self, error: str):
        self.state = "Failed"
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.last_failure = error
        self.failed_jobs += 1

    # -----------------------------
    # LEGACY BROWSER ACCESS
    # -----------------------------
    def launch_browser(self):
        if not self.browser_service:
            raise RuntimeError("BrowserService is not configured for AutoGrabService.")
        return self.browser_service.attach_to_edge_cdp()

    def check_rms_session(self) -> dict[str, Any]:
        browser = self.launch_browser()
        try:
            return browser.rms_session_status()
        finally:
            browser.shutdown()

    # -----------------------------
    # RMS FLOW (Adapter-based)
    # -----------------------------
    def scan_rms_queue(self):
        if not self.rms:
            raise RuntimeError("RMSAdapter not configured.")

        self.start_run()

        try:
            result = self.rms.scan_queue()

            if result.get("ok"):
                self.finish_run()
            else:
                self.fail_run(result.get("message", "Queue scan failed"))

            return result

        except Exception as e:
            self.fail_run(str(e))
            raise

    # -----------------------------
    # HEALTH
    # -----------------------------
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
                "browser_configured": self.browser_service is not None,
                "rms_configured": self.rms is not None,
            },
        }