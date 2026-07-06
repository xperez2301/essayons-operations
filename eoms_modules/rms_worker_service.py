import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    from eoms_modules.workers.base_worker import BaseWorker
except ImportError:
    from workers.base_worker import BaseWorker


def clean(value):
    return "" if value is None else str(value).strip()


class RMSWorkerService(BaseWorker):
    def __init__(self, base_dir=None):
        super().__init__("RMS Worker")
        self.base_dir = Path(base_dir or Path(__file__).resolve().parents[1])
        self.data_dir = Path(os.environ.get("DATA_DIR", self.base_dir / "data"))
        self.worker_log = self.data_dir / "rms_worker_log.json"
        self._status = "READY"

    def write_worker_log(self, entries):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.worker_log.with_suffix(self.worker_log.suffix + ".tmp")
        tmp.write_text(json.dumps(entries[-250:], indent=2), encoding="utf-8")
        os.replace(tmp, self.worker_log)

    def log_event(self, status, message, details=None):
        entry = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "status": clean(status),
            "message": clean(message),
            "details": details or {},
        }

        try:
            existing = json.loads(self.worker_log.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []

        existing.append(entry)
        self.write_worker_log(existing)
        return entry

    def log_worker_exception(self, exception_type, status, message, details=None):
        return self.log_event(
            status,
            message,
            {
                "operational_exception": {
                    "type": clean(exception_type),
                    "source_worker": "RMS Worker",
                    "status": clean(status),
                    "message": clean(message),
                },
                **(details or {}),
            },
        )

    def worker_status(self):
        try:
            events = json.loads(self.worker_log.read_text(encoding="utf-8")) if self.worker_log.exists() else []
            last_event = events[-1] if events else None
        except Exception:
            last_event = None

        return {
            "ok": True,
            "status": self.status(),
            "message": clean(last_event.get("message")) if last_event else "RMS worker has not run yet.",
            "last_event": last_event,
            "health": self.health(),
        }

    def close_edge_debug_browser(self):
        """
        Close only the RMS CDP Edge browser started for EOMS.

        Targets:
        - msedge.exe
        - --remote-debugging-port=9222

        This avoids closing normal Edge windows.
        """
        if clean(os.environ.get("EOMS_RMS_CLOSE_BROWSER", "1")).lower() in {"0", "false", "no", "off"}:
            return self.log_worker_exception(
                "rms_browser_close_disabled",
                "BROWSER LEFT OPEN",
                "Automatic RMS browser close is disabled.",
            )

        powershell_script = r'''
$ErrorActionPreference = "SilentlyContinue"

$targets = Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -ieq "msedge.exe" -and
    $_.CommandLine -like "*--remote-debugging-port=9222*"
  }

$count = 0
foreach ($p in $targets) {
  try {
    Stop-Process -Id $p.ProcessId -Force
    $count++
  } catch {}
}

Write-Output $count
'''

        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", powershell_script],
                cwd=str(self.base_dir),
                capture_output=True,
                text=True,
                timeout=20,
            )

            closed_count = 0
            try:
                closed_count = int(clean(completed.stdout).splitlines()[-1])
            except Exception:
                closed_count = 0

            return self.log_event(
                "BROWSER CLOSED",
                f"Closed {closed_count} RMS Edge debug browser process(es).",
                {
                    "closed_count": closed_count,
                    "stdout": clean(completed.stdout)[-500:],
                    "stderr": clean(completed.stderr)[-500:],
                },
            )

        except Exception as exc:
            return self.log_worker_exception(
                "rms_browser_close_warning",
                "BROWSER CLOSE WARNING",
                f"EOMS could not close RMS browser: {str(exc)[:300]}",
                {"error": str(exc)[:800]},
            )

    def run_auto_grab(self):
        self._status = "RUNNING"
        self.set_last_run()
        self.clear_error()

        self.log_event(
            "RUNNING",
            "RMS Worker started Auto Grab.",
            {"engine": "app.rms_full_import_with_playwright"},
        )

        command = """
import json
import traceback

try:
    import app

    result = app.rms_full_import_with_playwright(
        headless=app.rms_headless(True),
        max_bols=0
    )

    print(json.dumps({
        "ok": bool(result.get("ok")),
        "result": result
    }))

except Exception as exc:
    print(json.dumps({
        "ok": False,
        "error": str(exc),
        "traceback": traceback.format_exc()[-3000:]
    }))
"""

        try:
            completed = subprocess.run(
                [sys.executable, "-c", command],
                cwd=str(self.base_dir),
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                timeout=int(os.environ.get("RMS_WORKER_TIMEOUT_SECONDS", "900")),
            )

            stdout = clean(completed.stdout)
            stderr = clean(completed.stderr)

            parsed = None
            for line in reversed(stdout.splitlines()):
                line = clean(line)
                if line.startswith("{") and line.endswith("}"):
                    parsed = json.loads(line)
                    break

            if completed.returncode != 0:
                raise RuntimeError(
                    f"RMS Auto Grab exited with code {completed.returncode}. "
                    f"STDERR: {stderr[-800:]} STDOUT: {stdout[-800:]}"
                )

            if not isinstance(parsed, dict):
                raise RuntimeError(
                    "RMS Auto Grab did not return valid JSON. "
                    f"STDERR: {stderr[-800:]} STDOUT: {stdout[-800:]}"
                )

            if not parsed.get("ok"):
                result = parsed.get("result") or {}
                raise RuntimeError(parsed.get("error") or result.get("message") or "RMS Auto Grab returned ok=false.")

            result = parsed.get("result") or {}

            self._status = "COMPLETED"
            self.clear_error()

            completed_event = self.log_event(
                "COMPLETED",
                clean(result.get("message")) or "RMS Auto Grab completed.",
                {
                    "found": result.get("found", result.get("bol_count", 0)),
                    "imported": result.get("imported", result.get("added", 0)),
                    "updated": result.get("updated", 0),
                    "skipped": result.get("skipped", result.get("duplicates", 0)),
                    "need_review": result.get("need_review", 0),
                    "rms_missing": result.get("rms_missing", 0),
                    "rms_closeout_resolved": result.get("rms_closeout_resolved", 0),
                    "status": result.get("status"),
                    "raw_result": result,
                    "operational_exception_summary": {
                        "rms_closeout_created_or_updated": result.get("rms_missing", 0),
                        "rms_closeout_resolved": result.get("rms_closeout_resolved", 0),
                    },
                },
            )

            browser_event = self.close_edge_debug_browser()
            completed_event["details"]["browser_close"] = browser_event
            return completed_event

        except subprocess.TimeoutExpired as exc:
            self._status = "FAILED"
            self.set_error("RMS Auto Grab timed out.")

            failed_event = self.log_worker_exception(
                "rms_worker_timeout",
                "FAILED",
                "RMS Auto Grab timed out before completion.",
                {"error": str(exc)},
            )

            failed_event["details"]["browser_close"] = self.close_edge_debug_browser()
            return failed_event

        except Exception as exc:
            self._status = "FAILED"
            self.set_error(exc)

            failed_event = self.log_worker_exception(
                "rms_worker_failure",
                "FAILED",
                f"RMS Auto Grab failed: {str(exc)[:500]}",
                {"error": str(exc)[:1000]},
            )

            failed_event["details"]["browser_close"] = self.close_edge_debug_browser()
            return failed_event

    def run(self):
        return self.run_auto_grab()


rms_worker = RMSWorkerService()
