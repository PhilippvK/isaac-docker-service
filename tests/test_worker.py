from unittest.mock import MagicMock

import pytest

from worker import worker


@pytest.mark.parametrize("tags,expected", [
    (["etiss"], "iss"), (["etiss_perf"], "perf"), (["etiss", "llvm"], "compiler"), (["etiss", "etiss_perf"], "iss"),
])
def test_worker_claims_only_supported_job_tags(tmp_path, monkeypatch, tags, expected):
    redis = MagicMock()
    redis.lrem.return_value = 1
    redis.lrange.return_value = ["compiler", "iss", "perf"]
    monkeypatch.setattr(worker, "JOBS_DIR", str(tmp_path))
    monkeypatch.setattr(worker, "r", redis)
    monkeypatch.setattr(worker, "WORKER_TAGS", tags)
    for job_id, tag in (("compiler", "llvm"), ("iss", "etiss"), ("perf", "etiss_perf")):
        (tmp_path / job_id).mkdir()
        worker.save_status(job_id, {"tag": tag, "status": "queued"})
    assert worker.fetch_job_for_worker() == expected
    redis.lrem.assert_called_once_with("retarget_queue", 1, expected)




@pytest.mark.parametrize("line,expected", [
    ("[ 25%] Building CXX object", .3),
    ("\x1b[32m[ 50%]\x1b[0m Linking", .5),
    ("[1/4] Building", .3),
    ("[ 2 / 4 ] Building", .5),
    ("[100%] Built target", .9),
    ("[5/4] Built target", .9),
])
def test_build_output_formats_including_small_builds(line, expected):
    progress = worker.BuildProgress()
    value, stage = progress.consume(line)
    assert value == pytest.approx(expected)
    assert stage is None


def test_multi_stage_build_progress_reserves_install_and_packaging():
    progress = worker.BuildProgress()
    assert progress.consume("::progress:: 0.40 0.65 Building simulator") == (.4, "Building simulator")
    assert progress.consume("[100%] Built") == (.65, "Building simulator")
    assert progress.consume("::progress:: 0.76 0.90 Building plugins") == (.76, "Building plugins")
    assert progress.consume("[1/2] Compiling")[0] == pytest.approx(.83)
    assert progress.consume("[100%] Built")[0] == .9
    assert progress.consume("::progress:: 0.90 0.94 Installing") == (.9, "Installing")


@pytest.mark.parametrize("line", ["[1/0]", "[1/2/3]", "ordinary log output", "::progress:: 0.5 0.2 bad", "::progress:: 0.9 1.0 bad", "::progress:: . . bad"])
def test_invalid_progress_is_ignored(line):
    assert worker.BuildProgress().consume(line) is None
