import re
import requests
import time
import sys
from pathlib import Path
from io import BytesIO
from contextlib import ExitStack

RV_BASE_CONTAINER_ROOT = "/tools/etiss_arch_riscv/rv_base"


class RetargetClient:
    def __init__(self, api_url: str, token: str = None):
        """
        api_url: base URL, e.g., "http://localhost:8080"
        token: optional API key / token if known
        """
        self.api_url = api_url.rstrip("/")
        self.token = token

    def _rewrite_dsl(self, dsl_path: str) -> bytes:
        """
        Rewrites rv_base imports so they point to the container path.
        """

        dsl_filename = Path(dsl_path).name
        text = Path(dsl_path).read_text()

        import_re = re.compile(r'import\s+"([^"]+)"')

        def replace(match):
            path = match.group(1)

            if "rv_base" in path:
                new_path = path.split("rv_base", 1)[1].lstrip("/")
                return f'import "{RV_BASE_CONTAINER_ROOT}/{new_path}"'

            if "etiss_arch_riscv" in path:
                new_path = path.split("etiss_arch_riscv", 1)[1].lstrip("/")
                return f'import "/tools/etiss_arch_riscv/{new_path}"'

            return match.group(0)

        rewritten = import_re.sub(replace, text)

        return dsl_filename, rewritten.encode("utf-8")

    def submit_job(self, tag: str, dsl_path: str, config_path: str,
                   cpdsl_path=None, index_path=None, hls_path=None):
        dsl_filename, rewritten_dsl = self._rewrite_dsl(dsl_path)
        cpdsl_filename, rewritten_cpdsl = self._rewrite_dsl(cpdsl_path or dsl_path)
        # Generated top-level files can reference the split description using
        # its original absolute path. Both uploads now share the input directory.
        rewritten_dsl = re.sub(
            rb'import\s+"([^"]+)"',
            lambda match: b'import "' + cpdsl_filename.encode() + b'"'
            if Path(match.group(1).decode()).name == cpdsl_filename else match.group(0),
            rewritten_dsl,
        )
        with ExitStack() as stack:
            files = {
                "cdsl": (dsl_filename, BytesIO(rewritten_dsl)),
                "cpdsl": (cpdsl_filename, BytesIO(rewritten_cpdsl)),
                "config": stack.enter_context(open(config_path, "rb")),
            }
            for field, path in (("index", index_path), ("hls", hls_path)):
                if path is not None:
                    files[field] = stack.enter_context(open(path, "rb"))
            resp = requests.post(f"{self.api_url}/jobs", files=files, data={"tag": tag})
        resp.raise_for_status()
        data = resp.json()
        self.token = data["token"]
        return data["job_id"], data["token"]

    def abort_job(self, job_id: str):
        resp = requests.post(f"{self.api_url}/jobs/{job_id}/abort", params={"token": self.token})
        resp.raise_for_status()
        return resp.json()

    def get_status(self, job_id: str):
        resp = requests.get(f"{self.api_url}/jobs/{job_id}", params={"token": self.token})
        resp.raise_for_status()
        return resp.json()

    def get_log_buf(self, job_id: str, n_lines: int = 50):
        resp = requests.get(f"{self.api_url}/jobs/{job_id}/logs", params={"token": self.token, "n_lines": n_lines})
        resp.raise_for_status()
        return resp.text
        # with open(dest_path, "wb") as f:
        #     for chunk in resp.iter_content(1024 * 1024):
        #         f.write(chunk)

    def download_artifact(self, job_id: str, dest_path: str):
        resp = requests.get(f"{self.api_url}/jobs/{job_id}/artifact", params={"token": self.token}, stream=True)
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(1024*1024):
                f.write(chunk)

    def wait_for_completion(self, job_id: str, poll_interval: float = 5.0):
        """Waits for job completion and prints live progress"""
        last_progress = -1
        while True:
            status = self.get_status(job_id)
            prog = status.get("progress", 0.0)
            prog_percent = int(prog*100)
            log_buf = self.get_log_buf(job_id)
            print("log_buf", log_buf)
            if prog_percent != last_progress:
                sys.stdout.write(f"\rJob {job_id} progress: {prog_percent}%")
                sys.stdout.flush()
                last_progress = prog_percent
            if status["status"] in ("finished", "failed", "aborted"):
                print(f"\nJob {job_id} completed with status: {status['status']}")
                break
            time.sleep(poll_interval)
        return status["status"]

    def download_logs(self, job_id: str, dest_path: str):
    
        resp = requests.get(
            f"{self.api_url}/jobs/{job_id}/logs",
            params={"token": self.token},
            stream=True
        )
    
        resp.raise_for_status()
    
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(1024 * 1024):
                f.write(chunk)


# ---------------------------
# Example usage
# ---------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("tag", nargs="?", choices=["llvm", "etiss", "etiss_perf"])
    parser.add_argument("--abort", metavar="JOB_ID")
    parser.add_argument("--token")
    parser.add_argument("--api-url", default="http://localhost:8080")
    parser.add_argument("--cdsl", default="test_files/XIsaac.splitted.core_desc")
    parser.add_argument("--cpdsl")
    parser.add_argument("--config", default="test_files/config.yaml")
    parser.add_argument("--index")
    parser.add_argument("--hls", help="gzip tar of the HLS report directory contents")
    args = parser.parse_args()
    if args.abort:
        if not args.token:
            parser.error("--abort requires --token")
        print(RetargetClient(args.api_url, args.token).abort_job(args.abort))
        sys.exit(0)
    if not args.tag:
        parser.error("a target tag or --abort is required")
    if args.tag == "etiss_perf" and (not args.index or not args.hls):
        parser.error("etiss_perf requires --index and --hls")
    client = RetargetClient(args.api_url)

    # Submit a job
    # job_id, token = client.submit_job("test_files/test.dsl", "test_files/config.yaml")
    job_id, token = client.submit_job(args.tag, args.cdsl, args.config, args.cpdsl, args.index, args.hls)
    print(f"Submitted job {job_id} with token {token}")
    time.sleep(1)

    # Wait for completion while showing progress
    status = client.wait_for_completion(job_id)
    # if status != "finished":
    log_file = Path(f"{job_id}_logs.txt")
    print(f"Downloading logs to {log_file}")
    client.download_logs(job_id, str(log_file))
    if status != "finished":
        print("Artifact not available (job failed)")
    else:
        # Download artifact
        artifact_file = Path(f"{job_id}_artifact.tar.zst")
        print(f"Downloading artifact to {artifact_file}")
        client.download_artifact(job_id, str(artifact_file))
        print("Download finished")
