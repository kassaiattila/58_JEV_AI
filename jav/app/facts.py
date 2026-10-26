"""What is assessed, and with which facts (231, stage D, D-b3; the reassessment after D0 of 2026-10-26, P05, P06).

Plain-language summary: a fact catalogue names the levels of what a process assesses (for property: the policyholder,
its sites, their asset groups) and each fact a rule may read: its type, its unit or currency, its level and the codes
it may take, and each outcome a rule may give with how the outcomes of several rules combine. It is a rule file
(`configs/facts_<id>.json`), so a case reads it as it started. An assessed unit has a durable id, its level and its
parent, its facts typed by the catalogue, and for each fact the source claim it came from: the value, its original
form, where it was read, how sure the reading was and which reading or correction made it. The checked input is the set
of units a person accepted, with the product version it is assessed for and the day cover starts; it never changes (a
later correction makes a new one). A wrong unit, currency, level, code or parent is refused with what is wrong.

- `catalogue(id)`: the catalogue (`Catalogue`: `levels`, `facts`, `outcomes`).
- `checked_input(data)`: the checked input with every fact typed (`FactError`: what is wrong; a malformed one is a
  pydantic `ValidationError`).
- `typed_fact(catalogue, name, level, value)`: one fact's value as its type (`jav.core.measures`, a code, a day, ...).

Layer: application; it names no process and no business (a catalogue is data).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from jav.core import cfg
from jav.core.measures import Money, PerMille, Percentage, Quantity
from jav.core.versions import AT

__all__ = ["Catalogue", "CheckedInput", "FactDef", "FactError", "OutcomeDef", "SourceClaim", "Unit", "catalogue",
           "checked_input", "typed_fact", "typed_value"]

FactType = Literal["money", "quantity", "code", "codes", "bool", "date", "count", "decimal", "percentage", "permille", "text"]


class FactError(ValueError):
    """A fact that does not fit its catalogue: an unknown one, another unit, currency, level or code, a wrong parent."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FactDef(_Model):
    type: FactType
    level: str
    title: str
    unit: str | None = None
    currency: str | None = None
    options: tuple[str, ...] | None = None


class OutcomeDef(_Model):
    type: FactType
    title: str
    combine: Literal["worst", "max", "min", "union", "one"]
    currency: str | None = None
    unit: str | None = None
    options: tuple[str, ...] | None = None  # for `worst`: from the best to the worst


class Catalogue(_Model):
    id: str
    version: str
    levels: tuple[str, ...]
    facts: dict[str, FactDef]
    outcomes: dict[str, OutcomeDef]

    @model_validator(mode="after")
    def _consistent(self) -> Catalogue:
        for name, f in self.facts.items():
            if f.level not in self.levels:
                raise ValueError(f"fact {name}: no level {f.level!r}")
            if (f.type == "money") != (f.currency is not None) or (f.type == "quantity") != (f.unit is not None):
                raise ValueError(f"fact {name}: money names its currency and a quantity its unit")
        for name, o in self.outcomes.items():
            if o.combine == "worst" and not o.options:
                raise ValueError(f"outcome {name}: the worst of what - it names its options from the best")
        return self


def catalogue(catalogue_id: str) -> Catalogue:
    """The fact catalogue `catalogue_id` (`configs/facts_<id>.json`, read as the case at hand keeps it)."""
    data = cfg.load(f"facts_{catalogue_id}")
    return Catalogue(id=catalogue_id, version=str(data["meta"]["version"]), levels=tuple(data["levels"]),
                     facts=data["facts"], outcomes=data.get("outcomes") or {})


def _article(word: str) -> str:
    return f"an {word}" if word[:1] in "aeiou" else f"a {word}"


def _exact(name: str, value: Any) -> Decimal:
    if isinstance(value, (bool, float)):
        raise FactError(f"{name} is given as text or a whole number")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise FactError(f"{name} is a number, not {value!r}") from None
    if not number.is_finite():
        raise FactError(f"{name} is a finite number")
    return number


def typed_fact(cat: Catalogue, name: str, level: str, value: Any) -> Any:
    """One fact's value as its catalogue types it."""
    d = cat.facts.get(name)
    if d is None:
        raise FactError(f"no fact {name} in the catalogue {cat.id}")
    if d.level != level:
        raise FactError(f"{name} is a fact of {_article(d.level)}, not of {_article(level)}")
    try:
        return _typed(name, d, value)
    except ValidationError as exc:
        raise FactError(f"{name} does not fit its type {d.type}: {exc.errors()[0]['msg']}") from None


def typed_value(name: str, d: FactDef | OutcomeDef, value: Any) -> Any:
    """D-c1: a value as a fact's or an outcome's definition types it (a rule's comparison, an outcome it gives)."""
    try:
        return _typed(name, d, value)
    except ValidationError as exc:
        raise FactError(f"{name} does not fit its type {d.type}: {exc.errors()[0]['msg']}") from None


