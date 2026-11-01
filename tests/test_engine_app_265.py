"""265 (plan L, L4b): the application names the AI engine, not a JEV switch.

A recipe's engine setting (`engine`) takes any engine of `configs/engines.json`; a setting saved before 265 names it
with the JEV switch (`jev: on | off`), and is read, budgeted and saved again under the engine's name. A judgement
service's per-item amount counts only for its own engine. A batch whose engine cannot run in this installation does
not start (the owner's decision of 2026-11-01: stop and ask), and the application's own engine can only be set to one
that can run. Synthetic documents only; nothing is called.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from jav.ai import engine as engines
from jav.app import app_settings, datasets, work, work_readiness, work_recipes, work_runs, work_views
from jav.core import display, providers, store
from tests.pdfgen import INVOICE_LINES, write_text_pdf


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "e.sqlite"):
        yield tmp_path


def _package(folder: Path) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    write_text_pdf(folder / "invoice.pdf", INVOICE_LINES)
    return work.create_from_folder(folder, name="Engine")["id"]


def _assign(wp_id: str, params: dict, revision: int = 0) -> dict:
    return work_recipes.assign_recipe(wp_id, "processing", params=params, expected_revision=revision, actor="tester")


def _assign_raw(wp_id: str, params: dict) -> None:
    """An assignment as an installation before 265 saved it: the current recipe, its settings with the JEV switch."""
    r = work_recipes.recipe("processing")
    with store.connect() as c:
        c.execute("INSERT INTO recipe_assignments(workpackage_id, revision, recipe_id, recipe_version, recipe_hash, params,"
                  " actor, note, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                  (wp_id, 1, "processing", r["version"], work_recipes.recipe_hash(r), json.dumps(params), "old", None,
                   "2026-10-30T10:00:00"))


# --- the setting ---------------------------------------------------------------------------------------------------


def test_the_recipes_engine_setting_takes_every_engine_of_the_registry():
    r = work_recipes.recipe("processing")
    assert work_recipes.allowed_from(r["params"]["engine"]) == engines.ids()
    assert set(work_recipes.recipe("multi-format-processing")["params"]) >= {"engine"}


def test_an_assignment_saved_with_the_old_switch_is_saved_under_its_engine(db):
    wp = _package(db / "in")
    a = _assign(wp, {"jev": "off", "jev_cache": "live"})
    assert a["params"]["engine"] == "gpt" and "jev" not in a["params"] and a["params"]["jev_cache"] == "live"
    b = _assign(wp, {"engine": "decisions"}, a["revision"])
    assert b["params"]["engine"] == "decisions"


def test_a_setting_naming_two_different_engines_is_refused(db):
    wp = _package(db / "in")
    with pytest.raises(ValueError, match="two AI engines"):
        _assign(wp, {"engine": "decisions", "jev": "on"})
    assert _assign(wp, {"engine": "gpt", "jev": "off"})["params"]["engine"] == "gpt"  # agreeing: one engine


def test_the_old_switch_reads_as_its_engine_on_a_frozen_run():
    run = {"recipe": work_recipes.recipe("processing"), "params": {"jev": "off"}}
    assert work_readiness.run_engine(run) == "gpt"
    assert work_readiness.run_engine({**run, "params": {}}) == "jev"  # the recipe's default


# --- the budget ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["document", "email"])
def test_a_judgement_services_amount_counts_only_for_its_engine(kind):
    r = work_recipes.recipe("processing")
    base = {"arm": "auto", "azure_ocr": "off", "tasks": "off", "email_text": "off"}
    jev = work_readiness.item_budget(r, {**base, "engine": "jev"}, kind)
    decisions = work_readiness.item_budget(r, {**base, "engine": "decisions"}, kind)
    gpt = work_readiness.item_budget(r, {**base, "engine": "gpt"}, kind)
    assert "jev" in jev and "openai_decisions" not in jev
    assert "openai_decisions" in decisions and "jev" not in decisions
    assert not {"jev", "openai_decisions"} & set(gpt) and gpt["openai"] > Decimal(0)
    assert decisions.get("openai", Decimal(0)) == jev.get("openai", Decimal(0))  # the same GPT part beside the judge
    # a setting saved before 265 counts as the engine it names
    assert work_readiness.item_budget(r, {**base, "jev": "off"}, kind) == gpt


def test_the_rules_view_names_each_judgement_service_from_the_provider_registry():
    assert datasets.PROVIDER_NAMES == {p: providers.label(p) for p in providers.ids()}
    assert datasets.label_set("provider")["openai_decisions"] == "OpenAI Decisions"


# --- an engine that cannot run here --------------------------------------------------------------------------------


def test_a_batch_whose_engine_cannot_run_here_does_not_start(db):
    """OpenAI Decisions is switched off by default (configs/providers.json): the overview says why, and nothing starts
    until a person chooses another engine."""
    wp = _package(db / "in")
    _assign(wp, {"engine": "decisions"})
    ready = work_readiness.readiness(wp)
    assert ready["ready"] is False and ready["plan"]["engine"] == "decisions"
    [blocker] = [b for b in ready["blockers"] if b["code"] == "engine_unavailable"]
    assert blocker["message"] == display.text(work_readiness.ENGINE_UNAVAILABLE["switched_off"],
                                              engine=display.text(engines.get("decisions").label), provider="OpenAI Decisions")
    with pytest.raises(work.NotReady):
        work_runs.start_run(wp, mode="shadow", expected_assignment_revision=ready["assignment_revision"],
                            input_hash=ready["input_hash"], actor="tester")
    a = work_recipes.current_assignment(wp)
    _assign(wp, {**a["params"], "engine": "jev"}, a["revision"])
    assert "engine_unavailable" not in {b["code"] for b in work_readiness.readiness(wp)["blockers"]}


def test_a_switched_on_engine_can_start(db, monkeypatch):
    monkeypatch.setenv(providers.ON_ENV, "openai_decisions")
    wp = _package(db / "in")
    _assign(wp, {"engine": "decisions"})
    assert "engine_unavailable" not in {b["code"] for b in work_readiness.readiness(wp)["blockers"]}


def test_a_batch_without_ai_items_is_not_stopped_by_its_engine():
    assert work_readiness.engine_blocker({"engine": "decisions", "documents": 0, "emails": 0}) is None
    assert work_readiness.engine_blocker({"engine": "decisions", "documents": 1})["code"] == "engine_unavailable"


def test_the_application_engine_can_only_be_one_that_runs_here(db, monkeypatch):
    with pytest.raises(ValueError, match="cannot run here"):
        app_settings.save_engine_default("decisions", actor="tester")
    assert app_settings.engine_default() == "jev"
    monkeypatch.setenv(providers.ON_ENV, "openai_decisions")
    assert app_settings.save_engine_default("decisions", actor="tester")["engine"] == "decisions"


def test_the_settings_and_the_catalogue_list_the_engines_with_whether_they_run_here(db):
    choices = {c["engine"]: c for c in app_settings.engine_setting()["choices"]}
    assert (choices["jev"]["available"], choices["gpt"]["available"]) == (True, True)
    assert (choices["decisions"]["available"], choices["decisions"]["reason"]) == (False, providers.SWITCHED_OFF)
    assert choices["decisions"]["judge_provider"] == "openai_decisions" and choices["gpt"]["judge_provider"] is None
    processing = next(r for r in work_views.recipe_catalog() if r["id"] == "processing")
    assert [c["engine"] for c in processing["params"]["engine"]["choices"]] == engines.ids()


# --- the migration -------------------------------------------------------------------------------------------------


def test_the_migration_saves_an_old_switch_again_under_its_engine(db):
    old, named = _package(db / "old"), _package(db / "named")
    _assign_raw(old, {"arm": "auto", "jev": "off", "jev_cache": "reuse"})
    _assign(named, {"engine": "jev"})
    planned = work_recipes.migrate_assignments(write=False)
    assert [p["workpackage_id"] for p in planned] == [old]
    assert work_recipes.current_assignment(old)["revision"] == 1  # a dry run changes nothing
    [done] = work_recipes.migrate_assignments(write=True)
    a = work_recipes.current_assignment(old)
    assert a["revision"] == 2 and a["recipe_id"] == "processing" and a["params"]["engine"] == "gpt" and "jev" not in a["params"]
    assert done["note"] == a["note"] and a["actor"] == work_recipes.MIGRATION_ACTOR
    assert work_recipes.migrate_assignments(write=True) == []  # repeatable
    assert "recipe_changed" not in {w["code"] for w in work_readiness.readiness(old)["warnings"]}
