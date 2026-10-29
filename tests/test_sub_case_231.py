"""231 (stage U, U2c; the owner's decision of 2026-10-28: a chain is a multi-step process): a step runs a case of
another process, a sub-case, and waits until it closes.

A synthetic chain of three steps: two sub-cases read their own documents (each step its own source, given when the
chain starts; one of them takes the chain's period as well), and the third reads the document batches the first two
made, once both are done. A sub-case closed as done makes its step done and the next one starts; one closed otherwise
stops the step with why, and a retry starts a new sub-case. The start is refused when a step's documents are missing,
and a pack whose sub-case needs what the chain cannot give is refused. Synthetic process packs in a folder of their
own; the sub-cases are closed by the test (their runs would call AI), never processed.
"""

from __future__ import annotations

import json
import shutil

import pytest

from jav.app import case_views, document_processing, process_packs, process_runtime, registrations, scopes, sub_cases, work
from jav.core import cfg, store
from jav.core.config import PROJECT_ROOT
from jav.core.identity import person
from jav.core.process import cases, engine
from tests.test_workflows_146 import _invoices

registrations.load_all()
PERSON = "anna"
PERIOD = ["2026-03-01", "2026-03-31"]
HISTORY = {"tabs": [{"id": "history", "label": "History", "elements": [{"type": "timeline"}]}]}


def _meta(pid: str) -> dict:
    return {"name": f"process:{pid}", "version": "1.0.0", "description": "a synthetic pack",
            "changelog": [{"version": "1.0.0", "date": "2026-10-28", "note": "for the test"}]}


def _documents(pid: str, parts: list[str]) -> dict:
    return {"meta": _meta(pid), "id": pid, "title": f"Documents {pid}", "scope": {"parts": parts},
            "intake": [{"on": "manual", "starts": "manual"}], "resources": {},
            "steps": [{"id": "process", "uses": "process_documents@1", "title": "Processing", "params": {}}],
            "screens": HISTORY, "outputs": [], "goldens": []}


def _reader(pid: str) -> dict:
    return {"meta": _meta(pid), "id": pid, "title": "Reader", "scope": {"parts": ["sources"]},
            "intake": [{"on": "manual", "starts": "manual"}], "resources": {},
            "steps": [{"id": "wait", "uses": "wait_reply@1", "title": "Waiting", "params": {"remind_after_days": 5}}],
            "screens": HISTORY, "outputs": [], "goldens": []}


def _chain(pid: str, steps: list[dict], parts: tuple[str, ...] = ("period", "step_sources")) -> dict:
    tabs = [{"id": "overview", "label": "Overview", "elements": [{"type": "sub_case", "step": s["id"]} for s in steps]},
            *HISTORY["tabs"]]
    return {"meta": _meta(pid), "id": pid, "title": "Chain", "scope": {"parts": list(parts)},
            "intake": [{"on": "manual", "starts": "manual"}], "resources": {}, "steps": steps,
            "screens": {"tabs": tabs}, "outputs": [], "goldens": []}


STEPS = [{"id": "first", "uses": "run_case@1", "title": "First documents", "params": {"pack": "sub_period"}},
         {"id": "second", "uses": "run_case@1", "title": "Second documents", "params": {"pack": "sub_docs"}},
         {"id": "third", "uses": "run_case@1", "title": "Reading", "after": ["first", "second"],
          "params": {"pack": "sub_reads", "sources_from": ["first", "second"]}}]


@pytest.fixture
def db(tmp_path, monkeypatch):
    configs = tmp_path / "configs"
    shutil.copytree(PROJECT_ROOT / "configs", configs)
    packs = {"sub_period": _documents("sub_period", ["period", "source"]), "sub_docs": _documents("sub_docs", ["source"]),
             "sub_reads": _reader("sub_reads"), "sub_chain": _chain("sub_chain", STEPS)}
    for pid, pack in packs.items():
        (configs / "processes" / f"{pid}.json").write_text(json.dumps(pack), encoding="utf-8")
    monkeypatch.setattr(cfg, "CONFIG_DIR", configs)
    monkeypatch.setattr(cfg, "CALLSITE_DIR", configs / "callsites")
    monkeypatch.setattr(cfg, "TYPES_DIR", configs / "types")
    monkeypatch.setattr(cfg, "PROCESSES_DIR", configs / "processes")
    cfg.reload()
    with store.use_store(tmp_path / "chain.sqlite"):
        yield tmp_path
    cfg.reload()


def _write(db, pid: str, pack: dict) -> None:
    (db / "configs" / "processes" / f"{pid}.json").write_text(json.dumps(pack), encoding="utf-8")
    cfg.reload()


def _source(db, name: str) -> dict:
    return {"kind": "folder", "folder": str(_invoices(db / name, n=2))}


def _started(db) -> str:
    chain = process_runtime.start_case("sub_chain", {"period": PERIOD, "step_sources": {
        "first": _source(db, "a"), "second": _source(db, "b")}}, name="Invented March", actor=PERSON)
    engine.turn(chain, wake=True)
    return chain


def _step(case_id: str, step_id: str) -> dict:
    with store.connect() as c:
        return cases.step_row(c, case_id, step_id)


def _sub(case_id: str, step_id: str) -> str:
    return _step(case_id, step_id)["result"]["case_id"]


