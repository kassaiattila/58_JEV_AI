"""A step built on a reopened step goes out of date and is approved again (218, plan P3 P3l; DECISIONS 218).

Plain-language summary: in a workflow a later step builds on the approved result of its earlier steps (rule 3 of
plan 212 P0). When an earlier step is reopened - a new live run on its approved package, or its own approved version
reopened - the process core reopens it and the steps built on it go out of date: their approval no longer counts for
the chain. The owner's decisions of 2026-10-23: nothing runs by itself; the later step's approved version stays (with
its lock) while the earlier step is open, and once the earlier step is approved again the chain reopens the later
step's version with a reason, so its approval waits for a person again; an approval given before the earlier step's
new approval does not count either. Each step's result names the approved package version it was done with and the
results it built on. Every check uses the application's own operations (approving, reopening, rerunning), not the
core's functions. Synthetic data, a temporary store, no paid calls.
"""

from __future__ import annotations

from decimal import Decimal

from jav.app import package_release, work_readiness, work_runs, workflows as wf
from jav.core.process import cases, engine, tasks
from jav.domains.finance import reconcile_statement as rs
from tests.test_workflow_core_steps_214 import _core
from tests.test_workflow_tasks_215 import _finish, _monthly
from tests.test_workflows_146 import (  # noqa: F401 - the fixture is used by name
    _invoices, _process_all, _steps, db,
)

PERSON = "Example Person"


def _turns() -> None:
    """The worker's looks: the workflows' own tick, then every due case turned (229: the core's round; as after a
    restart, too)."""
    wf.tick(now=float("inf"))
    engine.turn_due()


def _view(wf_id: str) -> dict[str, dict]:
    return _steps(wf.view(wf_id))


def _approve_reconcile(wp_id: str) -> int:
    return rs.approve(wp_id, fingerprint=rs.current(wp_id)["fingerprint"], actor=PERSON)["version"]


def _rerun(run_id: str) -> str:
    """A person's new live run of the package (its to-dos run again): the application's rerun."""
    wp_id = work_runs.get_run(run_id)["workpackage_id"]
    ready = work_readiness.readiness(wp_id)
    return work_runs.start_run(wp_id, mode="apply", rerun_of=run_id, actor=PERSON,
                               expected_assignment_revision=ready["assignment_revision"],
                               input_hash=ready["input_hash"])["run_id"]


def _approved_chain(db) -> tuple[str, str, str]:  # noqa: F811
    """The monthly reconciliation with every step approved: (workflow, the invoices' run, the reconciliation's package)."""
    wf_id = _monthly(db)
    _process_all()  # the statements are read by code
    work_runs.approve_run(_view(wf_id)["statements"]["run_id"], actor=PERSON)
    estimate = _view(wf_id)["invoices"]["note"]["estimate"]
    wf.start_step(wf_id, "invoices", actor=PERSON, budget={p: str(Decimal(v) + 1) for p, v in estimate.items()})
    run_id = _view(wf_id)["invoices"]["run_id"]
    _finish(run_id)  # the worker is not run: its items would call AI
    work_runs.approve_run(run_id, actor=PERSON)
    _turns()
    rec = _view(wf_id)["reconcile"]["package"]["id"]
    assert _approve_reconcile(rec) == 1
    _turns()
    assert _core(wf_id) == {"invoices": "done", "statements": "done", "reconcile": "done"}
    assert cases.get(wf_id)["status"] == "closed"
    return wf_id, run_id, rec


def _own_task(wp_id: str) -> tasks.Task:
    return tasks.get(tasks.task_id("own_approval", wp_id))


def test_a_done_step_names_the_approved_package_version_and_the_results_it_built_on(db):  # noqa: F811
    wf_id, run_id, rec = _approved_chain(db)
    steps = cases.view(wf_id)["steps"]
    assert steps["invoices"]["result"]["ref"] == {"runs": [run_id]}
    fingerprint = package_release.own_approval(rec)["active"]["fingerprint"]
    assert steps["reconcile"]["result"]["ref"] == {"version": 1, "fingerprint": fingerprint}
    assert steps["reconcile"]["result"]["built_on"] == {"invoices": {"runs": [run_id]},
                                                        "statements": steps["statements"]["result"]["ref"]}
    done = [h for h in cases.view(wf_id)["history"] if h["kind"] == "step_done" and h["step_id"] == "reconcile"]
    assert done[-1]["detail"]["built_on"] == {"invoices": 1, "statements": 1}  # the core names the result versions


