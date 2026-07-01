from datetime import datetime

from eoms_modules.health_service import HealthService
from eoms_modules.rms_adapter import RMSAdapter


class RMSService:
    """
    Central RMS service layer.
    All RMS workflows should go through this class.
    """

    def __init__(self, browser_service):
        self.adapter = RMSAdapter(browser_service)

    def get_session_status(self):
        try:
            status = self.adapter.get_session_status()
            return {
                "ok": True,
                "message": "RMS session status checked",
                "data": status,
                "errors": [],
                "warnings": [],
            }
        except Exception as e:
            return {
                "ok": False,
                "message": "Failed to check RMS session status",
                "data": {},
                "errors": [str(e)],
                "warnings": [],
            }

    def run_health_check(self):
        try:
            session = self.adapter.get_session_status()
            logged_in = session.get("logged_in", False)

            if logged_in:
                return HealthService.healthy(
                    component="RMS",
                    message="RMS session is connected",
                    details=session,
                )

            return HealthService.warning(
                component="RMS",
                message="RMS session is not logged in",
                details=session,
                warnings=["Manual RMS login may be required."],
            )

        except Exception as e:
            return HealthService.failed(
                component="RMS",
                message="RMS health check failed",
                errors=[str(e)],
            )

    def capture_bols(self):
        started = datetime.now()

        report = {
            "started": started.isoformat(timespec="seconds"),
            "finished": None,
            "duration_seconds": None,
            "logged_in": False,
            "navigation": False,
            "bols_found": 0,
            "bols_processed": 0,
            "failures": 0,
            "status": "Running",
        }

        try:
            session = self.adapter.get_session_status()
            report["logged_in"] = session.get("logged_in", False)

            result = self.adapter.capture_bols()

            report["navigation"] = True
            report["bols_processed"] = result.get("count", 0)
            report["bols_found"] = result.get("count", 0)
            report["status"] = "Healthy" if result.get("ok") else "Warning"

            finished = datetime.now()
            report["finished"] = finished.isoformat(timespec="seconds")
            report["duration_seconds"] = round((finished - started).total_seconds(), 2)

            return {
                "ok": result.get("ok", False),
                "message": result.get("message", "RMS capture complete"),
                "health": HealthService.result(
                    component="RMS",
                    status=report["status"],
                    message=result.get("message", "RMS capture complete"),
                    details=report,
                ),
                "data": {
                    "report": report,
                    "items": result.get("data", []),
                },
                "errors": [],
                "warnings": [],
            }

        except Exception as e:
            finished = datetime.now()
            report["finished"] = finished.isoformat(timespec="seconds")
            report["duration_seconds"] = round((finished - started).total_seconds(), 2)
            report["status"] = "Failed"
            report["failures"] = 1

            return {
                "ok": False,
                "message": "RMS capture failed",
                "health": HealthService.failed(
                    component="RMS",
                    message="RMS capture failed",
                    details=report,
                    errors=[str(e)],
                ),
                "data": {
                    "report": report,
                    "items": [],
                },
                "errors": [str(e)],
                "warnings": [],
            }
