import json
import os
from datetime import datetime, timezone
from pathlib import Path
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

    def operational_status(self) -> dict:
        data_dir = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
        stores_file = data_dir / "stores.json"

        try:
            stores = json.loads(stores_file.read_text(encoding="utf-8"))
            if not isinstance(stores, list):
                stores = []
        except Exception:
            stores = []

        today = datetime.now().date().isoformat()
        open_exceptions = 0
        rms_closeouts = 0
        resolved_today = 0

        for store in stores:
            operational = store.get("operational") if isinstance(store, dict) else {}
            exceptions = operational.get("exceptions", []) if isinstance(operational, dict) else []

            if not isinstance(exceptions, list):
                continue

            for exception in exceptions:
                if not isinstance(exception, dict):
                    continue

                status = str(exception.get("status") or "").strip()
                exception_type = str(exception.get("type") or "").strip()

                if status in {"", "Open", "Acknowledged"}:
                    open_exceptions += 1

                    if exception_type == "rms_closeout":
                        rms_closeouts += 1

                resolved_at = str(exception.get("resolved_at") or "").strip()
                if status == "Resolved" and resolved_at.startswith(today):
                    resolved_today += 1

        health = self.center_health()
        workers = self.list_workers()

        last_worker_run = ""
        for worker in workers:
            worker_health = worker.get("health") or {}
            candidate = str(worker_health.get("last_run") or "").strip()
            if candidate and (not last_worker_run or candidate > last_worker_run):
                last_worker_run = candidate

        return {
            "ok": True,
            "worker_health": health.get("status", "UNKNOWN"),
            "open_exceptions": open_exceptions,
            "rms_closeouts": rms_closeouts,
            "resolved_today": resolved_today,
            "last_worker_run": last_worker_run,
            "workers_online": len(workers),
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

    def list_jobs(self, limit: Optional[int] = 50):
        return self.queue.list_jobs(limit=limit)

    def get_activity(self, limit: int = 25):
        return self.activity[-limit:]
