from datetime import datetime, timezone
from typing import Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AutomationCenterService:
    """
    FT3 Automation Center

    Owns:
    - worker registration
    - worker health
    - job queue foundation
    - scheduler foundation
    - last sync/status reporting

    Workers such as RMS, GPS7000, SMS, and Email plug into this center.
    """

    def __init__(self):
        self.workers: Dict[str, object] = {}
        self.jobs: List[dict] = []
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
        result = []

        for name, worker in self.workers.items():
            health_fn = getattr(worker, "health", None)
            status_fn = getattr(worker, "status", None)

            health = health_fn() if callable(health_fn) else {}
            status = status_fn() if callable(status_fn) else "UNKNOWN"

            result.append({
                "name": name,
                "status": status,
                "health": health,
            })

        return result

    def get_worker(self, worker_name: str):
        return self.workers.get(worker_name)

    def center_health(self) -> dict:
        workers = self.list_workers()

        offline = [
            worker for worker in workers
            if str(worker.get("status", "")).upper() in ["OFFLINE", "ERROR", "FAILED"]
        ]

        return {
            "ok": len(offline) == 0,
            "status": "HEALTHY" if len(offline) == 0 else "DEGRADED",
            "started_at": self.started_at,
            "worker_count": len(workers),
            "offline_workers": offline,
            "queue_depth": len(self.jobs),
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
        job = {
            "id": len(self.jobs) + 1,
            "worker": worker,
            "action": action,
            "payload": payload or {},
            "priority": priority,
            "status": "QUEUED",
            "created_at": utc_now_iso(),
            "started_at": None,
            "finished_at": None,
            "error": None,
        }

        self.jobs.append(job)

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

    def list_jobs(self) -> list:
        return sorted(
            self.jobs,
            key=lambda job: (job.get("status") != "QUEUED", job.get("priority", 5), job.get("id", 0))
        )

    def get_activity(self, limit: int = 25) -> list:
        return self.activity[-limit:]