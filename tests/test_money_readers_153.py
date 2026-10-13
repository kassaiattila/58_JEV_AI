"""153 (review A6): the stored amounts are read one way, and a statement amount is not rounded without a word.

The reconciliation views each had their own reader of a stored amount: some took "NaN", "Infinity" or "1E+3", one read
"12,5" as zero, and a rest of zero reached the AI's question as "" (a zero Decimal is falsy). The statement readers
rounded an amount with a non-zero digit beyond its cents ("10.005" became 10.00, "1.234,567" 1234.57), while the comma
reader refused it. Synthetic values only.
"""

from decimal import Decimal

import pytest

from jav import reconcile, reconcile_ai, reconcile_overview, reconcile_review, reconcile_statement, statement_table as st


@pytest.mark.parametrize("text", ["NaN", "Infinity", "1E+3", "12,5", "", None, "abc"])
def test_a_stored_amount_that_is_no_plain_decimal_is_none(text):
    assert reconcile.decimal_or_none(text) is None
    assert reconcile_overview._money(text) is None and reconcile_statement._money(text) is None
    assert reconcile_review._money(text) == Decimal(0)  # the review's sums take a missing amount as zero, as before


def test_a_plain_stored_amount_is_read_exactly():
    assert [reconcile.decimal_or_none(v) for v in ("1234.50", "-12.5", "0.00", "1.2345", 7)] == [
        Decimal("1234.50"), Decimal("-12.5"), Decimal("0.00"), Decimal("1.2345"), Decimal(7)]


def test_a_rest_of_zero_reaches_the_question_as_zero():
    assert reconcile_ai._payment({"rest": "0.00", "currency": "HUF"})["amount"] == "0.00"


@pytest.mark.parametrize("reader,text", [(st._xml_amount, "10.005"), (st._dot_amount, "12.345"), (st._money, "1.234,567")])
def test_a_statement_amount_beyond_its_cents_is_unreadable_not_rounded(reader, text):
    assert reader(text) is None


def test_trailing_zeros_beyond_the_cents_are_kept_exact():
    assert st._xml_amount("10.000") == Decimal("10.00") and st._dot_amount("7291.50") == Decimal("7291.50")
