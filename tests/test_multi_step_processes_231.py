"""231 (stage U, U2c; the owner's decision of 2026-10-28: a chain is a multi-step process): the multi-step workflows are
process packs a person starts from New case.

The monthly reconciliation, the mailbox to the reconciliation, the two invoice sources and the mailbox to the routing
are process packs whose steps run cases of other processes (sub-cases). The service names the steps that take their own
documents; a monthly reconciliation started on the service with its invoices' folder and its statements' folder reads
both in their own sub-cases, and once both are approved, its reconciliation's sub-case starts for the party and the
period with the party's accounts; what the sub-cases spent is the chain's cost. Synthetic documents and statements; the
runs are finished by the test, never processed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jav.app import capabilities, case_views, document_processing, process_packs, registrations, work_runs
from jav.core import store
from jav.core.process import cases, engine
from jav.domains.finance import party_views
from jav.service.api import create_app
from tests.statement_pdf import pdf_lines_as_text
from tests.test_workflow_tasks_215 import _finish
from tests.test_workflows_146 import MONTH, _invoices, _party, _statements

registrations.load_all()
PERSON = "anna"
HUMAN = {"X-Actor": PERSON}
CHAINS = {"monthly_reconciliation": [("invoices", "documents"), ("statements", "bank_statements")],
          "mailbox_reconciliation": [("emails", "mailbox"), ("statements", "bank_statements")],
          "two_sources_reconciliation": [("invoices", "documents"), ("emails", "mailbox"), ("statements", "bank_statements")],
          "mailbox_routing": [("emails", "mailbox")]}


@pytest.fixture
def db(tmp_path, monkeypatch):
    pdf_lines_as_text(monkeypatch)  # as 146's statements
    with store.use_store(tmp_path / "monthly.sqlite"):
        yield tmp_path


def _turns(case: str, n: int = 2) -> None:
    for _ in range(n):
        engine.turn(case, wake=True)


def _sub(case: str, step: str) -> str:
    with store.connect() as c:
        return cases.step_row(c, case, step)["result"]["case_id"]


def _approved(case: str) -> str:
    """The sub-case's documents: a person starts the live run, the run finishes (the test, no AI), a person approves."""
    _turns(case)
    case_views.act(case, "process", "start_run", PERSON)
    [run] = work_runs.run_rows(document_processing.package_of(case, "process"))
    _finish(run["run_id"])
    _turns(case)
    work_runs.approve_run(run["run_id"], actor=PERSON)
    _turns(case)
    return run["run_id"]


def test_the_four_chains_are_process_packs_a_person_starts(db) -> None:
    with TestClient(create_app(store_path=store.current_path()), base_url="http://127.0.0.1:8930") as c:
        listed = {p["id"]: p for p in c.get("/api/processes").json()["processes"]}
    for pid, steps in CHAINS.items():
        assert process_packs.load(pid).id == pid and listed[pid]["manual"]
        assert "step_sources" in listed[pid]["asks"]
        assert [(s["step"], s["pack"]) for s in listed[pid]["step_sources"]] == steps
    assert listed["mailbox_routing"]["step_sources"][0]["source_kinds"] == ["mailbox"]
    assert listed["documents"]["step_sources"] == []  # a one-step process takes its documents as it did


def test_a_monthly_reconciliation_reads_its_invoices_and_statements_then_reconciles(db) -> None:
    party = _party()
    party_views.register_account(party, "HU42 2222 3334 4444 5555 6666 7777", kind="account", currencies=["HUF"], actor="t")
    sources = {"invoices": {"kind": "folder", "folder": str(_invoices(db / "inv", n=2))},
               "statements": {"kind": "folder", "folder": str(_statements(db / "erste"))}}
    body = {"pack": "monthly_reconciliation", "name": "Invented June", "party_id": party, "period_start": MONTH[0],
            "period_end": MONTH[1]}
    with TestClient(create_app(store_path=store.current_path()), base_url="http://127.0.0.1:8930") as c:
        refused = c.post("/api/cases", headers=HUMAN, json={**body, "step_sources": {"invoices": sources["invoices"]}})
        assert refused.status_code in (400, 422) and "statements" in refused.text.lower()
        made = c.post("/api/cases", headers=HUMAN, json={**body, "step_sources": sources})
        assert made.status_code == 201, made.text
        chain = made.json()["case_id"]
        _turns(chain)
        invoices, statements = _sub(chain, "invoices"), _sub(chain, "statements")
        runs = [_approved(invoices), _approved(statements)]
        assert cases.get(invoices)["status"] == cases.CLOSED and cases.get(statements)["status"] == cases.CLOSED
        _turns(chain)
        reconcile = _sub(chain, "reconcile")
        with store.connect() as conn:
            scope = cases.find_case_in(conn, reconcile)["data"]["scope"]
        assert scope["party"] == party and scope["period"] == list(MONTH) and scope["accounts"]
        page = c.get(f"/api/cases/{chain}").json()
        shown = [e["data"]["case"]["id"] for e in page["tabs"][0]["elements"] if e["type"] == "sub_case"]
        assert shown == [invoices, statements, reconcile]
        assert page["steps"]["invoices"]["state"] == "done" and page["steps"]["reconcile"]["state"] == "running"
        sub_page = c.get(f"/api/cases/{reconcile}").json()
        assert sub_page["case"]["parent"]["id"] == chain and sub_page["case"]["parent"]["step"] == "reconcile"
    spent = capabilities.step_scopes(chain, "invoices", "run_case@1") + capabilities.step_scopes(chain, "statements", "run_case@1")
    assert set(runs) <= set(spent)  # the chain's cost counts what its sub-cases' runs spent
