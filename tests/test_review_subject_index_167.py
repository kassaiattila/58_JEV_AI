"""167 (review R-10): the to-do lookups by subject use an index.

The approval re-checks every item's open reasons under its write lock, joining `review_queue` by subject. There was no
index on the subject, and without table statistics SQLite started the join from every open reason of the store, so a
run of 468 items took about 0.47 s with every writer waiting. Now `ix_review_subject` exists and the subject drives
the join (`store.SUBJECT_REASONS`).
"""

import inspect
import sqlite3

from jav import work_runs
from jav.core import store

OPEN_REASONS = ("SELECT r.id, r.run_id FROM " + store.SUBJECT_REASONS
                + " WHERE q.subject_kind=? AND q.subject_id=? AND r.status='open' ORDER BY r.id")
OPEN_REASONS_MANY = ("SELECT q.subject_id, r.id FROM " + store.SUBJECT_REASONS
                     + " WHERE q.subject_kind=? AND q.subject_id IN (?,?) AND r.status='open' ORDER BY r.id")
OPEN_ITEM = "SELECT id FROM review_queue WHERE subject_kind=? AND subject_id=? AND status='open'"


def _plan(c: sqlite3.Connection, sql: str) -> str:
    args = ("document",) + ("doc-1",) * (sql.count("?") - 1)
    return " | ".join(r["detail"] for r in c.execute("EXPLAIN QUERY PLAN " + sql, args))


def _fill(c: sqlite3.Connection, n: int = 300) -> None:
    for i in range(n):
        cur = c.execute("INSERT INTO review_queue(subject_kind, subject_id, run_id, reasons, status, created_at)"
                        " VALUES ('document', ?, 'r', '[]', 'open', '2026-10-17')", (f"doc-{i}",))
        c.execute("INSERT INTO review_reasons(review_id, reason, producer, run_id, status, created_at)"
                  " VALUES (?, 'm2:missing', 'm2', 'r:item', 'open', '2026-10-17')", (cur.lastrowid,))


def test_the_subject_index_exists_and_every_subject_lookup_uses_it(tmp_path):
    with store.use_store(tmp_path / "jav.sqlite"), store.connect() as c:
        _fill(c)
        names = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='review_queue'")}
        assert "ix_review_subject" in names
        for sql in (OPEN_REASONS, OPEN_REASONS_MANY, OPEN_ITEM):
            plan = _plan(c, sql)
            assert "ix_review_subject" in plan, plan
            assert "ix_review_reasons_status_run" not in plan and "SCAN" not in plan, plan


def test_the_lookups_still_answer_the_same(tmp_path):
    with store.use_store(tmp_path / "jav.sqlite"):
        with store.connect() as c:
            _fill(c, n=3)
        assert [r["run_id"] for r in store.review_open_reasons("document", "doc-1")] == ["r:item"]
        many = store.review_open_reasons_many([("document", "doc-0"), ("document", "doc-2"), ("document", "missing")])
        assert {k: [r["reason"] for r in v] for k, v in many.items()} == {
            ("document", "doc-0"): ["m2:missing"], ("document", "doc-2"): ["m2:missing"], ("document", "missing"): []}


def test_the_approval_rechecks_through_the_subject_first_join():
    source = " ".join(inspect.getsource(work_runs.approve_run).split())
    assert '"SELECT r.run_id FROM " + store.SUBJECT_REASONS' in source
    assert "JOIN review_queue" not in source


def test_a_store_created_before_the_index_gets_it_on_connect(tmp_path):
    path = tmp_path / "jav.sqlite"
    with store.use_store(path), store.connect() as c:
        c.execute("DROP INDEX ix_review_subject")
    store._initialized.pop(str(path), None)  # a new process: the structure check runs again
    with store.use_store(path), store.connect() as c:
        assert c.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='ix_review_subject'").fetchone()
