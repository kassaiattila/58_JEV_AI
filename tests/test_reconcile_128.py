"""128 (backlog F-reconciliation, K1): which bank statement line paid which incoming invoice, by code.

The owner's decisions of 2026-10-08 (DECISIONS 128): exact amount and at least one signal first (card payments with an
exchange rate later); never "unpaid", only coverage by verified statements; measured on synthetic golden cases (every
case exactly) and later by the confirmations a person gives in the UI. Synthetic data and made-up accounts only; no AI
call.
"""

from __future__ import annotations

import copy
import hashlib
from decimal import Decimal

import pytest

from jav import reconcile, store

CASES = {c["id"]: c for c in reconcile.golden_cases()}


# --- the golden cases ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_golden_case(case_id):
    assert reconcile.check_case(CASES[case_id]) == []


def test_the_checker_notices_a_wrong_expectation():
    case = copy.deepcopy(CASES["one_payment"])
    case["expected"]["status"]["i1"] = "no_payment_found"
    case["expected"]["pairs"] = []
    problems = reconcile.check_case(case)
    assert len(problems) == 2 and problems[0].startswith("pairs") and problems[1].startswith("status")


def test_the_golden_set_keeps_the_twelve_legacy_cases_and_scores_in_full():
    assert len(CASES) >= 24
    assert {"one_payment", "partial_payments", "combined_payment", "ambiguous", "different_currency", "own_transfer",
            "duplicate_invoice", "negative_invoice", "amount_alone", "supplier_iban_domestic_equivalence",
            "own_account_iban_domestic_equivalence", "outgoing_invoice"} <= set(CASES)
    score = reconcile.golden_score()
    assert score["passed"] == score["total"] and not score["failures"]


def test_the_order_of_the_input_does_not_decide():
    snap = copy.deepcopy(CASES["ambiguous"]["snapshot"])
    first = reconcile.propose(snap)
    snap["invoices"].reverse()
    snap["statements"][0]["lines"].reverse()
    assert reconcile.propose(snap)["candidates"] == first["candidates"]


# --- the rules -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [100.0, "NaN", "Infinity", "100,00", "1 000.00", "1.001", None, ""])
def test_money_is_never_guessed_or_rounded(value):
    with pytest.raises(ValueError):
        reconcile.money(value)


def test_money_keeps_a_canonical_amount_exactly():
    assert reconcile.money("-10") == Decimal("-10") and reconcile.money("1234.5") == Decimal("1234.5")


def test_an_iban_and_its_domestic_number_are_one_account():
    assert reconcile.account_key("HU00 1111 2223 3333 4444 5555 6666") == reconcile.account_key("11112223-33334444-55556666")
    assert reconcile.account_key("11112223-33334444") == "111122233333444400000000"
    assert reconcile.account_key("1234 **** 5678") == ""


def test_a_signal_never_comes_from_the_amount():
    invoice = {"number": "INV-0001", "supplier_name": "Example Supplier Kft.", "payment_account": None}
    line = {"amount": "100.00", "counterparty_name": "Somebody", "counterparty_account": None, "memo": "100.00"}
    assert reconcile.signals(invoice, line) == []


def test_the_window_runs_from_before_the_issue_to_after_the_due_date():
    start, end = reconcile.window({"issue_date": "2026-04-01", "due_date": "2026-04-15"})
    assert (start.isoformat(), end.isoformat()) == ("2026-03-01", "2026-06-14")
    start, end = reconcile.window({"issue_date": "2026-04-01", "due_date": None})
    assert end.isoformat() == "2026-05-31"


@pytest.mark.parametrize(("validation", "expected"), [
    ([{"name": "closing_balance_check", "ok": True, "code": "closing.ok"},
      {"name": "totals_consistency", "ok": True, "code": "totals.na"}], True),
    ([{"name": "closing_balance_check", "ok": False, "code": "closing.mismatch"},
      {"name": "totals_consistency", "ok": True, "code": "totals.ok"}], False),
    ([{"name": "totals_consistency", "ok": True, "code": "totals.ok"}], False),
    ('[{"name": "closing_balance_check", "ok": true, "code": "closing.ok"},'
     ' {"name": "totals_consistency", "ok": true, "code": "totals.ok"}]', True),
    ("not json", False), (None, False)])
def test_a_statement_is_coverage_only_when_its_balances_check_out(validation, expected):
    assert reconcile.verified(validation) is expected


# --- stable line ids -----------------------------------------------------------------------------------------------


def _lines():
    return [{"booking_date": "2026-04-10", "direction": "debit", "amount": "100.00", "memo": "a"},
            {"booking_date": "2026-04-11", "direction": "debit", "amount": "50.00", "memo": "b"},
            {"booking_date": "2026-04-11", "direction": "debit", "amount": "50.00", "memo": "b"}]


def test_a_line_keeps_its_id_when_another_line_appears_before_it():
    before = reconcile.with_line_ids("s" * 64, _lines())
    after = reconcile.with_line_ids("s" * 64, [{"booking_date": "2026-04-01", "direction": "credit", "amount": "9.00"}, *_lines()])
    assert [x["id"] for x in before] == [x["id"] for x in after[1:]]


