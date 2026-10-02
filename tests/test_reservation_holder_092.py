"""092: a worker start takes over only the reservations of processes that have stopped (S-audit-1002 remainder).

Before this, the start-up recovery marked every open reservation uncertain, also the one a command-line measurement
was still waiting on; in that window the call could be settled by hand and its budget spent twice. Now every process
that reserves holds an operating-system lock for its lifetime, the reservation names it, and the recovery leaves the
reservations of a live holder alone. Stand-in calls only; no paid call.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

import pytest

from jav import store
from jav.runtime import calls

ROOT = Path(__file__).resolve().parents[1]


def _reserve(run_id: str = "r1", step_id: str = "s1") -> None:
    calls._reserve(run_id=run_id, step_id=step_id, provider="openai", model="m", max_cost_usd=Decimal("0.2"),
                   budget_scope=None, request_hash=None)


@pytest.fixture()
def db(tmp_path: Path):
    path = tmp_path / "jav.sqlite"
    with store.use_store(path):
        yield path
        calls.release_holder()


def test_a_live_process_reservation_survives_a_worker_start(db):
    _reserve()
    assert calls.recover_uncertain() == 0
    assert calls.journal("r1")[0]["status"] == "reserved"
    with pytest.raises(calls.NotUncertain, match="still in progress"):
        calls.resolve_uncertain(calls.journal("r1")[0]["id"], cost_usd=Decimal("0"), note="too early")


def test_a_measurement_waiting_on_its_answer_keeps_its_reservation(db):
    """The backlog's scenario: a worker starts while a command-line measurement waits for its answer."""
    calls.set_budget("measure", "openai", Decimal("0.3"))

    def answered_after_a_worker_start():
        assert calls.recover_uncertain() == 0  # the worker starts meanwhile and leaves this call alone
        row = calls.journal("r1")[0]
        with pytest.raises(calls.NotUncertain, match="still in progress"):
            calls.resolve_uncertain(row["id"], cost_usd=Decimal("0"), note="settled too early")
        with pytest.raises(calls.BudgetExceeded):  # the maximum is still committed: no second call fits
            calls.invoke(run_id="r2", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.2"),
                         budget_scope="measure", fn=lambda: calls.Outcome(response={}, cost_usd=Decimal("0.01")))
        return calls.Outcome(response={"ok": True}, cost_usd=Decimal("0.02"))

    calls.invoke(run_id="r1", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.2"),
                 budget_scope="measure", fn=answered_after_a_worker_start)
    row = calls.journal("r1")[0]
    assert (row["status"], row["cost_usd"]) == ("succeeded", "0.02")
    assert calls.budget_usage("measure")["committed_usd"] == Decimal("0.02")


def test_a_stopped_process_reservation_becomes_uncertain(db):
    _reserve()
    calls.release_holder()  # the process stops: the operating system releases its lock
    assert calls.recover_uncertain() == 1
    assert calls.journal("r1")[0]["status"] == "uncertain"


def test_a_reservation_without_a_holder_becomes_uncertain(db):
    """A reservation written before 092 names no holder: it is taken over, as before."""
    _reserve()
    with store.connect() as c:
        c.execute("UPDATE invocations SET holder=NULL")
    assert calls.recover_uncertain() == 1


def test_only_the_stopped_holders_reservations_are_taken_over(db):
    _reserve("old")
    calls.release_holder()
    _reserve("new")  # the same process again, now under a new holder
    assert calls.recover_uncertain() == 1
    assert calls.journal("old")[0]["status"] == "uncertain"
    assert calls.journal("new")[0]["status"] == "reserved"


def test_a_saved_answer_of_a_live_process_is_not_closed_by_the_recovery(db):
    """Between saving the answer and marking the call succeeded the process is still running; it closes the call
    itself, so the recovery must not close it in its place."""
    _reserve()
    inv_id = calls.journal("r1")[0]["id"]
    store.save_artifact(calls.RESPONSE_KIND, str(inv_id), {"response": {}, "cost_usd": "0.01"})
    calls.recover_uncertain()
    assert calls.journal("r1")[0]["status"] == "reserved"


def test_a_reservation_of_another_running_process_is_kept_until_it_stops(db):
    # The child dies without any clean-up when told to (os._exit), as a crashed process would. It is not killed from
    # here: on Windows a virtual environment's python.exe is a launcher, and killing it leaves the real process running.
    script = ("import os, sys\n"
              "from decimal import Decimal\n"
              "from pathlib import Path\n"
              "from jav import store\n"
              "from jav.runtime import calls\n"
              "with store.use_store(Path(sys.argv[1])):\n"
              "    calls._reserve(run_id='other', step_id='s1', provider='openai', model='m',\n"
              "                   max_cost_usd=Decimal('0.2'), budget_scope=None, request_hash=None)\n"
              "    print('reserved', flush=True)\n"
              "    sys.stdin.readline()\n"
              "    os._exit(1)\n")
    proc = subprocess.Popen([sys.executable, "-c", script, str(db)], cwd=ROOT, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, env={**os.environ, "PYTHONPATH": str(ROOT)})
    try:
        assert proc.stdout.readline().strip() == "reserved"
        assert calls.recover_uncertain() == 0
        assert calls.journal("other")[0]["status"] == "reserved"
    finally:
        proc.communicate("die\n", timeout=60)
    assert calls.recover_uncertain() == 1
    assert calls.journal("other")[0]["status"] == "uncertain"


def test_the_recovery_removes_the_lock_files_of_stopped_holders(db):
    _reserve("old")
    stale = calls.holder_path(calls.journal("old")[0]["holder"])
    calls.release_holder()
    stale.touch()  # a stopped process leaves its file behind
    os.utime(stale, (time.time() - 3600, time.time() - 3600))
    _reserve("new")
    live = calls.holder_path(calls.journal("new")[0]["holder"])
    calls.recover_uncertain()
    assert not stale.exists() and live.exists()
