import os
import time
import uuid
import json
import tarfile
import tempfile
import redis
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

            with open(status_file, "w") as f:
                json.dump(status, f)

        # case 2: queued job not in redis queue
        if state == "queued" and job_id not in queue:

            print(f"Removing orphan queue job: {job_id}")

            status["status"] = "failed"
            status["error"] = "queue entry lost"

            with open(status_file, "w") as f:
                json.dump(status, f)


@app.on_event("startup")
def cleanup_orphaned_jobs():
    cleanup_jobs()

@app.post("/jobs")
async def create_job(tag: str = Form(...), cdsl: UploadFile = File(...), cpdsl: UploadFile = File(...),
                     config: UploadFile = File(...)):

    job_id = str(uuid.uuid4())
    token = str(uuid.uuid4())

    base = job_path(job_id)
    os.makedirs(base + "/input", exist_ok=True)

    # TODO: handle missing cfg or cpdsl
    if cdsl:
        with open(base + f"/input/{cdsl.filename}", "wb") as f:
            f.write(await cdsl.read())

    if cpdsl:
        with open(base + f"/input/{cpdsl.filename}", "wb") as f:
            f.write(await cpdsl.read())

    if config:
        with open(base + "/input/config.yaml", "wb") as f:
            f.write(await config.read())

    status = {
        "job_id": job_id,
        "token": token,
        "status": "queued",
        "tag": tag,
        "created_at": time.time(),
        "progress": 0,
    }

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
        status = load_status(job_id)
        # tag = status.get("tag", "unknown")
        tag = None
        queue_.append({"job_id": job_id, "tag": tag})

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

        # with open(status_file) as f:
        #     s = json.load(f)

        entry = {
            "job_id": job_id,
            "status": s.get("status"),
            "progress": s.get("progress", 0),
            "eta_seconds": s.get("eta_seconds"),
            "elapsed_seconds": s.get("elapsed_seconds"),
            "tag": s.get("tag"),
        }

        if s.get("status") == "running":
            running.append(entry)

        elif s.get("status") == "finished":
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

    if not os.path.exists(artifact):
        raise HTTPException(status_code=404)

    return FileResponse(artifact, filename="artifact.tar.zst")


# @app.get("/status")
# def server_status():
# 
#     now = time.time()
# 
#     workers = r.hgetall("workers")
# 
#     alive_workers = 0
#     for ts in workers.values():
#         if now - float(ts) < 10:
#             alive_workers += 1
# 
#     queue_len = r.llen("retarget_queue")
# 
#     busy_workers = 0
#     for job_id in os.listdir(JOBS_DIR):
#         sf = os.path.join(JOBS_DIR, job_id, "status.json")
#         if os.path.exists(sf):
#             with open(sf) as f:
#                 s = json.load(f)
#                 if s.get("status") == "running":
#                     busy_workers += 1
# 
#     free_workers = max(alive_workers - busy_workers, 0)
# 
#     return {
#         "queue_length": queue_len,
#         "total_workers": alive_workers,
#         "busy_workers": busy_workers,
#         "free_workers": free_workers
#     }

# @app.get("/workers")
# def workers_status():
# 
#     now = time.time()
# 
#     workers = r.hgetall("workers")
# 
#     result = {}
#     alive = 0
# 
#     for wid, ts in workers.items():
#         age = now - float(ts)
# 
#         if age < 10:
#             state = "alive"
#             alive += 1
#         else:
#             state = "stale"
# 
#         result[wid] = {
#             "last_seen_seconds_ago": round(age, 2),
#             "state": state
#         }
# 
#     return {
#         "total_workers": len(workers),
#         "alive_workers": alive,
#         "workers": result
#     }


