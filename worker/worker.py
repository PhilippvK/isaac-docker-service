import os
import json
import time
import redis
import subprocess

REDIS_HOST = os.getenv("REDIS_HOST", "redis")

r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

JOBS_DIR = "/jobs"


def status_file(job_id):
    return os.path.join(JOBS_DIR, job_id, "status.json")


def load_status(job_id):
    with open(status_file(job_id)) as f:
        return json.load(f)


def save_status(job_id, data):
    with open(status_file(job_id), "w") as f:
        json.dump(data, f)


def update_progress(job_id, progress):
    s = load_status(job_id)
    s["progress"] = progress
    s["status"] = "running"
    save_status(job_id, s)


def finish_job(job_id):
    s = load_status(job_id)
    s["progress"] = 1.0
    s["status"] = "finished"
    save_status(job_id, s)


def run_job(job_id):

    base = os.path.join(JOBS_DIR, job_id)

    env = os.environ.copy()
    env["JOB_DIR"] = base
    env["CCACHE_DIR"] = "/ccache"

    log = open(base + "/logs.txt", "w")

    proc = subprocess.Popen(
        ["/scripts/run_retarget.sh"],
        stdout=log,
        stderr=log,
        env=env
    )

    while proc.poll() is None:
        update_progress(job_id, 0.5)
        time.sleep(10)

    subprocess.run([
        "tar",
        "--zstd",
        "-cf",
        base + "/artifact.tar.zst",
        "-C",
        base,
        "output"
    ])

    finish_job(job_id)


while True:

    job = r.blpop("retarget_queue")[1]

    run_job(job)
