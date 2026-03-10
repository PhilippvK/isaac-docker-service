import os
import uuid
import json
import tarfile
import redis
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

REDIS_HOST = os.getenv("REDIS_HOST", "redis")

r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

JOBS_DIR = "/jobs"

app = FastAPI()


def job_path(job_id):
    return os.path.join(JOBS_DIR, job_id)


def status_file(job_id):
    return os.path.join(job_path(job_id), "status.json")


def load_status(job_id):
    with open(status_file(job_id)) as f:
        return json.load(f)


def save_status(job_id, data):
    with open(status_file(job_id), "w") as f:
        json.dump(data, f)


@app.post("/jobs")
async def create_job(dsl: UploadFile = File(...),
                     config: UploadFile = File(...)):

    job_id = str(uuid.uuid4())
    token = str(uuid.uuid4())

    base = job_path(job_id)
    os.makedirs(base + "/input", exist_ok=True)

    with open(base + "/input/dsl.dsl", "wb") as f:
        f.write(await dsl.read())

    with open(base + "/input/config.yaml", "wb") as f:
        f.write(await config.read())

    status = {
        "job_id": job_id,
        "token": token,
        "status": "queued",
        "progress": 0
    }

    save_status(job_id, status)

    r.rpush("retarget_queue", job_id)

    return {"job_id": job_id, "token": token}


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

    if not os.path.exists(artifact):
        raise HTTPException(status_code=404)

    return FileResponse(artifact, filename="artifact.tar.zst")


@app.get("/status")
def server_status():

    queue_len = r.llen("retarget_queue")

    return {
        "queue_length": queue_len
    }
