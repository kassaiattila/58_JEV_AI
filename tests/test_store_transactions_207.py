"""207 (plan G-process-core, R1k): a store block nested in another one on the session's connection is part of the
outer block's transaction.

Since 203 an operation runs its store blocks on one shared connection. A block nested in another (an operation that
reads the package while the run start holds the write lock) committed at its own end, and with it the outer block's
work: the write lock ended in the middle of the outer block, so another writer could change the package between the
check and the run row, and an error in the outer block could no longer undo what it wrote before. Before 203 the nested
block had a connection of its own, so this could not happen. Now a block entered inside an open transaction is a
savepoint: it neither commits nor ends the lock, and its failure undoes only its own part. A block entered outside a
transaction commits at its end, as a block of its own connection always did. Synthetic data only.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jav.app import work, work_readiness, work_recipes, work_runs
from jav.core import store
from jav.core import queue
from tests.pdfgen import INVOICE_LINES, write_text_pdf


def _writer_waits(db: Path) -> bool:
    """Another connection asks for the write lock without waiting: True when it would have to wait."""
    other = sqlite3.connect(str(db), timeout=0)
    try:
        other.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        assert "locked" in str(exc)
        return True
    finally:
        other.close()
    return False


def _rows(db: Path) -> list[int]:
    """The committed rows, as another connection sees them."""
    other = sqlite3.connect(str(db))
    try:
        return [r[0] for r in other.execute("SELECT x FROM t ORDER BY x")]
    finally:
        other.close()


@pytest.fixture()
def db(tmp_path: Path):
    path = tmp_path / "s.sqlite"
    with store.use_store(path):
        with store.connect() as c:
            c.execute("CREATE TABLE t (x INTEGER)")
        with store.session():
            yield path


def test_a_nested_block_keeps_the_outer_write_lock_and_work(db):
    with store.connect() as c:
        store.begin_immediate(c)
        c.execute("INSERT INTO t VALUES (1)")
        with store.connect() as inner:
            inner.execute("SELECT COUNT(*) FROM t").fetchone()
        assert c.in_transaction
        assert _writer_waits(db)
        assert _rows(db) == []  # nothing committed before the outer block ends
    assert not _writer_waits(db)
    assert _rows(db) == [1]


def test_a_nested_begin_does_not_commit_the_outer_work(db):
    with pytest.raises(RuntimeError):
        with store.connect() as c:
            store.begin_immediate(c)
            c.execute("INSERT INTO t VALUES (1)")
            with store.connect() as inner:
                store.begin_immediate(inner)
                inner.execute("INSERT INTO t VALUES (2)")
            raise RuntimeError("the outer block fails after the nested one")
    assert _rows(db) == []


def test_a_failed_nested_block_undoes_only_its_own_part(db):
    with store.connect() as c:
        store.begin_immediate(c)
        c.execute("INSERT INTO t VALUES (1)")
        with pytest.raises(RuntimeError):
            with store.connect() as inner:
                inner.execute("INSERT INTO t VALUES (2)")
                raise RuntimeError("the nested step fails")
        assert _writer_waits(db)  # the outer block still holds the lock
        c.execute("INSERT INTO t VALUES (3)")
    assert _rows(db) == [1, 3]


def test_a_nested_queue_write_belongs_to_the_outer_transaction(db):
    with pytest.raises(RuntimeError):
        with store.connect() as c:
            store.begin_immediate(c)
            c.execute("INSERT INTO t VALUES (1)")
            queue.enqueue("probe", run_id="r1", payload={}, dedup_key="r1:a")
            raise RuntimeError("the outer block fails after enqueuing")
    assert _rows(db) == []
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_a_block_entered_outside_a_transaction_commits_at_its_end(db):
    with store.connect() as c:
        c.execute("SELECT COUNT(*) FROM t").fetchone()  # the outer block only reads
        with store.connect() as inner:
            inner.execute("INSERT INTO t VALUES (1)")
        assert _rows(db) == [1]  # as with a connection of its own
        with store.connect() as later:
            later.execute("INSERT INTO t VALUES (2)")
    assert _rows(db) == [1, 2]


def test_blocks_one_after_another_still_commit_each(db):
    with store.connect() as c:
        c.execute("INSERT INTO t VALUES (1)")
    assert _rows(db) == [1]
    with pytest.raises(RuntimeError):
        with store.connect() as c:
            c.execute("INSERT INTO t VALUES (2)")
            raise RuntimeError("a later step fails")
    assert _rows(db) == [1]


def test_a_module_registered_inside_a_transaction_gets_its_tables_without_a_commit(db, monkeypatch):
    """174 inside a write transaction: the set-up commits, so there only the tables are made, as part of it."""
    monkeypatch.setattr(store, "_EXTRA_SCHEMAS", dict(store._EXTRA_SCHEMAS))
    with pytest.raises(RuntimeError):
        with store.connect() as c:
            store.begin_immediate(c)
            c.execute("INSERT INTO t VALUES (1)")
            store.register_schema("late_module_207", "CREATE TABLE IF NOT EXISTS late_table_207 (x INTEGER);")
            with store.connect() as inner:
                inner.execute("INSERT INTO late_table_207(x) VALUES (1)")
            assert _writer_waits(db)
            raise RuntimeError("the outer block fails")
    assert _rows(db) == []
    with store.connect() as c:  # the next block outside a transaction runs the full set-up
        assert c.execute("SELECT COUNT(*) FROM late_table_207").fetchone()[0] == 0


def test_every_registered_schema_runs_statement_by_statement(tmp_path):
    from jav.runtime import preload

    preload.preload()
    other = sqlite3.connect(str(tmp_path / "fresh.sqlite"))
    try:
        other.execute("BEGIN IMMEDIATE")
        for ddl in (store._SCHEMA, *store._EXTRA_SCHEMAS.values()):
            statements = list(store._schema_statements(ddl))
            rest = ddl[len("".join(statements)):]  # what follows the last statement: only blanks or comments
            assert all(not line.strip() or line.strip().startswith("--") for line in rest.splitlines())
            for statement in statements:
                other.execute(statement)
        assert other.in_transaction
        tables = {r[0] for r in other.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        other.close()
    assert {"runs", "jobs", "review_queue", "workpackages"} <= tables


def test_starting_a_run_keeps_the_package_locked_until_the_run_is_written(tmp_path, monkeypatch):
    """The opponent review's case (205, 3.1): the run start reads the package under the write lock; another writer must
    wait until the run row is written, so the run's input is the package the check saw."""
    folder = tmp_path / "in"
    folder.mkdir()
    for n in (1, 2):
        write_text_pdf(folder / f"doc_{n}.pdf", [line.replace("MINTA-2026-001", f"MINTA-2026-00{n}") for line in INVOICE_LINES])
    db = tmp_path / "w.sqlite"
    with store.use_store(db):
        wp = work.create_from_folder(folder, name="Synthetic package")
        work_recipes.assign_recipe(wp["id"], "processing", params={"arm": "S"}, expected_revision=0, actor="t")
        ready = work_readiness.readiness(wp["id"])
        waits: list[bool] = []
        real = work_readiness._input_snapshot

        def snapshot(*args, **kwargs):
            waits.append(_writer_waits(db))
            return real(*args, **kwargs)

        monkeypatch.setattr(work_readiness, "_input_snapshot", snapshot)
        run = work_runs.start_run(wp["id"], mode="apply", expected_assignment_revision=1, input_hash=ready["input_hash"],
                                  actor="t")
    assert waits[-1] is True  # the last snapshot is the one taken under the run start's lock, after reading the package
    assert not _writer_waits(db)
    with store.use_store(db):
        assert work_runs.get_run(run["run_id"])["input_hash"] == ready["input_hash"]