def test_a_new_live_run_on_an_approved_step_makes_the_step_built_on_it_out_of_date(db):  # noqa: F811
    wf_id, run_id, rec = _approved_chain(db)
    rerun = _rerun(run_id)
    # at once, in the run's own transaction: the invoices step is open again and the reconciliation out of date
    assert _core(wf_id)["invoices"] in ("running", "running:approval") and _core(wf_id)["reconcile"] == "stale"
    assert cases.get(wf_id)["status"] == "open"
    _turns()
    assert _core(wf_id) == {"invoices": "running:approval", "statements": "done", "reconcile": "stale"}
    view = _view(wf_id)
    assert (view["invoices"]["done"], view["reconcile"]["done"]) == (False, False)
    assert (view["reconcile"]["status"], view["reconcile"]["stale_of"]) == ("stale", ["invoices"])
    assert "stale_of" not in view["invoices"]  # the view adds it only to a step out of date
    # the owner's decision: the reconciliation's approved version and its lock stay while the invoices are open
    assert package_release.own_approval(rec)["active"]["version"] == 1
    assert _own_task(rec).status == "decided"
    _finish(rerun)
    work_runs.approve_run(rerun, actor=PERSON)
    _turns()
    _turns()  # a later look (or one after a restart) does not take the old approval either
    assert _core(wf_id) == {"invoices": "done", "statements": "done", "reconcile": "running:approval"}
    approval = package_release.own_approval(rec)
    assert approval["active"] is None
    earlier = approval["versions"][0]
    assert (earlier["version"], earlier["reopened_by"], earlier["reopen_note"]) == (1, "tester (auto)", wf.REAPPROVE_NOTE)
    task = _own_task(rec)
    assert (task.status, task.detail.get("reopened")) == ("open", 1)  # it waits for a person again ("Waiting for me")
    view = _view(wf_id)
    # its package's own next step again (the reopened statement to check and approve), with what changed
    assert (view["reconcile"]["status"], view["reconcile"]["done"], view["reconcile"]["stale_of"]) == \
        ("pairing", False, ["invoices"])
    assert _approve_reconcile(rec) == 2
    _turns()
    assert _core(wf_id) == {"invoices": "done", "statements": "done", "reconcile": "done"}
    assert cases.get(wf_id)["status"] == "closed"
    result = cases.view(wf_id)["steps"]["reconcile"]["result"]
    assert result["ref"]["version"] == 2 and result["built_on"]["invoices"] == {"runs": sorted([run_id, rerun])}
    assert "stale_of" not in _view(wf_id)["reconcile"]


def test_an_approval_given_before_the_earlier_steps_new_approval_does_not_count(db):  # noqa: F811
    wf_id, run_id, rec = _approved_chain(db)
    rerun = _rerun(run_id)
    rs.reopen(rec, note="checked meanwhile", actor=PERSON)  # a person approves it again while the invoices are open
    assert _approve_reconcile(rec) == 2
    _turns()
    assert _core(wf_id)["reconcile"] == "stale"
    _finish(rerun)
    work_runs.approve_run(rerun, actor=PERSON)
    _turns()
    assert _core(wf_id)["reconcile"] == "running:approval"
    assert package_release.own_approval(rec)["versions"][0]["reopened_by"] == "tester (auto)"
    assert _approve_reconcile(rec) == 3
    _turns()
    assert _core(wf_id)["reconcile"] == "done"


def test_a_stopped_new_run_leaves_the_earlier_result_and_the_approval_built_on_it_counts(db):  # noqa: F811
    wf_id, run_id, rec = _approved_chain(db)
    rerun = _rerun(run_id)
    work_runs.cancel_run(rerun, actor=PERSON)
    _turns()
    _turns()
    assert _core(wf_id) == {"invoices": "done", "statements": "done", "reconcile": "done"}
    assert package_release.own_approval(rec)["active"]["version"] == 1  # nothing changed: nothing to approve again
    assert cases.get(wf_id)["status"] == "closed"


def test_reopening_the_last_steps_own_version_reopens_its_step_and_case(db):  # noqa: F811
    wf_id, _run_id, rec = _approved_chain(db)
    rs.reopen(rec, note="a late invoice arrived", actor=PERSON)
    assert cases.get(wf_id)["status"] == "open" and _core(wf_id)["reconcile"] in ("running", "running:approval")
    _turns()
    assert _core(wf_id)["reconcile"] == "running:approval"
    assert (_view(wf_id)["reconcile"]["done"], _view(wf_id)["reconcile"].get("stale_of")) == (False, None)
    assert _approve_reconcile(rec) == 2
    _turns()
    assert _core(wf_id)["reconcile"] == "done" and cases.get(wf_id)["status"] == "closed"


def test_a_trial_run_reopens_nothing(db):  # noqa: F811
    wf_id, run_id, _rec = _approved_chain(db)
    wp_id = work_runs.get_run(run_id)["workpackage_id"]
    ready = work_readiness.readiness(wp_id)
    work_runs.start_run(wp_id, mode="shadow", actor=PERSON, expected_assignment_revision=ready["assignment_revision"],
                        input_hash=ready["input_hash"])
    _turns()
    assert _core(wf_id) == {"invoices": "done", "statements": "done", "reconcile": "done"}


