"""141 (backlog F-EHC-trial; DECISIONS 141): the pairing's gaps the sports club's statements and invoices showed.

The owner chose four changes, all in code: (1) a transfer whose memo names several invoices whose amounts add up to it
exactly proposes them together; (2) a credit note that cancels exactly one invoice of its supplier settles it, so no
payment is looked for; (3) a line booked well before an invoice's issue date without its number is no candidate, and a
line whose memo names one invoice proposes no other; (4) a document's two-digit-year dates are read year first when
only that reading makes every one of them a recent date ("26.06.24" beside "26.07.10"). Synthetic documents and made-up
accounts only; no AI call.
"""

from __future__ import annotations

import copy
from datetime import date

import pytest

from jav import candidates, dates, reconcile, reconcile_package as rp
from jav.models import LineLayout
from tests import test_reconcile_k2_129 as k2
from tests import test_reconcile_package_131 as p131

db = p131.db
CASES = {c["id"]: c for c in reconcile.golden_cases()}
NEW = ("combined_payment_named", "combined_payment_sum_differs", "credit_note_cancels_invoice", "credit_note_with_a_named_payment",
       "credit_note_two_invoices", "unnamed_line_well_before_issue", "named_line_before_issue", "memo_names_another_invoice")
TODAY = date(2026, 10, 11)


def _result(case_id: str, **change) -> dict:
    snap = copy.deepcopy(CASES[case_id]["snapshot"])
    for key, value in change.items():
        snap[key] = value
    return reconcile.propose(snap)


def _pair(result: dict, line: str, invoice: str) -> dict:
    return next(c for c in result["candidates"] if c["line_id"] == line and c["invoice_id"] == invoice)


# --- the golden set -------------------------------------------------------------------------------------------------------


def test_the_golden_set_has_the_new_cases_and_every_case_passes():
    assert set(NEW) <= set(CASES)
    assert reconcile.golden_score() == {"passed": len(CASES), "total": len(CASES), "failures": {}}
    assert reconcile.ENGINE_VERSION == "1.16.0" and {"combined"} <= set(reconcile.RELATIONS)
    assert "credited" in reconcile.STATUSES


# --- one transfer, several invoices ---------------------------------------------------------------------------------------


def test_a_combined_payment_names_its_group_in_the_order_of_issue_and_counts_once_on_its_line():
    result = _result("combined_payment_named")
    group = [_pair(result, "t1", i) for i in ("i1", "i2", "i3")]
    assert all(c["combined"] == ["i1", "i2", "i3"] and not c["multiple_candidates"] for c in group)
    assert all(c["strength"] == group[0]["strength"] for c in group) and group[0]["strength"] > _pair(result, "t1", "i4")["strength"]
    assert "combined" not in _pair(result, "t1", "i4") or _pair(result, "t1", "i4")["combined"] is None
    assert "t1" not in result["unpaired_line_ids"]


def test_the_rest_of_a_combined_payment_is_proposed_after_a_part_was_allocated():
    case = CASES["combined_payment_named"]["snapshot"]
    allocations = [{"invoice_id": "i2", "line_id": "t1", "line_amount": "150.00", "invoice_amount": "150.00"}]
    result = _result("combined_payment_named", allocations=allocations)
    assert _pair(result, "t1", "i1")["combined"] == ["i1", "i3"] and _pair(result, "t1", "i3")["proposed"]
    assert not any(c["invoice_id"] == "i2" for c in result["candidates"]) and case["invoices"][1]["id"] == "i2"


def test_a_group_needs_every_invoice_named_and_at_most_the_configured_count(monkeypatch):
    snap = copy.deepcopy(CASES["combined_payment_named"]["snapshot"])
    snap["statements"][0]["lines"][0]["memo"] = "INV-0101, INV-0102"  # i3 not named: 250 is not the line's 300
    assert not any(c["proposed"] for c in reconcile.propose(snap)["candidates"])
    conf = copy.deepcopy(reconcile._conf())
    conf["combined"]["max_invoices"] = 2
    monkeypatch.setattr(reconcile, "_conf", lambda: conf)
    assert not any(c["proposed"] for c in _result("combined_payment_named")["candidates"])  # three named, at most two


# --- a credit note --------------------------------------------------------------------------------------------------------


def test_a_credit_note_settles_the_invoice_it_cancels_and_says_which_one():
    result = _result("credit_note_cancels_invoice")
    status = {s["invoice_id"]: s for s in result["invoices"]}
    assert status["i1"]["status"] == "credited" and status["i1"]["credited_by"] == "i2"
    assert next(e for e in result["excluded"] if e["id"] == "i2") == {"kind": "invoice", "id": "i2", "reason": "credit_note",
                                                                     "credits": "i1"}


def test_an_invoice_already_paid_is_not_cancelled_by_a_credit_note():
    snap = copy.deepcopy(CASES["credit_note_cancels_invoice"]["snapshot"])
    snap["statements"][0]["lines"] = [{**CASES["one_payment"]["snapshot"]["statements"][0]["lines"][0], "id": "t1", "memo": None}]
    snap["allocations"] = [{"invoice_id": "i1", "line_id": "t1", "line_amount": "100.00", "invoice_amount": "100.00"}]
    status = {s["invoice_id"]: s["status"] for s in reconcile.propose(snap)["invoices"]}
    assert status["i1"] == "confirmed"


