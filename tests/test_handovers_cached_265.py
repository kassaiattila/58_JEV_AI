"""265 (code review APPW-06): the handovers to check are built again only when a case or a handover changed.

The list of failed or uncertain handovers was built anew every 30 seconds, several queries per open case. It now has a
fingerprint: the case list's marks and the handovers' own (their rows change in place: attempts, status, time), so the
shared list cache keeps it until one of them changes. Invented rows; no AI.
"""

from __future__ import annotations

from jav.app import case_lists, registrations
from jav.core import store


def test_the_mark_follows_a_handovers_change(tmp_path) -> None:
    registrations.load_all()
    with store.use_store(tmp_path / "h.sqlite"):
        before = case_lists._handover_fingerprint({})
        assert case_lists._handover_fingerprint({}) == before
        with store.connect() as c:
            c.execute("INSERT INTO process_outbox(handover_id, case_id, step_id, target, payload, status, attempts,"
                      " created_at, updated_at) VALUES ('h1', 'wp-1', 'send', 'folder', '{}', 'failed', 1, 't0', 't0')")
        recorded = case_lists._handover_fingerprint({})
        assert recorded != before
        with store.connect() as c:
            c.execute("UPDATE process_outbox SET attempts=2, updated_at='t1' WHERE handover_id='h1'")
        assert case_lists._handover_fingerprint({}) != recorded
