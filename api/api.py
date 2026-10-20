import os
import asyncio
import re
import time
import uuid
import json
import redis
try:
    from job_state import State
except ImportError:
    from worker.job_state import State
from collections import deque
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import FileResponse
from fastapi.responses import HTMLResponse
from fastapi.responses import PlainTextResponse
from fastapi.responses import StreamingResponse

REDIS_HOST = os.getenv("REDIS_HOST", "redis")

r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

JOBS_DIR = "/jobs"

app = FastAPI()


def job_path(job_id):
    return os.path.join(JOBS_DIR, job_id)


def status_file(job_id):
    return os.path.join(job_path(job_id), "status.json")


def load_status(job_id):
    try:
        return State(r, JOBS_DIR).load(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Unknown job")


def save_status(job_id, data):
    State(r, JOBS_DIR).save(job_id, data)


def cleanup_jobs():

    print("Cleaning orphaned jobs...")

    queue = set(r.lrange("retarget_queue", 0, -1))

    running_jobs = set()

    # detect jobs currently owned by workers
    for key in r.keys("worker:*"):

        data = r.get(key)
        if not data:
            continue

        try:
            info = json.loads(data)
        except:
            continue

        job_id = info.get("job_id")
        if job_id:
            running_jobs.add(job_id)

    if not os.path.exists(JOBS_DIR):
        return

    for job_id in os.listdir(JOBS_DIR):

        job_dir = os.path.join(JOBS_DIR, job_id)
        status_file = os.path.join(job_dir, "status.json")

        if not os.path.exists(status_file):
            continue

        with open(status_file) as f:
            status = json.load(f)

        state = status.get("status")

        # case 1: job marked running but no worker owns it
        if state == "running" and job_id not in running_jobs:

            print(f"Marking orphaned job as failed: {job_id}")

            status["status"] = "failed"
            status["error"] = "worker disappeared"

            save_status(job_id, status)

        # case 2: queued job not in redis queue
        if state == "queued" and job_id not in queue:

            print(f"Removing orphan queue job: {job_id}")

            status["status"] = "failed"
            status["error"] = "queue entry lost"

            save_status(job_id, status)


@app.on_event("startup")
def cleanup_orphaned_jobs():
    if os.getenv("RESET_ON_STARTUP", "1") == "1":
        State(r, JOBS_DIR).reset()
    else:
        with State(r, JOBS_DIR).lock():
            cleanup_jobs()


@app.get("/health")
def health():
    return {"ready": True}

def rewrite_description(content, filenames):
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="CoreDSL files must be UTF-8 text")

    def rewrite(match):
        path = match[1]
        if "rv_base" in path:
            path = "/tools/etiss_arch_riscv/rv_base/" + path.split("rv_base", 1)[1].lstrip("/")
        elif "etiss_arch_riscv" in path:
            path = "/tools/etiss_arch_riscv/" + path.split("etiss_arch_riscv", 1)[1].lstrip("/")
        elif os.path.basename(path) in filenames:
            path = os.path.basename(path)
        return f'import "{path}"'

    return re.sub(r'import\s+"([^"]+)"', rewrite, text).encode()


@app.post("/jobs")
async def create_job(tag: str = Form(...), cdsl: UploadFile = File(...), cpdsl: UploadFile = File(...),
                     config: UploadFile = File(...), index: UploadFile = File(None),
                     hls: UploadFile = File(None)):

    if tag == "etiss_perf" and (index is None or hls is None):
        raise HTTPException(status_code=422, detail="etiss_perf requires index and hls uploads")
    for upload in (cdsl, cpdsl):
        if not upload.filename or upload.filename != os.path.basename(upload.filename) or upload.filename in (".", ".."):
            raise HTTPException(status_code=422, detail="Input filenames must be plain filenames")

    job_id = str(uuid.uuid4())
    token = str(uuid.uuid4())

    base = job_path(job_id)
    os.makedirs(base + "/input", exist_ok=True)

    for upload in (cdsl, cpdsl):
        content = rewrite_description(await upload.read(), (cdsl.filename, cpdsl.filename))
        with open(os.path.join(base, "input", upload.filename), "wb") as f:
            f.write(content)

    if config:
        with open(base + "/input/config.yaml", "wb") as f:
            f.write(await config.read())

    for upload, filename in ((index, "index.yaml"), (hls, "hls.tar.gz")):
        if upload is not None:
            with open(os.path.join(base, "input", filename), "wb") as f:
                f.write(await upload.read())

    status = {
        "job_id": job_id,
        "token": token,
        "status": "queued",
        "tag": tag,
        "created_at": time.time(),
        "progress": 0,
        "epoch": State(r, JOBS_DIR).epoch(),
    }

    with State(r, JOBS_DIR).lock():
        status["epoch"] = State(r, JOBS_DIR).epoch()
        save_status(job_id, status)
        r.rpush("retarget_queue", job_id)

    return {"job_id": job_id, "token": token}


@app.get("/jobs")
def jobs():

    queue = r.lrange("retarget_queue", 0, -1)

    running = []
    finished = []

    queue_ = []
    for job_id in queue:
        try:
            status = load_status(job_id)
        except HTTPException:
            continue
        if status.get("archived") or status["status"] != "queued":
            continue
        queue_.append({"job_id": job_id, "tag": status.get("tag", "unknown"), "token": status["token"]})

    if not os.path.exists(JOBS_DIR):
        return {
            "queued": queue_,
            "running": [],
            "finished": [],
            "recent_finished": [],
        }

    for job_id in os.listdir(JOBS_DIR):

        status_file = os.path.join(JOBS_DIR, job_id, "status.json")

        if not os.path.exists(status_file):
            continue
        s = load_status(job_id)
        if s.get("archived"):
            continue

        # with open(status_file) as f:
        #     s = json.load(f)

        entry = {
            "job_id": job_id,
            "status": s.get("status"),
            "progress": s.get("progress", 0),
            "stage": s.get("stage"),
            "eta_seconds": s.get("eta_seconds"),
            "elapsed_seconds": s.get("elapsed_seconds"),
            "tag": s.get("tag"),
            "token": s["token"],
        }

        if s.get("status") in ("running", "aborting"):
            running.append(entry)

        elif s.get("status") == "finished" and not s.get("history_hidden"):
            finished.append(entry)

    return {
        "queued": queue_,
        "running": running,
        "finished": finished,
        "recent_finished": last_finished_jobs(),
    }