def _typed(name: str, d: FactDef | OutcomeDef, value: Any) -> Any:
    if d.type == "money":
        money = value if isinstance(value, Money) else Money.model_validate(value)
        if money.currency != d.currency:
            raise FactError(f"{name} is in {d.currency}, not {money.currency}")
        return money
    if d.type == "quantity":
        quantity = value if isinstance(value, Quantity) else Quantity.model_validate(value)
        if quantity.unit != d.unit:
            raise FactError(f"{name} is in {d.unit}, not {quantity.unit}")
        return quantity
    if d.type == "percentage":
        return value if isinstance(value, Percentage) else Percentage.model_validate(value)
    if d.type == "permille":
        return value if isinstance(value, PerMille) else PerMille.model_validate(value)
    if d.type == "bool":
        if not isinstance(value, bool):
            raise FactError(f"{name} is true or false")
        return value
    if d.type == "count":
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise FactError(f"{name} is a whole number, zero or more")
        return value
    if d.type == "decimal":
        return _exact(name, value)
    if d.type == "date":
        try:
            return value if isinstance(value, date) else date.fromisoformat(str(value))
        except ValueError:
            raise FactError(f"{name} is a day (YYYY-MM-DD)") from None
    if d.type in ("code", "text"):
        if not isinstance(value, str) or not value.strip():
            raise FactError(f"{name} is a text")
        if d.options is not None and value not in d.options:
            raise FactError(f"{name} is one of {', '.join(d.options)}")
        return value
    codes = tuple(value) if isinstance(value, (list, tuple)) else None  # codes
    if codes is None or not all(isinstance(c, str) and c for c in codes):
        raise FactError(f"{name} is a list of codes")
    if d.options is not None and (wrong := [c for c in codes if c not in d.options]):
        raise FactError(f"{name} takes {', '.join(d.options)}, not {', '.join(wrong)}")
    return codes


class SourceRef(_Model):
    item: str
    file: str | None = None
    page: int | None = None
    quote: str | None = None


class Uncertainty(_Model):
    verdict: str | None = None
    confidence: Decimal | None = None
    open_reasons: tuple[str, ...] = ()


class Interpretation(_Model):
    reading: str  # the type pack (or other reading) and its version that made the value
    correction_revision: int | None = None  # a person's correction, by the revision that recorded it


class SourceClaim(_Model):
    """Where a fact came from: the value as read, its original form, its source, how sure, which reading made it."""

    value: Any
    original: str | None = None
    source: SourceRef
    uncertainty: Uncertainty = Uncertainty()
    interpretation: Interpretation


class Unit(_Model):
    """An assessed unit: a durable id, its level and its parent, its facts and their sources."""

    unit_id: str = Field(pattern=r"^u-[0-9a-f]{10}$")
    level: str
    parent_id: str | None = None
    facts: dict[str, Any] = Field(default_factory=dict)
    sources: dict[str, SourceClaim] = Field(default_factory=dict)


class CheckedInput(_Model):
    """The units a person accepted, for one product version, from the day cover starts."""

    form: Literal["checked_input/1"] = "checked_input/1"
    catalogue: str
    product: str = Field(pattern=rf"^[^{AT}\s]+{AT}[1-9][0-9]*$")
    cover_start: date
    units: tuple[Unit, ...]


def checked_input(data: Any) -> CheckedInput:
    """The checked input with every fact typed by its catalogue; `FactError` with what is wrong."""
    raw = data if isinstance(data, CheckedInput) else CheckedInput.model_validate(data)
    cat = catalogue(raw.catalogue)
    levels = {u.unit_id: u.level for u in raw.units}
    units = []
    for unit in raw.units:
        if unit.level not in cat.levels:
            raise FactError(f"unit {unit.unit_id}: no level {unit.level!r} in the catalogue {cat.id}")
        rank = cat.levels.index(unit.level)
        if unit.parent_id is None:
            if rank:
                raise FactError(f"{_article(unit.level)} has a parent, {_article(cat.levels[rank - 1])}")
        elif unit.parent_id not in levels:
            raise FactError(f"unit {unit.unit_id} names no unit {unit.parent_id} as its parent")
        elif not rank or levels[unit.parent_id] != cat.levels[rank - 1]:
            above = cat.levels[rank - 1] if rank else "none"
            raise FactError(f"{_article(unit.level)}'s parent is {_article(above)}, not {_article(levels[unit.parent_id])}")
        typed = {name: typed_fact(cat, name, unit.level, value) for name, value in unit.facts.items()}
        units.append(unit.model_copy(update={"facts": typed}))
    return raw.model_copy(update={"units": tuple(units)})