# @app.get("/workers")
# def workers_status():
# 
#     keys = r.keys("worker:*")
# 
#     workers = {}
# 
#     for key in keys:
#         wid = key.split(":")[1]
# 
#         ts = int(r.get(key))
# 
#         workers[wid] = {
#             "last_seen_unix": ts
#         }
# 
#     return {
#         "total_workers": len(keys),
#         "workers": workers
#     }
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

    for job_id in os.listdir(JOBS_DIR):
        try:
            status = load_status(job_id)
        except FileNotFoundError:
            continue  # skip jobs without a status file

        if status.get("status") in  ("finished", "failed"):
            jobs.append((status.get("finished_at", 0), job_id, status))

    jobs.sort(reverse=True)

    return [
        {"job_id": j[1], **j[2]}
        for j in jobs[:limit]
    ]




DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>

<title>Retarget Build Cluster</title>

<style>

body {
    font-family: Arial;
    background:#0f172a;
    color:#e2e8f0;
    margin:40px;
}

h1 { margin-bottom:20px }

.card{
    background:#1e293b;
    border-radius:10px;
    padding:20px;
    margin-bottom:20px;
}

.metric{
    font-size:18px;
    margin-right:30px;
}

table{
    width:100%;
    border-collapse:collapse;
}

th,td{
    padding:8px;
    text-align:left;
}

th{
    background:#334155;
}

tr:nth-child(even){
    background:#1e293b;
}

