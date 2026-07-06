from datetime import datetime, timezone


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


ALLOWED_WORKER_ACTIONS = {"run", "worker_status", "sync_positions"}
FAILED_RESULT_STATUSES = {"FAILED", "ERROR"}


class AutomationExecutorService:
    """
    Runs Automation Queue jobs against registered workers.
    Saves job updates back to the persistent queue.
    """

    def __init__(self, automation_center):
        self.automation_center = automation_center

    def save_job(self, job):
        save_fn = getattr(self.automation_center, "save_job", None)

        if callable(save_fn):
            save_fn(job)

        return job

    def result_failed(self, result):
        if not isinstance(result, dict):
            return False

        if result.get("ok") is False:
            return True

        status = str(result.get("status") or "").strip().upper()
        return status in FAILED_RESULT_STATUSES

    def run_job(self, job):
        worker_name = job.get("worker")
        action = job.get("action")

        worker = self.automation_center.get_worker(worker_name)

        if not worker:
            job["status"] = "FAILED"
            job["finished_at"] = utc_now_iso()
            job["error"] = f"Worker not found: {worker_name}"
            return self.save_job(job)

        if action not in ALLOWED_WORKER_ACTIONS:
            job["status"] = "FAILED"
            job["finished_at"] = utc_now_iso()
            job["error"] = f"Unsupported action for {worker_name}: {action}"
            return self.save_job(job)

        job["status"] = "RUNNING"
        job["started_at"] = utc_now_iso()
        self.save_job(job)

        try:
            if action == "run":
                result = worker.run()
            elif hasattr(worker, action):
                result = getattr(worker, action)()
            else:
                raise ValueError(f"Unsupported action for {worker_name}: {action}")

            if self.result_failed(result):
                job["status"] = "FAILED"
                job["error"] = (
                    result.get("error")
                    or result.get("message")
                    or f"{worker_name} returned a failed result."
                )
            else:
                job["status"] = "COMPLETED"
                job["error"] = None

            job["finished_at"] = utc_now_iso()
            job["result"] = result

        except Exception as exc:
            job["status"] = "FAILED"
            job["finished_at"] = utc_now_iso()
            job["error"] = str(exc)

            set_error = getattr(worker, "set_error", None)
            if callable(set_error):
                set_error(exc)

        return self.save_job(job)

    def run_next(self):
        queued = [
            job for job in self.automation_center.list_jobs(limit=None)
            if job.get("status") == "QUEUED"
        ]

        if not queued:
            return {
                "ok": True,
                "message": "No queued jobs.",
                "job": None,
            }

        queued.sort(key=lambda job: (job.get("priority", 5), job.get("id", 0)))
        job = queued[0]
        result = self.run_job(job)

        return {
            "ok": result.get("status") == "COMPLETED",
            "message": f"Job {result.get('id')} {result.get('status')}.",
            "job": result,
        }
