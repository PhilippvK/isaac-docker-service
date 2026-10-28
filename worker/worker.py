import json
import os
import re
import signal
import subprocess
import threading
import time
import traceback
import uuid

import redis
try:
    from job_state import State
except ImportError:
    from worker.job_state import State

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
WORKER_TAGS = os.getenv("WORKER_TAGS", "").split(",")
r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)
JOBS_DIR = os.getenv("JOBS_DIR", "/jobs")
WORKER_ID = str(uuid.uuid4())
WORKER_KEY = "worker:" + WORKER_ID
ETA_DEFAULT = 600
BUILD_TIMES = []
ACTIVE_JOB = None
ninja_progress = re.compile(r"\[\s*(\d+)\s*/\s*(\d+)\s*\]")
make_progress = re.compile(r"\[\s*(\d+)%\]")
stage_progress = re.compile(r"^::progress:: ([0-9.]+) ([0-9.]+) (.+)$")
ansi_escape = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class BuildProgress:
    """Map each build's local progress into a declared overall job interval."""
    def __init__(self):
        self.start, self.end, self.stage = 0.1, 0.9, None

    def consume(self, line):
        line = ansi_escape.sub("", line).strip()
        marker = stage_progress.match(line)
        if marker:
            try:
                start, end = float(marker[1]), float(marker[2])
            except ValueError:
                return None
            if not 0 <= start <= end <= 0.94:
                return None
            self.start, self.end, self.stage = start, end, marker[3]
            return self.start, self.stage
        match = make_progress.search(line)
        if match:
            fraction = min(1, int(match[1]) / 100)
        else:
            match = ninja_progress.search(line)
            if not match or int(match[2]) == 0:
                return None
            fraction = min(1, int(match[1]) / int(match[2]))
        return self.start + (self.end - self.start) * fraction, self.stage


def state():
    return State(r, JOBS_DIR)


def load_status(job_id):
    return state().load(job_id)


def save_status(job_id, data):
    state().save(job_id, data)


def set_worker_state(status, job_id=None):
    global ACTIVE_JOB
    ACTIVE_JOB = job_id
    state().register(WORKER_ID, WORKER_TAGS, job_id)


def get_eta():
    return sum(BUILD_TIMES) / len(BUILD_TIMES) if BUILD_TIMES else ETA_DEFAULT


def update_progress(job_id, progress, stage=None):
    s = load_status(job_id)
    start = s.get("start_time", time.time())
    extra = {"stage": stage} if stage is not None else {}
    state().update(job_id, status="running", worker=WORKER_ID, progress=progress, **extra,
                   start_time=start, elapsed_seconds=int(time.time() - start),
                   eta_seconds=int(get_eta() * (1 - progress)))


def complete(job_id, status, **extra):
    s = load_status(job_id)
    state().update(job_id, status=status, worker=WORKER_ID, finished_at=time.time(),
                   elapsed_seconds=time.time() - s.get("start_time", time.time()),
                   eta_seconds=None, progress=1.0, stage=status.capitalize(), **extra)


def finish_job(job_id):
    complete(job_id, "finished")


def fail_job(job_id, message):
    complete(job_id, "failed", error=message)


class Aborted(Exception):
    pass


def run_process(args, job_id, log, env):
    """A watchdog cancels silent builds too, including compiler descendants."""
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env=env, text=True, bufsize=1, start_new_session=True)
    done = threading.Event()
    progress = BuildProgress()

    def watch():
        while not done.wait(0.1):
            if state().cancelled(job_id):
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                    time.sleep(0.3)
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                return

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        for line in proc.stdout:
            log.write(line)
            log.flush()
            report = progress.consume(line)
            if report:
                update_progress(job_id, *report)
        code = proc.wait()
        if state().cancelled(job_id):
            raise Aborted()
        if code:
            raise subprocess.CalledProcessError(code, args)
    finally:
        done.set()
        watcher.join()
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
        proc.stdout.close()


def run_job(job_id):
    base = str(state().path(job_id))
    log_path = os.path.join(base, "logs.txt")
    env = {**os.environ, "JOB_DIR": base, "CCACHE_DIR": "/ccache",
           "JOB_TAG": load_status(job_id)["tag"]}
    set_worker_state("busy", job_id)
    try:
        if state().cancelled(job_id):
            raise Aborted()
        update_progress(job_id, 0.05, "Starting")
        start = time.time()
        with open(log_path, "w", buffering=1) as log:
            log.write(f"Starting job {job_id}\n")
            run_process([os.getenv("RETARGET_SCRIPT", "/scripts/run_retarget.sh")], job_id, log, env)
            BUILD_TIMES.append(time.time() - start)
            update_progress(job_id, 0.95, "Packaging artifacts")
            run_process(["tar", "--zstd", "-cf", os.path.join(base, "artifact.tar.zst"),
                         "-C", base, "output"], job_id, log, env)
        finish_job(job_id)
    except Aborted:
        with open(log_path, "a") as log:
            log.write("Job aborted\n")
        complete(job_id, "aborted")
    except Exception as exc:
        with open(log_path, "a") as log:
            log.write(traceback.format_exc())
        fail_job(job_id, str(exc))
    finally:
        set_worker_state("idle")


def heartbeat():
    while True:
        try:
            state().register(WORKER_ID, WORKER_TAGS, ACTIVE_JOB)
        except redis.RedisError:
            pass
        time.sleep(2)


def fetch_job_for_worker():
    return state().claim(WORKER_TAGS, WORKER_ID)


def main():
    threading.Thread(target=heartbeat, daemon=True).start()
    try:
        while True:
            try:
                job = fetch_job_for_worker()
                if job:
                    run_job(job)
                else:
                    time.sleep(0.25)
            except redis.RedisError:
                time.sleep(1)
    finally:
        r.delete(WORKER_KEY)


if __name__ == "__main__":
    main()
