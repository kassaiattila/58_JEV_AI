"""265 (code review APPR-07): a document's number becomes a fact through the shared number reader.

The fact readings read a number by dropping spaces and turning a comma into a point: "1.500" became 1.5 HUF and
"1.500.000" was refused. Now a value in the machine's own form (digits, at most two decimals after a point) is taken
as it is, any other through `numbers.read_number` (a money amount never has three decimals, so "1.500" is 1 500), and a
number its separators let be read two ways goes to a person instead of becoming a fact. Real catalogue; no paid call.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from jav.app import facts, fact_readings

CAT = facts.catalogue("property")


@pytest.mark.parametrize(("raw", "amount"), [
    ("1.500", "1500"), ("1.500.000", "1500000"), ("1 500 000", "1500000"), ("1500000", "1500000"),
    ("12000000.00", "12000000.00"), ("1.234,56", "1234.56"), (Decimal("250000"), "250000"), (250000, "250000"),
])
def test_a_money_amount_is_read_as_the_shared_reader_reads_it(raw, amount) -> None:
    value, why = fact_readings._typed(CAT, "sum_insured", raw, "HUF")
    assert why is None and value == {"amount": amount, "currency": "HUF"}


def test_a_number_that_reads_two_ways_goes_to_a_person() -> None:
    value, why = fact_readings._typed(CAT, "claims_5y_count", "1.500", None)
    assert value is None and why == "the number can be read two ways; a person checks it"


def test_text_that_is_no_number_is_still_refused() -> None:
    assert fact_readings._typed(CAT, "sum_insured", "sok", "HUF") == (None, "not an amount")
