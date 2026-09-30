"""The package's "next step" (057): computed in one place, shown by both the list and the package header. Synthetic
data."""

from jav.work_views import next_step
from tests import test_api
from tests.test_api import HUMAN, _ready_wp, _start

env = test_api.env

WP = {"items": [{"item_id": "a"}], "assignment": {"recipe_id": "r"}}


def _run(**kw):
    return {"status": "done", "mode": "shadow", "open_reasons": 0, "approval": None, "items": 49, "items_done": 49, **kw}


def test_rules_in_order():
    assert next_step({"items": [], "assignment": None}, None)["code"] == "empty"
    assert next_step({"items": [{"item_id": "a"}], "assignment": None}, None) == {"code": "configure", "label": "Recept kiválasztása", "stage": "process",
                                                                                "params": {}}
    assert next_step(WP, None)["code"] == "start"
    assert next_step(WP, None, ready=False)["code"] == "blocked"
    assert next_step(WP, _run(status="running", items_done=12))["label"] == "Fut: 12/49"
    assert next_step(WP, _run(status="failed"))["code"] == "rerun"
    review = next_step(WP, _run(status="needs_review", open_reasons=187))
    assert review == {"code": "review", "label": "Ellenőrzés: 187 teendő", "stage": "review", "params": {"n": 187}}
    assert next_step(WP, _run())["code"] == "go_live"
    assert next_step(WP, _run(mode="apply")) == {"code": "approve", "label": "Jóváhagyás", "stage": "result", "params": {}}
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
