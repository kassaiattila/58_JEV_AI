"""231 (stage U, U2d; the owner's decisions of 2026-10-28: one work list, the cases): "My work today" shows a person's
own steps and decisions on the cases too.

A person starts a case, starts its step that waits for a person's start, and cancels the case: each is in their day,
named by the case, labelled; the machine's work on the case (its steps run, its tasks opened) is nobody's day, and
another person's day holds none of them. A synthetic process pack in a folder of its own; nothing is processed.
"""

from __future__ import annotations

import json
import shutil

import pytest

from jav.app import activity, case_views, datasets, process_runtime, registrations
from jav.core import cfg, store
from jav.core.config import PROJECT_ROOT
from jav.core.identity import person
from jav.core.process import cases, engine

registrations.load_all()
PERSON = "anna"
PACK = {"meta": {"name": "process:day_test", "version": "1.0.0", "description": "a synthetic pack",
                 "changelog": [{"version": "1.0.0", "date": "2026-10-28", "note": "for the test"}]},
        "id": "day_test", "title": "Day test", "scope": {"parts": []}, "intake": [{"on": "manual", "starts": "manual"}],
        "resources": {}, "steps": [{"id": "wait", "uses": "wait_reply@1", "title": "Waiting", "start": "person",
                                    "params": {"remind_after_days": 5}}],
        "screens": {"tabs": [{"id": "history", "label": "History", "elements": [{"type": "timeline"}]}]},
        "outputs": [], "goldens": []}


@pytest.fixture
def db(tmp_path, monkeypatch):
    configs = tmp_path / "configs"
    shutil.copytree(PROJECT_ROOT / "configs", configs)
    (configs / "processes" / "day_test.json").write_text(json.dumps(PACK), encoding="utf-8")
    monkeypatch.setattr(cfg, "CONFIG_DIR", configs)
    monkeypatch.setattr(cfg, "CALLSITE_DIR", configs / "callsites")
    monkeypatch.setattr(cfg, "TYPES_DIR", configs / "types")
    monkeypatch.setattr(cfg, "PROCESSES_DIR", configs / "processes")
    cfg.reload()
    with store.use_store(tmp_path / "day.sqlite"):
        yield tmp_path
    cfg.reload()


def _case_rows(who: str, case: str) -> list[dict]:
    return [e for e in activity.entries(who) if e["workpackage_id"] == case]


def test_a_person_s_start_decision_and_cancel_of_a_case_are_in_their_day(db) -> None:
    case = process_runtime.start_case("day_test", {}, name="Invented day", actor=PERSON)
    engine.turn(case, wake=True)  # the machine: the step waits for a person's start (its task opened)
    case_views.start_step(case, "wait", PERSON)
    engine.turn(case, wake=True)
    cases.cancel(case, person(PERSON))
    rows = _case_rows(PERSON, case)
    assert sorted(r["action"] for r in rows) == ["case_closed", "case_started", "case_task_decided"]
    assert {r["workpackage_name"] for r in rows} == {"Invented day"}
    assert _case_rows("someone else", case) == []
    labels = datasets.label_set("activity_action")
    assert all(labels.get(r["action"]) for r in rows)  # each one labelled for the interface
