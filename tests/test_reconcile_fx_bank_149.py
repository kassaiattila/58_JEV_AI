"""149 (backlog F-outgoing-fx; DECISIONS 149): a forint bank line and an invoice in another currency.

The 22 foreign-currency outgoing invoices of the store (11 in francs, 11 in dollars) are paid into a forint account.
Measured on their 11 named payments of 2022-2026: a Hungarian buyer pays the forint value at the MNB rate of the
invoice's fulfilment day (5 of 5 to the forint), and a bank converts foreign money at its own rate on the booking day
(6 of 6 within 0.6-1.1% below the MNB rate); at the issue day's rate, as a card line is compared, they scatter from -6%
to +4%. So a forint bank line is compared at the rate of the fulfilment day, then of the booking day, each with its own
band (`policy.json` `reconcile.fx_bank_tolerance`), in the invoice's payment window; CHF is handled, and the forint bank
accounts count in such an invoice's coverage. A card line is compared as before.

Synthetic documents, made-up accounts and invented rates only; no AI call, no network.
"""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal

from jav import policy
from jav.domains.finance import reconcile

CASES = {c["id"]: c for c in reconcile.golden_cases()}


def _candidate(case: str, **line) -> dict:
    snap = copy.deepcopy(CASES[case]["snapshot"])
    snap["statements"][0]["lines"][0].update(line)
    [cand] = reconcile.propose(snap)["candidates"]
    return cand


def test_the_golden_cases_pass():
    score = reconcile.golden_score()
    assert score["failures"] == {} and score["passed"] == score["total"]


def test_the_fulfilment_days_rate_comes_first():
    cand = _candidate("fx_bank_fulfilment_rate")
    assert cand["proposed"] and cand["fx"]["basis"] == "fulfillment"
    assert cand["fx"]["rate_day"] == "2026-03-20" and cand["fx"]["converted"] == "368160.00" and cand["fx"]["deviation"] == "0.0000"


def test_the_booking_days_rate_when_the_fulfilment_days_is_outside_its_band():
    cand = _candidate("fx_bank_booking_rate")
    assert cand["proposed"] and cand["fx"]["basis"] == "booking" and cand["fx"]["deviation"] == "-0.0080"


def test_outside_both_bands_the_nearest_conversion_is_shown():
    cand = _candidate("fx_bank_outside")
    assert not cand["proposed"] and cand["amount_relation"] == "fx_outside"
    assert cand["fx"]["basis"] == "booking" and cand["fx"]["deviation"] == "-0.0909"


def test_the_bands_come_from_the_policy():
    assert policy.reconcile_fx_bank_tolerance("fulfillment") == (Decimal("0.005"), Decimal("0.005"))
    assert policy.reconcile_fx_bank_tolerance("booking") == (Decimal("0.02"), Decimal("0.02"))
    # just outside the fulfilment day's band and the booking day's: not proposed
    cand = _candidate("fx_bank_fulfilment_rate", amount="375700.00")  # +2.05% / +3.50%
    assert not cand["proposed"] and cand["amount_relation"] == "fx_outside"


def test_without_the_fulfilment_day_the_issue_day_is_used():
    snap = copy.deepcopy(CASES["fx_bank_fulfilment_rate"]["snapshot"])
    snap["invoices"][0]["fulfillment_date"] = None
    snap["fx_rates"]["USD"]["2026-04-01"] = {"rate": "368.16", "rate_day": "2026-04-01", "source": "mnb"}
    [cand] = reconcile.propose(snap)["candidates"]
    assert cand["proposed"] and cand["fx"]["basis"] == "fulfillment" and cand["fx"]["rate_day"] == "2026-04-01"


def test_a_card_line_is_compared_as_before():
    snap = copy.deepcopy(CASES["fx_card_within"]["snapshot"])
    [cand] = reconcile.propose(snap)["candidates"]
    assert cand["proposed"] and "basis" not in cand["fx"] and cand["fx"]["rate_day"] == "2026-04-01"
    assert reconcile.meets(snap["invoices"][0], {**snap["statements"][0]["lines"][0], "currency": "HUF",
                                                  "statement_type": "credit_card"}) == "fx"


def test_francs_are_handled():
    assert "CHF" in reconcile._conf()["currencies"]
    result = reconcile.propose(copy.deepcopy(CASES["fx_bank_booking_rate"]["snapshot"]))
    assert result["excluded"] == []


def test_the_snapshot_asks_for_the_fulfilment_and_the_booking_days():
    invoices = [{"currency": "CHF", "issue_date": "2026-04-01", "fulfillment_date": "2026-03-31"},
                {"currency": "HUF", "issue_date": "2026-04-02"},
                {"currency": "USD", "issue_date": "2026-04-03"}]
    statements = [{"statement_type": "bank_account", "currency": "HUF", "lines": [{"booking_date": "2026-04-10"}]},
                  {"statement_type": "bank_account", "currency": "EUR", "lines": [{"booking_date": "2026-04-11"}]}]
    assert reconcile.bank_rate_needs(invoices, statements) == {
        ("CHF", date(2026, 3, 31)), ("USD", date(2026, 4, 3)), ("CHF", date(2026, 4, 10)), ("USD", date(2026, 4, 10))}
    assert reconcile.bank_rate_needs(invoices, statements[1:]) == set()  # no forint bank account


def test_a_forint_bank_account_covers_a_foreign_invoice():
    snap = copy.deepcopy(CASES["fx_bank_fulfilment_rate"]["snapshot"])
    snap["statements"][0]["lines"] = []
    [status] = reconcile.propose(snap)["invoices"]
    assert status["status"] == "no_payment_found"  # before 149: not_covered (no dollar account)


def test_outside_its_band_a_converted_bank_line_is_listed_only_when_it_names_the_invoice():
    # a payment service converting above the MNB rate, tied by a name alone: 56 such listings on the store before
    cand = _candidate("fx_bank_outside")  # the line names INV-0001
    assert cand["amount_relation"] == "fx_outside"
    snap = copy.deepcopy(CASES["fx_bank_outside"]["snapshot"])
    snap["statements"][0]["lines"][0]["memo"] = "Payment"
    assert reconcile.propose(snap)["candidates"] == []
    snap["statements"][0]["lines"][0]["amount"] = "368160.00"  # within the band a name is enough, as in one currency
    [cand] = reconcile.propose(snap)["candidates"]
    assert cand["proposed"] and cand["signals"] == ["supplier_name"]


def test_the_forint_account_covers_only_an_outgoing_invoice_in_another_currency():
    snap = copy.deepcopy(CASES["fx_bank_debit_incoming"]["snapshot"])
    snap["statements"][0]["lines"] = []
    [status] = reconcile.propose(snap)["invoices"]
    assert status["status"] == "not_covered"  # incoming: its card and euro accounts, as before 149
