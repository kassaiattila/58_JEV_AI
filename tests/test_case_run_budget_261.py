"""261 (backlog F-reszugy-koltsegkeret; the owner's decisions of 2026-10-29): a multi-step case's start approves a cap for
each step's sub-case's live run; the sub-case's documents step then decides once, when its package is made, by the
run's estimate against that cap (a traced decision): within it the live run starts by itself, for the person who
approved it; over it the step waits for a person's start with a task on Waiting for me, which the person's start
decides; without a cap nothing changes. The start form's estimate per step, and the next period's caps filled in again.
Synthetic documents, no AI call (no run is processed).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jav.app import (case_views, document_processing, process_runtime, registrations, sub_cases, waiting, work_runs)
from jav.core import store, trace
from jav.core.process import cases, engine, tasks
from jav.service.api import create_app
from tests.statement_pdf import pdf_lines_as_text
from tests.test_workflows_146 import _invoices, _party, _statements

registrations.load_all()
PERSON = "anna"
HUMAN = {"X-Actor": PERSON}
MARCH = ["2026-03-01", "2026-03-31"]
WIDE = {"openai": "9", "jev": "9", "azure_di": "9"}
TINY = {"openai": "0.0001", "jev": "0.0001", "azure_di": "0.0001"}


@pytest.fixture
def db(tmp_path, monkeypatch):
    pdf_lines_as_text(monkeypatch)  # as 146's statements
    with store.use_store(tmp_path / "budget.sqlite"):
        yield tmp_path


def _turns(case: str, n: int = 2) -> None:
    for _ in range(n):
        engine.turn(case, wake=True)


def _sub(case: str, step: str) -> str:
    with store.connect() as c:
        return cases.step_row(c, case, step)["result"]["case_id"]


def _monthly(folder, budgets: dict | None) -> str:
    scope = {"party": _party(), "period": MARCH, "step_sources": {
        "invoices": {"kind": "folder", "folder": str(_invoices(folder / "inv", n=2))},
        "statements": {"kind": "folder", "folder": str(_statements(folder / "erste"))}}}
    if budgets is not None:
        scope["step_budgets"] = budgets
    return process_runtime.start_case("monthly_reconciliation", scope, name="Invented March", actor=PERSON)


def _invoices_case(folder, budgets: dict | None) -> tuple[str, str]:
    chain = _monthly(folder, budgets)
    _turns(chain)
    sub = _sub(chain, "invoices")
    _turns(sub)
    return chain, sub


def test_the_gate_starts_the_run_only_when_no_provider_is_over_its_cap() -> None:
    assert document_processing.run_budget_gate({"estimate": {"openai": "0.40", "jev": "0.10"},
                                                "budget": {"openai": "0.40", "jev": "0.20"}}) == {"over": {}, "decision": "start"}
    assert document_processing.run_budget_gate({"estimate": {"openai": "0.41", "jev": "0.10"}, "budget": {"openai": "0.40"}}) == {
        "over": {"jev": "0.10", "openai": "0.41"}, "decision": "needs_budget"}


def test_a_budget_names_known_providers_and_amounts() -> None:
    part = sub_cases.STEP_BUDGETS_PART
    assert part.check({"invoices": {"openai": "0.40"}}, ValueError) == {"invoices": {"openai": "0.40"}}
    for bad in ({"invoices": {"anthropic": "1"}}, {"invoices": {"openai": "-1"}}, {"invoices": {"openai": "a lot"}},
                {"invoices": {}}, {}):
        with pytest.raises(ValueError):
            part.check(bad, ValueError)


def test_within_its_cap_the_sub_cases_run_starts_by_itself_for_who_approved_it(db) -> None:
    chain, sub = _invoices_case(db, {"invoices": WIDE})
    with store.connect() as c:
        scope = cases.find_case_in(c, sub)["data"]["scope"]
    assert scope["run_budget"] == {"usd": WIDE, "approved_by": {"id": "local:anna", "name": "anna"}}
    wp = document_processing.package_of(sub, "process")
    [run] = work_runs.run_rows(wp)
    assert run["mode"] == "apply" and run["actor"] == "anna (auto)"
    [decided] = [t for t in trace.rows(point=document_processing.RUN_BUDGET_GATE) if t["case_id"] == sub]
    assert decided["outcome"]["decision"] == "start" and decided["run_id"] == run["run_id"]
    view = case_views.view(sub)
    [element] = [e for tab in view["tabs"] for e in tab["elements"] if e["type"] == "package_work"]
    assert element["data"]["budget"]["decision"] == "start" and element["data"]["budget"]["approved_by"] == "anna"
    with store.connect() as c:
        assert cases.find_case_in(c, _sub(chain, "statements"))["data"]["scope"].get("run_budget") is None  # no cap of its own


def test_over_its_cap_the_step_waits_for_a_persons_start_on_waiting_for_me(db) -> None:
    _chain, sub = _invoices_case(db, {"invoices": TINY})
    wp = document_processing.package_of(sub, "process")
    assert work_runs.run_rows(wp) == []
    tid = tasks.task_id(document_processing.RUN_BUDGET_TASK, f"{sub}:process")
    task = tasks.get(tid)
    assert task is not None and task.status == tasks.OPEN and task.detail["over"]
    assert any(r["_key"] == tid and r["_wp"] == sub for r in waiting.rows(PERSON))
    run_id = case_views.act(sub, "process", "start_run", PERSON) and work_runs.run_rows(wp)[0]["run_id"]
    assert tasks.get(tid).status == tasks.DECIDED and tasks.get(tid).outcome == {"run_id": run_id}
    _turns(sub)
    with store.connect() as c:
        assert cases.step_row(c, sub, "process")["waiting_for"] == "run_end"


def test_without_a_cap_nothing_starts_by_itself(db) -> None:
    _chain, sub = _invoices_case(db, None)
    assert work_runs.run_rows(document_processing.package_of(sub, "process")) == []
    assert tasks.get(tasks.task_id(document_processing.RUN_BUDGET_TASK, f"{sub}:process")) is None


def test_the_start_form_gets_each_steps_estimate_and_the_next_period_its_caps(db, monkeypatch) -> None:
    monkeypatch.setenv("JAV_API_ROOTS", str(db))
    folder = _invoices(db / "inv", n=2)
    found = sub_cases.estimates("monthly_reconciliation", {"invoices": {"kind": "folder", "folder": str(folder)}})
    assert found["steps"]["invoices"]["items"] == 2 and found["steps"]["invoices"]["usd"]
    chain = _monthly(db, {"invoices": WIDE})
    assert process_runtime.next_draft(chain)["step_budgets"] == {"invoices": WIDE}
    party = _party()
    with TestClient(create_app(store_path=store.current_path()), base_url="http://127.0.0.1:8930") as c:
        est = c.post("/api/processes/monthly_reconciliation/estimate",
                     json={"step_sources": {"invoices": {"kind": "folder", "folder": str(folder)}}})
        assert est.status_code == 200 and est.json()["steps"]["invoices"]["items"] == 2
        body = {"pack": "monthly_reconciliation", "name": "Invented April", "party_id": party, "period_start": "2026-04-01",
                "period_end": "2026-04-30", "step_sources": {"invoices": {"kind": "folder", "folder": str(folder)},
                                                              "statements": {"kind": "folder", "folder": str(db / "erste")}},
                "step_budgets": {"invoices": {"openai": "0.50"}}}
        made = c.post("/api/cases", headers=HUMAN, json=body)
        assert made.status_code == 201, made.text
        refused = c.post("/api/cases", headers=HUMAN, json={**body, "step_budgets": {"invoices": {"openai": "-1"}}})
        assert refused.status_code == 422
    with store.connect() as conn:
        assert cases.find_case_in(conn, made.json()["case_id"])["data"]["scope"]["step_budgets"] == {"invoices": {"openai": "0.50"}}
