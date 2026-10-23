"""159: the worker's PDF protection report survives a reader holding the file, and leaves no lock files behind."""

import logging
import os
import time

import pytest

from jav.documents import isolated_pdf
from jav.runtime import pdf_status
from jav.core import lock


def _worker_report():
    return {"state": "protected", "reason": "memory_limit_applied", "effective_memory_mb": 512,
            "helper_pid": 123, "process_pid": 456, "observed_at": time.time(),
            "configured": {"isolated": True, "memory_mb": 512, "require_memory_limit": False}}


@pytest.fixture(autouse=True)
def synthetic_protection(monkeypatch):
    monkeypatch.setattr(isolated_pdf, "protection_status", _worker_report)


def test_report_is_published_when_a_reader_briefly_holds_the_file(tmp_path, monkeypatch, caplog):
    # On Windows the service reading the report makes the replace fail with "access denied" for a moment.
    path = tmp_path / "test.sqlite"
    real_replace = os.replace
    failures = {"left": 2}

    def busy_then_free(src, dst):
        if failures["left"]:
            failures["left"] -= 1
            raise PermissionError(5, "Access is denied")
        real_replace(src, dst)

    monkeypatch.setattr(pdf_status, "REPLACE_RETRY_DELAY_S", 0)
    monkeypatch.setattr(os, "replace", busy_then_free)
    with caplog.at_level(logging.WARNING, logger="jav.runtime.pdf_status"), pdf_status.publish(path):
        assert pdf_status.worker_status(path, running=True)["state"] == "protected"
    assert failures["left"] == 0
    assert not [r for r in caplog.records if r.name == "jav.runtime.pdf_status"]


def test_a_report_that_stays_blocked_is_logged_and_does_not_stop_the_worker(tmp_path, monkeypatch, caplog):
    path = tmp_path / "test.sqlite"

    def always_busy(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(pdf_status, "REPLACE_RETRY_DELAY_S", 0)
    monkeypatch.setattr(os, "replace", always_busy)
    with caplog.at_level(logging.ERROR, logger="jav.runtime.pdf_status"), pdf_status.publish(path):
        assert pdf_status.worker_status(path, running=True)["state"] == "unknown"
    assert [r for r in caplog.records if "could not publish" in r.getMessage()]
    assert not list(tmp_path.glob("worker-pdf-status.*.tmp"))


def test_the_instance_lock_file_is_removed_when_the_worker_stops(tmp_path):
    path = tmp_path / "test.sqlite"
    with pdf_status.publish(path):
        assert len(list((tmp_path / "pdf-status").glob("*.lock"))) == 1
    assert not list((tmp_path / "pdf-status").glob("*.lock"))
    assert pdf_status.worker_status(path, running=True)["reason"] == "worker_instance_ended"


def test_lock_files_of_ended_instances_are_removed_but_a_held_one_is_kept(tmp_path):
    path = tmp_path / "test.sqlite"
    folder = tmp_path / "pdf-status"
    folder.mkdir()
    ended = [folder / f"{n:032x}.lock" for n in (1, 2, 3)]
    for p in ended:
        p.write_bytes(b"")
    held_path = folder / f"{9:032x}.lock"
    held = lock.hold(held_path)
    try:
        with pdf_status.publish(path):
            remaining = {p.name for p in folder.glob("*.lock")}
            assert held_path.name in remaining
            assert not remaining & {p.name for p in ended}
            assert len(remaining) == 2  # the held one and this worker's own
    finally:
        lock.release(held)
