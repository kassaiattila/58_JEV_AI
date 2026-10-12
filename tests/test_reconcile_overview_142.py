"""142 (DECISIONS 142, the reconciliation result's first part): the pairing page's overview.

The owner asked to see one transfer paying several invoices, or one invoice paid by several transfers, at once with
every fact of both sides, and to have the lines without an invoice, the invoices without a payment, the overdue
invoices, the possible double payments and every late payment stand out. The engine adds two facts (a possible double
payment, the day an invoice's statements are checked until); `jav/reconcile_overview.py` builds the groups, the timing
and the lists from the package's workspace. Synthetic documents and made-up accounts only; no AI call.
"""

from __future__ import annotations

import copy

from jav import reconcile, reconcile_overview as ov, reconcile_package as rp
from tests import test_reconcile_k2_129 as k2
from tests import test_reconcile_package_131 as p131

db = p131.db
CASES = {c["id"]: c for c in reconcile.golden_cases()}
NEW = ("repeat_after_allocation", "repeat_two_lines_named", "repeat_monthly_series_named_is_none",
       "repeat_monthly_series_unnamed_is_none", "repeat_rejected_line_is_none", "repeat_marked_line_is_none",
       "repeat_other_amount_is_none", "checked_until_stops_at_a_gap", "checked_until_the_last_statement")


# --- the engine's two facts ------------------------------------------------------------------------------------------------


def test_the_golden_set_has_the_new_cases_and_every_case_passes():
    assert set(NEW) <= set(CASES)
    assert reconcile.golden_score() == {"passed": len(CASES), "total": len(CASES), "failures": {}}
    assert reconcile.ENGINE_VERSION == "1.12.0"


def test_a_second_payment_names_the_lines_and_who_paid_first():
    [repeat] = reconcile.propose(CASES["repeat_after_allocation"]["snapshot"])["repeats"]
    assert (repeat["invoice_id"], repeat["line_ids"], repeat["paid_by"]) == ("i1", ["t1", "t2"], ["t1"])
    assert list(repeat["signals"]) == ["t2"] and "invoice_number" in repeat["signals"]["t2"]


def test_an_unnamed_line_well_before_the_issue_paid_another_month_but_a_named_one_counts():
    snap = copy.deepcopy(CASES["repeat_after_allocation"]["snapshot"])
    second = snap["statements"][0]["lines"][1]
    second.update(booking_date="2026-03-05", memo="monthly fee")  # 27 days before the issue date, not named
    assert reconcile.propose(snap)["repeats"] == []
    second["memo"] = "INV-0001"  # an advance payment naming the invoice
    assert [r["line_ids"] for r in reconcile.propose(snap)["repeats"]] == [["t1", "t2"]]


def test_a_line_paying_another_invoice_is_no_repeat():
    snap = copy.deepcopy(CASES["repeat_after_allocation"]["snapshot"])
    snap["invoices"].append({**snap["invoices"][0], "id": "i2", "number": "INV-0002", "issue_date": "2026-04-16",
                             "due_date": "2026-04-30"})
    snap["statements"][0]["lines"][1]["memo"] = "INV-0002"
    result = reconcile.propose(snap)
    assert result["repeats"] == [] and any(c["line_id"] == "t2" and c["invoice_id"] == "i2" and c["proposed"] for c in result["candidates"])


# --- the overview ------------------------------------------------------------------------------------------------------------


def _line(lid, day="2026-04-10", amount="100.00", state="open", **over):
    return {"id": lid, "booking_date": day, "amount": amount, "currency": "HUF", "direction": "debit", "state": state,
            "allocations": [], "candidates": [], "statement_verified": True, **over}


def _invoice(iid, amount="100.00", due="2026-04-15", state="no_payment_found", rest=None, **over):
    return {"id": iid, "amount": amount, "currency": "HUF", "issue_date": "2026-04-01", "due_date": due, "state": state,
            "rest": amount if rest is None else rest, "own": True, "checked_until": "2026-06-30", **over}


def _proposal(iid, *, several=False, relation="equal"):
    return {"invoice_id": iid, "proposed": True, "multiple_candidates": several, "amount_relation": relation}


def _share(iid, amount):
    return {"invoice_id": iid, "line_amount": amount, "invoice_amount": amount, "allocation_id": 1}


def _group(o, member):
    return next(g for g in o["groups"] if member in g["lines"] or member in g["invoices"])


def test_one_transfer_with_the_invoices_it_pays_is_one_group_with_each_pairs_days():
    lines = [_line("t1", day="2026-04-20", amount="300.00", state="proposed",
                   candidates=[_proposal("i1", relation="combined"), _proposal("i2", relation="combined")])]
    invoices = [_invoice("i1", amount="100.00", due="2026-04-15", state="proposed"),
                _invoice("i2", amount="200.00", due="2026-04-25", state="proposed")]
    o = ov.build(lines, invoices, [])
    [g] = o["groups"]
    assert (g["kind"], g["lines"], g["invoices"]) == ("proposed", ["t1"], ["i1", "i2"])
    assert {p["invoice_id"]: p["days_from_due"] for p in g["pairs"]} == {"i1": 5, "i2": -5}
    assert "late" in g["flags"] and set(g["lists"]) == {"to_decide", "late"}
    assert o["invoices"]["i1"]["days_from_due"] == 5 and o["invoices"]["i2"]["overdue_days"] is None


