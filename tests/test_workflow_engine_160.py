"""160-D (plan F-csak-gpt, Sz4; DECISIONS 160): a workflow step's own AI engine.

A step that names an engine (JEV and GPT, or GPT only) gives it to its package before the run starts; a step that
does not name one follows the application's setting at the moment the step starts. The wizard's estimate, the control
view and the repeat for the next period follow the step's engine. A reconciliation step and a step bringing an existing
package have no engine of their own here.

No AI call: the runs are started but never processed (as in tests/test_workflows_146.py).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from jav import app_settings, mailbox, store, work, workflows as wf
from tests import test_api, test_workflows_146
from tests.test_api import HUMAN
from tests.test_workflows_146 import MONTH, _invoices, _party, _statements

env = test_api.env
db = test_workflows_146.db
BUDGET = {"jev": "9", "openai": "9", "azure_di": "9"}


def _steps(view: dict) -> dict[str, dict]:
    return {s["id"]: s for s in view["steps"]}


def _monthly(db, *, engine: str | None = None, auto: bool = True) -> dict:
    invoices = {"source": {"kind": "folder", "folder": str(_invoices(db / "inv"))}, "budget": BUDGET}
    if engine is not None:
        invoices["engine"] = engine
    return wf.create(template_id="monthly_reconciliation", party_id=_party(), period_start=MONTH[0], period_end=MONTH[1],
                     steps={"invoices": invoices,
                            "statements": {"source": {"kind": "folder", "folder": str(_statements(db / "erste"))}},
                            "reconcile": {"source": {"kind": "none"}}}, actor="tester", auto=auto)


def _run_params(view: dict, step: str) -> dict:
    return work.get_run(_steps(view)[step]["run_id"])["params"]


def test_a_step_with_gpt_only_runs_its_package_without_jev(db):
    made = _monthly(db, engine="gpt")
    inv = _steps(made)["invoices"]
    assert inv["engine"] == "gpt" and inv["state"] == "started"
    assert _run_params(made, "invoices")["jev"] == "off"
    assert work.current_assignment(inv["package"]["id"])["params"]["jev"] == "off"


def test_a_step_without_its_own_engine_follows_the_application_when_it_starts(db):
    app_settings.save_engine_default("gpt", actor="tester")
    made = _monthly(db)
    assert _steps(made)["invoices"]["engine"] is None
    assert _run_params(made, "invoices")["jev"] == "off"


def test_a_steps_own_engine_wins_over_the_applications(db):
    app_settings.save_engine_default("gpt", actor="tester")
    made = _monthly(db, engine="jev")
    assert _run_params(made, "invoices")["jev"] == "on"


def test_a_mailbox_steps_engine_reaches_its_downloaded_package(db, monkeypatch):
    """The download's package gets the application's engine when it is made; the step's own replaces it before the
    run, keeping the package's other settings."""
    pulls = {"p1": {"id": "p1", "status": "running", "result": None}}
    monkeypatch.setattr(mailbox, "request_pull", lambda req, **kw: pulls["p1"] | {"request": req.model_dump(mode="json")})
    monkeypatch.setattr(mailbox, "pull", lambda pid: pulls[pid])
    made = wf.create(template_id="mailbox_reconciliation", party_id=_party(), period_start=MONTH[0], period_end=MONTH[1],
                     steps={"emails": {"source": {"kind": "mailbox", "request": {"accounts": ["someone@example.com"]}},
                                       "budget": BUDGET, "engine": "gpt"},
                            "statements": {"source": {"kind": "folder", "folder": str(db)}},
                            "reconcile": {"source": {"kind": "none"}}}, actor="tester")
    package = work.create_from_files(sorted(_invoices(db / "mail").iterdir()), name="Mail", owner="tester")
    work.assign_recipe(package["id"], "processing", params={"jev": "on", "jev_cache": "live"}, expected_revision=0, actor="tester")
    pulls["p1"] = {"id": "p1", "status": "ok", "result": {"workpackage": package["id"]}}
    view = wf.advance(made["workflow"]["id"], actor="tester (auto)")
    params = _run_params(view, "emails")
    assert params["jev"] == "off" and params["jev_cache"] == "live"


