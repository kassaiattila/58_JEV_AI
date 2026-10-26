"""How a document's extracted values become facts of assessed units (231, stage D, D-e2).

Plain-language summary: a type pack reads a document into values as printed (a policyholder's name, a flood zone
"alacsony", an amount "80000000" with its currency "HUF"). An assessment works with facts of its catalogue, on units (a
policyholder, its sites, their asset groups). A versioned rule file (`configs/fact_readings_<catalogue>.json`, kept as
a case started) says, per type pack, which unit each value describes, how the unit is keyed by the document's own
values (a site by its number), and how a printed word becomes a catalogue code. This module applies it: the result is
the fact claims the field check places, each naming the document it came from, and what could not be read, with why:
a word no code table knows, an amount without its currency, a value that does not fit the fact's type. Nothing is
guessed. It decides nothing either: the field check shows a value that differs between two documents to a person.

- `Readings`, `load(name)`: the rule file, checked against its catalogue.
- `claims(readings, pack, values, *, source=, reading=)` -> (claims, unread).

Layer: application, code only; it names no business (the units, the codes and the words are data).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jav.app import facts
from jav.core import cfg

__all__ = ["FactSpec", "Readings", "UnitSpec", "claims", "load", "normal"]

_VAR = re.compile(r"\{([a-z_]+)\}")
_EDGES = re.compile(r"^[\s.,;:()\[\]-]+|[\s.,;:()\[\]-]+$")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FactSpec(_Model):
    """Where a fact is read: a header field, a row's column, or a list's column as a list of codes."""

    field: str | None = None
    column: str | None = None
    list: str | None = None
    codes: str | None = None
    currency_field: str | None = None

    @model_validator(mode="after")
    def _one_place(self) -> FactSpec:
        places = (self.field is not None, self.column is not None and self.list is None, self.list is not None)
        if sum(places) != 1 or (self.list is not None and self.column is None):
            raise ValueError("a fact is read from a field, a row's column, or a list's column")
        return self


class UnitSpec(_Model):
    level: str
    key: str = Field(min_length=1)
    parent: str | None = None
    rows: str | None = None
    facts: dict[str, FactSpec]


class Readings(_Model):
    catalogue: str
    codes: dict[str, dict[str, Any]]
    packs: dict[str, tuple[UnitSpec, ...]]


def normal(word: Any) -> str:
    """A printed word as code tables compare it: without case, extra spaces or punctuation at its ends."""
    return _EDGES.sub("", re.sub(r"\s+", " ", str(word).casefold()))


def load(name: str = "fact_readings_property") -> Readings:
    """The rule file `name`, checked against its catalogue (`ValueError`: a level, fact or code table it does not have)."""
    readings = Readings.model_validate({k: v for k, v in cfg.load(name).items() if k != "meta"})
    cat = facts.catalogue(readings.catalogue)
    problems = []
    for pack, units in readings.packs.items():
        for unit in units:
            if unit.level not in cat.levels:
                problems.append(f"{pack}: no level {unit.level}")
            for fact, spec in unit.facts.items():
                if fact not in cat.facts or cat.facts[fact].level != unit.level:
                    problems.append(f"{pack}: {fact} is no fact of the level {unit.level}")
                if spec.codes is not None and spec.codes not in readings.codes:
                    problems.append(f"{pack}: no code table {spec.codes}")
            if unit.rows is not None and any(s.field is None and s.column is None and s.list is None
                                             for s in unit.facts.values()):
                problems.append(f"{pack}: {unit.level} reads its rows' columns")
    if problems:
        raise ValueError(f"fact readings {name}: " + "; ".join(problems))
    return readings


def _key(template: str, values: dict[str, Any], row: int | None) -> str | None:
    """The template with the document's values ({row}: the list row's number); None when one of them is missing."""
    parts = {name: row if name == "row" else values.get(name) for name in _VAR.findall(template)}
    if any(v is None or str(v).strip() == "" for v in parts.values()):
        return None
    return _VAR.sub(lambda m: normal(parts[m.group(1)]), template)


def _code(readings: Readings, table: str, value: Any) -> tuple[bool, Any]:
    known = readings.codes[table]
    word = normal(value)
    return (True, known[word]) if word in known else (False, None)


def _decimal(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value).replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _typed(cat: facts.Catalogue, fact: str, raw: Any, currency: Any) -> tuple[Any, str | None]:
    """The raw value as the fact's type takes it, or why it cannot."""
    d = cat.facts[fact]
    if d.type == "money":
        amount = _decimal(raw)
        if amount is None:
            return None, "not an amount"
        if not currency:
            return None, "the document states no currency"
        raw = {"amount": str(amount), "currency": str(currency).strip().upper()}
    elif d.type == "quantity":
        number = _decimal(raw)
        if number is None:
            return None, "not a number"
        raw = {"value": str(number), "unit": d.unit}
    elif d.type in ("percentage", "permille"):
        number = _decimal(raw)
        if number is None:
            return None, "not a number"
        raw = {"value": str(number)}
    elif d.type == "count":
        number = _decimal(raw)
        if number is None or number != number.to_integral_value() or number < 0:
            return None, "not a whole number"
        raw = int(number)
    elif d.type in ("code", "text") and not isinstance(raw, str):
        raw = str(raw)
    try:
        return facts.plain(facts.typed_value(fact, d, raw)), None
    except facts.FactError as exc:
        return None, str(exc)


