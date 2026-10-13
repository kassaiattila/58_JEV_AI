"""154: an amount whose separator is ambiguous is confirmed by the invoice's own totals.

A dollar invoice prints its VAT total without a thousands group ("486.00"), so the shared number reader cannot tell an
English decimal point from a malformed thousands group, and the S path opened a "separator ambiguous" to-do on 11 of
the 43 real outgoing invoices of the 2026-10-12 measurement. On every one of them the net and the gross total were
printed unambiguously ("1,800.00", "2,286.00") and net + VAT = gross to the last cent. When the pack's sum check holds
exactly and at least one other term is read unambiguously and is not zero, the reading is confirmed and no to-do is
raised; with every term flagged, a reading scaled the same way would add up too, so the to-do stays. The reader's flag
and the option text sent to JEV are unchanged (no new cache key). Synthetic values only, no model calls.
"""

from decimal import Decimal

import pytest

from jav import validators
from jav.jev_select import site_for
from jav.models import Candidate, FieldPick

VAT_SUM = ({"check": "vat_consistency"},)


def _pick(field: str, label: str, raw: str) -> FieldPick:
    return FieldPick(field=field, label=label, raw=raw, confidence=0.9, n_options=3, request_id="money")


def _totals(net: tuple[str, str, bool], vat: tuple[str, str, bool], gross: tuple[str, str, bool]) -> list[str]:
    """(label, printed form, flagged) per total; returns the S path's reasons for the outgoing invoice pack."""
    picks, cands = {}, []
    for no, (field, (label, raw, flagged)) in enumerate({"net_total": net, "vat_total": vat, "gross_total": gross}.items(), 1):
        picks[field] = _pick(field, label, raw)
        cands.append(Candidate(kind="money", label=label, raw=raw, line_no=no, context=f"L{no:02d}", ambiguous=flagged))
    _, reasons = site_for("invoice_out").picks_to_invoice(picks, {"money": cands})
    return [r for r in reasons if r.startswith("money:separator_ambiguous")]


def test_an_ambiguous_vat_total_confirmed_by_exact_totals_opens_no_to_do():
    assert _totals(("1800", "1,800.00", False), ("486", "486.00", True), ("2286", "2,286.00", False)) == []


def test_a_credit_note_with_negative_totals_is_confirmed_the_same_way():
    assert _totals(("-1800", "-1,800.00", False), ("-486", "-486.00", True), ("-2286", "-2,286.00", False)) == []


def test_totals_off_by_a_cent_keep_the_to_do():
    assert _totals(("1800", "1,800.00", False), ("486", "486.00", True), ("2286.01", "2,286.01", False)) == [
        "money:separator_ambiguous:vat_total:'486.00'"]


def test_every_term_flagged_keeps_every_to_do():
    # 100 + 27 = 127, but 10 000 + 2 700 = 12 700 as well: the sum cannot tell the two readings apart
    assert len(_totals(("100", "100.00", True), ("27", "27.00", True), ("127", "127.00", True))) == 3


def test_two_flagged_terms_are_confirmed_by_one_unambiguous_non_zero_term():
    assert _totals(("1800", "1,800.00", False), ("486", "486.00", True), ("2286", "2286.00", True)) == []


def test_the_only_unambiguous_term_being_zero_confirms_nothing():
    assert len(_totals(("12.5", "12.50", True), ("0", "0", False), ("12.5", "12.50", True))) == 2


def test_a_missing_total_confirms_nothing():
    picks = {"vat_total": _pick("vat_total", "486", "486.00"), "net_total": _pick("net_total", "1800", "1,800.00")}
    cands = [Candidate(kind="money", label="486", raw="486.00", line_no=1, context="L01", ambiguous=True),
             Candidate(kind="money", label="1800", raw="1,800.00", line_no=2, context="L02", ambiguous=False)]
    _, reasons = site_for("invoice_out").picks_to_invoice(picks, {"money": cands})
    assert "money:separator_ambiguous:vat_total:'486.00'" in reasons


@pytest.mark.parametrize(("values", "flagged", "expected"), [
    ({"net_total": Decimal("1800"), "vat_total": Decimal("486"), "gross_total": Decimal("2286")}, {"vat_total"}, {"vat_total"}),
    ({"net_total": Decimal("1800"), "vat_total": Decimal("486"), "gross_total": Decimal("2285")}, {"vat_total"}, set()),
    ({"net_total": None, "vat_total": Decimal("486"), "gross_total": Decimal("2286")}, {"vat_total"}, set()),
    ({"net_total": Decimal("100"), "vat_total": Decimal("27"), "gross_total": Decimal("127")},
     {"net_total", "vat_total", "gross_total"}, set()),
])
def test_confirmed_by_sum(values, flagged, expected):
    assert validators.confirmed_by_sum(values, flagged, VAT_SUM) == expected


def test_a_pack_without_the_sum_check_confirms_nothing():
    values = {"net_total": Decimal("1800"), "vat_total": Decimal("486"), "gross_total": Decimal("2286")}
    assert validators.confirmed_by_sum(values, {"vat_total"}, ({"check": "date_order"},)) == set()


def test_the_option_text_sent_to_jev_is_unchanged():
    cand = Candidate(kind="money", label="486", raw="486.00", line_no=1, context="L01", ambiguous=True)
    choice = site_for("invoice_out").build_choice("vat_total", [cand])
    assert choice.criteria["486"].endswith("(separator ambiguous)")
