import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


class AutomationQueueService:
    """
    Persistent Automation Queue.

    Stores automation jobs in data/automation_jobs.json so job history survives restarts.
    """

    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir or Path(__file__).resolve().parents[1])
        self.data_dir = Path(os.environ.get("DATA_DIR", self.base_dir / "data"))
        self.jobs_file = self.data_dir / "automation_jobs.json"
        self._lock = threading.RLock()
        self.jobs = self._load_jobs()
        self.next_id = self._next_id()

    def _load_jobs(self):
        try:
            if self.jobs_file.exists():
                data = json.loads(self.jobs_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
        except Exception:
            pass

        return []

    def _save_jobs(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.jobs_file.with_suffix(self.jobs_file.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self.jobs[-500:], indent=2),
            encoding="utf-8"
        )
        os.replace(tmp, self.jobs_file)

    def _next_id(self):
        if not self.jobs:
            return 1

        try:
            return max(int(job.get("id", 0)) for job in self.jobs) + 1
        except Exception:
            return len(self.jobs) + 1

    def create_job(self, worker, action, payload=None, priority=5):
        with self._lock:
            job = {
                "id": self.next_id,
                "worker": worker,
                "action": action,
                "payload": payload or {},
                "priority": priority,
                "status": "QUEUED",
                "created_at": utc_now_iso(),
                "started_at": None,
                "finished_at": None,
                "error": None,
                "result": None,
            }

            self.jobs.append(job)
            self.next_id += 1
            self._save_jobs()

            return dict(job)

    def save_job(self, job):
        with self._lock:
            for index, existing in enumerate(self.jobs):
                if int(existing.get("id")) == int(job.get("id")):
                    self.jobs[index] = job
                    self._save_jobs()
                    return dict(job)

            self.jobs.append(job)
            self._save_jobs()
            return dict(job)

    def list_jobs(self, limit=50):
        with self._lock:
            if limit is None:
                return [dict(job) for job in self.jobs]
            return [dict(job) for job in self.jobs[-limit:]]

    def queue_depth(self):
        with self._lock:
            return len([job for job in self.jobs if job.get("status") == "QUEUED"])

    def get_job(self, job_id):
        with self._lock:
            for job in self.jobs:
                if int(job["id"]) == int(job_id):
                    return dict(job)
        return None
