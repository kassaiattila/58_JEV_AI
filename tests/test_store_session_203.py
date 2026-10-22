"""203 (speed-up by measurement): one connection for an operation, and never across threads.

The test suite opened about 74 000 store connections, each open and close costing a few milliseconds on Windows; most
came from a few larger operations (an item in the worker, a work package, a run's state, the reconciliation's snapshot)
that opened one per small query. Those operations now run in one shared connection (`store.session`). A SQLite
connection belongs to the thread that opened it, and some libraries copy the caller's context into their own threads,
so a session's connection is used only on its own thread; another thread opens its own.
"""

from __future__ import annotations

import contextvars
import sqlite3
import threading

import pytest

from jav import store
from jav.runtime import queue, worker
from tests.test_runtime_worker import _start, env  # noqa: F401 - the worker's fixture: a package of two invoices


@pytest.fixture()
def opened(monkeypatch):
    seen: list[str] = []
    real = sqlite3.connect

    def counting(*args, **kwargs):
        seen.append(str(args[0]) if args else "")
        return real(*args, **kwargs)

    monkeypatch.setattr(store.sqlite3, "connect", counting)
    return seen


def test_a_session_is_not_used_from_another_thread(tmp_path):
    with store.use_store(tmp_path / "s.sqlite"), store.session():
        with store.connect() as c:
            outer = c
        seen: dict[str, object] = {}

        def elsewhere():
            try:
                with store.connect() as c:
                    seen["same"] = c is outer
                    seen["one"] = c.execute("SELECT 1").fetchone()[0]
            except sqlite3.ProgrammingError as exc:  # the connection of another thread
                seen["error"] = str(exc)

        thread = threading.Thread(target=contextvars.copy_context().run, args=(elsewhere,))
        thread.start()
        thread.join()
    assert seen == {"same": False, "one": 1}


def test_a_session_opened_on_another_thread_keeps_its_own_connection(tmp_path):
    db = tmp_path / "s.sqlite"
    with store.use_store(db), store.session():
        with store.connect() as c:
            outer = c

        def elsewhere():
            with store.session():
                with store.connect() as a, store.connect() as b:
                    seen.update(shared=a is b, outer=a is outer)

        seen: dict[str, bool] = {}
        thread = threading.Thread(target=contextvars.copy_context().run, args=(elsewhere,))
        thread.start()
        thread.join()
    assert seen == {"shared": True, "outer": False}


def test_a_nested_session_on_the_same_thread_keeps_the_outer_connection(tmp_path, opened):
    with store.use_store(tmp_path / "s.sqlite"):
        with store.connect():
            pass
        opened.clear()
        with store.session():
            with store.session(), store.connect():
                pass
            with store.connect():
                pass
    assert len(opened) == 1


def test_an_operation_marked_for_one_connection_opens_one(tmp_path, opened):
    @store.one_connection
    def several(n: int) -> int:
        for _ in range(n):
            with store.connect() as c:
                c.execute("SELECT 1")
        return n

    with store.use_store(tmp_path / "s.sqlite"):
        with store.connect():
            pass
        opened.clear()
        assert several(5) == 5
        assert len(opened) == 1
        assert several.__name__ == "several"  # the operation keeps its name (logs, tracebacks)


def test_a_failed_operation_keeps_what_its_finished_steps_wrote(tmp_path):
    @store.one_connection
    def write_then_fail() -> None:
        with store.connect() as c:
            c.execute("CREATE TABLE IF NOT EXISTS t (x INTEGER)")
            c.execute("INSERT INTO t VALUES (1)")
        with store.connect() as c:
            c.execute("INSERT INTO t VALUES (2)")
            raise RuntimeError("a later step fails")

    with store.use_store(tmp_path / "s.sqlite"):
        with pytest.raises(RuntimeError):
            write_then_fail()
        with store.connect() as c:  # as with a connection per step: the first step stays, the failed one is undone
            assert [r[0] for r in c.execute("SELECT x FROM t")] == [1]


def test_a_session_in_read_only_mode_opens_nothing_itself(tmp_path, opened):
    missing = tmp_path / "nincs.sqlite"
    with store.use_store(missing), store.read_only(), store.session():
        assert opened == []  # a read-only connection is never shared; each look opens its own
        with pytest.raises(store.StoreMissing):
            with store.connect():
                pass
    assert not missing.exists()


def test_an_item_in_the_worker_runs_in_one_store_connection(env, opened):  # noqa: F811
    _start(env["wp"]["id"])
    worker.startup()
    job = queue.claim("w1")
    db = str(env["tmp"] / "w.sqlite")
    opened.clear()
    assert worker.process(job) == "done"
    assert opened.count(db) == 1, len(opened)
