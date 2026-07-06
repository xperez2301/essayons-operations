from datetime import datetime, timezone


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


class AutomationQueueService:
    def __init__(self):
        self.jobs = []
        self.next_id = 1

    def create_job(self, worker, action, payload=None, priority=5):
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
        return job

    def list_jobs(self, limit=50):
        return self.jobs[-limit:]

    def queue_depth(self):
        return len([job for job in self.jobs if job["status"] == "QUEUED"])

    def get_job(self, job_id):
        for job in self.jobs:
            if int(job["id"]) == int(job_id):
                return job
        return None