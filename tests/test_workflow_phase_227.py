"""A workflow step's state lives in one place: its row in the process core (227, plan R3 R3d; DECISIONS 227).

Plain-language summary: before, a workflow step's state was kept twice, in the workflow's own table and in the
process core. The core's state alone could not take its place: it does not say what the step's start reached (a
start under way, a download queued, a package waiting for its approval or for a budget, nothing new), and the step
needs that to go on after a restart or after it went out of date. So that position moved into the step's row in the
core, as the step kind's own phase, which the core keeps through all of its own changes; the workflow's table keeps
only the step's own data (its source, budget, package, download, run and note). A store of before moves each step's
state into its core row and drops the old column in one write transaction, but only once every workflow has its case.
Two places that changed the workflow's table alone now tell the core too: a deleted package and a start left by a
stopped process fail the step in the core as well. Synthetic data, a temporary store, no paid calls.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from jav.app import work, work_runs, workflow_cases, workflows as wf
from jav.core import store
from jav.core import identity as actors
from jav.core.process import cases, engine, kinds, tasks
from jav.core.process.definition import ProcessDef, StepDef
from tests.test_workflows_146 import (  # noqa: F401 - the fixture is used by name
    MONTH, _approve_by_hand, _invoices, _party, _process_all, _statements, _steps, db,
)


def _monthly(db, **kw) -> str:  # noqa: F811
    return wf.create(template_id="monthly_reconciliation", party_id=_party(), period_start=MONTH[0], period_end=MONTH[1],
                     steps={"invoices": {"source": {"kind": "folder", "folder": str(_invoices(db / "inv"))}},
                            "statements": {"source": {"kind": "folder", "folder": str(_statements(db / "erste"))}},
                            "reconcile": {"source": {"kind": "none"}}}, actor="tester", **kw)["workflow"]["id"]


def _phases(wf_id: str) -> dict[str, str | None]:
    return {sid: s["phase"] for sid, s in cases.view(wf_id)["steps"].items()}


def _shown(wf_id: str) -> dict[str, str]:
    return {s["id"]: s["state"] for s in wf.view(wf_id)["steps"]}


def _core(wf_id: str) -> dict[str, str]:
    return {sid: s["state"] if s["waiting_for"] is None else f"{s['state']}:{s['waiting_for']}"
            for sid, s in cases.view(wf_id)["steps"].items()}


def _columns(table: str) -> set[str]:
    with store.connect() as c:
        return {r[1] for r in c.execute(f"PRAGMA table_info({table})")}


def _next_start() -> None:
    """The store's set-up as a process starting next runs it (the schema and its change helpers)."""
    store._initialized.clear()
    with store.connect():
        pass


# --- one place ------------------------------------------------------------------------------------------------------------


def test_the_workflows_table_keeps_no_step_state_and_the_view_shows_the_phase_of_the_core_row(db):  # noqa: F811
    assert "state" not in _columns("workflow_steps") and "phase" in _columns("process_steps")
    wf_id = _monthly(db)
    assert _phases(wf_id) == _shown(wf_id) == {"invoices": "needs_budget", "statements": "started", "reconcile": "waiting"}
    assert _core(wf_id) == {"invoices": "running:budget", "statements": "running:approval", "reconcile": "waiting"}
    _process_all()
    work_runs.approve_run(_steps(wf.view(wf_id))["statements"]["run_id"], actor="tester")
    wf.tick(now=1e9)
    engine.turn_due()  # 229: the core's round turns the due case
    assert _core(wf_id)["statements"] == "done" and _phases(wf_id)["statements"] == "started"
    estimate = _steps(wf.view(wf_id))["invoices"]["note"]["estimate"]
    wf.start_step(wf_id, "invoices", actor="tester", budget={p: str(Decimal(v) + 1) for p, v in estimate.items()})
    assert _phases(wf_id) == _shown(wf_id) == {"invoices": "started", "statements": "started", "reconcile": "waiting"}
    _approve_by_hand(_steps(wf.view(wf_id))["invoices"]["run_id"])
    wf.tick(now=2e9)
    engine.turn_due()  # 229: the core's round turns the due case
    assert _core(wf_id) == {"invoices": "done", "statements": "done", "reconcile": "running:approval"}
    assert _phases(wf_id) == _shown(wf_id) == {"invoices": "started", "statements": "started", "reconcile": "started"}


