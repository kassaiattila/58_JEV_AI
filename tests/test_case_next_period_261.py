"""261 (backlog F-reszugy-kovetkezo-idoszak; the owner's decisions of 2026-10-29): a case of a process repeated by period
offers its next period, from an open case too: the new case's form filled in from it (the next period, the own party,
each step's documents again taking only those no live run has processed yet, a mailbox's received range moved on, the
name with the new period), which a person checks and starts; the new case knows the case it follows, and the earlier
case its next one, so each case has one next case. A folder's or files' source that takes only the new documents leaves
out what a live run has processed (147's rule). Synthetic documents and statements, no AI call.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jav.app import case_views, document_processing, process_packs, process_runtime, registrations, scopes, work
from jav.core import store
from jav.core.process import cases
from jav.service.api import create_app
from tests.statement_pdf import pdf_lines_as_text
from tests.test_workflows_146 import _invoices, _party, _statements

registrations.load_all()
PERSON = "anna"
HUMAN = {"X-Actor": PERSON}
MARCH = ["2026-03-01", "2026-03-31"]
APRIL = ("2026-04-01", "2026-04-30")
NAME = "Monthly reconciliation · Example Kft. · 2026-03-01 – 2026-03-31"


@pytest.fixture
def db(tmp_path, monkeypatch):
    pdf_lines_as_text(monkeypatch)  # as 146's statements
    with store.use_store(tmp_path / "next.sqlite"):
        yield tmp_path


def _monthly(folder) -> tuple[str, str]:
    party = _party()
    scope = {"party": party, "period": MARCH, "step_sources": {
        "invoices": {"kind": "folder", "folder": str(_invoices(folder / "inv", n=2))},
        "statements": {"kind": "folder", "folder": str(_statements(folder / "erste"))}}}
    return process_runtime.start_case("monthly_reconciliation", scope, name=NAME, actor=PERSON), party


@pytest.mark.parametrize(("period", "following"), [
    (("2026-03-01", "2026-03-31"), ("2026-04-01", "2026-04-30")),  # a month: the next month
    (("2026-01-01", "2026-03-31"), ("2026-04-01", "2026-06-30")),  # a quarter: the next quarter
    (("2026-03-10", "2026-03-19"), ("2026-03-20", "2026-03-29")),  # any other: as long, right after it
])
def test_the_next_period_is_the_period_parts_own(period, following) -> None:
    assert scopes.next_period(*period) == following


def test_the_periodic_multi_step_processes_are_repeated_by_period() -> None:
    repeated = {p.id for p in process_packs.packs() if p.repeats}
    assert repeated == {"monthly_reconciliation", "two_sources_reconciliation", "mailbox_reconciliation"}
    assert all(scopes.PERIOD in process_packs.load(p).scope.parts for p in repeated)


def test_an_open_case_offers_its_next_period_filled_in_and_starts_it_once(db) -> None:
    case, party = _monthly(db)
    assert cases.get(case)["status"] == cases.OPEN and case_views.view(case)["next_period"] == {"case_id": None}
    draft = process_runtime.next_draft(case)
    assert {k: draft[k] for k in ("pack", "follows", "party_id", "period_start", "period_end", "name")} == {
        "pack": "monthly_reconciliation", "follows": case, "party_id": party, "period_start": APRIL[0],
        "period_end": APRIL[1], "name": "Monthly reconciliation · Example Kft. · 2026-04-01 – 2026-04-30"}
    assert draft["step_sources"]["invoices"] == {"kind": "folder", "folder": str(db / "inv"), "recursive": False,
                                                 "only_new": True}
    assert draft["step_sources"]["statements"]["only_new"] is True
    scope = {"party": party, "period": list(APRIL), "step_sources": draft["step_sources"]}
    with pytest.raises(process_runtime.NextPeriodError):  # the next period's case is a case of the same process
        process_runtime.start_next(case, "two_sources_reconciliation", scope, name=draft["name"], actor=PERSON)
    following = process_runtime.start_next(case, "monthly_reconciliation", scope, name=draft["name"], actor=PERSON)
    assert case_views.view(case)["next_period"] == {"case_id": following}
    page = case_views.view(following)
    assert page["case"]["follows"] == case and page["next_period"] == {"case_id": None}
    with store.connect() as c:
        kept = cases.find_case_in(c, following)["data"]["scope"]
    assert kept["period"] == list(APRIL) and kept["step_sources"]["invoices"]["only_new"] is True
    with pytest.raises(process_runtime.NextPeriodError):  # one next case each
        process_runtime.next_draft(case)


def test_a_case_of_a_process_not_repeated_offers_no_next_period(db) -> None:
    folder = _invoices(db / "docs", n=1)
    case = process_runtime.start_case("documents", {"source": {"kind": "folder", "folder": str(folder)}}, name="Documents",
                                      actor=PERSON)
    assert case_views.view(case)["next_period"] is None and "follows" not in case_views.view(case)["case"]
    with pytest.raises(process_runtime.NextPeriodError):
        process_runtime.next_draft(case)


def test_a_mailbox_source_moves_its_range_on_and_a_package_is_given_again() -> None:
    ranged = {"kind": "mailbox", "request": {"accounts": ["office@example.com"], "folders": ["Inbox"],
                                             "received_from": MARCH[0], "received_to": MARCH[1]}}
    moved = document_processing.repeated_source(ranged, APRIL, (MARCH[0], MARCH[1]))
    assert (moved["request"]["received_from"], moved["request"]["received_to"]) == APRIL
    days = {"kind": "mailbox", "request": {"accounts": ["office@example.com"], "since_days": 7}}
    assert document_processing.repeated_source(days, APRIL, (MARCH[0], MARCH[1]))["request"]["since_days"] == 7
    assert document_processing.repeated_source({"kind": "package", "workpackage_id": "wp-000000000001"}, APRIL,
                                               (MARCH[0], MARCH[1])) is None


def test_a_source_of_only_the_new_documents_leaves_out_what_a_live_run_processed(db, monkeypatch) -> None:
    folder = _invoices(db / "inv", n=3)
    processed = {work.fingerprint(folder / "invoice-1.pdf")}
    monkeypatch.setattr(work, "processed_live", lambda digests: processed & set(digests))
    make = document_processing.maker_of(document_processing.DOCUMENTS).make
    source = scopes.of(document_processing.SOURCE_PART).check(
        {"kind": "folder", "folder": str(folder), "only_new": True}, ValueError)
    assert source["only_new"] is True
    wp = make({"source": source}, "Next period", None)
    assert sorted(Path(i["source_path"]).name for i in work.get(wp)["items"]) == ["invoice-0.pdf", "invoice-2.pdf"]
    files = {"kind": "files", "files": [str(folder / "invoice-1.pdf")], "only_new": True}
    assert make({"source": files}, "Nothing new", None) is None  # nothing new: no package


def test_the_service_gives_the_next_period_and_starts_it_from_the_form(db, monkeypatch) -> None:
    monkeypatch.setenv("JAV_API_ROOTS", str(db))
    case, party = _monthly(db)
    with TestClient(create_app(store_path=store.current_path()), base_url="http://127.0.0.1:8930") as c:
        draft = c.get(f"/api/cases/{case}/next").json()
        assert draft["period_start"] == APRIL[0] and draft["follows"] == case
        body = {"pack": draft["pack"], "name": draft["name"], "party_id": party, "period_start": APRIL[0],
                "period_end": APRIL[1], "step_sources": draft["step_sources"], "follows": case}
        made = c.post("/api/cases", headers=HUMAN, json=body)
        assert made.status_code == 201, made.text
        assert c.get(f"/api/cases/{case}").json()["next_period"] == {"case_id": made.json()["case_id"]}
        again = c.post("/api/cases", headers=HUMAN, json=body)
        assert again.status_code == 422 and "next period" in again.text
        assert c.get(f"/api/cases/{case}/next").status_code == 422
