from datetime import datetime, timezone
from typing import Dict, List, Optional

from eoms_modules.automation_queue_service import AutomationQueueService


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AutomationCenterService:
    """FT3 Automation Center."""

    def __init__(self):
        self.workers: Dict[str, object] = {}
        self.queue = AutomationQueueService()
        self.jobs = self.queue.jobs
        self.activity: List[dict] = []
        self.started_at = utc_now_iso()

    def register_worker(self, worker) -> dict:
        worker_name = getattr(worker, "name", None)

        if callable(worker_name):
            worker_name = worker.name()

        if not worker_name:
            raise ValueError("Worker must expose a name or name() method.")

        self.workers[worker_name] = worker

        event = {
            "timestamp": utc_now_iso(),
            "type": "worker_registered",
            "worker": worker_name,
            "message": f"{worker_name} registered with Automation Center.",
        }

        self.activity.append(event)

        return {
            "ok": True,
            "worker": worker_name,
            "registered_at": event["timestamp"],
        }

    def list_workers(self) -> list:
        workers = []

        for name, worker in self.workers.items():
            workers.append({
                "name": name,
                "status": worker.status() if hasattr(worker, "status") else "UNKNOWN",
                "health": worker.health() if hasattr(worker, "health") else {},
            })

        return workers

    def get_worker(self, worker_name: str):
        return self.workers.get(worker_name)

    def center_health(self) -> dict:
        workers = self.list_workers()

        offline = [
            w for w in workers
            if str(w.get("status", "")).upper() in ("OFFLINE", "FAILED", "ERROR")
        ]

        return {
            "ok": len(offline) == 0,
            "status": "HEALTHY" if not offline else "DEGRADED",
            "started_at": self.started_at,
            "worker_count": len(workers),
            "offline_workers": offline,
            "queue_depth": self.queue.queue_depth(),
            "activity_count": len(self.activity),
            "checked_at": utc_now_iso(),
        }

    def enqueue_job(
        self,
        worker: str,
        action: str,
        payload: Optional[dict] = None,
        priority: int = 5,
    ) -> dict:

        job = self.queue.create_job(worker, action, payload, priority)
        self.jobs = self.queue.jobs

        self.activity.append({
            "timestamp": utc_now_iso(),
            "type": "job_queued",
            "worker": worker,
            "message": f"Queued {action} for {worker}.",
            "job_id": job["id"],
        })

        return {
            "ok": True,
            "job": job,
        }

    def save_job(self, job: dict):
        self.queue.save_job(job)
        self.jobs = self.queue.jobs

    def list_jobs(self):
        return self.queue.list_jobs()

    def get_activity(self, limit: int = 25):
        return self.activity[-limit:]