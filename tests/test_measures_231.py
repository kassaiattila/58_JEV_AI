"""231 (stage D, D-b1; the reassessment after D0 of 2026-10-26, P05): typed values a result hands on.

An amount of money is never a bare number: it carries its currency, sums only with the same currency, and rounds by a
named unit and mode. A quantity carries its unit, a rate says whether it is per hundred or per thousand (and the two do
not mix), and a validity names the days a version applies from and to. Each round-trips through JSON exactly (an
amount as text), and a float, NaN or infinity is refused. Synthetic values.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from jav.core import measures
from jav.core.measures import CurrencyMismatch, Money, Percentage, PerMille, Quantity, Rounding, Validity


def test_money_round_trips_through_json_exactly() -> None:
    m = Money(amount="1234.50", currency="HUF")
    assert m.model_dump(mode="json") == {"amount": "1234.50", "currency": "HUF"}
    assert Money.model_validate_json(m.model_dump_json()) == m


@pytest.mark.parametrize("bad", [0.1, "NaN", "Infinity", "-inf", "1e3x"])
def test_an_amount_is_never_a_float_nan_or_infinity(bad) -> None:
    with pytest.raises(ValidationError):
        Money(amount=bad, currency="HUF")


def test_a_currency_is_three_capital_letters() -> None:
    with pytest.raises(ValidationError):
        Money(amount="1", currency="huf")


def test_amounts_add_and_compare_only_in_one_currency() -> None:
    a, b = Money(amount="100", currency="HUF"), Money(amount="50.5", currency="HUF")
    assert (a + b).amount == Decimal("150.5") and (a - b).amount == Decimal("49.5") and b < a
    with pytest.raises(CurrencyMismatch):
        a + Money(amount="1", currency="EUR")
    with pytest.raises(CurrencyMismatch):
        _ = a < Money(amount="1", currency="EUR")


@pytest.mark.parametrize(("amount", "unit", "mode", "expected"), [
    ("1234.5", "1", "half_up", "1235"),
    ("1234.5", "1", "half_even", "1234"),
    ("1234.49", "1", "half_up", "1234"),
    ("12.345", "0.01", "half_up", "12.35"),
    ("12.349", "0.01", "down", "12.34"),
    ("1250", "100", "half_up", "1300"),
    ("1249", "100", "half_up", "1200"),
])
def test_rounding_by_a_named_unit_and_mode(amount, unit, mode, expected) -> None:
    rounded = Money(amount=amount, currency="HUF").rounded(Rounding(unit=unit, mode=mode))
    assert rounded.model_dump(mode="json")["amount"] == expected


def test_a_rate_of_money_is_unrounded_and_the_two_rates_do_not_mix() -> None:
    sum_insured = Money(amount="80000000", currency="HUF")
    assert PerMille(value="1.25").of(sum_insured) == Money(amount="100000", currency="HUF")
    assert Percentage(value="12.5").of(Money(amount="1001", currency="HUF")).amount == Decimal("125.125")

    class Tariff(BaseModel):
        rate: PerMille

    with pytest.raises(ValidationError):
        Tariff(rate=Percentage(value="1.25"))
    with pytest.raises(ValidationError):
        Tariff.model_validate({"rate": Percentage(value="1.25").model_dump(mode="json")})  # per 100 is not per 1000
    assert Tariff.model_validate({"rate": {"value": "1.25", "per": 1000}}).rate == PerMille(value="1.25")


def test_a_quantity_names_its_unit() -> None:
    area = Quantity(value="420", unit="m2")
    assert area.model_dump(mode="json") == {"value": "420", "unit": "m2"}
    with pytest.raises(ValidationError):
        Quantity(value="420", unit="sqm")


def test_a_validity_covers_its_days() -> None:
    v = Validity(valid_from=date(2026, 1, 1), valid_to=date(2026, 12, 31))
    assert v.covers(date(2026, 6, 1)) and not v.covers(date(2027, 1, 1)) and not v.covers(date(2025, 12, 31))
    assert Validity(valid_from=date(2026, 1, 1)).covers(date(2030, 1, 1))
    with pytest.raises(ValidationError):
        Validity(valid_from=date(2026, 2, 1), valid_to=date(2026, 1, 1))


def test_the_module_names_no_business() -> None:
    text = measures.__file__ and open(measures.__file__, encoding="utf-8").read().lower()
    assert not any(word in text for word in ("insurance", "quote", "premium", "tariff", "invoice"))
