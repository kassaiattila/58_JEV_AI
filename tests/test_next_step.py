"""The package's "next step" (057): computed in one place, shown by both the list and the package header. Synthetic
data."""

from jav.app.work_views import next_step, step_text
from jav.core import display
from tests import test_api
from tests.test_api import HUMAN, _ready_wp, _start

env = test_api.env

WP = {"items": [{"item_id": "a"}], "assignment": {"recipe_id": "r"}}


def _run(**kw):
    return {"status": "done", "mode": "shadow", "open_reasons": 0, "approval": None, "items": 49, "items_done": 49, **kw}


def test_rules_in_order():
    assert next_step({"items": [], "assignment": None}, None)["code"] == "empty"
    # 080: no "choose a recipe" step: without an assignment the default processing settings apply
    assert next_step({"items": [{"item_id": "a"}], "assignment": None}, None)["code"] == "start"
    assert next_step(WP, None)["code"] == "start"
    assert next_step(WP, None, ready=False)["code"] == "blocked"
    running = next_step(WP, _run(status="running", items_done=12))
    # 231 (D4): the caption is the interface's English source; the list shows it in the request's language
    assert running["label"] == "Running: 12/49" and step_text(running) == "Fut: 12/49"
    assert next_step(WP, _run(status="failed"))["code"] == "rerun"
    # 150: only a live run's to-dos are the next step (after a trial: tests/test_trial_todos_150.py)
    review = next_step(WP, _run(mode="apply", status="needs_review", open_reasons=187))
    assert review == {"code": "review", "label": "Review: 187 to-dos", "stage": "review", "params": {"n": 187}}
    assert step_text(review) == "Ellenőrzés: 187 teendő"
    with display.use("en"):
        assert step_text(review) == "Review: 187 to-dos"
    assert next_step(WP, _run())["code"] == "go_live"
    # 172: the package's Approve and release
    release = next_step(WP, _run(mode="apply"))
    assert release == {"code": "release", "label": "Approve and release", "stage": "result", "params": {}}
    assert step_text(release) == "Jóváhagyás és kiadás"
    assert next_step(WP, _run(mode="apply", approval="approved"))["stage"] == "result"


def test_list_row_counts_work_without_item_list():
    row = {"items": 3, "recipe_id": "invoice-extraction"}  # a list row: a count, not an item list
    assert next_step(row, None)["code"] == "start"


def test_workpackage_view_and_list_carry_the_next_step(env):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    view = c.get(f"/api/workpackages/{wp['id']}").json()
    assert view["next"]["code"] == "start" and view["last_run"] is None
    _start(c, wp["id"])
    view = c.get(f"/api/workpackages/{wp['id']}").json()
    assert view["next"]["code"] == "running" and view["runs"] == 1
    rows = c.post("/api/datasets/workpackages/query", json={}).json()["rows"]
    assert rows[0]["next_code"] == "running" and rows[0]["_stage"] == "process" and rows[0]["next_label"].startswith("Fut:")


def test_rerun_starts_a_new_run_once(env):
    from jav.runtime import worker

    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    first = _start(c, wp["id"]).json()["run_id"]
    ready = c.get(f"/api/workpackages/{wp['id']}/workflow/readiness").json()
    body = {"mode": "apply", "expected_revision": ready["assignment_revision"], "input_hash": ready["input_hash"]}
    assert c.post(f"/api/workpackages/{wp['id']}/workflow/start", headers=HUMAN, json=body).json()["run_id"] == first  # identical: the existing one
    busy = c.post(f"/api/workpackages/{wp['id']}/workflow/start", headers=HUMAN, json={**body, "rerun_of": first})
    assert busy.status_code == 422 and "still active" in busy.json()["message"]
    worker.run_worker(once=True)
    again = c.post(f"/api/workpackages/{wp['id']}/workflow/start", headers=HUMAN, json={**body, "rerun_of": first})
    assert again.status_code == 201 and again.json()["run_id"] != first
    twice = c.post(f"/api/workpackages/{wp['id']}/workflow/start", headers=HUMAN, json={**body, "rerun_of": first})
    assert twice.status_code == 200 and twice.json()["run_id"] == again.json()["run_id"]  # double click: one run


def test_every_kind_s_step_reads_as_the_interface_shows_it():
    """231 (D4): a step with a number reads from its parameters, as the interface's `stepLabel`; any other by its
    caption, which is the interface's source text."""
    assert step_text({"code": "reconcile_pair", "label": "Pairing: 3 open lines", "params": {"n": 3}}) == display.text(
        "Pairing: {{n}} open lines", n=3)
    assert step_text({"code": "quote_approved", "label": "Approved: version 2", "params": {"version": 2}}) == display.text(
        "Approved: version {{n}}", n=2)
    assert step_text({"code": "case_send", "label": "Send", "params": {}}) == display.text("Send")
    with display.use("en"):
        assert step_text({"code": "go_live", "label": "x", "params": {"trial_reasons": 4}}) == "Trial finished: live run (4 to-dos in the trial)"
        assert step_text({"code": "go_live", "label": "Trial OK: live run", "params": {}}) == "Trial OK: live run"
