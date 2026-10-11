"""Persistent, explicitly driven background-job queue."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from core.persistence import JsonObjectStore


JOB_STATUSES = {"queued", "running", "completed", "failed", "cancelled"}


def _parse_time(value):
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(parsed, datetime):
        raise ValueError("Job run_at must be an ISO 8601 timestamp.")
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


class BoodaJobManager:
    def __init__(self, file_path="memory/jobs.json", *, event_log=None,
                 version_store=None):
        self.store = JsonObjectStore(file_path)
        self.event_log = event_log
        self.version_store = version_store
        self.jobs = self.store.load()
        for job in self.jobs.values():
            if job.get("status") not in JOB_STATUSES:
                raise ValueError("Invalid job status in state file.")

    def _save(self):
        self.store.save(self.jobs)

    def enqueue(self, job_type, payload=None, *, run_at=None, max_attempts=3, job_id=None):
        if not isinstance(job_type, str) or not job_type.strip():
            raise ValueError("Job type must not be empty.")
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer.")
        job_id = job_id or f"job-{uuid4().hex}"
        if job_id in self.jobs:
            raise ValueError(f"Job already exists: {job_id}")
        job = {
            "job_id": job_id,
            "job_type": job_type.strip(),
            "payload": dict(payload or {}),
            "run_at": _parse_time(run_at).isoformat(),
            "status": "queued",
            "attempts": 0,
            "max_attempts": max_attempts,
            "result": None,
            "last_error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.jobs[job_id] = job
        self._save()
        self._record(job, "job_queued")
        return dict(job)

    def get(self, job_id):
        job = self.jobs.get(job_id)
        return dict(job) if job is not None else None

    def list(self, *, status=None, job_type=None):
        return [
            dict(job) for job in self.jobs.values()
            if (status is None or job["status"] == status)
            and (job_type is None or job["job_type"] == job_type)
        ]

    def ready(self, *, as_of=None):
        now = _parse_time(as_of)
        jobs = [
            job for job in self.jobs.values()
            if job["status"] == "queued" and _parse_time(job["run_at"]) <= now
        ]
        return [dict(job) for job in sorted(jobs, key=lambda item: item["run_at"])]

    def claim(self, job_id):
        job = self.jobs.get(job_id)
        if job is None or job["status"] != "queued":
            return None
        job["status"] = "running"
        job["attempts"] += 1
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save()
        self._record(job, "job_started")
        return dict(job)

    def complete(self, job_id, result=None):
        return self._finish(job_id, status="completed", result=result)

    def fail(self, job_id, error, *, retry_delay_seconds=0):
        job = self.jobs.get(job_id)
        if job is None or job["status"] != "running":
            return None
        retry = job["attempts"] < job["max_attempts"]
        job["status"] = "queued" if retry else "failed"
        job["last_error"] = str(error)
        if retry:
            job["run_at"] = (
                datetime.now(timezone.utc) + timedelta(seconds=max(0, retry_delay_seconds))
            ).isoformat()
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save()
        self._record(job, "job_failed" if job["status"] == "failed" else "job_retry_scheduled")
        return dict(job)

    def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if job is None or job["status"] not in {"queued", "running"}:
            return False
        job["status"] = "cancelled"
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save()
        self._record(job, "job_cancelled")
        return True

    def _finish(self, job_id, *, status, result=None):
        job = self.jobs.get(job_id)
        if job is None or job["status"] != "running":
            return None
        job["status"] = status
        job["result"] = result
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save()
        self._record(job, "job_completed")
        return dict(job)

    def _record(self, job, event_type):
        if self.version_store is not None:
            self.version_store.record("job", job["job_id"], job)
        if self.event_log is not None:
            self.event_log.record(
                event_type, entity_type="job", entity_id=job["job_id"],
                details={"job_type": job["job_type"], "status": job["status"]},
            )


class BoodaJobRunner:
    """Runs only job types with explicitly supplied handlers."""

    def __init__(self, manager, handlers):
        self.manager = manager
        self.handlers = dict(handlers)

    def run_due(self, *, max_jobs=20, as_of=None):
        if not isinstance(max_jobs, int) or isinstance(max_jobs, bool) or max_jobs < 0:
            raise ValueError("max_jobs must be a non-negative integer.")
        completed = []
        for queued in self.manager.ready(as_of=as_of)[:max_jobs]:
            job = self.manager.claim(queued["job_id"])
            if job is None:
                continue
            handler = self.handlers.get(job["job_type"])
            if handler is None:
                result = self.manager.fail(
                    job["job_id"], f"No handler registered for {job['job_type']}"
                )
            else:
                try:
                    value = handler(job["payload"])
                except Exception as error:
                    result = self.manager.fail(job["job_id"], error)
                else:
                    result = self.manager.complete(job["job_id"], value)
            completed.append(result)
        return completed