@app.get("/jobs/{job_id}")
def job_status(job_id: str, token: str):

    status = load_status(job_id)

    if token != status["token"]:
        raise HTTPException(status_code=403)

    return status


@app.get("/jobs/{job_id}/artifact")
def download_artifact(job_id: str, token: str):

    status = load_status(job_id)

    if token != status["token"]:
        raise HTTPException(status_code=403)

    artifact = os.path.join(job_path(job_id), "artifact.tar.zst")

    if status["status"] != "finished" or not os.path.exists(artifact):
        raise HTTPException(status_code=404)

    return FileResponse(artifact, filename=f"{job_id}_artifact.tar.zst")


@app.get("/workers")
def workers_status():

    keys = r.keys("worker:*")

    workers = {}

    idle = 0
    busy = 0

    for key in keys:

        wid = key.split(":")[1]

        data = r.get(key)

        if not data:
            continue

        info = json.loads(data)

        workers[wid] = {
            "state": info["state"],
            "job_id": info.get("job_id"),
            "tags": info.get("tags"),
            "last_seen_unix": info["ts"]
        }

        if info["state"] == "idle":
            idle += 1
        else:
            busy += 1

    return {
        "total_workers": len(workers),
        "idle_workers": idle,
        "busy_workers": busy,
        "workers": workers
    }

@app.get("/status")
def server_status():

    queue_len = r.llen("retarget_queue")

    keys = r.keys("worker:*")

    idle = 0
    busy = 0

    for key in keys:

        data = r.get(key)

        if not data:
            continue

        info = json.loads(data)

        if info["state"] == "idle":
            idle += 1
        else:
            busy += 1

    return {
        "queue_length": queue_len,
        "total_workers": idle + busy,
        "busy_workers": busy,
        "free_workers": idle
    }


def last_finished_jobs(limit=10):

    jobs = []

    for job_id in os.listdir(JOBS_DIR) if os.path.isdir(JOBS_DIR) else []:
        try:
            status = load_status(job_id)
        except HTTPException:
            continue  # skip jobs without a status file

        if not status.get("archived") and not status.get("history_hidden") and status.get("status") in ("finished", "failed", "aborted"):
            jobs.append((status.get("finished_at", 0), job_id, status))

    jobs.sort(reverse=True)

    return [
        {"job_id": j[1], **j[2]}
        for j in jobs[:limit]
    ]




@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(readonly: bool = False):
    from pathlib import Path
    html = Path(__file__).with_name("dashboard.html").read_text()
    return html.replace("__READONLY__", "true" if readonly else "false")


@app.get("/dashboard/readonly", response_class=HTMLResponse)
def readonly_dashboard():
    return dashboard(True)


@app.get("/jobs/{job_id}/logs")
def get_logs(job_id: str, token: str, n_lines: int = 0, stream: bool = False):
    print("get_logs", job_id, n_lines, stream)

    # check_job_token(job_id, token)
    status = load_status(job_id)
    if token != status["token"]:
        raise HTTPException(status_code=403)

    job_dir = os.path.join(JOBS_DIR, job_id)
    log_file = os.path.join(job_dir, "logs.txt")

    if not os.path.exists(log_file):
        # raise HTTPException(404, "Logs not available")
        if stream:
            # create empty file for streaming
            open(log_file, "a").close()
        else:
            return PlainTextResponse("Logs not yet available\n")

    if stream:
        # Stream new lines as they appear
        async def log_stream():
            with open(log_file, "r") as f:
                # Move to end of file if n_lines == 0
                if n_lines > 0:
                    last_lines = deque(f, maxlen=n_lines)
                    for line in last_lines:
                        yield line
                else:
                    f.seek(0, 2)  # move to end
                while True:
                    line = f.readline()
                    if line:
                        yield line
                    else:
                        if load_status(job_id)["status"] in ("finished", "failed", "aborted"):
                            break
                        await asyncio.sleep(0.2)

        return StreamingResponse(log_stream(), media_type="text/plain")
    elif n_lines > 0:
        # Efficiently get last n_lines without reading entire file
        with open(log_file, "r") as f:
            last_lines = deque(f, maxlen=n_lines)
        return PlainTextResponse("".join(last_lines))

    # Bound the download to a snapshot length: logs can grow while a response
    # is being sent, which would otherwise invalidate Content-Length.
    size = os.path.getsize(log_file)

    def snapshot():
        with open(log_file, "rb") as handle:
            remaining = size
            while remaining:
                chunk = handle.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(snapshot(), media_type="text/plain", headers={
        "Content-Length": str(size),
        "Content-Disposition": f'attachment; filename="{job_id}_logs.txt"',
    })


@app.post("/jobs/{job_id}/abort")
def abort_job(job_id: str, token: str):
    try:
        return State(r, JOBS_DIR).abort(job_id, token)
    except PermissionError:
        raise HTTPException(status_code=403)
    except FileNotFoundError:
        raise HTTPException(status_code=404)


@app.post("/jobs/completed/clear")
def clear_completed_jobs():
    return {"cleared": State(r, JOBS_DIR).clear_completed()}