def test_a_processing_step_built_on_a_reopened_one_needs_a_new_live_run_a_person_starts(db, monkeypatch):  # noqa: F811
    """A made-up template (none of today's has a processing step built on another): its old approval does not count
    once the earlier step is approved again; a person's new live run of its package, approved, does."""
    conf = wf.config()
    made_up = {"id": "a_then_b", "title": "A then B", "group": conf["templates"][0]["group"],
               "steps": [{"id": "a", "kind": "documents"}, {"id": "b", "kind": "documents", "after": ["a"]}]}
    monkeypatch.setattr(wf, "config", lambda: {**conf, "templates": [*conf["templates"], made_up]})
    budget = {"jev": "5", "openai": "5", "azure_di": "5"}
    wf_id = wf.create(template_id="a_then_b", party_id=None, period_start=None, period_end=None, actor="tester",
                      steps={sid: {"source": {"kind": "folder", "folder": str(_invoices(db / sid))}, "budget": budget}
                             for sid in ("a", "b")})["workflow"]["id"]
    first = {}
    for sid in ("a", "b"):
        first[sid] = _view(wf_id)[sid]["run_id"]
        _finish(first[sid])
        work_runs.approve_run(first[sid], actor=PERSON)
        _turns()
    assert _core(wf_id) == {"a": "done", "b": "done"} and cases.get(wf_id)["status"] == "closed"
    rerun_a = _rerun(first["a"])
    assert _core(wf_id)["b"] == "stale"
    _finish(rerun_a)
    work_runs.approve_run(rerun_a, actor=PERSON)
    _turns()
    _turns()
    assert _core(wf_id) == {"a": "done", "b": "running:approval"}  # its approved run is the old one
    view = _view(wf_id)
    assert (view["b"]["status"], view["b"]["done"], view["b"]["stale_of"]) == ("stale", False, ["a"])
    rerun_b = _rerun(first["b"])
    _finish(rerun_b)
    work_runs.approve_run(rerun_b, actor=PERSON)
    _turns()
    assert _core(wf_id) == {"a": "done", "b": "done"} and cases.get(wf_id)["status"] == "closed"
    assert cases.view(wf_id)["steps"]["b"]["result"]["built_on"] == {"a": {"runs": sorted([first["a"], rerun_a])}}


def test_a_step_still_in_progress_when_its_earlier_step_reopens_takes_no_approval_given_before_it(db):  # noqa: F811
    """The reconciliation was never approved when the invoices got a new run: approved while they are open, it is
    asked again once they are approved."""
    wf_id = _monthly(db)
    _process_all()
    work_runs.approve_run(_view(wf_id)["statements"]["run_id"], actor=PERSON)
    estimate = _view(wf_id)["invoices"]["note"]["estimate"]
    wf.start_step(wf_id, "invoices", actor=PERSON, budget={p: str(Decimal(v) + 1) for p, v in estimate.items()})
    run_id = _view(wf_id)["invoices"]["run_id"]
    _finish(run_id)
    work_runs.approve_run(run_id, actor=PERSON)
    _turns()
    assert _core(wf_id)["reconcile"] == "running:approval"
    rec = _view(wf_id)["reconcile"]["package"]["id"]
    rerun = _rerun(run_id)
    assert _core(wf_id)["reconcile"] == "stale"
    assert cases.view(wf_id)["steps"]["reconcile"]["result"]["built_on"]["invoices"] == {"runs": [run_id]}
    assert _approve_reconcile(rec) == 1  # approved while the invoices are open
    _turns()
    assert _view(wf_id)["reconcile"]["stale_of"] == ["invoices"]
    _finish(rerun)
    work_runs.approve_run(rerun, actor=PERSON)
    _turns()
    assert _core(wf_id)["reconcile"] == "running:approval"
    assert package_release.own_approval(rec)["versions"][0]["reopened_by"] == "tester (auto)"
    assert _approve_reconcile(rec) == 2
    _turns()
    assert _core(wf_id)["reconcile"] == "done"


def test_a_processing_steps_old_approval_counts_not_even_after_a_stopped_run(db):  # noqa: F811
    """The old approvals are those the step was done with and found at its first look after its earlier steps."""
    assert {"runs": ["run-1"]} in wf._old_approvals({"ref": {"runs": ["run-1"]}}, None)
    assert wf._old_approvals({"ref": {"runs": ["run-1"]}}, {"runs": ["run-1", "run-2"]}) == \
        [{"runs": ["run-1"]}, {"runs": ["run-1", "run-2"]}]
    assert wf._old_approvals({}, None) == []
