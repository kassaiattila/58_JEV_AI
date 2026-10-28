"""231 (plan stage C, C3b2; DECISIONS 231): document processing as a general capability, `process_documents@1`.

A process pack's step makes its own processing package from the case's source (a folder's or chosen files'
documents; the scope part `source`) by its package maker (the documents' by default; a domain registers others by name,
the statements' among them), bound to the step; a step that finds no document is done without a package. Its live run
is a person's action (it may call AI, so its budget is the package's own estimate); the step waits until a live run of
its package is approved, and is done with it. A synthetic process pack in a folder of its own; the runs are started
but never processed (their items would call AI).
"""

from __future__ import annotations

import json
import shutil

import pytest

from jav.app import (capabilities, case_views, document_processing, process_runtime, registrations, scopes, work,
                     work_readiness, work_runs)
from jav.core import cfg, store
from jav.core.config import PROJECT_ROOT
from jav.core.process import engine
from tests.test_cost_view_082 import _call
from tests.test_workflow_tasks_215 import _finish
from tests.test_workflows_146 import _invoices
from tests.statement_pdf import pdf_lines_as_text

registrations.load_all()
PERSON = "anna"
PACK = {"meta": {"name": "process:documents_test", "version": "1.0.0", "description": "a synthetic documents pack",
                 "changelog": [{"version": "1.0.0", "date": "2026-10-25", "note": "for the test"}]},
        "id": "documents_test", "title": "Documents", "scope": {"parts": ["source"]},
        "intake": [{"on": "manual", "starts": "manual"}], "resources": {},
        "steps": [{"id": "process", "uses": "process_documents@1", "title": "Processing", "params": {}}],
        "screens": {"tabs": [{"id": "history", "label": "History", "elements": [{"type": "timeline"}, {"type": "cost"}]}]},
        "outputs": [], "goldens": []}


@pytest.fixture
def db(tmp_path, monkeypatch):
    configs = tmp_path / "configs"
    shutil.copytree(PROJECT_ROOT / "configs", configs)
    (configs / "processes" / "documents_test.json").write_text(json.dumps(PACK), encoding="utf-8")
    monkeypatch.setattr(cfg, "CONFIG_DIR", configs)
    monkeypatch.setattr(cfg, "CALLSITE_DIR", configs / "callsites")
    monkeypatch.setattr(cfg, "TYPES_DIR", configs / "types")
    monkeypatch.setattr(cfg, "PROCESSES_DIR", configs / "processes")
    cfg.reload()
    with store.use_store(tmp_path / "docs.sqlite"):
        yield tmp_path
    cfg.reload()


def _turns(case: str, n: int = 2) -> dict:
    for _ in range(n):
        engine.turn(case, wake=True)
    return engine.state(case)


def test_the_source_part_takes_a_folder_or_files_that_exist(db):
    folder = _invoices(db / "inv")
    assert scopes.check(["source"], {"source": {"kind": "folder", "folder": str(folder)}})["source"]["kind"] == "folder"
    files = [str(p) for p in sorted(folder.iterdir())]
    assert scopes.check(["source"], {"source": {"kind": "files", "files": files}})["source"]["files"] == files
    with pytest.raises(scopes.ScopeError):
        scopes.check(["source"], {"source": {"kind": "folder", "folder": str(db / "nowhere")}})
    with pytest.raises(scopes.ScopeError):
        scopes.check(["source"], {"source": {"kind": "mailbox"}})


def test_the_step_makes_its_package_and_waits_for_a_person_s_start(db):
    folder = _invoices(db / "inv", n=3)
    case = process_runtime.start_case("documents_test", {"source": {"kind": "folder", "folder": str(folder)}},
                                      name="April invoices", actor=PERSON)
    state = _turns(case)
    assert state["steps"]["process"]["state"] == "running" and state["steps"]["process"]["waiting_for"] == "run_start"
    wp = document_processing.package_of(case, "process")
    assert wp is not None and len(work.get(wp)["items"]) == 3 and work.get(wp)["owner"] == PERSON
    assert document_processing.package_of(case, "process") == wp  # one package a step, made once
    view = case_views.view(case)
    assert [a["name"] for a in view["steps"]["process"]["actions"]] == ["start_run"]


