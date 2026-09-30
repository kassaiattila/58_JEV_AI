"""Tartós munkasor (040 K1; a V4 jobq.py mintája SQLite-ra): dedup, foglalás, hiba, visszaengedés, leállítás, árva foglalás."""

from pathlib import Path

import pytest

from jav import store
from jav.runtime import queue


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "q.sqlite"):
        yield tmp_path


def test_enqueue_is_idempotent_on_dedup_key(isolated):
    a = queue.enqueue("run_item", run_id="r1", payload={"item": "d1"}, dedup_key="r1:d1")
    b = queue.enqueue("run_item", run_id="r1", payload={"item": "MÁS"}, dedup_key="r1:d1")
    assert a.id == b.id and not a.deduped and b.deduped
    assert b.payload == {"item": "d1"}  # az első bizonylat marad, nem cserélődik ki


def test_claim_takes_oldest_available_once(isolated):
    first = queue.enqueue("run_item", run_id="r1", payload={"n": 1}, dedup_key="a")
    queue.enqueue("run_item", run_id="r1", payload={"n": 2}, dedup_key="b")
    job = queue.claim("w1")
    assert job.id == first.id and job.status == "claimed" and job.claimed_by == "w1"
    assert queue.claim("w1").payload == {"n": 2}
    assert queue.claim("w1") is None


def test_complete_and_terminal_is_sticky(isolated):
    queue.enqueue("run_item", run_id="r1", payload={}, dedup_key="a")
    job = queue.claim("w")
    assert queue.complete(job.id) == "done"
    assert queue.fail(job.id, "late", max_attempts=3, backoff_s=0) == "done"  # kész feladat nem hibásodik utólag


def test_fail_retries_then_dead(isolated):
    queue.enqueue("run_item", run_id="r1", payload={}, dedup_key="a")
    job = queue.claim("w")
    assert queue.fail(job.id, "boom", max_attempts=2, backoff_s=0) == "queued"
    job = queue.claim("w")
    assert job.attempts == 1
    assert queue.fail(job.id, "boom again", max_attempts=2, backoff_s=0) == "dead"
    assert queue.get(job.id).error == "boom again" and queue.claim("w") is None


def test_backoff_delays_next_claim(isolated):
    queue.enqueue("run_item", run_id="r1", payload={}, dedup_key="a")
    job = queue.claim("w")
    queue.fail(job.id, "x", max_attempts=5, backoff_s=3600)
    assert queue.claim("w") is None


def test_release_does_not_burn_attempt(isolated):
    queue.enqueue("run_item", run_id="r1", payload={}, dedup_key="a")
    job = queue.claim("w")
    assert queue.release(job.id, delay_s=0) == "queued"
    again = queue.claim("w")
    assert again.id == job.id and again.attempts == 0


def test_cancel_queued_and_running(isolated):
    queued = queue.enqueue("run_item", run_id="r1", payload={}, dedup_key="a")
    running = queue.enqueue("run_item", run_id="r1", payload={}, dedup_key="b")
    assert queue.cancel(queued.id) == "cancelled"
    claimed = queue.claim("w")
    assert claimed.id == running.id
    assert queue.cancel(claimed.id) == "cancel_requested"
    with pytest.raises(queue.JobCancelled):
        queue.check_cancellation(claimed.id)
    assert queue.finish_cancelled(claimed.id) == "cancelled"


def test_startup_sweep_requeues_orphan_claims_with_attempt(isolated):
    queue.enqueue("run_item", run_id="r1", payload={}, dedup_key="a")
    job = queue.claim("dead-worker")
    assert queue.recover_orphans().requeued == 1
    again = queue.claim("w2")
    assert again.id == job.id and again.attempts == 1


def test_pause_blocks_claims(isolated):
    queue.enqueue("run_item", run_id="r1", payload={}, dedup_key="a")
    queue.set_paused(True)
    assert queue.claim("w") is None
    queue.set_paused(False)
    assert queue.claim("w") is not None


def test_counts_by_status(isolated):
    queue.enqueue("run_item", run_id="r1", payload={}, dedup_key="a")
    queue.enqueue("run_item", run_id="r1", payload={}, dedup_key="b")
    queue.complete(queue.claim("w").id)
    assert queue.counts(run_id="r1") == {"done": 1, "queued": 1}