def test_one_invoice_paid_in_two_parts_is_one_paired_group_and_its_last_payment_counts():
    lines = [_line("t1", amount="40.00", state="allocated", allocations=[_share("i1", "40.00")]),
             _line("t2", day="2026-04-18", amount="60.00", state="allocated", allocations=[_share("i1", "60.00")])]
    o = ov.build(lines, [_invoice("i1", state="confirmed", rest="0")], [])
    [g] = o["groups"]
    assert (g["kind"], g["lines"], g["lists"]) == ("paired", ["t1", "t2"], ["late", "paired"])
    assert o["invoices"]["i1"]["paid_on"] == "2026-04-18" and o["invoices"]["i1"]["days_from_due"] == 3


def test_a_line_and_an_invoice_with_nothing_between_them_stand_alone():
    o = ov.build([_line("t1")], [_invoice("i1")], [])
    assert _group(o, "t1")["kind"] == "line_only" and _group(o, "t1")["lists"] == ["to_decide", "line_without_invoice"]
    g = _group(o, "i1")
    assert g["kind"] == "invoice_only" and g["lists"] == ["invoice_without_payment", "overdue"]
    assert o["invoices"]["i1"]["overdue_days"] == 76  # 2026-04-15 to 2026-06-30
    assert o["counts"]["line_without_invoice"] == 1 and o["counts"]["overdue"] == 1 and o["counts"]["all"] == 2


def test_an_invoice_is_not_overdue_before_its_due_date_or_without_one_or_beyond_its_statements():
    for invoice in (_invoice("i1", due="2026-07-15"), _invoice("i1", due=None), _invoice("i1", checked_until=None)):
        o = ov.build([], [invoice], [])
        assert o["invoices"]["i1"]["overdue_days"] is None and "overdue" not in _group(o, "i1")["lists"]
    assert "no_due_date" in _group(ov.build([], [_invoice("i1", due=None)], []), "i1")["flags"]


def test_a_possible_double_payment_joins_the_invoice_it_may_repeat():
    lines = [_line("t1", state="allocated", allocations=[_share("i1", "100.00")]), _line("t2", day="2026-04-20")]
    invoices = [_invoice("i1", state="confirmed", rest="0")]
    o = ov.build(lines, invoices, [{"invoice_id": "i1", "line_ids": ["t1", "t2"], "paid_by": ["t1"], "signals": {}}])
    g = _group(o, "i1")
    assert g["lines"] == ["t1", "t2"] and [p["state"] for p in g["pairs"]] == ["allocated", "repeat"]
    assert {"double_payment", "clarify", "to_decide"} <= set(g["lists"])
    assert o["invoices"]["i1"]["double_payment"] == {"line_ids": ["t1", "t2"], "paid_by": ["t1"]}


def test_a_line_that_may_repeat_two_invoices_joins_the_nearer_one():
    lines = [_line("t1", state="allocated", allocations=[_share("i1", "100.00")]),
             _line("t2", day="2026-05-12", state="allocated", allocations=[_share("i2", "100.00")]), _line("t3", day="2026-05-20")]
    invoices = [_invoice("i1", state="confirmed", rest="0"), _invoice("i2", due="2026-05-15", state="confirmed", rest="0")]
    repeats = [{"invoice_id": "i1", "line_ids": ["t1", "t3"], "paid_by": ["t1"], "signals": {}},
               {"invoice_id": "i2", "line_ids": ["t2", "t3"], "paid_by": ["t2"], "signals": {}}]
    o = ov.build(lines, invoices, repeats)
    assert _group(o, "t3")["invoices"] == ["i2"] and _group(o, "i1")["lines"] == ["t1"]


def test_another_partys_invoice_shows_only_in_a_pair_and_a_credited_one_stands_alone():
    o = ov.build([], [_invoice("i1", own=False), _invoice("i2", state="credited")], [])
    assert [g["invoices"] for g in o["groups"]] == [["i2"]] and o["groups"][0]["kind"] == "credited"
    assert o["invoices"]["i1"]["overdue_days"] is None


def test_several_candidates_and_an_unverified_statement_ask_for_the_documents():
    lines = [_line("t1", state="proposed", statement_verified=False, candidates=[_proposal("i1", several=True)])]
    g = ov.build(lines, [_invoice("i1", state="proposed")], [])["groups"][0]
    assert {"several_candidates", "statement_unverified"} <= set(g["flags"]) and "clarify" in g["lists"]


# --- the package's workspace -----------------------------------------------------------------------------------------------


def test_the_workspace_carries_the_overview_and_every_fact_of_the_card(db):
    invoice = k2._save("inv", k2._invoice(supplier_tax_id="12345678-2-41", fulfillment_date="2026-03-31", net_total="78.74",
                                          vat_total="21.26"))
    k2._save("other", k2._invoice(number="INV-0009", amount="555.00", due_date="2026-04-02"))
    p131._stmt("s", p131._line(day="2026-04-20", value_date="2026-04-21", running_balance="900.00"))
    ws = rp.workspace(p131._package())
    row = p131._invoice_row(ws, invoice)
    assert (row["supplier_tax_id"], row["payment_account"], row["fulfillment_date"], row["net_total"], row["vat_total"]) == (
        "12345678-2-41", k2.SUPPLIER, "2026-03-31", "78.74", "21.26")
    assert row["checked_until"] == "2026-06-30"
    [line] = ws["lines"]
    assert (line["value_date"], line["running_balance"]) == ("2026-04-21", "900.00")
    g = _group(ws["overview"], invoice)
    assert g["kind"] == "proposed" and g["pairs"][0]["days_from_due"] == 5 and "late" in g["flags"]
    other = _group(ws["overview"], next(i["id"] for i in ws["invoices"] if i["number"] == "INV-0009"))
    assert other["kind"] == "invoice_only" and "overdue" in other["lists"]
    assert ws["overview"]["invoices"][other["invoices"][0]]["overdue_days"] == 89  # 2026-04-02 to 2026-06-30
