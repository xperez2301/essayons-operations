from datetime import datetime, timezone


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


class AutomationHostService:
    """
    Automation Background Service Host foundation.

    This host owns Automation Kernel orchestration state only. It does not start
    threads, run timers, execute workers, call RMS, or replace the Scheduler,
    Queue, Execution Controller, Executor, or Workers.
    """

    def __init__(self):
        self.running = False
        self.started_at = ""
        self.stopped_at = ""
        self.last_heartbeat = ""
        self.last_scheduler_scan = ""
        self.last_queue_scan = ""
        self.active_workers = []
        self.jobs_processed = 0
        self.last_error = ""

    def start(self):
        now = utc_now_iso()
        self.running = True
        self.started_at = self.started_at or now
        self.stopped_at = ""
        self.last_heartbeat = now
        self.last_error = ""
        return self.get_status()

    def stop(self):
        now = utc_now_iso()
        self.running = False
        self.stopped_at = now
        self.last_heartbeat = now
        self.active_workers = []
        return self.get_status()

    def heartbeat(
        self,
        scheduler_scanned=False,
        queue_scanned=False,
        active_workers=None,
        jobs_processed=0,
        error=None,
    ):
        now = utc_now_iso()
        self.last_heartbeat = now

        if scheduler_scanned:
            self.last_scheduler_scan = now

        if queue_scanned:
            self.last_queue_scan = now

        if active_workers is not None:
            self.active_workers = list(active_workers)

        if jobs_processed:
            self.jobs_processed += int(jobs_processed)

        if error:
            self.last_error = str(error)

        return self.get_status()

    def record_scheduler_scan(self):
        self.last_scheduler_scan = utc_now_iso()
        return self.get_status()

    def record_queue_scan(self):
        self.last_queue_scan = utc_now_iso()
        return self.get_status()

    def record_job_processed(self, count=1):
        self.jobs_processed += int(count)
        return self.get_status()

    def set_active_workers(self, workers):
        self.active_workers = list(workers or [])
        return self.get_status()

    def set_error(self, error):
        self.last_error = str(error)
        return self.get_status()

    def clear_error(self):
        self.last_error = ""
        return self.get_status()

    def health(self):
        if not self.running:
            return "Stopped"

        if self.last_error:
            return "Unhealthy"

        return "Healthy"

    def get_status(self):
        return {
            "running": self.running,
            "status": "Running" if self.running else "Stopped",
            "health": self.health(),
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "last_heartbeat": self.last_heartbeat,
            "last_scheduler_scan": self.last_scheduler_scan,
            "last_queue_scan": self.last_queue_scan,
            "active_workers": list(self.active_workers),
            "workers_active": len(self.active_workers),
            "jobs_processed": self.jobs_processed,
            "last_error": self.last_error,
        }
