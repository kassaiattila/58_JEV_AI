"""152: a printed zero needs no separator check.

"0.00" reads as zero whichever of its separators is the decimal one, yet the shared number reader flags a dot with two
decimals as ambiguous, so every zero VAT total opened a "separator ambiguous" to-do: 22 to-dos on 11 of the 43 real
outgoing invoices of the S-path measurement of 2026-10-12, and a person typing "0.00" into a correction was refused.
The to-do and the manual input now let a zero through; a non-zero amount is flagged as before. The reader's flag itself
stays, because it is part of the option text a JEV question sends ("separator ambiguous"): changing it would give every
document with a printed zero a new cache key, so a paid re-measurement. Synthetic values only, no model calls.
"""

from decimal import Decimal

import pytest

from jav import numbers
from jav.jev_select import site_for
from jav.models import Candidate, FieldPick, normalize_value


def _picked(raw: str, label: str) -> tuple[Decimal | None, list[str]]:
    cand = Candidate(kind="money", label=label, raw=raw, line_no=1, context="L01", ambiguous=True)
    picks = {"vat_total": FieldPick(field="vat_total", label=label, raw=raw, confidence=0.9, n_options=1,
                                    request_id="money")}
    inv, reasons = site_for("invoice_out").picks_to_record(picks, {"money": [cand]})
    return inv.vat_total, reasons


@pytest.mark.parametrize("raw", ["0.00", "0.0", "0,000", "-0.00"])
def test_a_picked_zero_opens_no_separator_to_do(raw):
    value, reasons = _picked(raw, "0")
    assert value == Decimal("0")
    assert not [r for r in reasons if r.startswith("money:separator_ambiguous")]


def test_a_picked_non_zero_amount_with_the_same_notation_is_still_a_to_do():
    value, reasons = _picked("12.50", "12.5")
    assert value == Decimal("12.5")
    assert "money:separator_ambiguous:vat_total:'12.50'" in reasons


def test_the_option_text_sent_to_jev_is_unchanged():
    cand = Candidate(kind="money", label="0", raw="0.00", line_no=1, context="L01", ambiguous=True)
    assert numbers.read_number("0.00").ambiguous  # the reader's flag stays
    choice = site_for("invoice_out").build_choice("vat_total", [cand])
    assert choice.criteria["0"].endswith("(separator ambiguous)")


@pytest.mark.parametrize("raw", ["0.00", "0,000"])
def test_a_printed_zero_selected_on_the_page_is_read_without_a_to_do(raw):
    reasons: list[str] = []
    assert normalize_value("money", raw, "vat_total", reasons, origin="printed") == Decimal("0")
    assert reasons == []


def test_a_printed_non_zero_amount_selected_on_the_page_is_still_a_to_do():
    reasons: list[str] = []
    assert normalize_value("money", "12.50", "vat_total", reasons, origin="printed") == Decimal("12.50")
    assert reasons == ["money:separator_ambiguous:vat_total:'12.50'"]


@pytest.mark.parametrize("raw", ["0.00", "0,000", "0.0", "-0,00", "0"])
def test_a_typed_zero_is_accepted(raw):
    assert numbers.read_input(raw) == "0"


@pytest.mark.parametrize("raw", ["28.5", "28,000"])
def test_a_typed_ambiguous_non_zero_amount_is_still_refused(raw):
    with pytest.raises(numbers.AmbiguousNumber):
        numbers.read_input(raw)
