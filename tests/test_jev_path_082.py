"""The S path where a document type has no JEV path (082, the owner's decision of 2026-10-01).

The owner's decision: where there is no JEV path, GPT-based processing runs, so that the data is still read. So the S
choice is not "JEV only": the pre-start overview carries the chosen path, so that it can say why documents go to GPT,
and the help says the same. Synthetic PDFs, no paid calls.
"""

from jav import cfg, typepack, work
from tests import test_api
from tests.test_api import HUMAN

env = test_api.env


def test_with_s_chosen_a_type_without_a_jev_path_is_planned_on_the_g_path_with_an_openai_budget(env):
    c = env["client"]
    r = c.post("/api/workpackages", headers=HUMAN, json={"folder": str(env["folder"]), "name": "Receipts"})
    wp = r.json()["workpackage"]
    assert typepack.resolve_arm("nav_receipt", "S") == "G"  # a type with a G path only
    r = c.post(f"/api/workpackages/{wp['id']}/workflow", headers=HUMAN, json={
        "recipe_id": "invoice-extraction", "params": {"arm": "S", "doc_type": "nav_receipt"}, "expected_revision": 0, "note": "S"})
    assert r.status_code == 200, r.text
    ready = work.readiness(wp["id"])
    assert ready["plan"]["arm"] == "S" and ready["plan"]["paths"] == {"S": 0, "G": 2, "unknown": 0}
    assert ready["budget"]["openai"] > 0  # GPT runs there, within the run's OpenAI budget


def test_the_help_says_the_s_path_runs_gpt_where_there_is_no_jev_path():
    help_ = cfg.load("recipe_help")
    option = help_["params"]["arm"]["options"]["S"]
    assert "nincs JEV-útja" in option and "OpenAI" in option
    providers = next(row for row in help_["paths"]["rows"] if row["label"] == "Szolgáltatók")
    assert "OpenAI" in providers["S"]
