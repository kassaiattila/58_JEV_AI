"""Human tasks of today's work: a live run's approval and a workflow step's budget (215, plan G-process-core P2b).

Plain-language summary: a finished live run waits for its approval as a human task for its package's responsible
person; the approval decides it and a supersede withdraws it. A workflow step over its budget asks a person as a human
task in the workflow's case, and the person's start decides it. When a run of a workflow step's package is approved,
the workflow's case gets an event in the same transaction, so the worker's next look moves the chain on at once: no
check timer has to come due. An event of an earlier round of a task is refused. Synthetic data, a temporary store, no
paid calls.
"""

from __future__ import annotations

from decimal import Decimal

from jav.app import human_tasks, work, work_readiness, work_recipes, work_runs, workflow_cases, workflows as wf
from jav.core import store
from jav.core import identity as actors
from jav.core.process import cases, engine, tasks
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_workflow_core_steps_214 import _core, _history
from tests.test_workflows_146 import (  # noqa: F401 - the fixture is used by name
    MONTH, _invoices, _party, _process_all, _statements, _steps, db,
)


def _monthly(db, *, invoices: int = 2, **kw) -> str:  # noqa: F811
    folder = _invoices(db / "inv", n=invoices)
    return wf.create(template_id="monthly_reconciliation", party_id=_party(), period_start=MONTH[0], period_end=MONTH[1],
                     steps={"invoices": {"source": {"kind": "folder", "folder": str(folder)}},
                            "statements": {"source": {"kind": "folder", "folder": str(_statements(db / "erste"))}},
                            "reconcile": {"source": {"kind": "none"}}}, actor="tester", **kw)["workflow"]["id"]


def _finish(run_id: str) -> None:
    """Every job and item of the run finished (the worker is not run: its items would call AI)."""
    with store.connect() as c:
        c.execute("UPDATE jobs SET status='done' WHERE run_id=?", (run_id,))
    for i in work_runs.get_run(run_id)["input"]["items"]:
        work_runs.record_item_result(run_id, i["item_id"], status="done")
    work_runs.refresh_run_status(run_id)


def _package(db, owner: str | None) -> dict:  # noqa: F811
    folder = db / "docs"
    folder.mkdir()
    write_text_pdf(folder / "a.pdf", INVOICE_LINES)
    wp = work.create_from_folder(folder, name="Synthetic package", owner=owner)
    work_recipes.assign_recipe(wp["id"], "processing", params={"arm": "S"}, expected_revision=0, actor="t")
    ready = work_readiness.readiness(wp["id"])
    return {"wp": wp["id"], "start": {"expected_assignment_revision": 1, "input_hash": ready["input_hash"]}}


def test_a_finished_live_run_waits_for_its_approval_as_a_task_for_the_packages_owner(db):  # noqa: F811
    pkg = _package(db, owner="Teszt Elek")
    run_id = work_runs.start_run(pkg["wp"], mode="apply", actor="t", **pkg["start"])["run_id"]
    trial = work_runs.start_run(pkg["wp"], mode="shadow", actor="t", **pkg["start"])["run_id"]
    assert tasks.get(f"run_approval:{run_id}") is None  # not finished yet
    _finish(run_id)
    _finish(trial)
    task = tasks.get(f"run_approval:{run_id}")
    assert (task.status, task.assignee, task.case_id, task.opened_by.kind) == ("open", "local:Teszt Elek", None, "machine")
    assert tasks.get(f"run_approval:{trial}") is None  # a trial run is only viewed
    work_runs.refresh_run_status(run_id)
    assert [h["kind"] for h in tasks.history(f"run_approval:{run_id}")] == ["opened"]  # once
    work_runs.approve_run(run_id, actor="Example Person")
    task = tasks.get(f"run_approval:{run_id}")
    assert (task.status, task.closed_by.id, task.outcome["approval"]) == ("decided", "local:Example Person", "approved")


def test_a_superseded_run_withdraws_its_approval_task_and_a_package_without_an_owner_goes_to_its_runs_starter(db):  # noqa: F811
    pkg = _package(db, owner=None)
    older = work_runs.start_run(pkg["wp"], mode="apply", actor="Run Starter", **pkg["start"])["run_id"]
    _finish(older)
    newer = work_runs.start_run(pkg["wp"], mode="apply", rerun_of=older, actor="Run Starter", **pkg["start"])["run_id"]
    _finish(newer)
    assert tasks.get(f"run_approval:{older}").assignee == "local:Run Starter"
    work_runs.supersede_run(older, actor="teszt.elek")
    task = tasks.get(f"run_approval:{older}")
    assert (task.status, task.closed_by.id) == ("withdrawn", "local:teszt.elek")
    assert task.note == f"superseded by {newer}"
    assert tasks.get(f"run_approval:{newer}").status == "open"


