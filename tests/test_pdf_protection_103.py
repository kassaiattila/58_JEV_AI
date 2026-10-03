"""PDF protection must describe the live helper, never a configured or former limit."""

import sys
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from jav import api, isolated_pdf
from tests import pdf_reader_probe as probe


@pytest.fixture(autouse=True)
def isolated_default(monkeypatch):
    monkeypatch.setattr(isolated_pdf, "_default", None)
    yield
    if isolated_pdf._default is not None:
        isolated_pdf._default.close()


def test_closing_helper_clears_effective_protection():
    reader = isolated_pdf.Reader(memory_mb=512, startup_timeout_s=60)
    try:
        reader.call(probe.helper_pid, timeout_s=10)
        assert reader.memory_limited
    finally:
        reader.close()
    assert reader.memory_limited is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows job failure injection")
def test_windows_limit_failure_is_visible_and_strict_mode_refuses(monkeypatch):
    def unavailable(*args):
        raise OSError("synthetic job assignment failure")

    monkeypatch.setattr(isolated_pdf, "_windows_job", unavailable)
    reader = isolated_pdf.Reader(memory_mb=512, startup_timeout_s=60)
    try:
        assert reader.call(probe.echo, timeout_s=10, value="allowed") == "allowed"
        state = reader.protection_status()
        assert state["state"] == "unprotected"
        assert state["reason"] == "windows_job_unavailable"
        assert state["effective_memory_mb"] is None
    finally:
        reader.close()
    reader = isolated_pdf.Reader(memory_mb=512, startup_timeout_s=60, require_memory_limit=True)
    try:
        with pytest.raises(isolated_pdf.PdfReaderLimit) as error:
            reader.call(probe.echo, timeout_s=10, value="must not run")
        assert error.value.reason == "memory_limit_unavailable"
        assert reader.protection_status()["state"] == "unprotected"
    finally:
        reader.close()


def test_health_has_separate_service_and_worker_protection(tmp_path):
    with TestClient(api.create_app(store_path=tmp_path / "test.sqlite"), base_url="http://127.0.0.1:8930") as client:
        report = client.get("/api/health").json()["pdf_protection"]
    assert set(report) == {"service", "worker"}
    assert report["service"]["configured"]["require_memory_limit"] is False
    assert report["worker"]["state"] in {"unknown", "stale"}
    assert report["worker"]["effective_memory_mb"] is None


def test_status_does_not_start_a_helper_and_default_strict_mode_is_off():
    report = isolated_pdf.protection_status()
    assert report["state"] == "unknown"
    assert report["reason"] == "not_started"
    assert report["configured"]["require_memory_limit"] is False
    assert report["effective_memory_mb"] is None
    assert isolated_pdf._default is None


@pytest.mark.parametrize("isolated,memory_mb", [(False, 512), (True, 0)])
def test_strict_mode_refuses_disabled_limits_before_calling_parser(monkeypatch, isolated, memory_mb):
    settings = replace(isolated_pdf.settings(), isolated=isolated, memory_mb=memory_mb, require_memory_limit=True)
    monkeypatch.setattr(isolated_pdf, "settings", lambda: settings)

    def forbidden():
        pytest.fail("a parser must not be called without the required memory limit")

    with pytest.raises(isolated_pdf.PdfReaderLimit) as error:
        isolated_pdf.run(forbidden, kind="read")
    assert error.value.reason == "memory_limit_unavailable"
    assert isolated_pdf.protection_status()["state"] == "unprotected"


def test_disabled_isolation_is_visible_and_non_strict_mode_still_works(monkeypatch):
    settings = replace(isolated_pdf.settings(), isolated=False)
    monkeypatch.setattr(isolated_pdf, "settings", lambda: settings)
    assert isolated_pdf.run(lambda: 42, kind="read") == 42
    report = isolated_pdf.protection_status()
    assert (report["state"], report["reason"]) == ("unprotected", "isolation_disabled")


def test_helper_death_and_restart_cannot_reuse_a_green_observation():
    reader = isolated_pdf.Reader(memory_mb=512, startup_timeout_s=60)
    try:
        reader.call(probe.helper_pid, timeout_s=10)
        first = reader.protection_status()
        assert first["state"] == "protected" and first["effective_memory_mb"] == 512
        reader._proc.kill()
        reader._proc.join(10)
        stale = reader.protection_status()
        assert stale["state"] == "stale" and stale["effective_memory_mb"] is None
        reader.call(probe.helper_pid, timeout_s=10)
        second = reader.protection_status()
        assert second["state"] == "protected"
        assert second["helper_pid"] != first["helper_pid"]
    finally:
        reader.close()


