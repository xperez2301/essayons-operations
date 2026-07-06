import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def clean(value):
    return "" if value is None else str(value).strip()


class RMSWorkerService:
    """
    FT3 Automation Worker foundation.

    Purpose:
    - Keep browser automation logic separate from the EOMS web app.
    - Allow RMS automation to run from a worker machine or local operator machine.
    - Avoid relying on Azure App Service to launch Playwright browsers.
    """

    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir or Path(__file__).resolve().parents[1])
        self.data_dir = Path(os.environ.get("DATA_DIR", self.base_dir / "data"))
        self.worker_log = self.data_dir / "rms_worker_log.json"

    def log_event(self, status, message, details=None):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        details = details or {}

        entry = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "status": clean(status),
            "message": clean(message),
            "details": details,
        }

        try:
            existing = json.loads(self.worker_log.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []

        existing.append(entry)
        self.worker_log.write_text(json.dumps(existing[-250:], indent=2), encoding="utf-8")
        return entry

    def worker_status(self):
        if not self.worker_log.exists():
            return {
                "ok": True,
                "status": "NOT STARTED",
                "message": "RMS worker has not run yet.",
                "last_event": None,
            }

        try:
            events = json.loads(self.worker_log.read_text(encoding="utf-8"))
            last_event = events[-1] if events else None
        except Exception:
            last_event = None

        return {
            "ok": True,
            "status": clean(last_event.get("status")) if last_event else "UNKNOWN",
            "message": clean(last_event.get("message")) if last_event else "No worker events found.",
            "last_event": last_event,
        }

    def start_edge_debug_browser(self):
        """
        Starts the existing START_RMS_EDGE_DEBUG.bat helper if available.
        This keeps FT3 compatible with the CDP workflow that already worked in FT1.
        """
        bat_path = self.base_dir / "START_RMS_EDGE_DEBUG.bat"

        if not bat_path.exists():
            return self.log_event(
                "ERROR",
                "START_RMS_EDGE_DEBUG.bat was not found.",
                {"expected_path": str(bat_path)},
            )

        subprocess.Popen(
            ["cmd", "/c", "start", "", str(bat_path)],
            cwd=str(self.base_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )

        return self.log_event(
            "EDGE DEBUG STARTED",
            "Started user-controlled Edge for RMS on CDP port 9222.",
            {"bat_path": str(bat_path)},
        )


rms_worker = RMSWorkerService()