.status-idle{color:#22c55e;font-weight:bold}
.status-busy{color:#f97316;font-weight:bold}

.progressbar{
    background:#334155;
    border-radius:6px;
    height:18px;
    width:100%;
}

.progress{
    background:#3b82f6;
    height:18px;
    border-radius:6px;
}

.badge {
    padding: 2px 8px;
    border-radius: 8px;
    color: white;
    font-size: 12px;
    margin-left: 4px;
}

</style>
</head>

<body>

<h1>⚙ Retarget Build Cluster</h1>

<div class="card" id="metrics">Loading...</div>

<div class="card">

<h2>Workers</h2>

<table id="workers">

<thead>
<tr>
<th>Worker</th>
<th>Status</th>
<th>Current Job</th>
<th>Last Seen</th>
<th>Tags</th>
</tr>
</thead>

<tbody></tbody>

</table>

</div>

<div class="card">

<h2>Running Jobs</h2>

<table id="running">

<thead>
<tr>
<th>Job ID</th>
<th>Progress</th>
<th>Elapsed</th>
<th>ETA</th>
<th>Tag</th>
</tr>
</thead>

<tbody></tbody>

</table>

</div>

<div class="card">

<h2>Queued Jobs</h2>

<table id="queued">

<thead>
<tr>
<th>Position</th>
<th>Job ID</th>
<th>Tag</th>
</tr>
</thead>

<tbody></tbody>

</table>

</div>

<div class="card">
<h2>Recently Finished Jobs</h2>
<table id="finished">
<thead>
<tr>
<th>Job ID</th>
<th>Status</th>
<th>Finished At</th>
<th>Tag</th>
</tr>
</thead>
<tbody></tbody>
</table>
</div>

<script>
const TAG_COLORS = {
    "llvm": "#4CAF50",
    "etiss": "#2196F3",
    "etiss-perf": "#FF9800"
};

function tagBadges(tags){
    if(!tags) return "";
    return tags.map(tag=>`<span class="badge" style="background:${TAG_COLORS[tag]||'#888'}">${tag}</span>`).join(" ");
}

function formatEta(s){

    if(!s) return "-"

    const m=Math.floor(s/60)
    const sec=s%60

    return m+"m "+sec+"s"
}

function progressBar(p){

    return `
    <div class="progressbar">
        <div class="progress" style="width:${p}%"></div>
    </div>
    ${Math.round(p)}%
    `
}

function formatDateTimeConditional(ts){
    if(ts === undefined || ts === null){
        return "invalid"
    }
    const d = new Date(ts*1000)
    const now = new Date()

    const isToday = d.getFullYear() === now.getFullYear() &&
                    d.getMonth() === now.getMonth() &&
                    d.getDate() === now.getDate()

    const hh = String(d.getHours()).padStart(2,'0')
    const min = String(d.getMinutes()).padStart(2,'0')
    const sec = String(d.getSeconds()).padStart(2,'0')
    const timePart = `${hh}:${min}:${sec}`

    if(isToday){
        return timePart
    } else {
        const yyyy = d.getFullYear()
        const mm = String(d.getMonth()+1).padStart(2,'0')
        const dd = String(d.getDate()).padStart(2,'0')
        return `${yyyy}-${mm}-${dd} ${timePart}`
    }
}

async function refresh(){

    const status=await fetch("/status").then(r=>r.json())
    const workers=await fetch("/workers").then(r=>r.json())
    const jobs=await fetch("/jobs").then(r=>r.json())

    document.getElementById("metrics").innerHTML=
        "<span class='metric'>Workers: "+status.total_workers+"</span>"+
        "<span class='metric'>Busy: "+status.busy_workers+"</span>"+
        "<span class='metric'>Free: "+status.free_workers+"</span>"+
        "<span class='metric'>Queue: "+status.queue_length+"</span>"

    /* workers */

    const wt=document.querySelector("#workers tbody")
    wt.innerHTML=""

    for(const [id,w] of Object.entries(workers.workers)){

        const row=document.createElement("tr")

        const sc=w.state==="idle"?"status-idle":"status-busy"

        row.innerHTML=
        "<td>"+id+"</td>"+
        "<td class='"+sc+"'>"+w.state+"</td>"+
        "<td>"+(w.job_id||"-")+"</td>"+
        "<td>"+formatDateTimeConditional(w.last_seen_unix)+"</td>"+
        "<td>"+tagBadges(w.tags)+"</td>"

        wt.appendChild(row)
    }

    /* running jobs */

    const rt=document.querySelector("#running tbody")
    rt.innerHTML=""

    for(const j of jobs.running){

        const row=document.createElement("tr")

        row.innerHTML=
        "<td>"+j.job_id+"</td>"+
        "<td>"+progressBar(Math.round(j.progress * 100))+"</td>"+
        "<td>"+formatEta(j.elapsed_seconds)+"</td>"+
        "<td>"+formatEta(j.eta_seconds)+"</td>"+
        "<td>"+tagBadges([j.tag])+"</td>"

        rt.appendChild(row)
    }

    /* queued jobs */

    const qt=document.querySelector("#queued tbody")
    qt.innerHTML=""

    // jobs.queued.forEach((j,i)=>{
    var i = 0;
    for(const j of jobs.queued){

        const row=document.createElement("tr")

        row.innerHTML=
        "<td>"+(i+1)+"</td>"+
        "<td>"+j.job_id+"</td>"+
        "<td>"+tagBadges([j.tag])+"</td>"

        qt.appendChild(row)
        i = i + 1;

    // })
    }

    const ft=document.querySelector("#finished tbody")
        ft.innerHTML=""
        jobs.recent_finished.forEach(j=>{
            const row=document.createElement("tr")
            row.innerHTML=
                "<td>"+j.job_id+"</td>"+
                "<td>"+j.status+"</td>"+
                "<td>"+formatDateTimeConditional(j.finished_at)+"</td>"+
                "<td>"+tagBadges([j.tag])+"</td>"
            ft.appendChild(row)
        })

}

refresh()
setInterval(refresh,2000)

</script>

</body>
</html>
"""

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_HTML


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
        def log_stream():
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
                        time.sleep(0.2)

        return StreamingResponse(log_stream(), media_type="text/plain")
    elif n_lines > 0:
        # Efficiently get last n_lines without reading entire file
        with open(log_file, "r") as f:
            last_lines = deque(f, maxlen=n_lines)
        return PlainTextResponse("".join(last_lines))

    return FileResponse(
        log_file,
        filename=f"{job_id}_logs.txt",
        media_type="text/plain"
    )
