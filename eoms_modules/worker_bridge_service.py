import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


def utc_now():
    return datetime.now(timezone.utc)


def utc_now_iso():
    return utc_now().isoformat()


def parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


class WorkerBridgeService:
    """Persistent control-plane state for external Docker workers."""

    def __init__(self, data_dir=None):
        base_dir = Path(__file__).resolve().parents[1]
        self.data_dir = Path(data_dir or os.environ.get("DATA_DIR", base_dir / "data"))
        self.workers_file = self.data_dir / "workers.json"
        self.jobs_file = self.data_dir / "worker_jobs.json"
        self._lock = threading.RLock()

    def _read(self, path):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []

    def _write(self, path, value):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, path)

    def heartbeat(self, payload):
        worker_id = str(payload.get("worker_id") or "rms-docker-worker").strip()
        now = utc_now_iso()
        with self._lock:
            workers = self._read(self.workers_file)
            worker = next((item for item in workers if item.get("worker_id") == worker_id), None)
            if worker is None:
                worker = {"worker_id": worker_id, "registered_at": now}
                workers.append(worker)
            worker.update({
                "name": str(payload.get("name") or "Docker RMS Worker").strip(),
                "version": str(payload.get("version") or "unknown").strip(),
                "state": str(payload.get("state") or "ONLINE").upper(),
                "current_job": payload.get("current_job"),
                "last_job": payload.get("last_job") or worker.get("last_job"),
                "last_heartbeat": now,
                "diagnostics": payload.get("diagnostics") or {},
            })
            self._write(self.workers_file, workers)
            return dict(worker)

    def enqueue(self, action="rms_auto_grab", payload=None, priority=5):
        with self._lock:
            jobs = self._read(self.jobs_file)
            job = {
                "id": str(uuid4()),
                "worker": "Docker RMS Worker",
                "action": action,
                "payload": payload or {},
                "priority": int(priority),
                "status": "QUEUED",
                "created_at": utc_now_iso(),
                "claimed_at": None,
                "finished_at": None,
                "worker_id": None,
                "runtime_seconds": None,
                "result": None,
                "error": None,
            }
            jobs.append(job)
            self._write(self.jobs_file, jobs[-500:])
            return dict(job)

    def claim_next(self, worker_id):
        with self._lock:
            jobs = self._read(self.jobs_file)
            queued = [job for job in jobs if str(job.get("status")).upper() == "QUEUED"]
            if not queued:
                return None
            queued.sort(key=lambda job: (int(job.get("priority", 5)), job.get("created_at", "")))
            selected = queued[0]
            selected["status"] = "RUNNING"
            selected["worker_id"] = worker_id
            selected["claimed_at"] = utc_now_iso()
            self._write(self.jobs_file, jobs)
            return dict(selected)

    def complete(self, job_id, worker_id, payload):
        with self._lock:
            jobs = self._read(self.jobs_file)
            job = next((item for item in jobs if str(item.get("id")) == str(job_id)), None)
            if job is None:
                return None, "not_found"
            if job.get("worker_id") and job.get("worker_id") != worker_id:
                return None, "wrong_worker"
            if str(job.get("status")).upper() in {"COMPLETED", "FAILED"}:
                return dict(job), "already_complete"

            status = "COMPLETED" if payload.get("ok") else "FAILED"
            job["status"] = status
            job["finished_at"] = utc_now_iso()
            job["result"] = payload.get("result")
            job["error"] = payload.get("error") or (
                None if status == "COMPLETED" else "Worker reported an unsuccessful result."
            )
            claimed = parse_time(job.get("claimed_at"))
            if claimed:
                job["runtime_seconds"] = round((utc_now() - claimed).total_seconds(), 2)
            self._write(self.jobs_file, jobs)
            return dict(job), "completed"

    def list_jobs(self, limit=50):
        with self._lock:
            jobs = self._read(self.jobs_file)
            return [dict(job) for job in jobs[-limit:]]

    def status(self):
        with self._lock:
            workers = self._read(self.workers_file)
            jobs = self._read(self.jobs_file)
        worker = max(workers, key=lambda item: item.get("last_heartbeat", ""), default=None)
        now = utc_now()
        if worker:
            heartbeat = parse_time(worker.get("last_heartbeat"))
            online = bool(heartbeat and now - heartbeat <= timedelta(seconds=90))
            state = "Busy" if online and worker.get("current_job") else ("Online" if online else "Offline")
        else:
            state = "Offline"

        today = now.date()
        completed_today = []
        runtimes = []
        for job in jobs:
            finished = parse_time(job.get("finished_at"))
            if str(job.get("status")).upper() == "COMPLETED" and finished and finished.date() == today:
                completed_today.append(job)
            if job.get("runtime_seconds") is not None:
                runtimes.append(float(job["runtime_seconds"]))

        return {
            "ok": True,
            "status": state,
            "worker": worker,
            "jobs_completed_today": len(completed_today),
            "average_runtime_seconds": round(sum(runtimes) / len(runtimes), 2) if runtimes else 0,
            "queue_depth": len([job for job in jobs if job.get("status") == "QUEUED"]),
            "last_job": jobs[-1] if jobs else None,
            "checked_at": utc_now_iso(),
        }


worker_bridge = WorkerBridgeService()
