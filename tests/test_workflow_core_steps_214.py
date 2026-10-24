"""The process core moves a workflow's steps on (214, plan G-process-core P1b-3).

Plain-language summary: a workflow's steps are run by its case on the process core: each step's way (started, waits
for a budget, for its package's approval or for its download, done) is in the case's history, and a waiting step has
its check timer. A person's start reaches the case with the person's name: a step started before the steps it waits
for are done is recorded as the order overridden. Two behaviours differ from before, on purpose: a start that a
stopped process left is failed at the next turn (before, after an hour), and a mailbox download a person started
finishes its step even while the automatic chain is off (before, it stood until the chain was switched on). A
workflow an older process made gets its case at its first turn. Synthetic data, a temporary store, stand-in downloads,
no paid calls.
"""

from __future__ import annotations

from decimal import Decimal

from jav.app import work, work_runs, workflow_cases, workflows as wf
from jav.core import store
from jav.core.process import cases, engine
from jav.domains.email import mailbox
from tests.test_workflows_146 import (  # noqa: F401 - the fixture is used by name
    MONTH, _approve_by_hand, _invoices, _party, _process_all, _statements, _steps, db,
)


def _core(wf_id: str) -> dict[str, str]:
    view = cases.view(wf_id)
    return {sid: s["state"] if s["waiting_for"] is None else f"{s['state']}:{s['waiting_for']}"
            for sid, s in view["steps"].items()}


def _history(wf_id: str) -> list[tuple]:
    return [(h["step_id"], h["kind"], h["actor"]) for h in cases.view(wf_id)["history"]]


def _monthly(db, **kw) -> str:  # noqa: F811
    return wf.create(template_id="monthly_reconciliation", party_id=_party(), period_start=MONTH[0], period_end=MONTH[1],
                     steps={"invoices": {"source": {"kind": "folder", "folder": str(_invoices(db / "inv"))}},
                            "statements": {"source": {"kind": "folder", "folder": str(_statements(db / "erste"))}},
                            "reconcile": {"source": {"kind": "none"}}}, actor="tester", **kw)["workflow"]["id"]


def _due_now(wf_id: str) -> None:
    """The case's check timers come due (the test does not wait for the clock)."""
    with store.connect() as c:
        c.execute("UPDATE process_timers SET due_at=0 WHERE case_id=? AND status='armed'", (wf_id,))


def test_the_case_runs_the_steps_and_its_history_shows_their_way(db):  # noqa: F811
    wf_id = _monthly(db)
    assert _core(wf_id) == {"invoices": "running:budget", "statements": "running:approval", "reconcile": "waiting"}
    assert {(t["step_id"], t["name"], t["status"]) for t in engine.state(wf_id)["timers"]} == {("statements", "check", "armed")}
    _process_all()
    statements = _steps(wf.view(wf_id))["statements"]
    work_runs.approve_run(statements["run_id"], actor="tester")
    wf.tick(now=1e9)
    assert _core(wf_id)["statements"] == "done"
    estimate = _steps(wf.view(wf_id))["invoices"]["note"]["estimate"]
    wf.start_step(wf_id, "invoices", actor="Example Person", budget={p: str(Decimal(v) + 1) for p, v in estimate.items()})
    assert _core(wf_id)["invoices"] == "running:approval"
    assert ("invoices", "wait_ended", "local:Example Person") in _history(wf_id)
    _approve_by_hand(_steps(wf.view(wf_id))["invoices"]["run_id"])
    wf.tick(now=2e9)
    assert _core(wf_id) == {"invoices": "done", "statements": "done", "reconcile": "running:approval"}
    kinds = [k for _, k, _ in _history(wf_id)]
    assert kinds.count("step_started") == 3 and kinds.count("step_done") == 2 and "timer_fired" not in kinds


def test_a_person_starting_a_step_before_its_order_is_recorded_as_the_order_overridden(db):  # noqa: F811
    wf_id = _monthly(db, auto=False)
    assert _core(wf_id) == {"invoices": "running:person", "statements": "running:person", "reconcile": "waiting"}
    view = wf.start_step(wf_id, "reconcile", actor="Example Person")
    rec = _steps(view)["reconcile"]
    assert rec["state"] == "failed" and "no account" in rec["note"]  # the party has no account with a statement yet
    overridden = next(h for h in cases.view(wf_id)["history"] if h["kind"] == "order_overridden")
    assert overridden["actor"] == "local:Example Person"
    assert overridden["detail"] == {"skipped": ["invoices", "statements"], "reason": "a person started the step"}
    assert _core(wf_id)["reconcile"] == "failed" and _core(wf_id)["invoices"] == "running:person"  # the chain is off


def test_a_start_a_stopped_process_left_fails_at_the_next_turn(db):  # noqa: F811
    wf_id = _monthly(db, advance_now=False)
    with store.connect() as c:  # a process claimed the case, began the start and stopped a moment ago
        store.begin_immediate(c)
        cases.begin(c, wf_id, "invoices", workflow_cases.maker("tester"))
        cases.set_phase(c, wf_id, "invoices", "starting")
        c.execute("INSERT INTO process_claims(case_id, holder, claimed_at) VALUES (?, 'stopped-holder', 'x')", (wf_id,))
    view = wf.advance(wf_id, actor="tester (auto)")
    assert _steps(view)["invoices"]["state"] == "failed" and _steps(view)["invoices"]["note"] == wf.INTERRUPTED
    assert _core(wf_id)["invoices"] == "failed" and wf.release_stale_starts() == 0
    assert _steps(wf.start_step(wf_id, "invoices", actor="tester"))["invoices"]["state"] == "needs_budget"


