import json
import multiprocessing as mp
import os
import time
from pathlib import Path

import pytest
import redis
from fastapi.testclient import TestClient

from api import api
from worker import worker
from worker.job_state import State


@pytest.fixture
def real_state(tmp_path, monkeypatch):
    host = os.getenv("TEST_REDIS_HOST")
    if not host:
        pytest.skip("Set TEST_REDIS_HOST to an isolated test Redis (database 15 is cleared)")
    r = redis.Redis(host=host, db=15, decode_responses=True)
    r.flushdb()
    state = State(r, tmp_path)
    state.reset()
    monkeypatch.setattr(worker, "r", r)
    monkeypatch.setattr(worker, "JOBS_DIR", str(tmp_path))
    monkeypatch.setattr(api, "r", r)
    monkeypatch.setattr(api, "JOBS_DIR", str(tmp_path))
    yield state
    r.flushdb()


def add(state, job, tag="etiss"):
    state.path(job).mkdir()
    state.save(job, {"job_id": job, "tag": tag, "status": "queued", "token": "secret", "epoch": state.epoch()})
    state.redis.rpush("retarget_queue", job)


def wait_for(predicate, timeout=10):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if predicate():
            return
        time.sleep(.03)
    raise AssertionError("Timed out waiting for job state")


def execute_one(tags, gate, results):
    worker.WORKER_ID = str(os.getpid())
    worker.WORKER_TAGS = tags
    gate.wait()
    job = worker.fetch_job_for_worker()
    results.put((os.getpid(), job))
    if job:
        worker.run_job(job)


def test_competing_workers_execute_each_job_once(real_state, monkeypatch):
    state = real_state
    script = state.root / "build.sh"
    script.write_text('#!/bin/bash\nset -e\nmkdir -p "$JOB_DIR/output"\necho "$JOB_TAG" >> "$JOB_DIR/executions"\nsleep .3\necho built > "$JOB_DIR/output/result"\n')
    script.chmod(0o755)
    monkeypatch.setenv("RETARGET_SCRIPT", str(script))
    for job, tag in [("compiler", "llvm"), ("iss1", "etiss"), ("iss2", "etiss"), ("perf", "etiss_perf")]:
        add(state, job, tag)
    ctx = mp.get_context("fork")
    gate, results = ctx.Barrier(8), ctx.Queue()
    processes = [ctx.Process(target=execute_one, args=(tags, gate, results))
                 for tags in [["etiss", "etiss_perf"]]*4 + [["etiss_perf"]]*2 + [["llvm"]]*2]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(15)
            assert process.exitcode == 0
        claims = [results.get(timeout=2)[1] for _ in processes]
        assert sorted(j for j in claims if j) == ["compiler", "iss1", "iss2", "perf"]
        assert state.redis.llen("retarget_queue") == 0
        for job in ("compiler", "iss1", "iss2", "perf"):
            assert state.load(job)["status"] == "finished"
            assert len((state.path(job) / "executions").read_text().splitlines()) == 1
            assert (state.path(job) / "artifact.tar.zst").stat().st_size > 0
    finally:
        for process in processes:
            if process.is_alive():
                process.kill()
                process.join()


@pytest.mark.parametrize("reset", [False, True])
def test_abort_or_reset_kills_silent_build_and_descendants(real_state, monkeypatch, reset):
    state = real_state
    script = state.root / "silent.sh"
    script.write_text('''#!/bin/bash
bash -c 'trap "" TERM; echo $$ > "$JOB_DIR/child.pid"; sleep 60' &
wait
''')
    script.chmod(0o755)
    monkeypatch.setenv("RETARGET_SCRIPT", str(script))
    add(state, "job")
    add(state, "queued")
    ctx = mp.get_context("fork")
    gate, results = ctx.Barrier(1), ctx.Queue()
    process = ctx.Process(target=execute_one, args=(["etiss"], gate, results))
    process.start()
    try:
        wait_for(lambda: (state.path("job") / "child.pid").exists())
        child = int((state.path("job") / "child.pid").read_text())
        if reset:
            old_epoch = state.epoch()
            state.reset()
            assert state.epoch() != old_epoch
            assert state.redis.llen("retarget_queue") == 0
            assert state.load("queued")["archived"]
        else:
            state.abort("job", "secret")
            state.abort("queued", "secret")
            assert state.redis.llen("retarget_queue") == 0
        process.join(8)
        assert process.exitcode == 0
        assert state.load("job")["status"] == "aborted"
        assert not (state.path("job") / "artifact.tar.zst").exists()
        proc = Path(f"/proc/{child}/stat")
        assert not proc.exists() or proc.read_text().split()[2] == "Z"
    finally:
        if process.is_alive():
            process.kill()
            process.join()


def test_restart_clears_dashboard_states_without_deleting_artifacts(real_state):
    state = real_state
    add(state, "old")
    state.register("stale-worker", ["etiss"])
    (state.path("old") / "artifact.tar.zst").write_bytes(b"keep me")
    with TestClient(api.app) as client:
        assert client.get("/jobs").json() == {"queued": [], "running": [], "finished": [], "recent_finished": []}
        assert client.get("/workers").json()["total_workers"] == 0
        assert client.get("/status").json()["queue_length"] == 0
        assert state.redis.llen("retarget_queue") == 0
        assert (state.path("old") / "artifact.tar.zst").read_bytes() == b"keep me"
        state.register("live-worker", ["etiss"])
        assert client.get("/workers").json()["idle_workers"] == 1


