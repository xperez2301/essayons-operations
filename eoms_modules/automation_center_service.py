import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from eoms_modules.automation_queue_service import AutomationQueueService
from eoms_modules.automation_scheduler_service import get_scheduler_state


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

    def latest_job(self):
        jobs = self.queue.list_jobs(limit=None)
        return jobs[-1] if jobs else None

    def latest_failure(self):
        jobs = self.queue.list_jobs(limit=None)
        for job in reversed(jobs):
            if str(job.get("status") or "").upper() == "FAILED":
                return job
        return None

    def worker_state(self, workers=None) -> str:
        workers = workers if workers is not None else self.list_workers()
        if not workers:
            return "NO WORKERS"

        states = {str(worker.get("status") or "").upper() for worker in workers}
        if states.intersection({"RUNNING", "STARTING EDGE", "EDGE DEBUG STARTED"}):
            return "RUNNING"
        if states.intersection({"FAILED", "ERROR", "OFFLINE"}):
            return "ATTENTION"
        if states == {"WAITING FOR CONFIG"}:
            return "WAITING FOR CONFIG"
        return "READY"

    def center_health(self) -> dict:
        workers = self.list_workers()

        offline = [
            w for w in workers
            if str(w.get("status", "")).upper() in ("OFFLINE", "FAILED", "ERROR")
        ]

        latest_job = self.latest_job()
        latest_failure = self.latest_failure()

        return {
            "ok": len(offline) == 0,
            "status": "HEALTHY" if not offline else "DEGRADED",
            "started_at": self.started_at,
            "worker_count": len(workers),
            "worker_state": self.worker_state(workers),
            "offline_workers": offline,
            "queue_depth": self.queue.queue_depth(),
            "latest_job": latest_job,
            "latest_failure": latest_failure,
            "activity_count": len(self.activity),
            "checked_at": utc_now_iso(),
        }

    def load_stores_for_status(self) -> dict:
        data_dir = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
        stores_file = data_dir / "stores.json"

        try:
            raw = stores_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {
                "ok": False,
                "stores": [],
                "status": "WARNING",
                "warning": f"{stores_file.name} was not found. Operational exception counts are unavailable.",
            }
        except Exception as exc:
            return {
                "ok": False,
                "stores": [],
                "status": "WARNING",
                "warning": f"{stores_file.name} could not be read: {str(exc)[:180]}",
            }

        try:
            stores = json.loads(raw)
        except json.JSONDecodeError as exc:
            return {
                "ok": False,
                "stores": [],
                "status": "WARNING",
                "warning": f"{stores_file.name} is malformed JSON at line {exc.lineno}, column {exc.colno}. Operational exception counts are unavailable.",
            }

        if not isinstance(stores, list):
            return {
                "ok": False,
                "stores": [],
                "status": "WARNING",
                "warning": f"{stores_file.name} must contain a list. Operational exception counts are unavailable.",
            }

        return {
            "ok": True,
            "stores": stores,
            "status": "OK",
            "warning": "",
        }

    def operational_status(self) -> dict:
        stores_state = self.load_stores_for_status()
        stores = stores_state["stores"]
        scheduler_state = self.scheduler_state_from_stores(stores)

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
            "worker_state": health.get("worker_state", "UNKNOWN"),
            "open_exceptions": open_exceptions,
            "rms_closeouts": rms_closeouts,
            "resolved_today": resolved_today,
            "last_worker_run": last_worker_run,
            "workers_online": len(workers),
            "stores_status": stores_state["status"],
            "stores_warning": stores_state["warning"],
            "scheduler_state": scheduler_state,
            "checked_at": utc_now_iso(),
        }

    def scheduler_state_from_stores(self, stores) -> dict:
        if isinstance(stores, list):
            for store in stores:
                if not isinstance(store, dict):
                    continue

                operational = store.get("operational")
                if not isinstance(operational, dict):
                    continue

                automation = operational.get("automation")
                if not isinstance(automation, dict):
                    continue

                if isinstance(automation.get("scheduler"), dict):
                    return get_scheduler_state(store)

        return get_scheduler_state({})

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
