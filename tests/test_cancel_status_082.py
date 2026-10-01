"""Stopping a run (082): the run's status after a stop, without a manual refresh.

Seen in a real stop: with an item running, the stop cancelled the queued jobs one by one. The worker noticed the request
on the running item at once, finished it and refreshed the run while queued jobs were still left, so the run stayed
"running" after every job had ended; in the same window the worker could also claim the next queued item. And a running
item that failed after the stop went back to the queue, where a job with a stop request is never claimed again. Synthetic
PDFs, a fake JEV client, no paid calls.
"""

from pathlib import Path

import pytest

from jav import store, work
from jav.adapters import jev as jev_mod
from jav.runtime import queue, worker
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_runtime_worker import FakeClient


@pytest.fixture()
def env(tmp_path: Path):
    adapter = jev_mod.JevAdapter(client=FakeClient(), cache_dir=tmp_path / "cache", model="jev-1.13.0")
    folder = tmp_path / "bejovo"
    folder.mkdir()
    for n in (1, 2, 3):
        write_text_pdf(folder / f"szamla_{n}.pdf", [line.replace("MINTA-2026-001", f"MINTA-2026-00{n}") for line in INVOICE_LINES])
    with store.use_store(tmp_path / "w.sqlite"), jev_mod.use_adapter(adapter):
        wp = work.create_from_folder(folder, name="Synthetic invoices")
        work.assign_recipe(wp["id"], "invoice-extraction", params={"arm": "S", "doc_type": "invoice_hu"}, expected_revision=0, actor="t")
        ready = work.readiness(wp["id"])
        run_id = work.start_run(wp["id"], mode="shadow", expected_assignment_revision=1, input_hash=ready["input_hash"], actor="t")["run_id"]
        yield {"run_id": run_id}


def test_a_stop_cancels_the_queued_items_and_asks_the_running_one_in_one_step(env):
    run_id = env["run_id"]
    running = queue.claim("w1")
    assert work.cancel_run(run_id, actor="teszt.elek") == {"cancelled": 2, "cancel_requested": 1}
    assert queue.counts(run_id=run_id) == {"cancelled": 2, "claimed": 1}
    assert queue.claim("w1") is None  # nothing of the run is left to start
    assert work.get_run(run_id)["status"] == "running"  # the running item stops at its next step
    assert worker.process(running) == "cancelled"
    assert work.get_run(run_id)["status"] == "cancelled"


def test_the_run_ends_cancelled_when_the_worker_reacts_before_the_stop_returns(env, monkeypatch):
    run_id = env["run_id"]
    running = queue.claim("w1")
    stop = queue.cancel_run_jobs

    def worker_reacts_at_once(rid: str) -> dict[str, int]:
        out = stop(rid)
        worker.process(running)  # the worker notices the request at its next step and refreshes the run itself
        return out

    monkeypatch.setattr(queue, "cancel_run_jobs", worker_reacts_at_once)
    work.cancel_run(run_id)
    run = work.get_run(run_id)
    assert run["status"] == "cancelled" and run["finished_at"]  # no manual refresh needed
    assert queue.counts(run_id=run_id) == {"cancelled": 3}


def test_a_running_item_that_fails_after_the_stop_is_cancelled_not_requeued(env):
    run_id = env["run_id"]
    running = queue.claim("w1")

    def stop_then_fail(action_name: str) -> None:
        if action_name == "load_pdf":
            work.cancel_run(run_id)
            raise RuntimeError("an error in the step after the stop")

    assert worker.process(running, after_step=stop_then_fail) == "cancelled"
    assert queue.counts(run_id=run_id) == {"cancelled": 3}
    run = work.get_run(run_id)
    assert run["status"] == "cancelled"
    assert next(i for i in run["items"] if i["item_id"] == running.payload["item_id"])["status"] == "failed"  # what happened


def test_a_job_released_after_the_stop_is_cancelled(env):
    running = queue.claim("w1")
    work.cancel_run(env["run_id"])
    assert queue.release(running.id, delay_s=0) == "cancelled"
    assert queue.fail(running.id, "late", max_attempts=2, backoff_s=0) == "cancelled"  # a terminal job stays as it is


def test_a_second_stop_while_the_item_is_still_running_keeps_the_run_running(env):
    run_id = env["run_id"]
    queue.claim("w1")
    work.cancel_run(run_id)
    assert work.cancel_run(run_id) == {"cancel_requested": 1}
    assert work.get_run(run_id)["status"] == "running"