def test_a_person_starts_the_live_run_and_its_approval_finishes_the_step(db):
    folder = _invoices(db / "inv", n=2)
    case = process_runtime.start_case("documents_test", {"source": {"kind": "folder", "folder": str(folder)}},
                                      name="April invoices", actor=PERSON)
    _turns(case)
    case_views.act(case, "process", "start_run", PERSON)
    wp = document_processing.package_of(case, "process")
    [run] = work_runs.run_rows(wp)
    assert run["mode"] == "apply" and run["actor"] == PERSON
    state = _turns(case)
    assert state["steps"]["process"]["waiting_for"] == "run_end"  # C3b4: the machine's work while the run works
    _finish(run["run_id"])
    assert _turns(case)["steps"]["process"]["waiting_for"] == "run_approval"  # then a person's approval
    work_runs.approve_run(run["run_id"], actor=PERSON)
    state = _turns(case)
    assert state["steps"]["process"]["state"] == "done" and state["status"] == "closed"
    assert state["steps"]["process"]["result"] == {"package": wp, "runs": [run["run_id"]]}


def test_the_case_s_cost_counts_what_its_package_s_runs_spent(db):
    """U-A8 (the walkthrough of 2026-10-28): the calls of the step's package's runs are the step's, so the case's cost
    shows them (before, it looked only for the step's own budgets and showed nothing spent)."""
    folder = _invoices(db / "inv", n=2)
    case = process_runtime.start_case("documents_test", {"source": {"kind": "folder", "folder": str(folder)}},
                                      name="April invoices", actor=PERSON)
    _turns(case)
    assert capabilities.step_scopes(case, "process", "process_documents@1") == []
    case_views.act(case, "process", "start_run", PERSON)
    wp = document_processing.package_of(case, "process")
    [run] = work_runs.run_rows(wp)
    item = work.get(wp)["items"][0]["item_id"]
    _call(run["run_id"], item, "openai", "gpt-test", cost="0.006053")
    _call(run["run_id"], item, "jev", "jev-test", cost="0.001599")
    assert capabilities.step_scopes(case, "process", "process_documents@1") == [run["run_id"]]
    cost = next(e["data"] for tab in case_views.view(case)["tabs"] for e in tab["elements"] if e["type"] == "cost")
    assert cost["total_usd"] == "0.007652"
    assert {(line["step"], line["provider"], line["calls"], line["cost_usd"]) for line in cost["lines"]} == {
        ("process", "openai", 1, "0.006053"), ("process", "jev", 1, "0.001599")}


def test_the_case_page_says_while_the_worker_has_something_to_do_for_it(db):
    """U-A8 (the walkthrough of 2026-10-28): the page asks again while the case is due (a ready step, an event a
    waiting step takes), not only while a step waits for the machine; a step waiting for a person's start is not."""
    folder = _invoices(db / "inv", n=2)
    case = process_runtime.start_case("documents_test", {"source": {"kind": "folder", "folder": str(folder)}},
                                      name="April invoices", actor=PERSON)
    assert case_views.view(case)["case"]["due"] is True  # its first step is ready
    _turns(case)
    assert case_views.view(case)["case"]["due"] is False  # it waits for a person's start


def test_a_folder_without_documents_finishes_the_step_without_a_package(db):
    empty = db / "empty"
    empty.mkdir()
    case = process_runtime.start_case("documents_test", {"source": {"kind": "folder", "folder": str(empty)}},
                                      name="Nothing", actor=PERSON)
    state = _turns(case)
    assert state["steps"]["process"]["state"] == "done" and state["steps"]["process"]["result"] == {"documents": 0}
    assert document_processing.package_of(case, "process") is None


def test_the_statements_maker_is_registered_by_name():
    assert "documents" in document_processing.maker_names() and "statements" in document_processing.maker_names()


STATEMENTS_PACK = {**PACK, "meta": {**PACK["meta"], "name": "process:statements_test"}, "id": "statements_test",
                   "title": "Bank statements", "scope": {"parts": ["party", "period", "source"]},
                   "steps": [{"id": "process", "uses": "process_documents@1", "title": "Statements",
                              "params": {"maker": "statements"}}]}


def test_the_statements_maker_makes_a_package_of_the_party_s_statements_in_the_period(db, monkeypatch):
    from tests.test_workflows_146 import MONTH, _party, _statements

    pdf_lines_as_text(monkeypatch)  # as 146's
    (cfg.PROCESSES_DIR / "statements_test.json").write_text(json.dumps(STATEMENTS_PACK), encoding="utf-8")
    cfg.reload()
    party = _party()
    folder = _statements(db / "erste")
    case = process_runtime.start_case("statements_test", {"party": party, "period": list(MONTH),
                                                          "source": {"kind": "folder", "folder": str(folder)}},
                                      name="June statements", actor=PERSON)
    _turns(case)
    wp = document_processing.package_of(case, "process")
    assert wp is not None and work.get(wp)["items"]
    assert work.package_rule(wp) is work.rule_named("statements")
    stored = __import__("jav.app.package_scope", fromlist=["stored"]).stored(wp)
    assert (stored["party_id"], stored["period_start"], stored["period_end"]) == (party, MONTH[0], MONTH[1])
    assert stored["parts"][document_processing.OWNER_PART] == f"{case}:process"


