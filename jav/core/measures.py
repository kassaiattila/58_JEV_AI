"""Typed values a result hands on (231, stage D, D-b1; the reassessment after D0 of 2026-10-26, P05).

Plain-language summary: an amount of money is never a bare number. It carries its currency, sums and compares only
with the same currency, and is rounded by a named unit and mode, once, where the rule says. A quantity carries its
unit; a rate says whether it is per hundred or per thousand, and the two never mix; a validity names the days a version
applies from and to. Each round-trips through JSON exactly (an amount as text), and a float, NaN or infinity is
refused, so an amount is never read approximately.

- `Money(amount, currency)`: `+`, `-` and comparisons within one currency (`CurrencyMismatch` otherwise); `times(n)`
  unrounded; `rounded(Rounding)`.
- `Rounding(unit, mode)`: the unit ("1", "0.01", "100") and `half_up`, `half_even` or `down`.
- `Quantity(value, unit)`: a unit of a closed list.
- `Percentage(value)`, `PerMille(value)`: a rate (`per` 100 or 1000 in JSON); `of(money)` is unrounded.
- `Validity(valid_from, valid_to)`: `covers(day)`.

Layer: shared core; it names no business and imports nothing of the application.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

__all__ = ["CurrencyMismatch", "Money", "PerMille", "Percentage", "Quantity", "Rate", "Rounding", "UNITS", "Validity"]

UNITS = ("m2", "m3", "piece", "year", "day", "kWh")
_MODES = {"half_up": ROUND_HALF_UP, "half_even": ROUND_HALF_EVEN, "down": ROUND_DOWN}


class CurrencyMismatch(ValueError):
    """Two amounts of different currencies summed or compared."""


def _exact(value: Any) -> Decimal:
    """A finite decimal from text, an integer or a decimal; a float (approximate), NaN or infinity is refused."""
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("an amount is given as text or a whole number, never as a float")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"not a number: {value!r}") from None
    if not number.is_finite():
        raise ValueError("an amount is finite")
    return number


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Rounding(_Frozen):
    unit: Decimal
    mode: Literal["half_up", "half_even", "down"] = "half_up"

    _unit = field_validator("unit", mode="before")(lambda cls, v: _exact(v))

    @field_validator("unit")
    @classmethod
    def _positive(cls, unit: Decimal) -> Decimal:
        if unit <= 0:
            raise ValueError("a rounding unit is above zero")
        return unit

    @field_serializer("unit")
    def _text(self, unit: Decimal) -> str:
        return str(unit)

    def apply(self, value: Decimal) -> Decimal:
        steps = (value / self.unit).quantize(Decimal(1), rounding=_MODES[self.mode])
        out = steps * self.unit
        return out.quantize(self.unit) if self.unit.as_tuple().exponent < 0 else out.quantize(Decimal(1))


class Money(_Frozen):
    amount: Decimal
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    _amount = field_validator("amount", mode="before")(lambda cls, v: _exact(v))

    @field_serializer("amount")
    def _text(self, amount: Decimal) -> str:
        return str(amount)

    def _same(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise TypeError(f"an amount of money with {type(other).__name__}")
        if other.currency != self.currency:
            raise CurrencyMismatch(f"{self.currency} with {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._same(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __lt__(self, other: Money) -> bool:
        self._same(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._same(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._same(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._same(other)
        return self.amount >= other.amount

    def times(self, factor: Decimal | int | str) -> Money:
        """The amount times a factor, unrounded."""
        return Money(amount=self.amount * _exact(factor), currency=self.currency)

    def rounded(self, rounding: Rounding) -> Money:
        return Money(amount=rounding.apply(self.amount), currency=self.currency)


class Quantity(_Frozen):
    value: Decimal
    unit: Literal["m2", "m3", "piece", "year", "day", "kWh"]

    _value = field_validator("value", mode="before")(lambda cls, v: _exact(v))

    @field_serializer("value")
    def _text(self, value: Decimal) -> str:
        return str(value)


class Rate(_Frozen):
    """A rate per `per` (100 or 1000); the subclasses fix it, so a per-thousand rate is never read as a percentage."""

    value: Decimal
    per: int

    _value = field_validator("value", mode="before")(lambda cls, v: _exact(v))

    @field_serializer("value")
    def _text(self, value: Decimal) -> str:
        return str(value)

    def of(self, money: Money) -> Money:
        """The rate of an amount, unrounded."""
        return money.times(self.value / Decimal(self.per))


class Percentage(Rate):
    per: Literal[100] = 100


class PerMille(Rate):
    per: Literal[1000] = 1000


class Validity(_Frozen):
    valid_from: date
    valid_to: date | None = None

    @model_validator(mode="after")
    def _ordered(self) -> Validity:
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("a validity ends on or after its start")
        return self

    def covers(self, day: date) -> bool:
        return self.valid_from <= day and (self.valid_to is None or day <= self.valid_to)
