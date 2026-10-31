"""265 (code review X-10): every worker reports its PDF protection in its own file.

All the workers wrote one shared report, so with several workers the last writer's state stood for everyone, and a
stopped worker's report could hide a running one's. Each worker instance now reports beside its own lock file; the
status is the weakest live worker's, and an ended worker's report counts only while no worker is live. A stand-in for
the reader's protection; temporary folders only.
"""

from __future__ import annotations

import time

from jav.documents import isolated_pdf
from jav.runtime import pdf_status


def _report(state: str) -> dict:
    protected = state == "protected"
    return {"state": state, "reason": "memory_limit_applied" if protected else "not_isolated",
            "effective_memory_mb": 512 if protected else None, "helper_pid": 123 if protected else None,
            "process_pid": 456, "observed_at": time.time(),
            "configured": {"isolated": protected, "memory_mb": 512, "require_memory_limit": False}}


def test_the_weakest_live_worker_is_the_state(tmp_path, monkeypatch) -> None:
    path = tmp_path / "test.sqlite"
    monkeypatch.setattr(pdf_status, "REPORT_INTERVAL_S", 60)
    monkeypatch.setattr(isolated_pdf, "protection_status", lambda: _report("protected"))
    with pdf_status.publish(path):
        assert pdf_status.worker_status(path, running=True)["state"] == "protected"
        monkeypatch.setattr(isolated_pdf, "protection_status", lambda: _report("unprotected"))
        with pdf_status.publish(path):
            assert pdf_status.worker_status(path, running=True)["state"] == "unprotected"
        # the unprotected worker stopped: the running one's report stands, not the ended one's
        assert pdf_status.worker_status(path, running=True)["state"] == "protected"
    ended = pdf_status.worker_status(path, running=True)
    assert ended["state"] == "stale" and ended["reason"] == "worker_instance_ended"
