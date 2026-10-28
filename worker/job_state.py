"""Job transitions serialized across API and worker processes on the shared volume."""
import fcntl
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

TERMINAL = {"finished", "failed", "aborted"}


class State:
    def __init__(self, redis, directory):
        self.redis = redis
        self.root = Path(directory)

    @contextmanager
    def lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / ".state.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def path(self, job):
        if not job or Path(job).name != job or job in (".", ".."):
            raise FileNotFoundError(job)
        return self.root / job

    def load(self, job):
        if not self.path(job).is_dir():
            raise FileNotFoundError(job)
        return json.loads((self.path(job) / "status.json").read_text())

    def save(self, job, data):
        base = self.path(job)
        fd, name = tempfile.mkstemp(dir=base)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(data, handle)
            os.replace(name, base / "status.json")
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def epoch(self):
        value = self.redis.get("service:epoch")
        return value if isinstance(value, str) else None

    def reset(self):
        with self.lock():
            epoch = str(uuid.uuid4())
            self.redis.set("service:epoch", epoch)
            self.redis.delete("retarget_queue", "workers")
            for key in self.redis.scan_iter("worker:*"):
                self.redis.delete(key)
            for base in self.root.iterdir():
                if not base.is_dir():
                    continue
                try:
                    status = self.load(base.name)
                except FileNotFoundError:
                    continue
                status["archived"] = True
                if status["status"] not in TERMINAL:
                    status.update(status="aborted", finished_at=time.time(), error="service restarted")
                self.save(base.name, status)

    def clear_completed(self):
        count = 0
        with self.lock():
            for base in self.root.iterdir():
                if not base.is_dir():
                    continue
                try:
                    status = self.load(base.name)
                except FileNotFoundError:
                    continue
                if status.get("archived") or status.get("history_hidden") or status["status"] not in TERMINAL:
                    continue
                status["history_hidden"] = True
                self.save(base.name, status)
                count += 1
        return count

    def claim(self, tags, worker):
        with self.lock():
            for job in self.redis.lrange("retarget_queue", 0, -1):
                try:
                    status = self.load(job)
                except FileNotFoundError:
                    self.redis.lrem("retarget_queue", 1, job)
                    continue
                if status.get("archived") or status["status"] != "queued":
                    self.redis.lrem("retarget_queue", 1, job)
                    continue
                if status["tag"] in tags and self.redis.lrem("retarget_queue", 1, job) == 1:
                    status.update(status="running", worker=worker, start_time=time.time())
                    self.save(job, status)
                    return job
        return None

    def abort(self, job, token):
        with self.lock():
            status = self.load(job)
            if status["token"] != token:
                raise PermissionError()
            if status["status"] == "queued":
                self.redis.lrem("retarget_queue", 0, job)
                status.update(status="aborted", finished_at=time.time())
            elif status["status"] == "running":
                status["status"] = "aborting"
            self.save(job, status)
            return status

    def cancelled(self, job):
        status = self.load(job)
        return status.get("archived") or status["status"] in {"aborting", "aborted"}

    def update(self, job, **changes):
        with self.lock():
            status = self.load(job)
            if status.get("archived") or status["status"] in {"aborting", "aborted"}:
                if changes.get("status") in TERMINAL:
                    status.update(status="aborted", finished_at=time.time(), eta_seconds=None)
            elif status["status"] not in TERMINAL:
                if "progress" in changes:
                    changes["progress"] = max(status.get("progress", 0), changes["progress"])
                status.update(changes)
            self.save(job, status)
            return status

    def register(self, worker, tags, job=None):
        with self.lock():
            epoch = self.epoch()
            if job:
                status = self.load(job)
                if status.get("archived") or status.get("epoch") != epoch:
                    return
            self.redis.set("worker:" + worker, json.dumps({
                "state": "busy" if job else "idle", "job_id": job,
                "tags": tags, "ts": int(time.time()), "epoch": epoch,
            }), ex=10)
