import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api import api


@pytest.fixture
def service(tmp_path, monkeypatch):
    redis = MagicMock()
    redis.lrange.return_value = []
    redis.keys.return_value = []
    redis.llen.return_value = 0
    monkeypatch.setattr(api, "JOBS_DIR", str(tmp_path))
    monkeypatch.setattr(api, "r", redis)
    # Enter the context so startup cleanup runs, just as it does under Uvicorn.
    with TestClient(api.app) as client:
        yield client, redis, tmp_path


def submit(client, tag="llvm", extra_files=None):
    response = client.post(
        "/jobs",
        data={"tag": tag},
        files={
            "cdsl": ("test.dsl", b"core description"),
            "cpdsl": ("test.core_desc", b"split description"),
            "config": ("custom.yaml", b"option: true\n"),
            **(extra_files or {}),
        },
    )
    assert response.status_code == 200
    return response.json()


def test_submission_persists_inputs_and_enqueues_job(service):
    client, redis, root = service
    job = submit(client)
    base = root / job["job_id"]
    assert (base / "input/test.dsl").read_bytes() == b"core description"
    assert (base / "input/test.core_desc").read_bytes() == b"split description"
    assert (base / "input/config.yaml").read_bytes() == b"option: true\n"
    status = json.loads((base / "status.json").read_text())
    assert status.items() >= {**job, "status": "queued", "tag": "llvm", "progress": 0}.items()
    redis.rpush.assert_called_once_with("retarget_queue", job["job_id"])
    response = client.get(f"/jobs/{job['job_id']}", params={"token": job["token"]})
    assert response.status_code == 200
    assert response.json() == status


def test_submission_requires_all_files(service):
    client, redis, root = service
    response = client.post("/jobs", data={"tag": "llvm"})
    assert response.status_code == 422
    redis.rpush.assert_not_called()
    assert not [p for p in root.iterdir() if p.is_dir()]


@pytest.mark.parametrize("field", ["cdsl", "cpdsl"])
def test_submission_rejects_paths_in_upload_names(service, field):
    client, redis, root = service
    files = {key: (key, b"content") for key in ("cdsl", "cpdsl", "config")}
    files[field] = ("../outside.core_desc", b"content")
    response = client.post("/jobs", data={"tag": "etiss"}, files=files)
    assert response.status_code == 422
    redis.rpush.assert_not_called()
    assert not [p for p in root.iterdir() if p.is_dir()]


@pytest.mark.parametrize("suffix", ["", "/logs", "/artifact"])
def test_job_endpoints_reject_wrong_token(service, suffix):
    client, _, _ = service
    job = submit(client)
    response = client.get(f"/jobs/{job['job_id']}{suffix}", params={"token": "wrong"})
    assert response.status_code == 403


def test_logs_and_artifact_downloads(service):
    client, _, root = service
    job = submit(client)
    url = f"/jobs/{job['job_id']}"
    params = {"token": job["token"]}
    assert client.get(url + "/logs", params=params).text == "Logs not yet available\n"
    assert client.get(url + "/artifact", params=params).status_code == 404
    base = root / job["job_id"]
    (base / "logs.txt").write_text("first\nsecond\nthird\n")
    response = client.get(url + "/logs", params={**params, "n_lines": 2})
    assert response.status_code == 200
    assert response.text == "second\nthird\n"
    assert client.get(url + "/logs", params=params).text == "first\nsecond\nthird\n"
    (base / "artifact.tar.zst").write_bytes(b"test artifact")
    status = api.load_status(job["job_id"])
    status["status"] = "finished"
    api.save_status(job["job_id"], status)
    response = client.get(url + "/artifact", params=params)
    assert response.status_code == 200
    assert response.content == b"test artifact"
    assert f'filename="{job["job_id"]}_artifact.tar.zst"' in response.headers["content-disposition"]