def _data(case_id: str) -> dict:
    with store.connect() as c:
        return cases.find_case_in(c, case_id)["data"]


def _close(case_id: str, outcome: str) -> None:
    with cases.transaction() as c:
        cases.close(c, case_id, outcome, person(PERSON))


def test_a_step_runs_a_case_of_another_process_with_its_own_documents_and_the_chain_s_scope(db) -> None:
    chain = _started(db)
    first, second = _sub(chain, "first"), _sub(chain, "second")
    assert process_runtime.pack_of(first)[0] == "sub_period" and process_runtime.pack_of(second)[0] == "sub_docs"
    assert _data(first)["parent"] == {"case": chain, "step": "first"}
    assert _data(first)["scope"] == {"period": PERIOD, "source": {**_source(db, "a"), "recursive": False}}
    assert _data(second)["scope"] == {"source": {**_source(db, "b"), "recursive": False}}  # it takes no period
    assert work.get(first)["name"] == "Invented March" and work.get(first)["owner"] == PERSON
    assert _step(chain, "first")["waiting_for"] == sub_cases.CLOSED and _step(chain, "third")["state"] == cases.WAITING
    shown = case_views.view(chain)["tabs"][0]["elements"][0]["data"]
    assert shown["case"]["id"] == first and shown["case"]["status"] == cases.OPEN and shown["process"] == "Documents sub_period"
    assert case_views.view(first)["case"]["parent"] == {"id": chain, "name": "Invented March", "step": "first",
                                                        "step_title": "First documents", "title": "Chain",
                                                        "tab": "overview"}  # 261 (B1a): the tab it leads back to


def test_a_sub_case_closed_as_done_makes_its_step_done_and_the_next_reads_the_earlier_batches(db) -> None:
    chain = _started(db)
    first, second = _sub(chain, "first"), _sub(chain, "second")
    for sub in (first, second):
        engine.turn(sub, wake=True)  # its step makes its batch from the folder and waits for a person's live run
    batches = [document_processing.package_of(first, "process"), document_processing.package_of(second, "process")]
    assert all(batches)
    _close(first, "done")
    engine.turn(chain, wake=True)
    assert _step(chain, "first")["state"] == cases.DONE and _step(chain, "third")["state"] == cases.WAITING
    assert _step(chain, "first")["result"] == {"pack": "sub_period", "case_id": first, "outcome": "done"}
    _close(second, "done")
    engine.turn(chain, wake=True)
    third = _sub(chain, "third")
    assert _data(third)["scope"] == {"sources": batches}
    _close(third, "done")
    engine.turn(chain, wake=True)
    assert cases.get(chain)["status"] == cases.CLOSED and cases.get(chain)["outcome"] == "done"


def test_a_sub_case_closed_otherwise_stops_its_step_and_a_retry_starts_a_new_one(db) -> None:
    chain = _started(db)
    first = _sub(chain, "first")
    _close(first, "cancelled")
    engine.turn(chain, wake=True)
    row = _step(chain, "first")
    assert row["state"] == cases.FAILED and "cancelled" in row["note"]
    cases.retry(chain, "first", person(PERSON))
    engine.turn(chain, wake=True)
    again = _sub(chain, "first")
    assert again != first and _step(chain, "first")["result"]["earlier"] == [{"case_id": first, "outcome": "cancelled"}]


def test_the_start_is_refused_without_a_step_s_documents_and_leaves_nothing(db) -> None:
    before = len(work.list_workpackages())
    with pytest.raises(scopes.ScopeError):
        process_runtime.start_case("sub_chain", {"period": PERIOD, "step_sources": {"first": _source(db, "a")}},
                                   name="Invented March", actor=PERSON)
    with pytest.raises(scopes.ScopeError):
        process_runtime.start_case("sub_chain", {"period": PERIOD, "step_sources": {
            "first": _source(db, "a"), "second": _source(db, "b"), "fourth": _source(db, "c")}}, name="x", actor=PERSON)
    assert len(work.list_workpackages()) == before


@pytest.mark.parametrize(("steps", "parts", "why"), [
    (STEPS, ("period",), "step_sources"),  # its sub-cases take their own documents, the chain holds none
    (STEPS, ("step_sources",), "period"),  # the first sub-case needs the period
    ([*STEPS[:2], {**STEPS[2], "after": ["first"]}], ("period", "step_sources"), "does not wait for"),
    ([STEPS[1], {**STEPS[2], "params": {"pack": "sub_reads"}}], ("step_sources",), "sources_from"),
    ([{**STEPS[1], "params": {"pack": "sub_chain"}}], ("period", "step_sources"), "itself"),
    ([{**STEPS[1], "params": {"pack": "sub_none"}}], ("step_sources",), "no process pack"),
])
def test_a_chain_whose_sub_case_needs_what_it_cannot_give_is_refused(db, steps, parts, why) -> None:
    _write(db, "sub_chain", _chain("sub_chain", steps, parts))
    with pytest.raises(process_packs.PackError, match=why):
        process_packs.load("sub_chain")


def test_the_step_sources_the_start_form_asks(db) -> None:
    asked = sub_cases.step_sources(process_packs.load("sub_chain"))
    assert [(a["step"], a["title"], a["pack"]) for a in asked] == [("first", "First documents", "sub_period"),
                                                                  ("second", "Second documents", "sub_docs")]
    assert asked[0]["source_kinds"] == ["folder", "files"]
