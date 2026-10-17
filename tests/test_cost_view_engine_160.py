"""160 (plan F-csak-gpt, L3): the cost view knows that a run without JEV calls GPT instead.

The pre-start overview saved with the run records whether JEV is on, but the cost view's expectation ignored it: a run
without JEV still said "JEV: expected" and called its OpenAI calls (the type and the intent recognised by GPT)
unexpected. Synthetic call-log rows, no paid call.
"""

from decimal import Decimal

from jav import costs, work
from tests import test_api, test_cost_view_082
from tests.test_api import HUMAN, _start

env = test_api.env


def _run_without_jev(c, folder) -> tuple[str, str]:
    wp = c.post("/api/workpackages", headers=HUMAN, json={"folder": str(folder), "name": "Without JEV"}).json()["workpackage"]
    r = c.post(f"/api/workpackages/{wp['id']}/workflow", headers=HUMAN,
               json={"recipe_id": "processing", "params": {"jev": "off"}, "expected_revision": 0})
    assert r.status_code == 200, r.text
    run_id = _start(c, wp["id"]).json()["run_id"]
    return run_id, sorted(i["item_id"] for i in wp["items"])[0]


def test_a_run_without_jev_expects_openai_and_not_jev(env):
    run_id, item = _run_without_jev(env["client"], env["folder"])
    assert work.get_run(run_id)["plan"]["jev"] is False
    test_cost_view_082._call(run_id, item, "openai", "gpt-4.1-mini", cost="0.001000")
    rows = {r["provider"]: r for r in costs.plan_vs_actual(run_id)["providers"]}
    assert rows["openai"]["expected"] == "yes" and not rows["openai"]["unexpected"]
    assert "jev" not in rows or rows["jev"]["expected"] == "no"


def test_a_jev_call_in_a_run_without_jev_is_unexpected(env):
    run_id, item = _run_without_jev(env["client"], env["folder"])
    test_cost_view_082._call(run_id, item, "jev", "jev-1.13.0", cost="0.002000")
    rows = {r["provider"]: r for r in costs.plan_vs_actual(run_id)["providers"]}
    assert rows["jev"]["expected"] == "no" and rows["jev"]["unexpected"] and rows["jev"]["usd"] == Decimal("0.002")
