"""160 (review R-3, R-4): only a queued or running run can be stopped, and a person's stop always ends as stopped.

R-3: a finished, even an approved, run could be stopped: "stopped and approved", or a finished live run with to-dos
stopped for good (it can finish between two clicks). A finished run is superseded instead; stopping it is refused.
R-4: when a person stopped a run while an item was running and an earlier item had failed, the run ended "failed",
not "stopped": it stayed the package's current run, hid an earlier run's to-dos, and a workflow step did not move on.
Synthetic PDFs, a fake JEV client, no paid calls."""

import pytest

from jav import work, work_runs
from jav.runtime import worker
from jav.core import queue
from tests.test_cancel_status_082 import env  # noqa: F401 - the fixture is used by name


def test_a_finished_run_cannot_be_stopped(env):  # noqa: F811
    run_id = env["run_id"]
    while (job := queue.claim("w1")) is not None:
        worker.process(job)
    finished = work_runs.get_run(run_id)["status"]
    assert finished in ("done", "needs_review")
    with pytest.raises(work.RevisionConflict, match="supersede"):
        work_runs.cancel_run(run_id, actor="someone")
    assert work_runs.get_run(run_id)["status"] == finished


def test_a_stopped_run_is_stopped_even_when_an_earlier_item_failed(env):  # noqa: F811
    run_id = env["run_id"]
    first = queue.claim("w1")
    assert queue.fail(first.id, "a broken document", max_attempts=1, backoff_s=0) == "dead"
    running = queue.claim("w1")
    work_runs.cancel_run(run_id, actor="someone")
    assert worker.process(running) == "cancelled"
    assert work_runs.get_run(run_id)["status"] == "cancelled"
