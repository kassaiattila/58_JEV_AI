"""261 (plan B, the owner's decisions of 2026-10-29: the UI unification): a multi-step case shows its sub-cases' work
as one table (B1a, the data): each sub-case says what its steps' elements give a parent to show (a document step's
documents, its current run's open to-dos and state), and a sub-case's page names the parent's tab it leads back to.
Synthetic documents and statements, no AI call (no run is processed).
"""

from __future__ import annotations

import pytest

from jav.app import case_views, document_processing, process_runtime, registrations, work_views
from jav.core import store
from jav.core.process import cases, engine
from tests.statement_pdf import pdf_lines_as_text
from tests.test_workflows_146 import _invoices, _party, _statements

registrations.load_all()
PERSON = "anna"
MARCH = ["2026-03-01", "2026-03-31"]
WIDE = {"openai": "9", "jev": "9", "azure_di": "9"}


@pytest.fixture
def db(tmp_path, monkeypatch):
    pdf_lines_as_text(monkeypatch)  # as 146's statements
    with store.use_store(tmp_path / "unify.sqlite"):
        yield tmp_path


def _monthly(folder, budgets: dict | None = None) -> str:
    scope = {"party": _party(), "period": MARCH, "step_sources": {
        "invoices": {"kind": "folder", "folder": str(_invoices(folder / "inv", n=2))},
        "statements": {"kind": "folder", "folder": str(_statements(folder / "erste"))}}}
    if budgets is not None:
        scope["step_budgets"] = budgets
    case = process_runtime.start_case("monthly_reconciliation", scope, name="Invented March", actor=PERSON)
    for _ in range(2):
        engine.turn(case, wake=True)
    return case


def _sub_cases(case: str) -> dict[str, dict]:
    page = case_views.view(case)
    return {e["step"]: e["data"] for tab in page["tabs"] for e in tab["elements"] if e["type"] == "sub_case"}


def _sub(case: str, step: str) -> str:
    with store.connect() as c:
        return cases.step_row(c, case, step)["result"]["case_id"]


def test_a_sub_case_says_what_its_document_step_holds_before_a_run(db) -> None:
    case = _monthly(db)
    invoices = _sub(case, "invoices")
    for _ in range(2):
        engine.turn(invoices, wake=True)
    work = _sub_cases(case)["invoices"]["case"]["work"]
    batch = work[0]["batch"]
    assert batch == document_processing.package_of(invoices, "process")
    assert work == [{"step": "process", "title": work[0]["title"], "tab": "documents", "batch": batch, "documents": 2,
                     "todos": None, "run": None}]


def test_a_sub_case_says_its_live_runs_state_once_it_started(db) -> None:
    case = _monthly(db, {"invoices": WIDE})  # within the cap the live run starts by itself (261, M5)
    invoices = _sub(case, "invoices")
    for _ in range(2):
        engine.turn(invoices, wake=True)
    [brief] = _sub_cases(case)["invoices"]["case"]["work"]
    assert brief["documents"] == 2 and brief["run"]["mode"] == "apply" and brief["run"]["approved"] is False


def test_a_sub_cases_page_names_the_parents_tab_it_leads_back_to(db) -> None:
    case = _monthly(db)
    parent = case_views.view(_sub(case, "invoices"))["case"]["parent"]
    assert {k: parent[k] for k in ("id", "step", "tab")} == {"id": case, "step": "invoices", "tab": "overview"}


def test_a_sub_cases_batch_leads_back_to_its_case_and_the_case_it_is_part_of(db) -> None:
    case = _monthly(db)
    invoices = _sub(case, "invoices")
    for _ in range(2):
        engine.turn(invoices, wake=True)
    owner = work_views.workpackage_view(document_processing.package_of(invoices, "process"))["owner_case"]
    assert owner["id"] == invoices and owner["tab"] == "documents"
    assert owner["parent"] == {"id": case, "name": "Invented March", "step": "invoices",  # 263: the step it opens under
                               "step_title": owner["parent"]["step_title"], "tab": "overview"}


def test_a_steps_start_that_may_spend_names_its_cost_cap_and_the_shared_actions_show_it(db) -> None:
    case = _monthly(db)
    invoices = _sub(case, "invoices")
    for _ in range(2):
        engine.turn(invoices, wake=True)
    [start] = case_views.view(invoices)["steps"]["process"]["actions"]
    assert start["name"] == "start_run" and start["cap"]  # B1e: the package's estimate by provider
    assert all(float(v) >= 0 for v in start["cap"].values())
    assert case_views._step_actions(invoices, "process", {}) == {"actions": [start]}
    assert case_views.gives("actions", "process_documents") and case_views.gives("actions", None)


def test_a_forms_fields_a_person_gives_are_described_and_the_pages_state_is_not() -> None:  # B1g
    from datetime import date

    from pydantic import BaseModel, ConfigDict, Field

    from jav.app import capabilities

    class Invented(BaseModel):
        model_config = ConfigDict(extra="forbid")
        day: date = Field(title="The day")
        reason: str = Field(title="Why", min_length=1)
        note: str | None = Field(default=None, title="A note")
        count: int = Field(default=1, title="How many")
        expected_state: int  # the page's state, sent back as given

    assert capabilities.form_fields(Invented) == [
        {"name": "day", "label": "The day", "kind": "date", "required": True},
        {"name": "reason", "label": "Why", "kind": "text", "required": True},
        {"name": "note", "label": "A note", "kind": "text", "required": False},
        {"name": "count", "label": "How many", "kind": "int", "required": False}]
    action = capabilities.form_action("invent", "Invent", lambda c, s: True, Invented, lambda c, s, a, v: None,
                                      prefill=lambda c, s: {"values": {"expected_state": 3}, "blocked": None})
    assert case_views._form("wp-x", "s", action) == {"fields": capabilities.form_fields(Invented),
                                                     "values": {"expected_state": 3}, "blocked": None}
    class Hidden(BaseModel):
        expected_state: int

    assert case_views._form("wp-x", "s", capabilities.form_action("h", "H", lambda c, s: True, Hidden,
                                                                  lambda c, s, a, v: None)) is True


def test_an_element_without_a_brief_gives_none() -> None:
    page = {"steps": {"a": {"title": "A"}}, "tabs": [{"id": "t", "elements": [
        {"type": "x", "step": "a", "data": {"next": None}}, {"type": "y", "step": None, "data": None},
        {"type": "z", "step": "a", "data": {"brief": {"documents": 3}}}]}]}
    assert case_views.briefs(page) == [{"step": "a", "title": "A", "tab": "t", "documents": 3}]