def _linked(db, **kw) -> str:  # noqa: F811
    """A workflow whose invoices step was brought with a package (a folder's, without runs) and whose statements step
    has an empty folder."""
    empty = db / "empty"
    empty.mkdir(exist_ok=True)
    linked = work.create_from_folder(_invoices(db / "inv"), name="June invoices", owner="tester")["id"]
    return wf.create(template_id="monthly_reconciliation", party_id=_party(), period_start=MONTH[0], period_end=MONTH[1],
                     steps={"invoices": {"source": {"kind": "package", "workpackage_id": linked}},
                            "statements": {"source": {"kind": "folder", "folder": str(empty)}},
                            "reconcile": {"source": {"kind": "none"}}}, actor="tester", **kw)["workflow"]["id"]


def test_a_linked_step_and_a_step_that_found_nothing_new_keep_their_phase_in_the_core(db):  # noqa: F811
    wf_id = _linked(db)
    assert _phases(wf_id) == _shown(wf_id) == {"invoices": "linked", "statements": "nothing_new", "reconcile": "waiting"}
    assert _core(wf_id)["invoices"] == "running:approval" and _core(wf_id)["statements"] == "done"


def test_a_claim_is_made_on_the_phase_of_the_core_row(db):  # noqa: F811
    wf_id = _monthly(db, advance_now=False)
    assert not wf._set_logged(wf_id, "invoices", "failed", "t", {"note": "x"}, expect=("starting",), phase="failed")
    assert _phases(wf_id)["invoices"] == "waiting"
    assert wf._set_logged(wf_id, "invoices", "failed", "t", {"note": "x"}, expect=("waiting",), phase="failed", note="x")
    assert _phases(wf_id)["invoices"] == "failed" and _shown(wf_id)["invoices"] == "failed"


# --- the two places that told only the workflow's table -------------------------------------------------------------------


def test_a_deleted_package_fails_its_step_in_the_core_too_and_withdraws_its_budget_task(db):  # noqa: F811
    wf_id = _monthly(db)
    budget = workflow_cases.budget_task(wf_id, "invoices")
    assert tasks.get(budget).status == tasks.OPEN
    wf.update(wf_id, actor="tester", archived=True)
    work.delete_workpackage(_steps(wf.view(wf_id))["invoices"]["package"]["id"], actor="someone")
    assert _core(wf_id)["invoices"] == "failed" and _phases(wf_id)["invoices"] == "failed"
    assert cases.view(wf_id)["steps"]["invoices"]["note"] == wf.PACKAGE_DELETED
    assert tasks.get(budget).status == tasks.WITHDRAWN  # before, the deleted package's task stayed open for a person
    wf.update(wf_id, actor="tester", archived=False)
    restarted = _steps(wf.start_step(wf_id, "invoices", actor="tester"))["invoices"]
    assert restarted["state"] == "needs_budget" and _core(wf_id)["invoices"] == "running:budget"


def test_a_done_steps_deleted_package_reopens_the_step_and_fails_it_in_the_core(db):  # noqa: F811
    wf_id = _linked(db, advance_now=False)
    with cases.transaction() as c:  # done without a run of its package, as an email routing is once each attachment is
        who = workflow_cases.maker("tester")  # decided (a package with runs is never deleted)
        cases.begin(c, wf_id, "invoices", who)
        cases.complete(c, wf_id, "invoices", who, {"state": "linked"})
    wf.update(wf_id, actor="tester", archived=True)
    work.delete_workpackage(_steps(wf.view(wf_id))["invoices"]["package"]["id"], actor="someone")
    assert _core(wf_id)["invoices"] == "failed" and _phases(wf_id)["invoices"] == "failed"
    kinds_of = [h["kind"] for h in cases.view(wf_id)["history"] if h["step_id"] == "invoices"]
    assert kinds_of[-2:] == ["reopened", "step_failed"]
    assert _shown(wf_id)["invoices"] == "failed" and cases.get(wf_id)["status"] == "open"


def test_a_start_left_long_ago_is_failed_in_the_core_too(db):  # noqa: F811
    wf_id = _monthly(db, advance_now=False)
    with store.connect() as c:  # a process claimed the start two hours ago and never came back
        c.execute("UPDATE process_steps SET phase='starting' WHERE case_id=? AND step_id='invoices'", (wf_id,))
        c.execute("UPDATE workflow_steps SET updated_at='2026-01-01T00:00:00+00:00' WHERE workflow_id=? AND step='invoices'",
                  (wf_id,))
    assert wf.release_stale_starts() == 1
    assert _core(wf_id)["invoices"] == "failed" and _phases(wf_id)["invoices"] == "failed"
    assert _shown(wf_id)["invoices"] == "failed" and wf.release_stale_starts() == 0


# --- a store of before ------------------------------------------------------------------------------------------------------