def test_a_step_over_its_budget_asks_the_packages_owner_and_the_persons_start_decides_it(db):  # noqa: F811
    wf_id = _monthly(db)
    tid = tasks.task_id(workflow_cases.BUDGET_TASK, f"{wf_id}:invoices")
    task = tasks.get(tid)
    assert (task.status, task.assignee, task.case_id, task.step_id) == ("open", "local:tester", wf_id, "invoices")
    assert set(task.detail["over"]) and _core(wf_id)["invoices"] == "running:budget"
    estimate = _steps(wf.view(wf_id))["invoices"]["note"]["estimate"]
    budget = {p: str(Decimal(v) + 1) for p, v in estimate.items()}
    view = wf.start_step(wf_id, "invoices", actor="Example Person", budget=budget)
    assert _steps(view)["invoices"]["state"] == "started" and _core(wf_id)["invoices"] == "running:approval"
    task = tasks.get(tid)
    assert (task.status, task.closed_by.id) == ("decided", "local:Example Person")
    assert task.outcome == {"budget": {p: str(Decimal(v)) for p, v in budget.items()}}
    seen = [(s, k) for s, k, _ in _history(wf_id) if s == "invoices"]
    assert seen.index(("invoices", "task_decided")) < seen.index(("invoices", "event_applied"))
    assert ("invoices", "wait_ended", "local:Example Person") in _history(wf_id)


def test_the_approval_of_a_workflow_steps_run_moves_the_chain_on_at_the_workers_next_look(db):  # noqa: F811
    wf_id = _monthly(db, invoices=0)  # no invoices: that step has nothing new
    assert _steps(wf.view(wf_id))["invoices"]["state"] == "nothing_new"
    _process_all()
    run_id = _steps(wf.view(wf_id))["statements"]["run_id"]
    assert tasks.get(f"run_approval:{run_id}").status == "open"
    assert engine.turn_due() == 0  # nothing has happened yet
    work_runs.approve_run(run_id, actor="Example Person")
    assert cases.view(wf_id)["events"] == {f"run_approval:{run_id}#1": {"kind": workflow_cases.APPROVAL,
                                                                        "status": "pending", "conflicts": 0}}
    assert engine.turn_due() == 2  # no check timer came due: the event moved it (231 C3a-2: and the case it started)
    assert _core(wf_id)["statements"] == "done" and _steps(wf.view(wf_id))["reconcile"]["state"] == "started"
    assert cases.view(wf_id)["events"][f"run_approval:{run_id}#1"]["status"] == "applied"
    assert engine.turn_due() == 0


def test_an_event_of_an_earlier_round_of_a_task_is_refused(db):  # noqa: F811
    wf_id = _monthly(db)
    tid = tasks.task_id(workflow_cases.BUDGET_TASK, f"{wf_id}:invoices")
    stale = {"task": tid, "round": 7, "status": "decided"}
    assert cases.send_event(wf_id, "stale-1", workflow_cases.BUDGET, stale, actors.person("tester"),
                            step_id="invoices") == "accepted"
    assert engine.turn_due() == 1
    assert cases.view(wf_id)["events"]["stale-1"]["status"] == "refused"
    assert _core(wf_id)["invoices"] == "running:budget" and tasks.get(tid).status == "open"


def test_the_owner_rule_names_the_packages_owner_then_a_listed_creator_then_anyone(db):  # noqa: F811
    from jav.app import app_settings

    with_owner = work.create_workpackage(name="A", source_kind="manual", source_ref=None, owner="Teszt Elek")["id"]
    without = work.create_workpackage(name="B", source_kind="manual", source_ref=None)["id"]
    app_settings.save_users(["Teszt Elek", "Minta Anna"])
    with store.connect() as c:
        assert human_tasks.assignee_for(c, with_owner, "Minta Anna") == "local:Teszt Elek"
        assert human_tasks.assignee_for(c, without, "minta  anna") == "local:Minta Anna"  # as the list writes it
        assert human_tasks.assignee_for(c, without, "cli") is None  # not a person on the list: anyone's
        assert human_tasks.assignee_for(c, None, None) is None