def claims(readings: Readings, pack: str, values: dict[str, Any], *, source: Callable[[str, str | None, int | None], dict[str, Any]],
           reading: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The fact claims of one document's values, in the rule file's order of units (a unit's parent first), and what
    could not be read: [{unit, fact, value, why}] (`why` one of a few sentences; `value` the words no table knows). `source(field, list_field, row)` names where a value was printed
    (the document, its page and quote); `reading` names the type pack and its version."""
    cat = facts.catalogue(readings.catalogue)
    out: list[dict[str, Any]] = []
    unread: list[dict[str, Any]] = []
    for unit in readings.packs.get(pack, ()):
        rows = [(None, values)] if unit.rows is None else list(enumerate(values.get(unit.rows) or [], start=1))
        for row, row_values in rows:
            scope = {**values, **(row_values if row is not None else {})}
            key = _key(unit.key, scope, row)
            parent = _key(unit.parent, scope, row) if unit.parent else None
            for fact, spec in unit.facts.items():
                if spec.list is not None:
                    printed = [r.get(spec.column) for r in values.get(spec.list) or [] if isinstance(r, dict)]
                    printed = [p for p in printed if p not in (None, "")]
                    if not printed:
                        continue
                    found = [_code(readings, spec.codes, p) for p in printed] if spec.codes else [(True, p) for p in printed]
                    unknown = [p for p, (ok, _v) in zip(printed, found) if not ok]
                    raw, why = ([v for _ok, v in found], None) if not unknown else (None, "not a known code")
                    printed = unknown or printed  # the words no table knows, as the person reads them
                    where = source(spec.list, spec.list, None)
                else:
                    printed = (row_values if spec.column is not None and row is not None else values).get(spec.column or spec.field)
                    if printed is None or printed == "":
                        continue
                    raw, why = printed, None
                    if spec.codes is not None:
                        ok, raw = _code(readings, spec.codes, printed)
                        why = None if ok else "not a known code"
                    where = source(spec.column or spec.field, unit.rows if row is not None else None, row)
                value = None
                if why is None:
                    value, why = _typed(cat, fact, raw, values.get(spec.currency_field) if spec.currency_field else None)
                if why is None and key is None:
                    why = "the document does not say which unit it is"
                if why is not None:
                    unread.append({"unit": key, "fact": fact, "value": printed, "why": why})
                    continue
                out.append({"unit": key, "level": unit.level, "parent": parent, "fact": fact, "value": value,
                            "original": None if isinstance(printed, list) else str(printed), "source": where,
                            "reading": reading})
    return out, unread