def test_the_estimate_follows_the_steps_engine(db):
    folder = _invoices(db / "inv", n=2)
    source = {"kind": "folder", "folder": str(folder)}
    with_jev = wf.estimate(kind="documents", source=source)
    gpt_only = wf.estimate(kind="documents", source=source, engine="gpt")
    assert "jev" in with_jev["usd"] and "jev" not in gpt_only["usd"]
    assert Decimal(gpt_only["usd"]["openai"]) > Decimal(with_jev["usd"]["openai"])
    app_settings.save_engine_default("gpt", actor="tester")
    assert "jev" in wf.estimate(kind="documents", source=source, engine="jev")["usd"]


def test_the_repeat_for_the_next_period_keeps_the_steps_engine(db):
    made = _monthly(db, engine="gpt", auto=False)
    draft = wf.repeat_draft(made["workflow"]["id"])
    assert draft["steps"]["invoices"]["engine"] == "gpt" and draft["steps"]["statements"]["engine"] is None


def test_an_engine_is_checked(db):
    party = _party()
    folder = str(_invoices(db / "inv"))

    def make(**invoices) -> None:
        wf.create(template_id="monthly_reconciliation", party_id=party, period_start=MONTH[0], period_end=MONTH[1],
                  steps={"invoices": {"source": {"kind": "folder", "folder": folder}, **invoices},
                         "statements": {"source": {"kind": "folder", "folder": str(db)}},
                         "reconcile": {"source": {"kind": "none"}}}, actor="tester", advance_now=False)

    with pytest.raises(wf.WorkflowError, match="unknown engine"):
        make(engine="both")
    with pytest.raises(wf.WorkflowError, match="no engine"):
        wf.create(template_id="monthly_reconciliation", party_id=party, period_start=MONTH[0], period_end=MONTH[1],
                  steps={"invoices": {"source": {"kind": "folder", "folder": folder}},
                         "statements": {"source": {"kind": "folder", "folder": str(db)}},
                         "reconcile": {"source": {"kind": "none"}, "engine": "gpt"}}, actor="tester", advance_now=False)
    docs = work.create_from_folder(_invoices(db / "other"), name="Brought")
    with pytest.raises(wf.WorkflowError, match="no engine"):
        make(source={"kind": "package", "workpackage_id": docs["id"]}, engine="gpt")


def test_the_service_takes_and_shows_a_steps_engine(env):
    c = env["client"]
    body = {"template": "monthly_reconciliation", "party_id": _party(), "period_start": MONTH[0],
            "period_end": MONTH[1], "auto": False,
            "steps": {"invoices": {"source": {"kind": "folder", "folder": str(env["folder"])}, "engine": "gpt"},
                      "statements": {"source": {"kind": "folder", "folder": str(env["folder"])}},
                      "reconcile": {"source": {"kind": "none"}}}}
    made = c.post("/api/workflows", headers=HUMAN, json=body)
    assert made.status_code == 201, made.text
    assert _steps(made.json())["invoices"]["engine"] == "gpt"
    bad = c.post("/api/workflows", headers=HUMAN, json={**body, "steps": {**body["steps"], "invoices": {
        "source": {"kind": "folder", "folder": str(env["folder"])}, "engine": "both"}}})
    assert bad.status_code == 422
    est = c.post("/api/workflows/estimate", json={"kind": "documents", "engine": "gpt",
                                                  "source": {"kind": "folder", "folder": str(env["folder"])}})
    assert est.status_code == 200, est.text
    assert "jev" not in est.json()["usd"] and est.json()["items"] == 2


def test_the_store_keeps_the_steps_engine(db):
    made = _monthly(db, engine="gpt", auto=False)
    with store.connect() as c:
        row = c.execute("SELECT engine FROM workflow_steps WHERE workflow_id=? AND step='invoices'",
                        (made["workflow"]["id"],)).fetchone()
    assert row["engine"] == "gpt"