def test_zero_limit_is_unprotected_even_when_helper_runs():
    reader = isolated_pdf.Reader(memory_mb=0, startup_timeout_s=60)
    try:
        assert reader.call(probe.echo, timeout_s=10, value=7) == 7
        assert reader.protection_status()["state"] == "unprotected"
        assert reader.protection_status()["reason"] == "memory_limit_disabled"
    finally:
        reader.close()


def test_settings_change_invalidates_and_replaces_the_helper(monkeypatch):
    isolated_pdf.run(probe.helper_pid, kind="read")
    previous = isolated_pdf._default
    settings = replace(isolated_pdf.settings(), memory_mb=512, require_memory_limit=True)
    monkeypatch.setattr(isolated_pdf, "settings", lambda: settings)
    assert isolated_pdf.protection_status()["state"] == "stale"
    isolated_pdf.run(probe.helper_pid, kind="read")
    assert isolated_pdf._default is not previous
    assert previous.memory_limited is False
    assert isolated_pdf.protection_status()["effective_memory_mb"] == 512


def _worker_report():
    return {"state": "protected", "reason": "memory_limit_applied", "effective_memory_mb": 512,
            "helper_pid": 123, "process_pid": 456, "observed_at": time.time(),
            "configured": {"isolated": True, "memory_mb": 512, "require_memory_limit": False}}


def test_worker_instance_lock_rejects_a_recent_report_after_restart(tmp_path, monkeypatch):
    from jav.runtime import pdf_status

    path = tmp_path / "test.sqlite"
    monkeypatch.setattr(isolated_pdf, "protection_status", _worker_report)
    with pdf_status.publish(path):
        first = pdf_status.worker_status(path, running=True)
        assert first["state"] == "protected"
    # Simulate a new worker holding its ordinary lock before it publishes a new report.
    old = pdf_status.worker_status(path, running=True)
    assert old["state"] == "stale" and old["reason"] == "worker_instance_ended"
    assert old["effective_memory_mb"] is None
    with pdf_status.publish(path):
        second = pdf_status.worker_status(path, running=True)
        assert second["state"] == "protected" and second["instance"] != first["instance"]


@pytest.mark.parametrize("age", [11, -1])
def test_expired_or_future_worker_report_is_stale(tmp_path, monkeypatch, age):
    from jav.runtime import pdf_status

    path = tmp_path / "test.sqlite"
    monkeypatch.setattr(isolated_pdf, "protection_status", _worker_report)
    with pdf_status.publish(path):
        report = pdf_status.worker_status(path, running=True)
        stale = pdf_status.worker_status(path, running=True, now=report["reported_at"] + age)
        assert stale["state"] == "stale" and stale["reason"] == "report_expired"
        assert stale["effective_memory_mb"] is None
        stopped = pdf_status.worker_status(path, running=False)
        assert stopped["state"] == "stale" and stopped["reason"] == "worker_not_running"


@pytest.mark.parametrize("contents", [None, "broken", "[]", '{"schema": 0}', '{"schema": 1, "instance": "../../outside"}'])
def test_missing_or_invalid_worker_report_is_unknown(tmp_path, contents):
    from jav.runtime import pdf_status

    path = tmp_path / "test.sqlite"
    if contents is not None:
        pdf_status.report_path(path).write_text(contents, encoding="utf-8")
    report = pdf_status.worker_status(path, running=True)
    assert report["state"] == "unknown" and report["effective_memory_mb"] is None


def test_heartbeat_refreshes_while_worker_is_busy_and_tracks_helper_loss(tmp_path, monkeypatch):
    from jav.runtime import pdf_status

    path = tmp_path / "test.sqlite"
    monkeypatch.setattr(pdf_status, "REPORT_INTERVAL_S", 0.02)
    state = _worker_report()
    monkeypatch.setattr(isolated_pdf, "protection_status", lambda: dict(state))
    with pdf_status.publish(path):
        first = pdf_status.worker_status(path, running=True)
        state.update(state="stale", reason="helper_stopped", effective_memory_mb=None)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            report = pdf_status.worker_status(path, running=True)
            if report["state"] == "stale":
                break
            time.sleep(0.01)
        assert report["state"] == "stale"
        assert report["reported_at"] > first["reported_at"]


def test_status_does_not_wait_for_a_busy_parser():
    reader = isolated_pdf.Reader(memory_mb=512, startup_timeout_s=60)
    try:
        reader.call(probe.helper_pid, timeout_s=10)
        with reader._lock:
            assert reader.protection_status()["state"] == "protected"
    finally:
        reader.close()


