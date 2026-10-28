from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from api import api
from client.cient import RetargetClient


def test_client_submits_perf_uploads_and_reads_plain_logs(tmp_path, monkeypatch):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    redis = MagicMock()
    redis.keys.return_value = []
    redis.lrange.return_value = []
    monkeypatch.setattr(api, "r", redis)
    monkeypatch.setattr(api, "JOBS_DIR", str(jobs))
    paths = {}
    for key, filename, content in (
        ("cdsl", "core.core_desc", b'import "/host/generated/instructions.core_desc"\nCore XIsaacCore {}'),
        ("cpdsl", "instructions.core_desc", b'import "/local/rv_base/RVI.core_desc"'),
        ("config", "config.yaml", b"{}"),
        ("index", "index.yaml", b"index data"),
        ("hls", "hls.tar.gz", b"archive data"),
    ):
        paths[key] = tmp_path / filename
        paths[key].write_bytes(content)
    with TestClient(api.app) as http:
        monkeypatch.setattr("client.cient.requests.post", http.post)
        monkeypatch.setattr("client.cient.requests.get", http.get)
        client = RetargetClient("http://testserver")
        job_id, token = client.submit_job(
            "etiss_perf", paths["cdsl"], paths["config"], paths["cpdsl"], paths["index"], paths["hls"],
        )
        assert client.get_status(job_id)["token"] == token
        base = jobs / job_id
        assert (base / "input/index.yaml").read_bytes() == b"index data"
        assert (base / "input/hls.tar.gz").read_bytes() == b"archive data"
        assert '/tools/etiss_arch_riscv/rv_base/RVI.core_desc' in (base / "input/instructions.core_desc").read_text()
        assert (base / "input/core.core_desc").read_text().startswith('import "instructions.core_desc"')
        (base / "logs.txt").write_text("first\nsecond\n")
        assert client.get_log_buf(job_id, 1) == "second\n"

        assert client.abort_job(job_id)["status"] == "aborted"
        assert client.abort_job(job_id)["status"] == "aborted"
