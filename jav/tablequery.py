"""Unified list query (056 U1): search, column filters, sorting and paging over a set of rows.

Every list in the interface goes through this (decision of 2026-09-28: paging, sorting and filtering always run in the
service). Rows are dicts keyed by the columns' `key`; `_key` is the row's stable id (for selection).

Rules (ported from the legacy project's `ui/src/utils/table-sort.ts` to the service side):
- sorting: text in Hungarian alphabetical order (in a mixed text column a plain number sorts as a number, before the
  texts; an accented letter comes after its base letter: a < á, o < ó < ö < ő; double letters — cs, sz … — are not
  handled separately), numbers and money as numbers, dates as ISO text; an empty value is **always last**, in
  descending order too; the sort is stable;
- search and the "contains" filter: case- and accent-insensitive ("szamla" finds "Számla").
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field

Kind = Literal["text", "number", "money", "date", "datetime", "enum", "bool", "id"]
NUMERIC = ("number", "money")
MAX_FACET = 250  # upper limit of the filter choices of an enum column


@dataclass(frozen=True)
class Column:
    """Describes a column: the interface draws from it, and it decides how sorting and filtering work."""

    key: str
    label: str
    kind: Kind = "text"
    hidden: bool = False  # hidden by default (can be switched on in the column picker)
    labels: dict[str, str] | None = None  # enum code -> Hungarian caption; search and sort use the caption
    extra: dict[str, Any] = field(default_factory=dict)  # extras for the interface (e.g. link target)

    def spec(self) -> dict[str, Any]:
        d = asdict(self)
        extra = d.pop("extra")
        return {**d, **extra}


class Sort(BaseModel):
    col: str
    desc: bool = False


class Filter(BaseModel):
    col: str
    op: Literal["contains", "eq", "neq", "in", "gte", "lte", "empty", "notempty"]
    value: Any = None


class Query(BaseModel):
    """The interface's unified list request."""

    q: str | None = Field(default=None, max_length=200)
    filters: list[Filter] = Field(default_factory=list, max_length=50)
    sort: list[Sort] = Field(default_factory=list, max_length=5)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)
    keys: list[str] | None = Field(default=None, max_length=10000)  # only these rows (selection)


# --- normalisation ---------------------------------------------------------------------------------------------

_ACCENT_RANK = {"á": 1, "é": 1, "í": 1, "ó": 1, "ö": 2, "ő": 3, "ú": 1, "ü": 2, "ű": 3}


def fold(value: Any) -> str:
    """For search: lower case, without accents."""
    s = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


_OWN_LETTER = str.maketrans({"ö": "o￿", "ő": "o￿", "ü": "u￿", "ű": "u￿"})


def _hu_key(s: str) -> tuple:
    """Hungarian alphabetical key: ö/ő and ü/ű are separate letters after o and u; á, é, í, ó, ú are one letter with
    their base letter, and with the same base the degree of the accent decides (a < á, o < ó)."""
    low = s.casefold()
    return (fold(low.translate(_OWN_LETTER)), tuple(_ACCENT_RANK.get(ch, 0) for ch in low))


def to_number(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    s = str(value).replace(" ", "").replace(" ", "")
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def shown(col: Column, value: Any) -> Any:
    """The displayed value: the caption for an enum code."""
    if col.labels and value is not None:
        return col.labels.get(str(value), value)
    return value


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == []


_PLAIN_NUMBER = re.compile(r"^-?\d+(?:[.,]\d+)?$")


def _sort_value(value: Any, kind: str) -> Any:
    if kind in NUMERIC:
        n = to_number(value)
        return n if n is not None else _hu_key(str(value))
    if kind == "text" and _PLAIN_NUMBER.match(str(value).strip()):
        return to_number(str(value).strip())  # in a mixed text column a plain number sorts as a number (numbers first)
    if kind == "bool":
        return int(bool(value))
    return _hu_key(str(value))


# --- filtering -------------------------------------------------------------------------------------------------


def _match(row: dict[str, Any], f: Filter, col: Column) -> bool:
    v = row.get(f.col)
    if f.op == "empty":
        return _empty(v)
    if f.op == "notempty":
        return not _empty(v)
    if _empty(v):
        return False
    if f.op == "contains":
        return fold(f.value or "") in fold(shown(col, v))
    if f.op == "in":
        wanted = f.value if isinstance(f.value, list) else [f.value]
        return str(v) in {str(w) for w in wanted}
    if col.kind in NUMERIC:
        a, b = to_number(v), to_number(f.value)
        if a is None or b is None:
            return False
    else:
        a, b = (str(v), str(f.value)) if col.kind in ("date", "datetime", "id") else (fold(v), fold(f.value))
    if f.op == "eq":
        return a == b
    if f.op == "neq":
        return a != b
    if f.op == "gte":
        return a >= b
    return a <= b  # lte


# --- query -----------------------------------------------------------------------------------------------------


def _check_col(cols: dict[str, Column], name: str) -> Column:
    if name not in cols:
        raise ValueError(f"unknown column: {name}")
    return cols[name]


def facets(columns: list[Column], rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    out = {}
    for c in columns:
        if c.kind in ("enum", "bool"):
            vals = {str(r.get(c.key)) for r in rows if not _empty(r.get(c.key))}
            out[c.key] = sorted(vals, key=lambda v, c=c: _hu_key(str(shown(c, v))))[:MAX_FACET]  # by caption
    return out


def select(columns: list[Column], rows: list[dict[str, Any]], q: Query) -> list[dict[str, Any]]:
    """The filtered and sorted rows (without paging): the part shared by the query and the download."""
    cols = {c.key: c for c in columns}
    for f in q.filters:
        _check_col(cols, f.col)
    for s in q.sort:
        _check_col(cols, s.col)
    out = rows
    if q.keys is not None:
        wanted = set(q.keys)
        out = [r for r in out if str(r.get("_key")) in wanted]
    if q.q and q.q.strip():
        needle = fold(q.q.strip())
        out = [r for r in out if any(needle in fold(shown(c, r[c.key])) for c in columns if not _empty(r.get(c.key)))]
    for f in q.filters:
        out = [r for r in out if _match(r, f, cols[f.col])]
    for s in reversed(q.sort):  # stable, multi-level: the least important key first
        kind = cols[s.col].kind
        col = cols[s.col]
        keyed = [(_sort_value(shown(col, r.get(s.col)), kind), r) for r in out if not _empty(r.get(s.col))]
        blank = [r for r in out if _empty(r.get(s.col))]
        # in a numeric column non-numeric values go after the numbers and empty ones at the very end, in both directions
        nums = sorted((p for p in keyed if isinstance(p[0], Decimal)), key=lambda p: p[0], reverse=s.desc)
        rest = sorted((p for p in keyed if not isinstance(p[0], Decimal)), key=lambda p: p[0], reverse=s.desc)
        out = [r for _, r in nums] + [r for _, r in rest] + blank
    return list(out)


def run_query(columns: list[Column], rows: list[dict[str, Any]], q: Query) -> dict[str, Any]:
    """One page of the filtered, sorted rows; `total` is the full count, `matched` the count after filtering."""
    matched = select(columns, rows, q)
    return {"columns": [c.spec() for c in columns], "rows": matched[q.offset: q.offset + q.limit], "total": len(rows),
            "matched": len(matched), "offset": q.offset, "limit": q.limit, "facets": facets(columns, rows)}


__all__ = ["Column", "Filter", "Query", "Sort", "facets", "fold", "run_query", "select", "shown", "to_number"]
