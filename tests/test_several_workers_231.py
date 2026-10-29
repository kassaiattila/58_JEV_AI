"""231 (stage E, E1; the owner's decisions of 2026-10-29: several workers, one by default).

A worker's claim records its process's holder: the recovery frees only a stopped process's claims, so a running
worker's item stays its own while another worker starts or looks for stopped claims. Each worker takes a numbered slot
of the configured ones (the first keeps the single worker's lock), and every slot taken means no other may start. Only
the first slot runs the scheduled ticks. A stop request made before a worker started is not meant for it. An empty
store; nothing runs and no AI is asked.
"""

from __future__ import annotations

import os
import time

import pytest

from jav.core import calls, cfg, lock, queue, store
from jav.runtime import worker

STOPPED = "1-0123456789abcdef"  # a holder no process keeps (its lock file is not held)


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "workers.sqlite"):
        yield tmp_path


def _two_slots(monkeypatch) -> None:
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: {**real(name), "workers": 2} if name == "service" else real(name))


def test_a_running_process_keeps_its_claim_and_a_stopped_one_s_goes_back(db) -> None:
    mine = queue.enqueue("run_item", run_id="r1", payload={}, dedup_key="a")
    theirs = queue.enqueue("run_item", run_id="r1", payload={}, dedup_key="b")
    assert queue.claim("w1", holder=calls.holder()).id == mine.id
    assert queue.claim("w2", holder=STOPPED).id == theirs.id
    assert queue.recover_orphans().requeued == 1
    assert queue.get(mine.id).status == "claimed"  # a running worker's item is not taken from it
    again = queue.get(theirs.id)
    assert again.status == "queued" and again.attempts == 1
    calls.release_holder()  # the process stops
    assert queue.recover_orphans().requeued == 1 and queue.get(mine.id).status == "queued"


def test_each_worker_takes_a_free_slot_of_the_configured_ones(db, monkeypatch) -> None:
    assert worker.slots() == 1 and worker.status()["workers"] == 0
    _two_slots(monkeypatch)
    with worker._slot(None) as first, worker._slot(None) as second:
        assert (first, second) == (0, 1)
        assert worker.lock_path(0).name == "worker.lock" and worker.lock_path(1).name == "worker-2.lock"
        assert worker.running_slots() == [0, 1] and worker.running()
        st = worker.status()
        assert (st["running"], st["workers"], st["slots"]) == (True, 2, 2)
        with pytest.raises(lock.AlreadyRunning, match="every worker slot"):
            with worker._slot(None):
                pass
    assert not worker.running()


def test_an_error_inside_a_slot_is_not_taken_for_a_busy_slot(db) -> None:
    with pytest.raises(lock.AlreadyRunning, match="from the work"):
        with worker._slot(None):
            raise lock.AlreadyRunning("from the work")
    assert not worker.running()


def test_only_the_first_slot_runs_the_scheduled_ticks(db, monkeypatch) -> None:
    from jav.app import app_settings

    ran: list[int] = []
    monkeypatch.setattr(app_settings, "tick", lambda: ran.append(1))
    _two_slots(monkeypatch)
    worker.run_worker(once=True, slot=1, idle_sleep_s=0)
    assert ran == []
    worker.run_worker(once=True, slot=0, idle_sleep_s=0)
    assert ran == [1]


def test_a_stop_request_made_before_a_worker_started_is_not_for_it(db) -> None:
    worker.request_stop()
    old = time.time() - 60
    os.utime(worker.stop_path(), (old, old))
    assert not worker._stop_requested(time.time() - 30)
    worker.request_stop()
    assert worker._stop_requested(time.time() - 30)
