"""265 (code review CORE-05, CORE-12, X-05, X-06, X-14): the frequent lookups read an index, not the whole table.

An earlier answer to the same question (looked up under the write lock), a package's decision state, a run's to-dos
(filtered by a substring of the run identifier before), the runs of a to-do reason and a day's case history each read
their whole table as the store grew. Each now has its index, and the run's to-dos are a range on the identifier. The
query planner's answer is checked on an empty store; no AI, no data.
"""

from __future__ import annotations

import pytest

from jav.app import registrations
from jav.core import store


@pytest.fixture()
def db(tmp_path):
    registrations.load_all()
    with store.use_store(tmp_path / "ix.sqlite"), store.connect() as c:
        yield c


def _plan(c, sql: str, args: tuple) -> str:
    return " | ".join(r[-1] for r in c.execute("EXPLAIN QUERY PLAN " + sql, args).fetchall())


@pytest.mark.parametrize(("sql", "args", "index"), [
    ("SELECT 1 FROM invocations WHERE provider=? AND request_hash=? AND status='succeeded' LIMIT 1", ("openai", "h"),
     "ix_invocations_answer"),
    ("SELECT MAX(id) FROM decision_journal WHERE workpackage_id=? AND kind IN (?, ?)", ("wp-1", "a", "b"),
     "decision_journal_package"),
    ("SELECT COUNT(*) FROM review_reasons WHERE status=? AND run_id >= ? AND run_id < ?", ("open", "run-1:", "run-1;"),
     "ix_review_reasons_status_run"),
    ("SELECT DISTINCT run_id FROM review_reasons WHERE reason=?", ("email:suspicious",), "ix_review_reasons_reason"),
    ("SELECT id FROM process_history WHERE at >= ? AND at < ?", (0, 10), "ix_process_history_at"),
])
def test_the_lookup_reads_its_index(db, sql, args, index) -> None:
    assert index in _plan(db, sql, args)


def test_a_runs_to_dos_are_the_same_by_range(db) -> None:
    """The range finds what the substring did: the run's own flow identifiers, not another run's that starts alike."""
    from jav.app import work_runs

    for run_id in ("run-1:a", "run-1:b-detect", "run-10:a", "run-1"):
        db.execute("INSERT INTO review_queue(subject_kind, subject_id, run_id, reasons, status, created_at)"
                   " VALUES ('document', ?, ?, '[\"x\"]', 'open', '2026-11-01')", (run_id, run_id))
        review_id = db.execute("SELECT MAX(id) FROM review_queue").fetchone()[0]
        db.execute("INSERT INTO review_reasons(review_id, run_id, reason, producer, status, created_at)"
                   " VALUES (?,?,?,?,?,?)", (review_id, run_id, "x", "test", "open", "2026-11-01"))
    assert work_runs._own_reason_count(db, "run-1", "open") == 2
    assert store.close_run_reasons(db, "run-1") == 2
    assert work_runs._own_reason_count(db, "run-10", "open") == 1