def test_the_case_page_shows_the_package_and_its_start_with_the_estimate(db):
    folder = _invoices(db / "inv", n=2)
    case = process_runtime.start_case("documents", {"source": {"kind": "folder", "folder": str(folder)}},
                                      name="April invoices", actor=PERSON)
    _turns(case)
    page = case_views.view(case)
    [element] = [e for t in page["tabs"] for e in t["elements"] if e["type"] == "package_work"]
    data = element["data"]
    wp = document_processing.package_of(case, "process")
    assert data["package"] == {"id": wp, "name": "April invoices", "items": 2, "kind": "folder"}
    assert data["can_start"] is True and isinstance(data["estimate"], dict) and data["runs"] == []
    case_views.act(case, "process", "start_run", PERSON)
    after = next(e for t in case_views.view(case)["tabs"] for e in t["elements"] if e["type"] == "package_work")["data"]
    assert after["can_start"] is False and [r["mode"] for r in after["runs"]] == ["apply"]


def test_the_work_package_list_leaves_a_case_step_s_package_out(db):
    from jav.app import datasets

    folder = _invoices(db / "inv", n=1)
    plain = work.create_from_folder(folder, name="Plain", owner=PERSON)["id"]
    case = process_runtime.start_case("documents", {"source": {"kind": "folder", "folder": str(folder)}},
                                      name="Case invoices", actor=PERSON)
    _turns(case)
    inner = document_processing.package_of(case, "process")
    _cols, rows = datasets.rows("workpackages", {})
    ids = {r["id"] for r in rows}
    assert plain in ids and case in ids and inner not in ids  # the case's package opens from its page


def test_a_person_s_scope_keeps_the_package_bound_to_its_case(db):
    """C3b4: a person's party, period or role, given or taken away on the package's page, keeps the further parts a
    process put in its scope, so the step never loses its package (it would make a second one)."""
    from jav.app import package_scope
    from tests.test_workflows_146 import _party

    folder = _invoices(db / "inv", n=1)
    case = process_runtime.start_case("documents", {"source": {"kind": "folder", "folder": str(folder)}},
                                      name="April invoices", actor=PERSON)
    _turns(case)
    wp = document_processing.package_of(case, "process")
    package_scope.set_scope(wp, party_id=_party(), period_start="2026-04-01", period_end="2026-04-30", role_name=None,
                            actor=PERSON)
    assert document_processing.package_of(case, "process") == wp
    package_scope.clear_scope(wp, actor=PERSON)
    assert document_processing.package_of(case, "process") == wp
    assert package_scope.stored(wp)["party_id"] is None
    assert package_scope.scope_of(wp) is None  # only the binding is left: no scope of a person's shows


def test_the_case_list_says_what_the_step_waits_for(db):
    """C3b4: a person's start while the package waits for its live run, the machine's work while the run works."""
    from jav.app import datasets

    folder = _invoices(db / "inv", n=1)
    case = process_runtime.start_case("documents", {"source": {"kind": "folder", "folder": str(folder)}},
                                      name="April invoices", actor=PERSON)
    _turns(case)
    waits = lambda: {r["id"]: r["waits_for"] for r in datasets.rows("cases", {})[1]}[case]  # noqa: E731
    assert waits() == "person_start"
    case_views.act(case, "process", "start_run", PERSON)
    _turns(case)
    assert waits() == "work"


def test_an_adopted_package_s_step_reads_its_runs(db):
    """C3b4: the step of a package taken over: waiting for its start, for its run, for its approval, or done."""
    folder = _invoices(db / "inv", n=1)
    wp = work.create_from_folder(folder, name="Older", owner=PERSON)["id"]
    adopt = document_processing.CAPABILITY.adopt
    assert (adopt(wp, None).state, adopt(wp, None).waiting_for) == ("running", "run_start")
    ready = work_readiness.readiness(wp)
    run = work_runs.start_run(wp, mode="apply", expected_assignment_revision=ready["assignment_revision"],
                              input_hash=ready["input_hash"], actor=PERSON)["run_id"]
    assert adopt(wp, None).waiting_for == "run_end"
    _finish(run)
    assert adopt(wp, None).waiting_for == "run_approval"
    work_runs.approve_run(run, actor=PERSON)
    done = adopt(wp, None)
    assert (done.state, done.result) == ("done", {"package": wp, "runs": [run]})


