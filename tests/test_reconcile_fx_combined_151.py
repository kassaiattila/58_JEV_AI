"""151 (backlog F-fx-combined-payment; DECISIONS 151): one forint bank line paying two invoices of another currency.

A buyer paid two franc invoices with one forint transfer naming both. Each alone is far from the line's amount, so 149's
comparison listed both outside the band and proposed neither; a combined payment was proposed only within one currency
(141). Now a forint bank line naming two or more invoices of one other currency is compared with their sum, converted
at the MNB rate of the fulfilment days, then of the booking day, each with its 149 band; within it the invoices are
proposed together. Allocating the group splits the line's forints in the ratio of the converted amounts. Synthetic
documents, made-up accounts and invented rates only; no AI call, no network.
"""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal

import pytest

from jav import parties
from jav.core import store
from jav.domains.finance import fx, reconcile
from jav.domains.finance import reconcile_package as rp
from tests import test_reconcile_k2_129 as k2
from tests.test_fx_130 import Service
from tests.test_reconcile_outgoing_148 import CLUB_TAX
from tests.test_reconcile_package_131 import OWN_KEY, _stmt
from tests.test_reconcile_package_131 import _line as _pkg_line

CASES = {c["id"]: c for c in reconcile.golden_cases()}


def _result(case: str, **line) -> dict:
    snap = copy.deepcopy(CASES[case]["snapshot"])
    snap["statements"][0]["lines"][0].update(line)
    return reconcile.propose(snap)


def _by_invoice(result: dict) -> dict:
    return {c["invoice_id"]: c for c in result["candidates"]}


def test_the_golden_cases_pass():
    score = reconcile.golden_score()
    assert score["failures"] == {} and score["passed"] == score["total"]


def test_two_franc_invoices_named_by_one_forint_line_are_proposed_together():
    got = _by_invoice(_result("fx_bank_combined"))
    assert [got[i]["proposed"] for i in ("i1", "i2")] == [True, True]
    assert {got[i]["amount_relation"] for i in ("i1", "i2")} == {"combined"}
    assert got["i1"]["combined"] == got["i2"]["combined"] == ["i1", "i2"]  # in the order of issue
    # each alone is outside both bands; together they are 0.8% below the booking day's rate
    assert got["i1"]["combined_fx"] == got["i2"]["combined_fx"] == {
        "basis": "booking", "converted": "2835000.00", "deviation": "-0.0080"}
    assert (got["i1"]["fx"]["converted"], got["i2"]["fx"]["converted"]) == ("2025000.00", "810000.00")
    assert got["i1"]["fx"]["basis"] == got["i2"]["fx"]["basis"] == "booking"


def test_the_fulfilment_days_rate_comes_first():
    got = _by_invoice(_result("fx_bank_combined", amount="2786000.00"))  # 7000 CHF x 398.00 exactly
    assert got["i1"]["proposed"] and got["i1"]["combined_fx"] == {"basis": "fulfillment", "converted": "2786000.00",
                                                                  "deviation": "0.0000"}


def test_a_sum_outside_both_bands_proposes_nothing():
    got = _by_invoice(_result("fx_bank_combined_outside"))
    assert not got["i1"]["proposed"] and not got["i2"]["proposed"]
    assert {got[i]["amount_relation"] for i in ("i1", "i2")} == {"fx_outside"}
    assert "combined" not in got["i1"] and "combined_fx" not in got["i1"]


def test_invoices_of_two_currencies_are_not_combined():
    snap = copy.deepcopy(CASES["fx_bank_combined"]["snapshot"])
    snap["invoices"][1]["currency"] = "USD"
    snap["fx_rates"]["USD"] = {"2026-04-01": {"rate": "360.00", "rate_day": "2026-04-01", "source": "mnb"},
                               "2026-04-20": {"rate": "362.00", "rate_day": "2026-04-20", "source": "mnb"}}
    assert not any(c["proposed"] for c in reconcile.propose(snap)["candidates"])


def test_without_a_rate_for_every_invoice_nothing_is_combined():
    snap = copy.deepcopy(CASES["fx_bank_combined"]["snapshot"])
    snap["fx_rates"] = {}
    got = _by_invoice(reconcile.propose(snap))
    assert {got[i]["amount_relation"] for i in ("i1", "i2")} == {"no_rate"} and not got["i1"]["proposed"]


