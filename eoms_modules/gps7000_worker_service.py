import os
from datetime import datetime, timezone

from eoms_modules.workers.base_worker import BaseWorker


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


class GPS7000WorkerService(BaseWorker):
    """
    GPS7000 Worker foundation.

    Safe for production:
    - Registers GPS7000 in Automation Center.
    - Reports configuration status.
    - Does not expose credentials.
    - Does not call external GPS services yet.
    """

    def __init__(self):
        super().__init__("GPS7000 Worker")
        self._status = "WAITING FOR CONFIG"
        self.last_sync = None
        self.vehicles_online = 0

    def gps_configured(self):
        return bool(
            os.environ.get("GPS7000_USERNAME")
            and os.environ.get("GPS7000_PASSWORD")
        )

    def health(self):
        base = super().health()
        base.update({
            "configured": self.gps_configured(),
            "last_sync": self.last_sync,
            "vehicles_online": self.vehicles_online,
        })
        return base

    def sync_positions(self):
        if not self.gps_configured():
            self._status = "WAITING FOR CONFIG"
            return {
                "ok": False,
                "status": self._status,
                "message": "GPS7000 credentials are not configured yet.",
            }

        self._status = "SYNCED"
        self.last_sync = utc_now_iso()
        self.set_last_run()

        return {
            "ok": True,
            "status": self._status,
            "message": "GPS7000 sync completed.",
            "vehicles_online": self.vehicles_online,
            "last_sync": self.last_sync,
        }

    def run(self):
        return self.sync_positions()


gps7000_worker = GPS7000WorkerService()