def test_a_download_a_person_started_finishes_its_step_while_the_chain_is_off(db, monkeypatch):  # noqa: F811
    pulls = {"p1": {"id": "p1", "status": "running", "result": None}}
    monkeypatch.setattr(mailbox, "request_pull", lambda req, **kw: pulls["p1"] | {"request": req.model_dump(mode="json")})
    monkeypatch.setattr(mailbox, "pull", lambda pid: pulls[pid])
    wf_id = wf.create(template_id="mailbox_reconciliation", party_id=_party(), period_start=MONTH[0], period_end=MONTH[1],
                      steps={"emails": {"source": {"kind": "mailbox", "request": {"accounts": ["someone@example.com"]}},
                                        "budget": {"jev": "9", "openai": "9", "azure_di": "9"}},
                             "statements": {"source": {"kind": "folder", "folder": str(db)}},
                             "reconcile": {"source": {"kind": "none"}}}, actor="tester", auto=False)["workflow"]["id"]
    assert _steps(wf.start_step(wf_id, "emails", actor="Example Person"))["emails"]["state"] == "pulling"
    assert _core(wf_id)["emails"] == "running:fetch"
    package = work.create_from_files(sorted(_invoices(db / "mail").iterdir()), name="Mail", owner="tester")
    pulls["p1"] = {"id": "p1", "status": "ok", "result": {"workpackage": package["id"]}}
    assert wf.tick(now=1e9) == 0  # no automatic workflow; the download's check is not due yet
    assert _steps(wf.view(wf_id))["emails"]["state"] == "pulling"
    _due_now(wf_id)
    wf.tick(now=2e9)
    emails = _steps(wf.view(wf_id))["emails"]
    assert emails["state"] == "started" and emails["package"]["id"] == package["id"]
    assert work_runs.get_run(emails["run_id"])["actor"] == "tester (auto)"
    assert _steps(wf.view(wf_id))["statements"]["state"] == "waiting"  # the chain is still off


def test_a_download_check_that_fails_is_tried_again_at_the_next_turn(db, monkeypatch):  # noqa: F811
    package = work.create_from_files(sorted(_invoices(db / "mail").iterdir()), name="Mail", owner="tester")
    answers = iter([OSError("the pull's log is locked"), {"id": "p1", "status": "ok", "result": {"workpackage": package["id"]}}])

    def pull(pid):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(mailbox, "request_pull", lambda req, **kw: {"id": "p1", "status": "running", "result": None})
    monkeypatch.setattr(mailbox, "pull", pull)
    wf_id = wf.create(template_id="mailbox_reconciliation", party_id=_party(), period_start=MONTH[0], period_end=MONTH[1],
                      steps={"emails": {"source": {"kind": "mailbox", "request": {"accounts": ["someone@example.com"]}},
                                        "budget": {"jev": "9", "openai": "9", "azure_di": "9"}},
                             "statements": {"source": {"kind": "folder", "folder": str(db)}},
                             "reconcile": {"source": {"kind": "none"}}}, actor="tester")["workflow"]["id"]
    assert _steps(wf.view(wf_id))["emails"]["state"] == "pulling" and _core(wf_id)["emails"] == "running:fetch"
    view = wf.advance(wf_id, actor="tester (auto)")
    assert _steps(view)["emails"]["state"] == "started" and _steps(view)["emails"]["package"]["id"] == package["id"]
    assert "step_failed" not in [k for _, k, _ in _history(wf_id)]


def test_an_approval_in_a_workflow_with_the_chain_off_is_seen_by_its_check_timer(db):  # noqa: F811
    wf_id = _monthly(db, auto=False)
    wf.start_step(wf_id, "invoices", actor="tester", budget={"jev": "9", "openai": "9", "azure_di": "9"})
    _approve_by_hand(_steps(wf.view(wf_id))["invoices"]["run_id"])
    assert _core(wf_id)["invoices"] == "running:approval"
    _due_now(wf_id)
    wf.tick(now=1e9)
    assert _core(wf_id)["invoices"] == "done" and _steps(wf.view(wf_id))["invoices"]["done"]


def test_a_workflow_an_older_process_made_gets_its_case_at_its_first_turn(db):  # noqa: F811
    wf_id = _monthly(db, advance_now=False)
    with store.connect() as c:  # an older process made it: no case (227: its steps' states in the column of before)
        c.execute("ALTER TABLE workflow_steps ADD COLUMN state TEXT NOT NULL DEFAULT 'waiting'")
        for table in ("process_cases", "process_steps", "process_history", "process_timers"):
            c.execute(f"DELETE FROM {table} WHERE case_id=?", (wf_id,))
    wf.advance(wf_id, actor="tester (auto)")
    history = _history(wf_id)
    assert history[0][1] == "adopted"
    assert _core(wf_id) == {"invoices": "running:budget", "statements": "running:approval", "reconcile": "waiting"}
