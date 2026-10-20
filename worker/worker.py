import re
import os
import json
import time
import redis
import uuid
import tempfile
import subprocess

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
WORKER_TAGS = os.environ.get("WORKER_TAGS", "").split(",")

r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

ninja_progress = re.compile(r"\[(\d+)/(\d+)\]")

JOBS_DIR = "/jobs"
WORKER_ID = str(uuid.uuid4())
WORKER_KEY = f"worker:{WORKER_ID}"
ETA_DEFAULT = 10 * 60

BUILD_TIMES = []


def set_worker_state(state, job_id=None):
    data = {
        "state": state,
        "job_id": job_id,
        "tags": WORKER_TAGS,
        "ts": int(time.time())
    }

    r.set(WORKER_KEY, json.dumps(data), ex=10)


def status_file(job_id):
    return os.path.join(JOBS_DIR, job_id, "status.json")


def load_status(job_id):
    with open(status_file(job_id)) as f:
        return json.load(f)


def save_status(job_id, data):
    # with open(status_file(job_id), "w") as f:
    #     json.dump(data, f)
    base = os.path.join(JOBS_DIR, job_id)
    status_path = os.path.join(base, "status.json")

    tmp_fd, tmp_path = tempfile.mkstemp(dir=base)

    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f)

        os.replace(tmp_path, status_path)   # atomic replace

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def get_eta():
    if len(BUILD_TIMES) == 0:
        return ETA_DEFAULT
    return sum(BUILD_TIMES) / len(BUILD_TIMES)


def update_progress(job_id, progress):
    s = load_status(job_id)
    s["progress"] = progress
    s["status"] = "running"
    s["worker"] = WORKER_ID
    eta = get_eta()
    start_time = s.get("start_time")
    if start_time is None:
        start_time = time.time()
        s["start_time"] = start_time
    print("start_time", start_time)
    s["elapsed_seconds"] = int(time.time() - start_time)
    s["eta_seconds"] = int(eta * (1 - progress))
    save_status(job_id, s)


def finish_job(job_id):
    s = load_status(job_id)
    s["progress"] = 1.0
    s["status"] = "finished"
    s["worker"] = WORKER_ID
    s["eta_seconds"] = None
    start_time = s.get("start_time")
    if start_time is None:
        start_time = time.time()
        s["start_time"] = start_time
    s["elapsed_seconds"] = time.time() - start_time
    s["finished_at"] = time.time()
    set_worker_state("idle", None)
    save_status(job_id, s)


def fail_job(job_id, message):
    s = load_status(job_id)
    s["progress"] = 1.0
    s["status"] = "failed"
    s["worker"] = WORKER_ID
    s["error"] = message,
    s["eta_seconds"] = None
    start_time = s.get("start_time")
    if start_time is None:
        start_time = time.time()
        s["start_time"] = start_time
    s["elapsed_seconds"] = time.time() - start_time
    s["finished_at"] = time.time()
    set_worker_state("idle", None)
    save_status(job_id, s)


def run_job(job_id):

    base = os.path.join(JOBS_DIR, job_id)
    set_worker_state("busy", job_id)

    env = os.environ.copy()
    env["JOB_DIR"] = base
    env["CCACHE_DIR"] = "/ccache"

    log_path = os.path.join(base, "logs.txt")
    update_progress(job_id, 0.05)

    try:

        with open(log_path, "w", buffering=1) as log:
            log.write(f"Starting job {job_id}\n")
            print(f"Starting job {job_id}")

            # proc = subprocess.Popen(
            #     ["/scripts/run_retarget.sh"],
            #     stdout=log,
            #     stderr=log,
            #     env=env
            # )
            proc = subprocess.Popen(
                ["/scripts/run_retarget.sh"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                bufsize=1
            )

            # monitor process
            # while True:

            #     ret = proc.poll()

            #     if ret is not None:
            #         break

            #     update_progress(job_id, 0.5)
            #     time.sleep(10)

            start_time = time.time()


            for line in proc.stdout:

                log.write(line)
                log.flush()  # ensure line is immediately written
                # print("line", line)

                m = ninja_progress.search(line)
                # print("m", m)
                if m:
                    cur = int(m.group(1))
                    # print("cur", cur)
                    total = int(m.group(2))
                    start = 0.1
                    end = 0.9
                    length = end - start
                    if total > 150:
                        # print("total", total)

                        progress_ = cur / total
                        progress = start + progress_ * length
                        progress = round(progress, 3)
                        # print("progress", progress)

                        update_progress(job_id, progress)

            ret = proc.wait()

            log.write(f"Process exited with code {ret}\n")

            if ret != 0:
                log.write("Retargeting script failed\n")
                fail_job(job_id, f"retarget.sh exited with code {ret}")
                return
            end_time = time.time()
            diff_time = end_time - start_time
            print("diff_time", diff_time)
            BUILD_TIMES.append(diff_time)
        update_progress(job_id, 0.95)

        # compress artifacts
        artifact = os.path.join(base, "artifact.tar.zst")

        subprocess.run(
            [
                "tar",
                "--zstd",
                "-cf",
                artifact,
                "-C",
                base,
                "output"
            ],
            check=True
        )

        finish_job(job_id)

    except subprocess.CalledProcessError as e:

        with open(log_path, "a") as log:
            log.write(f"\nArtifact compression failed: {e}\n")

        fail_job(job_id, "artifact compression failed")

    except Exception as e:

        with open(log_path, "a") as log:
            log.write("\nWorker exception:\n")
            log.write(traceback.format_exc())

        fail_job(job_id, str(e))

    finally:

        set_worker_state("idle", None)



# def heartbeat():
#     while True:
#         r.hset("workers", WORKER_ID, time.time())
#         r.expire("workers", 10)  # if worker dies, entry disappears
#         time.sleep(2)


def heartbeat():

    while True:

        data = r.get(WORKER_KEY)

        if data:
            d = json.loads(data)
            set_worker_state(d["state"], d.get("job_id"))
        else:
            set_worker_state("idle")

        time.sleep(3)

# in a separate thread
import threading
threading.Thread(target=heartbeat, daemon=True).start()

set_worker_state("idle", None)

def fetch_job_for_worker():

    queue = r.lrange("retarget_queue", 0, -1)

    for job_id in queue:

        # job_id = job_id.decode()
        print("job_id", job_id)

        status = load_status(job_id)
        print("status", status)

        if status["tag"] in WORKER_TAGS:

            r.lrem("retarget_queue", 1, job_id)
            return job_id

    return None

while True:
    # job = r.blpop("retarget_queue")[1]
    # run_job(job)
    job = fetch_job_for_worker()
    print("job", job)
    if job:
        run_job(job)
    time.sleep(5.0)
