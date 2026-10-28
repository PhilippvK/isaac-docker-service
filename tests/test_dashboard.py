import os
import socket
import threading

from playwright.sync_api import sync_playwright
import uvicorn

from tests.test_concurrency import add, real_state, wait_for


def test_dashboard_submission_actions_and_readonly(real_state, tmp_path):
    from api import api
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(api.app, lifespan="off", log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        wait_for(lambda: server.started)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url + "/dashboard")
            assert not page.locator("#submit-panel").is_visible()
            assert not page.locator("#log-panel").is_visible()
            page.get_by_role("button", name="New job", exact=True).click()
            page.locator('[name="tag"]').select_option("etiss")
            for field, name in [("cdsl", "top.core_desc"), ("cpdsl", "split.core_desc"), ("config", "config.yaml")]:
                page.locator(f'[name="{field}"]').set_input_files({"name": name, "mimeType": "text/plain", "buffer": b"test"})
            page.get_by_role("button", name="Submit job", exact=True).click()
            page.locator("#queued tr").wait_for()
            row = page.locator("#queued tr")
            assert row.locator("td").nth(1).inner_text() == "etiss"
            assert row.get_by_role("button", name="Monitor logs", exact=True).count() == 0
            assert row.get_by_role("button", name="Download logs", exact=True).count() == 0
            assert row.locator(".badge.tag-etiss").count() == 1
            assert row.get_by_role("button", name="Abort", exact=True).inner_text() == ""
            job = row.locator("td").first.inner_text()
            row.get_by_role("button", name="Abort", exact=True).click()
            page.locator("#finished tr").wait_for()
            assert real_state.load(job)["status"] == "aborted"
            page.get_by_role("button", name="New job", exact=True).click()
            page.get_by_role("button", name="Submit job", exact=True).click()
            page.locator("#queued tr").wait_for()
            job = page.locator("#queued tr td").first.inner_text()
            assert real_state.claim(["etiss"], "browser-worker") == job
            (real_state.path(job) / "logs.txt").write_text("compiler is running\n")
            page.locator("#running tr").wait_for()
            row = page.locator("#running tr")
            assert row.get_by_role("progressbar").count() == 1
            assert row.locator(".progress").count() == 1
            row.get_by_role("button", name="Monitor logs", exact=True).click()
            page.wait_for_function("document.getElementById('logs').textContent.includes('compiler is running')")
            (real_state.path(job) / "logs.txt").write_text("compiler is running\nfinished\n")
            page.wait_for_function("document.getElementById('logs').textContent.includes('finished')")
            page.get_by_role("button", name="Close monitor", exact=True).click()
            assert not page.locator("#log-panel").is_visible()
            with page.expect_download() as download:
                row.get_by_role("button", name="Download logs", exact=True).click()
            saved = tmp_path / "downloaded-logs"
            download.value.save_as(saved)
            assert saved.read_text().endswith("finished\n")
            (real_state.path(job) / "artifact.tar.zst").write_bytes(b"test artifact")
            real_state.update(job, status="finished", progress=1, finished_at=1)
            page.locator("#finished tr").filter(has_text=job).wait_for()
            with page.expect_download() as download:
                page.locator("#finished tr").filter(has_text=job).get_by_role("button", name="Download artifact", exact=True).click()
            assert download.value.suggested_filename == f"{job}_artifact.tar.zst"
            download.value.save_as(tmp_path / "artifact")
            assert (tmp_path / "artifact").read_bytes() == b"test artifact"
            page.get_by_role("button", name="New job", exact=True).click()
            page.locator('[name="tag"]').select_option("etiss_perf")
            assert page.locator('[name="index"]').get_attribute("required") is not None
            for field, name in [("index", "index.yml"), ("hls", "hls.tar.gz")]:
                page.locator(f'[name="{field}"]').set_input_files({"name": name, "mimeType": "application/octet-stream", "buffer": b"perf input"})
            page.get_by_role("button", name="Submit job", exact=True).click()
            page.locator("#queued tr").wait_for()
            perf_job = page.locator("#queued tr td").first.inner_text()
            assert real_state.load(perf_job)["tag"] == "etiss_perf"
            assert (real_state.path(perf_job) / "input/index.yaml").read_bytes() == b"perf input"
            assert (real_state.path(perf_job) / "input/hls.tar.gz").read_bytes() == b"perf input"
            page.get_by_role("button", name="New job", exact=True).click()
            page.locator('[name="tag"]').select_option("spike")
            for field, name in [("cdsl", "top.core_desc"), ("cpdsl", "split.core_desc"), ("config", "config.yaml")]:
                page.locator(f'[name="{field}"]').set_input_files({"name": name, "mimeType": "text/plain", "buffer": b"test"})
            page.get_by_role("button", name="Submit job", exact=True).click()
            page.locator("#queued tr").wait_for()
            spike_row = page.locator("#queued tr").filter(has=page.locator(".badge.tag-spike"))
            spike_job = spike_row.locator("td").first.inner_text()
            assert real_state.load(spike_job)["tag"] == "spike"
            assert spike_row.count() == 1
            add(real_state, "readonly-running")
            assert real_state.claim(["etiss"], "readonly-worker") == "readonly-running"
            real_state.update("readonly-running", progress=.42, elapsed_seconds=78, eta_seconds=120, stage="Building ETISS")
            real_state.register("readonly-worker", ["etiss"], "readonly-running")
            real_state.register("idle-worker", ["llvm"])
            page.wait_for_function("document.querySelector('[aria-valuenow=\"42\"]') !== null")
            assert "Building ETISS" in page.locator("#running .progress-label").inner_text()
            if os.getenv("DASHBOARD_SCREENSHOT"):
                page.screenshot(path=os.environ["DASHBOARD_SCREENSHOT"], full_page=True)
            readonly = browser.new_page()
            writes = []
            readonly.on("request", lambda request: writes.append(request.method) if request.method != "GET" else None)
            readonly.goto(url + "/dashboard/readonly")
            readonly.locator("#finished tr").first.wait_for()
            readonly.locator("#running tr").first.wait_for()
            readonly.locator("#queued tr").first.wait_for()
            assert readonly.get_by_text("Read-only view — controls are disabled.").is_visible()
            assert all(b.is_disabled() for b in readonly.locator("button").all())
            assert readonly.locator('[name="cdsl"]').is_disabled()
            readonly.locator("#submit").evaluate("form => form.dispatchEvent(new Event('submit', {cancelable:true}))")
            assert not readonly.locator("#submit-panel").is_visible()
            assert not readonly.locator("#log-panel").is_visible()
            assert not writes
            page.get_by_role("button", name="Clear recently completed jobs", exact=True).click()
            page.wait_for_function("document.querySelectorAll('#finished tr').length === 0")
            assert real_state.load(job)["history_hidden"]
            assert (real_state.path(job) / "artifact.tar.zst").read_bytes() == b"test artifact"
            assert real_state.load("readonly-running")["status"] == "running"
            assert real_state.load(perf_job)["status"] == "queued"
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)
        sock.close()