def test_abort_is_authorized_idempotent_and_race_safe(real_state):
    state = real_state
    with TestClient(api.app) as client:
        add(state, "job")
        assert client.post("/jobs/job/abort", params={"token": "bad"}).status_code == 403
        assert client.post("/jobs/missing/abort", params={"token": "secret"}).status_code == 404
        for _ in range(2):
            assert client.post("/jobs/job/abort", params={"token": "secret"}).json()["status"] == "aborted"
        assert state.claim(["etiss"], "worker") is None
        state.update("job", status="finished")
        assert state.load("job")["status"] == "aborted"


def test_aborting_one_worker_does_not_interrupt_another(real_state, monkeypatch):
    state = real_state
    script = state.root / "parallel.sh"
    script.write_text('''#!/bin/bash
set -e
mkdir -p "$JOB_DIR/output"
if [[ $(basename "$JOB_DIR") == slow ]]; then
    touch "$JOB_DIR/started"
    sleep 60
fi
echo done > "$JOB_DIR/output/result"
''')
    script.chmod(0o755)
    monkeypatch.setenv("RETARGET_SCRIPT", str(script))
    add(state, "slow")
    add(state, "fast")
    ctx = mp.get_context("fork")
    gate, results = ctx.Barrier(2), ctx.Queue()
    processes = [ctx.Process(target=execute_one, args=(["etiss"], gate, results)) for _ in range(2)]
    try:
        for process in processes:
            process.start()
        wait_for(lambda: (state.path("slow") / "started").exists())
        state.abort("slow", "secret")
        for process in processes:
            process.join(8)
            assert process.exitcode == 0
        assert state.load("slow")["status"] == "aborted"
        assert state.load("fast")["status"] == "finished"
        assert (state.path("fast") / "artifact.tar.zst").stat().st_size > 0
        assert not (state.path("slow") / "artifact.tar.zst").exists()
    finally:
        for process in processes:
            if process.is_alive():
                process.kill()
                process.join()


def claim_racer(root, host, gate, output):
    state = State(redis.Redis(host=host, db=15, decode_responses=True), root)
    gate.wait()
    output.put(state.claim(["etiss"], "racer"))


def test_abort_racing_a_claim_never_resurrects_job(real_state):
    state = real_state
    ctx = mp.get_context("fork")
    for index in range(8):
        job = f"race-{index}"
        add(state, job)
        gate, output = ctx.Barrier(2), ctx.Queue()
        process = ctx.Process(target=claim_racer, args=(state.root, os.environ["TEST_REDIS_HOST"], gate, output))
        process.start()
        gate.wait()
        state.abort(job, "secret")
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join()
        assert process.exitcode == 0
        assert output.get(timeout=2) in (None, job)
        state.update(job, status="finished")
        assert state.load(job)["status"] == "aborted"
        assert state.redis.llen("retarget_queue") == 0


def test_clear_history_preserves_active_jobs_and_files(real_state):
    state = real_state
    with TestClient(api.app) as client:
        for job, status in [("queued", "queued"), ("running", "running"), ("finished", "finished"), ("failed", "failed"), ("aborted", "aborted")]:
            add(state, job)
            record = state.load(job)
            record["status"] = status
            state.save(job, record)
            (state.path(job) / "logs.txt").write_text("retain logs")
        (state.path("finished") / "artifact.tar.zst").write_bytes(b"retain artifact")
        assert client.post("/jobs/completed/clear").json() == {"cleared": 3}
        assert client.post("/jobs/completed/clear").json() == {"cleared": 0}
        jobs = client.get("/jobs").json()
        assert jobs["recent_finished"] == []
        assert jobs["finished"] == []
        assert [job["job_id"] for job in jobs["running"]] == ["running"]
        assert [job["job_id"] for job in jobs["queued"]] == ["queued"]
        assert client.get("/jobs/finished/artifact", params={"token": "secret"}).content == b"retain artifact"
        for job in ("finished", "failed", "aborted"):
            assert client.get(f"/jobs/{job}/logs", params={"token": "secret"}).text == "retain logs"


def test_make_progress_reaches_dashboard_before_completion(real_state, monkeypatch):
    state = real_state
    add(state, "progress-job")
    script = state.root / "progress.sh"
    script.write_text('''#!/bin/bash
set -e
mkdir -p "$JOB_DIR/output"
echo '::progress:: 0.32 0.90 Building ETISS'
echo '[ 50%] Building CXX object'
while [[ ! -f "$JOB_DIR/continue" ]]; do sleep .05; done
echo '[ 10%] Built smaller target'
echo '::progress:: 0.90 0.94 Installing ETISS'
echo built > "$JOB_DIR/output/result"
''')
    script.chmod(0o755)
    monkeypatch.setenv("RETARGET_SCRIPT", str(script))
    ctx = mp.get_context("fork")
    gate, results = ctx.Barrier(1), ctx.Queue()
    process = ctx.Process(target=execute_one, args=(["etiss"], gate, results))
    process.start()
    try:
        wait_for(lambda: state.load("progress-job").get("progress", 0) > .6)
        client = TestClient(api.app)
        response = client.get("/jobs")
        assert response.status_code == 200
        job = response.json()["running"][0]
        assert job["progress"] == pytest.approx(.61)
        assert job["stage"] == "Building ETISS"
        state.update("progress-job", progress=.2)
        assert state.load("progress-job")["progress"] == pytest.approx(.61)
    finally:
        (state.path("progress-job") / "continue").touch()
        process.join(8)
        if process.is_alive():
            process.kill()
            process.join()
    assert process.exitcode == 0
    assert state.load("progress-job")["status"] == "finished"
    assert state.load("progress-job")["progress"] == 1
