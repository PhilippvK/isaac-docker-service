import requests
import time
import sys
from pathlib import Path

class RetargetClient:
    def __init__(self, api_url: str, token: str = None):
        """
        api_url: base URL, e.g., "http://localhost:8080"
        token: optional API key / token if known
        """
        self.api_url = api_url.rstrip("/")
        self.token = token

    def submit_job(self, dsl_path: str, config_path: str):
        files = {
            "dsl": open(dsl_path, "rb"),
            "config": open(config_path, "rb")
        }
        resp = requests.post(f"{self.api_url}/jobs", files=files)
        resp.raise_for_status()
        data = resp.json()
        self.token = data["token"]
        return data["job_id"], data["token"]

    def get_status(self, job_id: str):
        resp = requests.get(f"{self.api_url}/jobs/{job_id}", params={"token": self.token})
        resp.raise_for_status()
        return resp.json()

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
            if prog_percent != last_progress:
                sys.stdout.write(f"\rJob {job_id} progress: {prog_percent}%")
                sys.stdout.flush()
                last_progress = prog_percent
            if status["status"] in ("finished", "failed"):
                print(f"\nJob {job_id} completed with status: {status['status']}")
                break
            time.sleep(poll_interval)
        return status["status"]

# ---------------------------
# Example usage
# ---------------------------
if __name__ == "__main__":
    client = RetargetClient("http://localhost:8080")

    # Submit a job
    # job_id, token = client.submit_job("test_files/test.dsl", "test_files/config.yaml")
    job_id, token = client.submit_job("test_files/XIsaac.splitted.core_desc", "test_files/config.yaml")
    print(f"Submitted job {job_id} with token {token}")

    # Wait for completion while showing progress
    status = client.wait_for_completion(job_id)

    # Download artifact
    artifact_file = Path(f"{job_id}_artifact.tar.zst")
    print(f"Downloading artifact to {artifact_file}")
    client.download_artifact(job_id, str(artifact_file))
    print("Download finished")