def test_a_deleted_package_cancels_its_case_instead_of_being_made_again(db):
    """C3b4: a package without runs may be deleted; its step then closes its case as cancelled."""
    folder = _invoices(db / "inv", n=1)
    case = process_runtime.start_case("documents", {"source": {"kind": "folder", "folder": str(folder)}},
                                      name="April invoices", actor=PERSON)
    _turns(case)
    wp = document_processing.package_of(case, "process")
    work.delete_workpackage(wp, actor=PERSON)
    state = _turns(case)
    assert state["status"] == "closed" and state["outcome"] == "cancelled"
    assert document_processing.package_of(case, "process") is None  # not made again from the folder



# --- 231 (C3d): an asynchronous maker (a mailbox download): its fetch starts once and the step waits for it -----------

ASYNC_PACK = {**PACK, "meta": {**PACK["meta"], "name": "process:async_test"}, "id": "async_test", "title": "Async",
              "steps": [{"id": "process", "uses": "process_documents@1", "title": "Fetching", "params": {"maker": "async_test"}}]}


class _Fetches:
    """A stand-in asynchronous maker: each fetch is a row the test moves on (no download is ever made)."""

    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []
        self.state: dict[str, document_processing.Collected] = {}

    def fetch(self, scope, name, owner, taker) -> str:
        fid = f"fetch-{len(self.started) + 1}"
        self.started.append((fid, taker))
        self.state[fid] = document_processing.Collected("running")
        return fid

    def collect(self, fid: str) -> document_processing.Collected:
        return self.state[fid]


@pytest.fixture
def fetches(db, monkeypatch):
    f = _Fetches()
    (cfg.PROCESSES_DIR / "async_test.json").write_text(json.dumps(ASYNC_PACK), encoding="utf-8")
    cfg.reload()
    monkeypatch.setitem(document_processing._MAKERS, "async_test", document_processing.Maker(
        "async_test", __name__, fetch=f.fetch, collect=f.collect, sources=("folder",)))
    return f


def test_an_asynchronous_maker_s_fetch_starts_once_and_its_package_is_bound_when_it_is_done(db, fetches):
    folder = _invoices(db / "inv", n=2)
    case = process_runtime.start_case("async_test", {"source": {"kind": "folder", "folder": str(folder)}},
                                      name="Fetched", actor=PERSON)
    state = _turns(case, 3)
    assert state["steps"]["process"]["waiting_for"] == "fetching" and fetches.started == [("fetch-1", f"case:{case}:process")]
    wp = work.create_from_folder(folder, name="Fetched", owner=PERSON)["id"]  # what the fetch made
    fetches.state["fetch-1"] = document_processing.Collected("done", wp, note="the connection broke after 2 emails")
    state = _turns(case)
    assert state["steps"]["process"]["waiting_for"] == "run_start" and len(fetches.started) == 1  # not fetched again
    assert document_processing.package_of(case, "process") == wp
    from jav.core.process import cases as core_cases

    assert any(h["kind"] == "fetch_interrupted" for h in core_cases.view(case)["history"])


def test_a_failed_fetch_fails_the_step_and_a_retry_fetches_anew(db, fetches):
    folder = _invoices(db / "inv", n=1)
    case = process_runtime.start_case("async_test", {"source": {"kind": "folder", "folder": str(folder)}},
                                      name="Fetched", actor=PERSON)
    _turns(case)
    fetches.state["fetch-1"] = document_processing.Collected("failed", note="Outlook is not running")
    state = _turns(case)
    assert state["steps"]["process"]["state"] == "failed" and "Outlook is not running" in state["steps"]["process"]["note"]
    from jav.core import identity
    from jav.core.process import cases as core_cases

    core_cases.retry(case, "process", identity.who(PERSON))
    _turns(case)
    assert [f for f, _taker in fetches.started] == ["fetch-1", "fetch-2"]
    fetches.state["fetch-2"] = document_processing.Collected("done", None)  # nothing new
    state = _turns(case)
    assert state["steps"]["process"]["state"] == "done" and state["steps"]["process"]["result"] == {"documents": 0}