def test_identical_lines_get_their_occurrence():
    ids = [x["id"] for x in reconcile.with_line_ids("s" * 64, _lines())]
    assert len(set(ids)) == 3 and ids[1].rsplit(":", 1)[0] == ids[2].rsplit(":", 1)[0]
    assert ids[1].endswith(":0") and ids[2].endswith(":1")


# --- the store adapter ---------------------------------------------------------------------------------------------


def _doc(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()


def _save(name: str, doc_type: str, fields: dict, validation: list | None = None) -> str:
    doc = _doc(name)
    store.upsert_document(doc_id=doc, source_path=f"C:/synthetic/{name}.pdf", has_text=True, page_count=1, year=2026,
                          doc_type=doc_type, run_id=f"cli-{name}")
    store.insert_datapoints(run_id=f"cli-{name}", doc_id=doc, doc_type=doc_type, arm="S", datapoints=fields, field_conf={},
                            validation=validation or [], route="auto", review_reasons=[], final_status="done")
    return doc


VERIFIED = [{"name": "closing_balance_check", "ok": True, "code": "closing.ok"},
            {"name": "totals_consistency", "ok": True, "code": "totals.ok"}]


def test_the_store_snapshot_pairs_an_invoice_with_its_line(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        inv = _save("invoice", "invoice_hu", {"invoice_number": "INV-0001", "supplier_name": "Example Supplier Kft.",
                                              "payment_iban": "99998887-77776666-55554444", "gross_total": "100.00",
                                              "amount_due": "0", "currency": "HUF", "issue_date": "2026-04-01",
                                              "due_date": "2026-04-15"})
        st = _save("statement", "statement_cib", {
            "account_no": "11112223-33334444-55556666", "currency": "HUF", "statement_type": "bank_account",
            "period_start": "2026-03-01", "period_end": "2026-06-30",
            "transactions": [{"booking_date": "2026-04-10", "direction": "debit", "amount": "100.00",
                              "counterparty_name": "Example Supplier", "counterparty_account": "99998887-77776666-55554444"}]},
            VERIFIED)
        snap = reconcile.snapshot()
        assert snap["invoices"][0]["amount"] == "100.00"  # a zero amount due falls back to the gross total
        assert snap["statements"][0]["verified"] is True
        result = reconcile.propose(snap)
        assert [(c["invoice_id"], c["statement_id"], c["proposed"]) for c in result["candidates"]] == [(inv, st, True)]
        summary = reconcile.scan()
        assert summary["proposed_pairs"] == 1 and summary["invoice_status"] == {"proposed": 1}
        assert summary["statements"] == summary["verified_statements"] == 1 and summary["lines"] == 1


def test_the_store_snapshot_drops_the_repeat_of_a_confirmed_copy(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        fields = {"invoice_number": "INV-0001", "supplier_name": "Example Supplier Kft.", "gross_total": "100.00",
                  "currency": "HUF", "issue_date": "2026-04-01"}
        first, repeat = _save("first", "invoice_hu", fields), _save("repeat", "invoice_hu", fields)
        with store.connect() as c:
            c.execute("INSERT INTO duplicate_decisions(pair_key, doc_id, other_doc_id, decision, actor, decided_at)"
                      " VALUES (?,?,?,?,?,?)", (f"{first}|{repeat}", repeat, first, "copy", "t", "2026-10-08T10:00:00+00:00"))
        result = reconcile.propose(reconcile.snapshot())
        assert [(e["id"], e["reason"]) for e in result["excluded"]] == [(repeat, "duplicate_copy")]


def test_a_persons_correction_is_the_invoices_value(tmp_path):
    from jav import corrections
    from tests.test_duplicates_126 import _id, _run
    from tests.test_duplicates_126 import _save as _save_in_run

    with store.use_store(tmp_path / "r.sqlite"):
        _run("run-1", ["invoice"])
        _save_in_run("invoice", {"invoice_number": "INV-0001", "supplier_name": "Unrelated Name Kft.", "gross_total": "999.00",
                                 "currency": "HUF", "issue_date": "2026-04-01"}, run_id="run-1")  # misread amount
        _save("statement", "statement_cib", {
            "account_no": "11112223-33334444-55556666", "currency": "HUF", "period_start": "2026-03-01", "period_end": "2026-06-30",
            "transactions": [{"booking_date": "2026-04-10", "direction": "debit", "amount": "100.00", "memo": "INV-0001"}]},
            VERIFIED)
        assert [c["proposed"] for c in reconcile.propose(reconcile.snapshot())["candidates"]] == [False]
        corrections.save("run-1", _id("invoice"), fields={"gross_total": "100"}, expected_revision=0, actor="t")
        assert [c["proposed"] for c in reconcile.propose(reconcile.snapshot())["candidates"]] == [True]


@pytest.mark.parametrize(("amount", "reason"), [(None, "missing_amount"), ("", "missing_amount"), ("1 000", "invalid_amount"),
                                                ("0", "non_positive_amount"), ("100.00", None)])
def test_every_unusable_amount_names_its_reason(amount, reason):
    snap = copy.deepcopy(CASES["one_payment"]["snapshot"])
    snap["invoices"][0]["amount"] = amount
    excluded = [e["reason"] for e in reconcile.propose(snap)["excluded"] if e["kind"] == "invoice"]
    assert excluded == ([reason] if reason else [])