def test_worker_and_queue_counts(service):
    client, redis, _ = service
    redis.llen.return_value = 3
    redis.keys.return_value = ["worker:idle", "worker:busy", "worker:expired"]
    redis.get.side_effect = lambda key: {
        "worker:idle": json.dumps({"state": "idle", "tags": ["llvm"], "ts": 100}),
        "worker:busy": json.dumps({"state": "busy", "job_id": "job", "ts": 101}),
        "worker:expired": None,
    }[key]
    response = client.get("/status")
    assert response.status_code == 200
    assert response.json() == {
        "queue_length": 3, "total_workers": 2, "busy_workers": 1, "free_workers": 1,
    }
    response = client.get("/workers")
    assert response.status_code == 200
    data = response.json()
    assert (data["total_workers"], data["idle_workers"], data["busy_workers"]) == (2, 1, 1)
    assert data["workers"]["busy"]["job_id"] == "job"
    assert data["workers"]["idle"]["tags"] == ["llvm"]


def test_cleanup_fails_only_orphaned_jobs(service):
    _, redis, root = service
    states = {"queued": "queued", "lost": "queued", "active": "running",
              "orphan": "running", "done": "finished"}
    for job_id, state in states.items():
        (root / job_id).mkdir()
        api.save_status(job_id, {"status": state})
    redis.lrange.return_value = ["queued"]
    redis.keys.return_value = ["worker:active"]
    redis.get.return_value = json.dumps({"job_id": "active"})
    api.cleanup_jobs()
    assert api.load_status("lost") == {"status": "failed", "error": "queue entry lost"}
    assert api.load_status("orphan") == {"status": "failed", "error": "worker disappeared"}
    for job_id in ("queued", "active", "done"):
        assert api.load_status(job_id) == {"status": states[job_id]}


def test_etiss_submission_uses_etiss_tag(service):
    client, _, _ = service
    job = submit(client, "etiss")
    assert api.load_status(job["job_id"])["tag"] == "etiss"


def test_perf_submission_preserves_index_and_hls(service):
    client, _, root = service
    job = submit(client, "etiss_perf", {
        "index": ("my-index.yaml", b"index data"),
        "hls": ("reports.tar.gz", b"archive bytes"),
    })
    base = root / job["job_id"] / "input"
    assert (base / "index.yaml").read_bytes() == b"index data"
    assert (base / "hls.tar.gz").read_bytes() == b"archive bytes"
    assert api.load_status(job["job_id"])["tag"] == "etiss_perf"


@pytest.mark.parametrize("field", [None, "index", "hls"])
def test_perf_submission_requires_both_extra_inputs(service, field):
    client, redis, root = service
    files = {key: (key, b"content") for key in ("cdsl", "cpdsl", "config")}
    if field:
        files[field] = (field, b"content")
    response = client.post("/jobs", data={"tag": "etiss_perf"}, files=files)
    assert response.status_code == 422
    redis.rpush.assert_not_called()
    assert not [p for p in root.iterdir() if p.is_dir()]


def test_dashboard_uploads_rewrite_host_import_paths(service):
    client, _, root = service
    job = submit(client, "etiss", {
        "cdsl": ("top.core_desc", b'import "/host/generated/split.core_desc"'),
        "cpdsl": ("split.core_desc", b'import "/host/etiss_arch_riscv/rv_base/RVI.core_desc"'),
    })
    base = root / job["job_id"] / "input"
    assert (base / "top.core_desc").read_text() == 'import "split.core_desc"'
    assert (base / "split.core_desc").read_text() == 'import "/tools/etiss_arch_riscv/rv_base/RVI.core_desc"'


def test_running_log_download_is_a_bounded_snapshot(service):
    import asyncio
    client, _, root = service
    job = submit(client)
    log = root / job["job_id"] / "logs.txt"
    log.write_bytes(b"original\n")
    response = api.get_logs(job["job_id"], job["token"])
    with log.open("ab") as handle:
        handle.write(b"appended during download\n")

    async def consume():
        return b"".join([chunk async for chunk in response.body_iterator])

    assert asyncio.run(consume()) == b"original\n"
    assert response.headers["content-length"] == str(len(b"original\n"))


def test_finished_log_stream_closes_after_tail(service):
    client, _, root = service
    job = submit(client)
    status = api.load_status(job["job_id"])
    status["status"] = "finished"
    api.save_status(job["job_id"], status)
    (root / job["job_id"] / "logs.txt").write_text("first\nlast\n")
    response = client.get(f"/jobs/{job['job_id']}/logs", params={"token": job["token"], "stream": True, "n_lines": 1})
    assert response.status_code == 200
    assert response.text == "last\n"
