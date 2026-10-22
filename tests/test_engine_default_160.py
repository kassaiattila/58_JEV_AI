"""160-D (plan F-csak-gpt, Sz4; DECISIONS 160): the application's AI engine setting, JEV and GPT or GPT only.

The owner's decision of 2026-10-16: JEV and GPT stays the default; GPT only can be chosen for the application, a
workflow step and a package, and a run freezes the setting when it starts. The application's setting is the default of
every new setting: a package without saved settings (the documents step of a workflow, a watched folder without its own
processing), a mailbox download's package and an assignment that does not name the engine. Saved settings and runs keep
their own engine, and an assignment saved before 086 (without the engine) stays JEV and GPT.

Synthetic data, no AI call: the runs are started but never processed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from jav import app_settings, emails, ingest_server, mailbox, store, work, work_readiness, work_recipes, work_runs, workflows as wf
from tests import test_api
from tests.test_api import HUMAN, INVOICE_LINES, write_text_pdf
from tests.test_mailbox import MAILS, REQ, FakeBridge

env = test_api.env


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "e.sqlite"):
        yield tmp_path


def _package(folder: Path, name: str = "Engine") -> str:
    folder.mkdir(parents=True, exist_ok=True)
    write_text_pdf(folder / "invoice.pdf", INVOICE_LINES)
    return work.create_from_folder(folder, name=name)["id"]


def _start(wp_id: str) -> dict:
    ready = work_readiness.readiness(wp_id)
    res = work_runs.start_run(wp_id, mode="shadow", expected_assignment_revision=ready["assignment_revision"],
                         input_hash=ready["input_hash"], actor="tester")
    return work_runs.get_run(res["run_id"])


# --- the setting itself -------------------------------------------------------------------------------------------


def test_the_default_is_jev_and_gpt_until_someone_changes_it(db):
    assert app_settings.engine_default() == "jev"
    assert app_settings.engine_setting() == {"engine": "jev", "actor": None, "updated_at": None}
    saved = app_settings.save_engine_default("gpt", actor="tester")
    assert saved["engine"] == "gpt" and saved["actor"] == "tester" and saved["updated_at"]
    assert app_settings.engine_default() == "gpt"
    assert app_settings.save_engine_default("jev", actor="tester")["engine"] == "jev"


def test_an_unknown_engine_is_refused(db):
    with pytest.raises(ValueError, match="engine"):
        app_settings.save_engine_default("jev-only", actor="tester")
    assert app_settings.engine_default() == "jev"


# --- what follows it ------------------------------------------------------------------------------------------------


def test_a_package_without_saved_settings_follows_the_application(db):
    wp = _package(db / "in")
    assert work_readiness.readiness(wp)["plan"]["jev"] is True
    app_settings.save_engine_default("gpt", actor="tester")
    ready = work_readiness.readiness(wp)
    assert ready["assignment_default"] is True and ready["plan"]["jev"] is False
    assert "jev" not in ready["budget"] and ready["budget"]["openai"] > 0
    run = _start(wp)  # starting the run saves the settings it used: GPT only
    assert run["params"]["jev"] == "off"
    assert work_recipes.current_assignment(wp)["params"]["jev"] == "off"


def test_an_assignment_that_does_not_name_the_engine_takes_the_applications(db):
    app_settings.save_engine_default("gpt", actor="tester")
    wp = _package(db / "in")
    a = work_recipes.assign_recipe(wp, "processing", params={"jev_cache": "live"}, expected_revision=0, actor="tester")
    assert a["params"]["jev"] == "off" and a["params"]["jev_cache"] == "live"
    named = work_recipes.assign_recipe(wp, "processing", params={"jev": "on"}, expected_revision=a["revision"], actor="tester")
    assert named["params"]["jev"] == "on"  # a named engine wins over the application's


def test_saved_settings_and_runs_keep_their_own_engine(db):
    wp = _package(db / "in")
    work_recipes.assign_recipe(wp, "processing", params={"jev": "on"}, expected_revision=0, actor="tester")
    run = _start(wp)
    app_settings.save_engine_default("gpt", actor="tester")
    assert work_recipes.current_assignment(wp)["params"]["jev"] == "on"
    assert work_readiness.readiness(wp)["plan"]["jev"] is True
    assert work_runs.get_run(run["run_id"])["params"]["jev"] == "on"


def test_an_assignment_saved_before_the_engine_setting_stays_jev_and_gpt(db):
    """Before 086 an assignment had no `jev` setting; those runs used JEV, and the application's setting does not
    reinterpret them."""
    wp = _package(db / "in")
    work_recipes.assign_recipe(wp, "processing", params={"jev": "on"}, expected_revision=0, actor="tester")
    with store.connect() as c:  # the shape of an old assignment: every setting except the engine
        c.execute("UPDATE recipe_assignments SET params=? WHERE workpackage_id=?",
                  ('{"arm":"auto","azure_ocr":"on","jev_cache":"reuse","tasks":"off","unknown_documents":"facts"}', wp))
    app_settings.save_engine_default("gpt", actor="tester")
    assert work_readiness.readiness(wp)["plan"]["jev"] is True


def test_a_recipe_without_the_engine_setting_is_unaffected(db):
    app_settings.save_engine_default("gpt", actor="tester")
    wp = _package(db / "in")
    a = work_recipes.assign_recipe(wp, "invoice-extraction", params={}, expected_revision=0, actor="tester")
    assert "jev" not in a["params"]


def test_a_mailbox_download_package_gets_the_applications_engine(db, monkeypatch):
    monkeypatch.setattr(ingest_server, "BRIDGE_DATA_ROOT", db / "bridge" / "data")
    monkeypatch.setattr(emails, "BRIDGE_DATA_ROOT", db / "bridge" / "data")
    app_settings.save_engine_default("gpt", actor="tester")
    res = mailbox.fetch(REQ, actor="teszt", runner=FakeBridge(MAILS), inbox_root=db / "inbox")
    assert work.get(res["workpackage"])["assignment"]["params"]["jev"] == "off"


def test_a_watched_folder_package_gets_the_applications_engine(env):
    c = env["client"]
    app_settings.save_engine_default("gpt", actor="tester")
    saved = c.put("/api/settings/folders", headers=HUMAN, json={"folders": [
        {"path": str(env["folder"]), "recipe_id": "processing", "params": {"jev_cache": "live"}}]})
    assert saved.status_code == 200, saved.text
    [f] = saved.json()["folders"]
    later = datetime.now(timezone.utc) + timedelta(minutes=5)
    result = app_settings.scan(f["id"], now=later, actor=HUMAN["X-Actor"])
    params = work.get(result["workpackage"])["assignment"]["params"]
    assert params["jev"] == "off" and params["jev_cache"] == "live"


def test_the_workflow_estimate_follows_the_applications_engine(db):
    folder = db / "inv"
    folder.mkdir()
    for i in range(2):
        (folder / f"invoice-{i}.pdf").write_bytes(b"%PDF-1.4\n% synthetic invoice " + str(i).encode() + b"\n%%EOF\n")
    with_jev = wf.estimate(kind="documents", source={"kind": "folder", "folder": str(folder)})
    app_settings.save_engine_default("gpt", actor="tester")
    gpt_only = wf.estimate(kind="documents", source={"kind": "folder", "folder": str(folder)})
    assert "jev" in with_jev["usd"] and "jev" not in gpt_only["usd"]
    assert Decimal(gpt_only["usd"]["openai"]) > Decimal(with_jev["usd"]["openai"])


# --- the service ----------------------------------------------------------------------------------------------------


def test_the_service_reads_and_saves_the_setting(env):
    c = env["client"]
    assert c.get("/api/settings/engine").json() == {"engine": "jev", "actor": None, "updated_at": None}
    assert c.put("/api/settings/engine", json={"engine": "gpt"}).status_code == 422  # a person's name is needed
    assert c.put("/api/settings/engine", headers=HUMAN, json={"engine": "both"}).status_code == 422
    saved = c.put("/api/settings/engine", headers=HUMAN, json={"engine": "gpt"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["engine"] == "gpt" and saved.json()["actor"] == HUMAN["X-Actor"]
    assert c.get("/api/settings/engine").json()["engine"] == "gpt"


def test_the_catalogue_shows_the_applications_engine_as_the_default(env):
    """The processing settings editor starts a package without saved settings from the catalogue's defaults, so the
    catalogue gives the engine the application would use."""
    c = env["client"]

    def jev_default() -> str:
        return next(r for r in c.get("/api/recipes").json()["recipes"] if r["id"] == "processing")["params"]["jev"]["default"]

    assert jev_default() == "on"
    c.put("/api/settings/engine", headers=HUMAN, json={"engine": "gpt"})
    assert jev_default() == "off"