def _as_before(states: dict[str, dict[str, str]], *, without_case: tuple[str, ...] = (), broken: str | None = None) -> None:
    """The workflows as the code before 227 left them: their steps' states in the workflow's table, none in the core;
    those `without_case` made before 214 (no case), `broken` with a saved template the core cannot read. One
    connection: a schema change makes the next one run the change helpers at once."""
    with store.connect() as c:
        c.execute("ALTER TABLE workflow_steps ADD COLUMN state TEXT NOT NULL DEFAULT 'waiting'")
        for wf_id, steps in states.items():
            for step, state in steps.items():
                c.execute("UPDATE workflow_steps SET state=? WHERE workflow_id=? AND step=?", (state, wf_id, step))
            c.execute("UPDATE process_steps SET phase=NULL WHERE case_id=?", (wf_id,))
        for wf_id in without_case:
            for table in ("process_cases", "process_steps", "process_history", "process_timers"):
                c.execute(f"DELETE FROM {table} WHERE case_id=?", (wf_id,))
        if broken is not None:
            c.execute("UPDATE workflows SET definition='{not json' WHERE id=?", (broken,))


def test_a_store_of_before_moves_each_steps_state_into_its_core_row_and_drops_the_column(db):  # noqa: F811
    first, second = _monthly(db), _monthly(db, advance_now=False)
    _as_before({first: {"invoices": "needs_budget", "statements": "started", "reconcile": "waiting"},
                second: {"invoices": "pulling", "statements": "nothing_new", "reconcile": "failed"}},
               without_case=(second,))
    _next_start()
    assert "state" not in _columns("workflow_steps")
    assert _phases(first) == {"invoices": "needs_budget", "statements": "started", "reconcile": "waiting"}
    assert _phases(second) == {"invoices": "pulling", "statements": "nothing_new", "reconcile": "failed"}
    assert _core(second) == {"invoices": "running:fetch", "statements": "done", "reconcile": "failed"}
    rows = cases.view(first)
    _next_start()  # moved once: the next start changes nothing
    assert cases.view(first) == rows


def test_the_column_stays_while_a_workflow_has_no_case_so_no_step_state_is_lost(db):  # noqa: F811
    good, broken = _monthly(db, advance_now=False), _monthly(db, advance_now=False)
    _as_before({good: {"invoices": "needs_budget"}, broken: {"invoices": "pulling"}}, without_case=(broken,),
               broken=broken)  # its workflow cannot be adopted
    _next_start()
    assert "state" in _columns("workflow_steps") and _phases(good)["invoices"] == "needs_budget"
    with store.connect() as c:
        assert c.execute("SELECT state FROM workflow_steps WHERE workflow_id=? AND step='invoices'",
                         (broken,)).fetchone()[0] == "pulling"
        c.execute("UPDATE workflows SET definition=? WHERE id=?",
                  (json.dumps(wf.template("monthly_reconciliation")), broken))
    _next_start()  # the template readable again: adopted, moved, and only then the column dropped
    assert "state" not in _columns("workflow_steps") and _phases(broken)["invoices"] == "pulling"


# --- the core's own rule ----------------------------------------------------------------------------------------------------

ME = actors.person("Tester")
DEF = ProcessDef(id="phase_227", version="1", title="Phase", steps=(
    StepDef(id="a", kind="phase_227_step"), StepDef(id="b", kind="phase_227_step", after=("a",))))
kinds.register(kinds.StepKind("phase_227_step", __name__, lambda ctx: kinds.DONE))


@pytest.fixture
def core(tmp_path):
    with store.use_store(tmp_path / "core.sqlite"):
        cases.start("c1", DEF, {}, ME)
        yield "c1"


def test_the_core_keeps_a_steps_phase_through_its_own_changes_and_never_reads_it(core):
    with cases.transaction() as c:
        assert cases.set_phase(c, core, "a", "one")
        assert not cases.set_phase(c, core, "a", "two", expect=("other",))  # a claim another process got first
        cases.begin(c, core, "a", ME)
        cases.complete(c, core, "a", ME)
        cases.begin(c, core, "b", ME)
        assert cases.set_phase(c, core, "b", "first")
        cases.fail(c, core, "b", ME, "it broke")
        cases.retry_in(c, core, "b", ME)
        assert cases.step_row(c, core, "b")["phase"] == "first"  # failed and retried: kept
        cases.begin(c, core, "b", ME)
        assert cases.reopen_in(c, core, "a", ME, reason="again") == ["b"]
        assert cases.step_row(c, core, "a")["phase"] == "one" and cases.step_row(c, core, "b")["phase"] == "first"
    assert cases.view(core)["steps"]["b"] == {"state": "stale", "waiting_for": None, "result_version": 0, "result": None,
                                             "note": None, "phase": "first"}
