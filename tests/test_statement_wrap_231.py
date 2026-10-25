"""231 (plan stage C, C3b4; DECISIONS 231): the statement packages made before the bank statements were a process pack,
each wrapped by a new case of the pack (`process_runtime.wrap_case`, the pack's `wraps`).

A package with runs cannot be a case's container, so a new case is made around it: the package keeps its id, kind,
items, runs and approvals and becomes the package of the case's document processing step, which starts in the state its
runs give (done with an approved live run, else waiting for its start). Made-up statements of a made-up party; the runs
are finished by the test, never processed (their items would read files).
"""

from __future__ import annotations

import pytest

from jav.app import (case_views, document_processing, process_packs, process_runtime, registrations, work,
                     work_readiness, work_runs)
from jav.core import identity, store
from jav.core.process import cases
from jav.domains.finance import statement_package
from jav.domains.finance import statement_table as st
from tests.test_workflow_tasks_215 import _finish
from tests.test_workflows_146 import MONTH, _party, _statements

registrations.load_all()
PERSON = "anna"
MACHINE = identity.machine("cases-adopt")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "_pdf_lines", lambda path: path.read_text(encoding="utf-8").splitlines())  # as 146's
    with store.use_store(tmp_path / "wrap.sqlite"):
        yield tmp_path


def _old_package(folder) -> tuple[str, str]:
    """A statement package as the old form made it: the party's statements of the month from the folder."""
    party = _party()
    wp = statement_package.make_for_case({"party": party, "period": list(MONTH),
                                          "source": {"kind": "folder", "folder": str(folder)}}, "June statements", PERSON)
    assert wp is not None
    return wp, party


def _live_run(wp: str) -> str:
    ready = work_readiness.readiness(wp)
    return work_runs.start_run(wp, mode="apply", expected_assignment_revision=ready["assignment_revision"],
                               input_hash=ready["input_hash"], actor=PERSON)["run_id"]


def _wrapped_case(wp: str) -> str:
    [case] = [r["id"] for r in work.list_workpackages(include_archived=True)
              if r["source_kind"] == process_runtime.CONTAINER and cases.get(r["id"])["data"].get("wrapped", {}).get(
                  "workpackage_id") == wp]
    return case


def _runs(wp: str) -> list[tuple]:
    with store.connect() as c:  # the runs as stored, their input and approval among them
        return [tuple(r) for r in c.execute("SELECT * FROM runs WHERE workpackage_id=? ORDER BY run_id", (wp,))]


def test_an_approved_package_gets_a_done_case_and_keeps_everything_it_had(db):
    wp, party = _old_package(_statements(db / "erste"))
    run = _live_run(wp)
    _finish(run)
    work_runs.approve_run(run, actor=PERSON)
    before = (work.get(wp), _runs(wp))
    [row] = process_runtime.adopt_all(actor=MACHINE)
    assert (row["workpackage_id"], row["result"]) == (wp, "to wrap") and work.get(wp) == before[0]  # nothing changed
    [row] = process_runtime.adopt_all(actor=MACHINE, write=True)
    assert row["result"] == "wrapped"
    case = _wrapped_case(wp)
    after = work.get(wp)
    assert (after["source_kind"], after["revision"], after["items"]) == (statement_package.KIND, before[0]["revision"],
                                                                        before[0]["items"])
    assert _runs(wp) == before[1]  # the runs and their approvals stay
    assert document_processing.package_of(case, "process") == wp and wp in document_processing.owned_packages()
    state = cases.get(case)
    assert state["status"] == cases.CLOSED and state["outcome"] == "done"
    data = state["data"]
    assert data["scope"]["party"] == party and data["scope"]["period"] == list(MONTH)
    assert data["scope"]["source"] == {"kind": "package", "workpackage_id": wp}
    assert work.get(case)["owner"] == before[0]["owner"] and work.get(case)["name"] == "June statements"
    assert [e["action"] for e in work.workpackage_events(wp)][-1] == "case_wrapped"
    assert process_runtime.adopt_all(actor=MACHINE, write=True) == []  # a step's package already: not listed again


def test_a_package_without_a_live_run_waits_for_a_person_s_start_on_its_case_page(db):
    wp, _party_id = _old_package(_statements(db / "erste"))
    [row] = process_runtime.adopt_all(actor=MACHINE, write=True)
    case = _wrapped_case(wp)
    step = cases.get(case)  # the case is open, its step waits for the run's start
    assert step["status"] == cases.OPEN
    page = case_views.view(case)
    assert page["steps"]["process"]["waiting_for"] == "run_start"
    [element] = [e for t in page["tabs"] for e in t["elements"] if e["type"] == "package_work"]
    assert element["data"]["package"]["id"] == wp and element["data"]["can_start"] is True
    case_views.act(case, "process", "start_run", PERSON)
    assert [r["mode"] for r in work_runs.run_rows(wp)] == ["apply"]


def test_a_package_whose_folder_is_gone_is_wrapped_all_the_same(db):
    folder = _statements(db / "erste")
    wp, _party_id = _old_package(folder)
    folder.rename(folder.with_name("moved"))  # the made-up statements' folder is no longer where it was
    [row] = process_runtime.adopt_all(actor=MACHINE, write=True)
    assert row["result"] == "wrapped"


def test_an_archived_package_s_case_is_archived_too(db):
    wp, _party_id = _old_package(_statements(db / "erste"))
    work.archive_workpackage(wp, actor=PERSON)
    process_runtime.adopt_all(actor=MACHINE, write=True)
    assert work.get(_wrapped_case(wp))["status"] == "archived"


def test_a_package_a_step_has_already_is_not_wrapped_again(db):
    wp, _party_id = _old_package(_statements(db / "erste"))
    rule = process_packs.load("bank_statements").wraps[0]
    assert process_runtime.wrap_case("bank_statements", wp, rule, actor=MACHINE) == "wrapped"
    assert process_runtime.wrap_case("bank_statements", wp, rule, actor=MACHINE) == "exists"
    assert len([r for r in work.list_workpackages(include_archived=True)
                if r["source_kind"] == process_runtime.CONTAINER]) == 1  # the second container was undone
