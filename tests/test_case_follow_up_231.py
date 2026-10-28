"""231 (stage U, U1; the owner's decision of 2026-10-28: a button on the closed case): a case closed with an outcome its pack
names offers a person to start another process from the same documents.

A renewal a person sends to the full quote closes; its pack names the full quote as what follows that outcome, so the
closed case offers it, and a person starts it from the case's own scope (its documents). The offer is made once: the
started case is named on the closed one afterwards. A case closed otherwise, or still open, offers nothing; a pack
naming a process that does not take its scope's parts is refused. Two synthetic process packs in a folder of their own;
no run is started (its items would call AI).
"""

from __future__ import annotations

import json
import shutil

import pytest

from jav.app import case_views, process_packs, process_runtime, registrations
from jav.core import cfg, store
from jav.core.config import PROJECT_ROOT
from jav.core.identity import person
from jav.core.process import cases, engine
from tests.test_workflows_146 import _invoices

registrations.load_all()
PERSON = "anna"


def _pack(pid: str, follow_ups: list[dict] | None = None) -> dict:
    return {"meta": {"name": f"process:{pid}", "version": "1.0.0", "description": "a synthetic documents pack",
                     "changelog": [{"version": "1.0.0", "date": "2026-10-28", "note": "for the test"}]},
            "id": pid, "title": f"Documents {pid}", "scope": {"parts": ["source"]},
            "intake": [{"on": "manual", "starts": "manual"}], "resources": {},
            "steps": [{"id": "process", "uses": "process_documents@1", "title": "Processing", "params": {}}],
            "screens": {"tabs": [{"id": "history", "label": "History", "elements": [{"type": "timeline"}]}]},
            "outputs": [], "goldens": []} | ({"follow_ups": follow_ups} if follow_ups is not None else {})


FOLLOW = [{"on": "referred", "pack": "follow_full", "title": "Start the full quote from these documents"}]


@pytest.fixture
def db(tmp_path, monkeypatch):
    configs = tmp_path / "configs"
    shutil.copytree(PROJECT_ROOT / "configs", configs)
    for pid, follow in (("follow_renewal", FOLLOW), ("follow_full", None)):
        (configs / "processes" / f"{pid}.json").write_text(json.dumps(_pack(pid, follow)), encoding="utf-8")
    monkeypatch.setattr(cfg, "CONFIG_DIR", configs)
    monkeypatch.setattr(cfg, "CALLSITE_DIR", configs / "callsites")
    monkeypatch.setattr(cfg, "TYPES_DIR", configs / "types")
    monkeypatch.setattr(cfg, "PROCESSES_DIR", configs / "processes")
    cfg.reload()
    with store.use_store(tmp_path / "follow.sqlite"):
        yield tmp_path
    cfg.reload()


def _closed(db, outcome: str) -> tuple[str, dict]:
    source = {"kind": "folder", "folder": str(_invoices(db / f"inv-{outcome}", n=2))}
    case = process_runtime.start_case("follow_renewal", {"source": source}, name="Invented renewal", actor=PERSON)
    engine.turn(case, wake=True)
    with cases.transaction() as c:
        cases.close(c, case, outcome, person(PERSON))
    return case, source


def test_a_case_closed_with_the_named_outcome_offers_the_process_that_follows(db) -> None:
    case, source = _closed(db, "referred")
    assert case_views.view(case)["follow_ups"] == [
        {"pack": "follow_full", "title": "Start the full quote from these documents", "case_id": None}]
    new = process_runtime.follow_up(case, "follow_full", actor=PERSON)
    assert process_runtime.pack_of(new)[0] == "follow_full"
    with store.connect() as c:
        data = cases.find_case_in(c, new)["data"]
    assert data["scope"]["source"]["folder"] == source["folder"] and data["follows"] == case
    assert case_views.view(case)["follow_ups"][0]["case_id"] == new
    with pytest.raises(process_runtime.FollowUpError):
        process_runtime.follow_up(case, "follow_full", actor=PERSON)  # started once


def test_a_case_closed_otherwise_or_open_offers_nothing(db) -> None:
    case, _ = _closed(db, "declined")
    assert case_views.view(case).get("follow_ups") in (None, [])
    with pytest.raises(process_runtime.FollowUpError):
        process_runtime.follow_up(case, "follow_full", actor=PERSON)
    source = {"kind": "folder", "folder": str(_invoices(db / "inv-open", n=1))}
    open_case = process_runtime.start_case("follow_renewal", {"source": source}, name="Open", actor=PERSON)
    assert case_views.view(open_case).get("follow_ups") in (None, [])


def test_a_pack_naming_a_process_that_does_not_take_its_parts_is_refused(db) -> None:
    folder = cfg.PROCESSES_DIR
    bad = _pack("follow_bad", [{"on": "referred", "pack": "reconciliation", "title": "Reconcile"}])
    (folder / "follow_bad.json").write_text(json.dumps(bad), encoding="utf-8")
    cfg.reload()
    with pytest.raises(process_packs.PackError, match="follow"):
        process_packs.load("follow_bad")
