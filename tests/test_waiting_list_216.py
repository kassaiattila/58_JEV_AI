"""The "Waiting for me" list (216, plan G-process-core P2e): the open human tasks for the person working now.

Plain-language summary: the list shows what waits for the person chosen in "Who is working?": their own tasks and
anyone's (marked), each with its kind, what it is about, its package, since when it waits, where it comes from and
where it is done. By default it shows only live work (a live run's to-dos and every approval); on request the to-dos
of trial runs and earlier measurements too (the owner's decisions of 2026-10-23). Another person's task never shows.
Synthetic data, a temporary store, no paid calls.
"""

from __future__ import annotations

from jav.app import app_settings, datasets, work, work_runs
from jav.app.tablequery import Query
from jav.core import store
from tests.test_review_tasks_215 import _pkg, _reconcile, _run
from tests.test_workflow_tasks_215 import _finish
from tests.test_workflows_146 import db  # noqa: F401 - the fixture is used by name

ME = "Teszt Elek"


def _item(wp_id: str) -> str:
    return work.get(wp_id)["items"][0]["item_id"]


def _raise_on(wp_id: str, run_id: str, *reasons: str) -> int:
    item = _item(wp_id)
    return store.review_enqueue(subject_kind="document", subject_id=item, run_id=f"{run_id}:{item}", reasons=list(reasons),
                                producer="tests")


def _rows(actor: str = ME, **scope: str) -> dict[str, dict]:
    page = datasets.query("waiting", {"actor": actor, **scope}, Query())
    return {r["_key"]: r for r in page["rows"]}


def test_the_list_shows_a_persons_live_work_and_where_each_is_done(db):  # noqa: F811
    mine = _pkg(db, "a", owner=ME)
    live = _run(mine)
    rid = _raise_on(mine["wp"], live, "pick:supplier", "money:total")
    _finish(live)
    reconciliation = _reconcile()
    work.set_owner(reconciliation, ME, actor="t")
    rows = _rows()
    assert set(rows) == {f"review:{rid}", f"run_approval:{live}", f"own_approval:{reconciliation}:pair"}
    todo = rows[f"review:{rid}"]
    assert {k: todo[k] for k in ("kind", "what", "workpackage_name", "origin", "assignee", "reason", "reasons")} == {
        "kind": "review", "what": "a.pdf", "workpackage_name": "Synthetic a", "origin": "live", "assignee": "mine",
        "reason": "pick:supplier", "reasons": 2}
    assert (todo["_wp"], todo["_stage"]) == (mine["wp"], f"review/{_item(mine['wp'])}")
    approval = rows[f"run_approval:{live}"]
    assert (approval["kind"], approval["what"], approval["origin"], approval["_wp"], approval["_stage"]) == (
        "run_approval", "Live run", "live", mine["wp"], "result")
    own = rows[f"own_approval:{reconciliation}:pair"]
    assert (own["kind"], own["what"], own["origin"], own["_wp"], own["_stage"]) == (
        "own_approval", "Reconciliation statement", "live", reconciliation, None)
    assert todo["opened_at"] <= approval["opened_at"]


def test_by_default_only_live_work_and_on_request_trials_and_measurements_too(db):  # noqa: F811
    trial_pkg = _pkg(db, "b", owner=ME)
    trial = _run(trial_pkg, mode="shadow")
    tried = _raise_on(trial_pkg["wp"], trial, "pick:supplier")
    measured = store.review_enqueue(subject_kind="document", subject_id="doc-m", run_id="eval-1", reasons=["pick:x"],
                                    producer="tests")
    assert _rows() == {}
    every = _rows(all="true")
    assert {k: every[k]["origin"] for k in every} == {f"review:{tried}": "trial", f"review:{measured}": "measurement"}
    assert every[f"review:{measured}"]["assignee"] == "anyone"
    assert every[f"review:{measured}"]["_wp"] is None


def test_anyones_task_shows_for_everyone_marked_and_anothers_never(db):  # noqa: F811
    app_settings.save_users([ME, "Minta Anna"])
    nobodys = _pkg(db, "c", owner=None)
    run = _run(nobodys, actor="cli")  # not a person on the list: the approval is anyone's
    _finish(run)
    others = _pkg(db, "d", owner="Minta Anna")
    other_run = _run(others)
    _finish(other_run)
    mine, hers = _rows(), _rows("Minta Anna")
    assert set(mine) == {f"run_approval:{run}"} and mine[f"run_approval:{run}"]["assignee"] == "anyone"
    assert set(hers) == {f"run_approval:{run}", f"run_approval:{other_run}"}
    assert hers[f"run_approval:{other_run}"]["assignee"] == "mine"
    work_runs.approve_run(run, actor=ME)
    assert _rows() == {}  # decided: no longer waiting


def test_the_list_needs_a_person(db):  # noqa: F811
    assert datasets.get("waiting").scope == ("actor",)
    page = datasets.query("waiting", {"actor": ME}, Query())
    assert [c["key"] for c in page["columns"]][:6] == ["kind", "what", "workpackage_name", "opened_at", "origin", "assignee"]