def test_api_preserves_the_named_limit_reason(tmp_path):
    app = api.create_app(store_path=tmp_path / "test.sqlite")

    @app.get("/api/synthetic-limit")
    def fail():
        raise isolated_pdf.PdfReaderLimit("the PDF reader memory limit is unavailable", reason="memory_limit_unavailable")

    app.router.routes.insert(0, app.router.routes.pop())  # before the application's UI fallback route
    with TestClient(app, base_url="http://127.0.0.1:8930") as client:
        response = client.get("/api/synthetic-limit")
    assert response.status_code == 422
    assert response.json()["reason"] == "memory_limit_unavailable"


def test_report_does_not_claim_protection_with_inconsistent_limit(tmp_path, monkeypatch):
    from jav.runtime import pdf_status

    path = tmp_path / "test.sqlite"
    state = _worker_report()
    state["effective_memory_mb"] = 0
    monkeypatch.setattr(isolated_pdf, "protection_status", lambda: state)
    with pdf_status.publish(path):
        assert pdf_status.worker_status(path, running=True)["state"] == "unknown"


def test_api_reports_the_workers_own_settings_and_state(tmp_path, monkeypatch):
    from jav import store
    from jav.runtime import lock, pdf_status, worker

    path = tmp_path / "test.sqlite"
    monkeypatch.setattr(pdf_status, "REPORT_INTERVAL_S", 60)
    app = api.create_app(store_path=path)
    with TestClient(app, base_url="http://127.0.0.1:8930") as client, store.use_store(path):
        with lock.single_instance(worker.lock_path()):
            with monkeypatch.context() as mp:
                mp.setattr(isolated_pdf, "protection_status", _worker_report)
                publisher = pdf_status.publish(path)
                publisher.__enter__()
            try:
                report = client.get("/api/health").json()["pdf_protection"]
                assert report["service"]["state"] == "unknown"
                assert report["service"]["configured"]["memory_mb"] == 1024
                assert report["worker"]["state"] == "protected"
                assert report["worker"]["configured"]["memory_mb"] == 512
                assert client.get("/api/worker").json()["pdf_protection"]["state"] == "protected"
            finally:
                publisher.__exit__(None, None, None)
        assert client.get("/api/health").json()["pdf_protection"]["worker"]["state"] == "stale"


@pytest.mark.parametrize("succeeds", [True, False])
def test_posix_helper_acknowledges_only_an_applied_memory_limit(monkeypatch, succeeds):
    from types import SimpleNamespace

    def set_limit(*args):
        if not succeeds:
            raise OSError("synthetic resource limit failure")

    class Pipe:
        sent = []

        def send(self, data):
            self.sent.append(data)

        def recv(self):
            raise EOFError

    monkeypatch.setitem(sys.modules, "resource", SimpleNamespace(RLIMIT_AS=9, setrlimit=set_limit))
    monkeypatch.setattr(isolated_pdf, "sys", SimpleNamespace(platform="linux"))
    pipe = Pipe()
    isolated_pdf._serve(pipe, 512 * 1_048_576)
    assert pipe.sent[0][0] == "ready"
    assert pipe.sent[0][1]["memory_limited"] is succeeds


def test_strict_limit_failure_is_final_in_the_actual_worker(tmp_path, monkeypatch):
    from jav import store, work
    from jav.runtime import worker
    from tests.pdfgen import INVOICE_LINES, write_text_pdf

    folder = tmp_path / "input"
    folder.mkdir()
    write_text_pdf(folder / "synthetic.pdf", INVOICE_LINES)
    settings = replace(isolated_pdf.settings(), memory_mb=0, require_memory_limit=True)
    monkeypatch.setattr(isolated_pdf, "settings", lambda: settings)
    with store.use_store(tmp_path / "test.sqlite"):
        package = work.create_from_folder(folder, name="Synthetic protection check")
        work.assign_recipe(package["id"], "invoice-extraction", params={"arm": "S", "doc_type": "invoice_hu"},
                           expected_revision=0, actor="test")
        ready = work.readiness(package["id"])
        run = work.start_run(package["id"], mode="shadow", expected_assignment_revision=1,
                             input_hash=ready["input_hash"], actor="test")
        result = worker.run_worker(once=True)
        assert result["results"] == {"dead": 1}
        item = work.get_run(run["run_id"])["items"][0]
        assert item["status"] == "failed"
        assert item["error"].startswith("PdfReaderLimit:")
        assert "memory limit is disabled" in item["error"]