def test_the_combined_conversion_keeps_each_invoices_share():
    invoices = [{"currency": "CHF", "amount": "5000.00", "fulfillment_date": "2026-04-01", "issue_date": "2026-04-01"},
                {"currency": "CHF", "amount": "2000.00", "fulfillment_date": "2026-04-03", "issue_date": "2026-04-03"}]
    line = {"amount": "2818000.00", "currency": "HUF", "booking_date": "2026-04-20"}
    rates = {"CHF": {d: {"rate": r, "rate_day": d, "source": "mnb"}
                     for d, r in (("2026-04-01", "398.00"), ("2026-04-03", "414.00"), ("2026-04-20", "405.00"))}}
    relation, conv = reconcile.convert_combined(invoices, line, rates)
    # each invoice at its own fulfilment day: 5000 x 398 + 2000 x 414 = 2818000
    assert relation == "fx_within" and conv["basis"] == "fulfillment" and conv["converted"] == "2818000.00"
    assert [p["rate_day"] for p in conv["parts"]] == ["2026-04-01", "2026-04-03"]
    assert reconcile.split_line(Decimal("2818000.00"), conv) == [Decimal("1990000.00"), Decimal("828000.00")]


def test_the_split_puts_the_rounding_on_the_last_invoice():
    conv = {"parts": [{"converted": "1000.00"}, {"converted": "1000.00"}, {"converted": "1000.00"}]}
    shares = reconcile.split_line(Decimal("100.00"), conv)
    assert shares == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")] and sum(shares) == Decimal("100.00")


RATES = {"2026-04-01": {"CHF": (1, "398,00")}, "2026-04-20": {"CHF": (1, "405,00")}}


@pytest.fixture
def package(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        with fx.use_transport(Service(RATES)):
            fx.fetch(date(2026, 4, 1), date(2026, 4, 20), ["CHF"])
        club = parties.create("Sporting Club", identities=[("tax", parties.tax_key(CLUB_TAX), CLUB_TAX),
                                                           ("name", "sporting club", "Sporting Club")], actor="t")["id"]
        common = {"supplier_name": "Sporting Club", "supplier_tax_id": CLUB_TAX, "buyer_name": "Northwind Trading Ltd.",
                  "currency": "CHF", "issue_date": "2026-04-01", "fulfillment_date": "2026-04-01", "due_date": "2026-05-01"}
        i1 = k2._save("o1", k2._invoice(number="OUT-1", amount="5000.00", **common), doc_type="invoice_out")
        i2 = k2._save("o2", k2._invoice(number="OUT-2", amount="2000.00", **common), doc_type="invoice_out")
        _stmt("stmt", _pkg_line(memo="OUT-1 OUT-2", amount="2812320.00", direction="credit", day="2026-04-20",
                                counterparty_name="Northwind Trading"))
        wp = rp.create(name="April", accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30", actor="reviewer",
                       party_id=club)["workpackage_id"]
        (line,) = rp.workspace(wp)["lines"]
        yield {"wp": wp, "i1": i1, "i2": i2, "line": line}


def test_the_package_accepts_the_combined_proposal_and_splits_the_line(package):
    line = package["line"]
    assert {c["invoice_id"]: c["amount_relation"] for c in line["candidates"]} == {package["i1"]: "combined",
                                                                                  package["i2"]: "combined"}
    assert all(c["combined_fx"]["basis"] == "booking" for c in line["candidates"])
    assert rp.accept_proposed(package["wp"], actor="reviewer") == 2
    ws = rp.workspace(package["wp"])
    (after,) = ws["lines"]
    assert sorted((s["invoice_id"], s["line_amount"], s["invoice_amount"]) for s in after["allocations"]) == sorted([
        (package["i1"], "2008800.00", "5000.00"), (package["i2"], "803520.00", "2000.00")])
    assert {i["id"]: i["state"] for i in ws["invoices"]} == {package["i1"]: "confirmed", package["i2"]: "confirmed"}


def test_a_combined_group_outside_the_band_needs_a_reason(package):
    pairs = [{"invoice_doc_id": package["i1"], "line_id": package["line"]["id"]}]
    with pytest.raises(rp.PackageError, match="whole"):  # one invoice alone takes the whole line: not a converted pair
        rp.allocate(package["wp"], pairs + [{"invoice_doc_id": package["i2"], "line_id": package["line"]["id"],
                                             "line_amount": "1.00"}], note=None, actor="reviewer")
    with store.connect() as c:  # the rates move: the group falls outside both bands
        c.execute("UPDATE fx_rates SET rate='300'")
    group = pairs + [{"invoice_doc_id": package["i2"], "line_id": package["line"]["id"]}]
    with pytest.raises(rp.PackageError, match="reason"):
        rp.allocate(package["wp"], group, note=None, actor="reviewer")
    assert len(rp.allocate(package["wp"], group, note="the bank's own rate", actor="reviewer")) == 2