def test_a_credit_note_of_another_supplier_or_amount_cancels_nothing():
    for change in ({"supplier_name": "Another Supplier Kft.", "payment_account": None}, {"amount": "-90.00"}):
        snap = copy.deepcopy(CASES["credit_note_cancels_invoice"]["snapshot"])
        snap["invoices"][1].update(change)
        status = {s["invoice_id"]: s["status"] for s in reconcile.propose(snap)["invoices"]}
        assert status["i1"] == "no_payment_found", change


# --- cleaner proposals ----------------------------------------------------------------------------------------------------


def test_a_recurring_bill_paid_before_the_next_invoice_is_issued_is_not_proposed_for_it(monkeypatch):
    assert _result("unnamed_line_well_before_issue")["candidates"] == []
    conf = copy.deepcopy(reconcile._conf())
    conf["proposal"]["unnamed_days_before_issue"] = 30
    monkeypatch.setattr(reconcile, "_conf", lambda: conf)
    assert [c["proposed"] for c in _result("unnamed_line_well_before_issue")["candidates"]] == [True]


def test_a_line_naming_one_invoice_keeps_the_other_only_as_a_listed_candidate():
    result = _result("memo_names_another_invoice")
    other = _pair(result, "t1", "i2")
    assert (other["proposed"], other["amount_relation"], other["signals"]) == (False, "equal", ["supplier_account", "supplier_name"])
    assert not _pair(result, "t1", "i1")["multiple_candidates"]


# --- the package ----------------------------------------------------------------------------------------------------------


def test_accepting_the_proposals_allocates_a_combined_payment_whole(db):
    stmt = p131._stmt("april", p131._line(amount="300.00", memo="INV-0101, INV-0102, INV-0103"))
    for number, amount in (("INV-0101", "100.00"), ("INV-0102", "150.00"), ("INV-0103", "50.00")):
        k2._save(number, k2._invoice(number, amount))
    wp = p131._package()
    ws = rp.workspace(wp)
    [line] = ws["lines"]
    assert line["state"] == "proposed" and sum(c["proposed"] for c in line["candidates"]) == 3
    assert rp.accept_proposed(wp, actor="t") == 3
    line = p131._line_row(rp.workspace(wp), line["id"])
    assert (line["state"], line["rest"]) == ("allocated", "0.00") and stmt


def test_a_credited_invoice_shows_its_credit_note_in_the_package(db):
    p131._stmt("april", p131._line(amount="999.00", memo="other"))
    invoice = k2._save("inv", k2._invoice("INV-0201", "100.00"))
    k2._save("credit", k2._invoice("CN-0202", "-100.00", issue_date="2026-04-05"))
    row = p131._invoice_row(rp.workspace(p131._package()), invoice)
    assert row["state"] == "credited"


# --- two-digit-year dates -------------------------------------------------------------------------------------------------


def _lines(*texts: str) -> list[LineLayout]:
    return [LineLayout(no=n, page=1, text=t) for n, t in enumerate(texts, start=1)]


def test_short_dates_are_read_year_first_when_only_that_makes_every_one_recent():
    texts = ["Fizetés módja:   Teljesítés időpontja:   Számla kelte:   Fizetési határidő:", "Átutalás   26.07.10   26.06.24   26.07.10"]
    assert dates.document_short_order(texts, today=TODAY) == "ymd"
    hits = dates.find_dates_in(texts[1], short_order="ymd", today=TODAY)
    assert [(h.value.isoformat(), h.ambiguous) for h in hits] == [("2026-07-10", False), ("2026-06-24", False), ("2026-07-10", False)]


def test_short_dates_two_readings_could_explain_stay_undecided():
    assert dates.document_short_order(["Kelt: 26.06.24"], today=TODAY) is None  # 2026-06-24 or 2024-06-26
    assert dates.document_short_order(["15.03.23 and 20.04.23"], today=TODAY) is None  # day first only: as before
    assert dates.document_short_order(["no date here", "INV-2026-0042"], today=TODAY) is None
    assert dates.find_dates_in("26.06.24", today=TODAY)[0].ambiguous  # without the document's order, flagged as before


def test_the_date_candidates_of_a_hungarian_invoice_use_the_year_first_reading(monkeypatch):
    monkeypatch.setattr(dates, "date", type("D", (date,), {"today": classmethod(lambda cls: TODAY)}))
    lines = _lines("Számla kelte:   Fizetési határidő:", "26.06.24   26.07.10")
    found = candidates.find_dates(lines, [ln.text for ln in lines])
    assert sorted(c.label for c in found) == ["2026-06-24", "2026-07-10"] and not any(c.ambiguous for c in found)


@pytest.mark.parametrize("text", ["01.02.03", "12.11.10"])
def test_codes_that_look_like_old_dates_are_not_read_year_first(text):
    assert dates.document_short_order([text], today=TODAY) is None
