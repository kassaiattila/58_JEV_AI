"""Egységes lista-lekérdezés (056 U1): keresés, oszlopszűrők, rendezés, lapozás egy sorhalmazon.

A felület minden listája ezen megy át (döntés 2026-09-28: a lapozás, a rendezés és a szűrés mindenhol a
szolgáltatásban fut). A sorok szótárak, a kulcsuk az oszlop `key`-e; a `_key` a sor stabil azonosítója (kijelöléshez).

Szabályok (a régi projekt `ui/src/utils/table-sort.ts`-éből portolva, szolgáltatás oldalra):
- rendezés: a szöveg magyar ábécé szerint (vegyes szöveges oszlopban a tiszta szám számként, a szövegek előtt) (az ékezetes betű az alapbetű után: a < á, o < ó < ö < ő; a kettős
  betűket — cs, sz … — nem kezeljük külön), a szám és a pénz számként, a dátum ISO-szövegként; az üres érték
  **mindig a végén**, csökkenő rendezésben is; a rendezés stabil;
- keresés és „tartalmaz” szűrő: kis-nagybetű és ékezet nélkül („szamla” megtalálja a „Számla”-t).
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
MAX_FACET = 250  # a felsorolt oszlop szűrő-választékának felső határa


@dataclass(frozen=True)
class Column:
    """Egy oszlop leírása: ebből rajzol a felület, és ez dönti el a rendezés és a szűrés módját."""

    key: str
    label: str
    kind: Kind = "text"
    hidden: bool = False  # alapból rejtett (az oszlopválasztóban bekapcsolható)
    labels: dict[str, str] | None = None  # felsorolt kód -> magyar felirat; a keresés és a rendezés a feliratra megy
    extra: dict[str, Any] = field(default_factory=dict)  # a felületnek szóló többlet (pl. hivatkozás-cél)

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
    """A felület egységes lista-kérése."""

    q: str | None = Field(default=None, max_length=200)
    filters: list[Filter] = Field(default_factory=list, max_length=50)
    sort: list[Sort] = Field(default_factory=list, max_length=5)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)
    keys: list[str] | None = Field(default=None, max_length=10000)  # csak ezek a sorok (kijelölés)


# --- normalizálás ----------------------------------------------------------------------------------------------

_ACCENT_RANK = {"á": 1, "é": 1, "í": 1, "ó": 1, "ö": 2, "ő": 3, "ú": 1, "ü": 2, "ű": 3}


def fold(value: Any) -> str:
    """Kereséshez: kisbetű, ékezet nélkül."""
    s = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


_OWN_LETTER = str.maketrans({"ö": "o￿", "ő": "o￿", "ü": "u￿", "ű": "u￿"})


def _hu_key(s: str) -> tuple:
    """Magyar ábécé-kulcs: az ö/ő és az ü/ű külön betű az o, illetve az u után; az á, é, í, ó, ú az alapbetűvel egy
    betű, azonos alapnál az ékezet foka dönt (a < á, o < ó)."""
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
    """A megjelenő érték: felsorolt kódnál a felirat."""
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
        return to_number(str(value).strip())  # vegyes szöveges oszlopban a tiszta szám számként (a számok előre)
    if kind == "bool":
        return int(bool(value))
    return _hu_key(str(value))


# --- szűrés ----------------------------------------------------------------------------------------------------


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


# --- lekérdezés ------------------------------------------------------------------------------------------------


def _check_col(cols: dict[str, Column], name: str) -> Column:
    if name not in cols:
        raise ValueError(f"unknown column: {name}")
    return cols[name]


def facets(columns: list[Column], rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    out = {}
    for c in columns:
        if c.kind in ("enum", "bool"):
            vals = {str(r.get(c.key)) for r in rows if not _empty(r.get(c.key))}
            out[c.key] = sorted(vals, key=lambda v, c=c: _hu_key(str(shown(c, v))))[:MAX_FACET]  # a felirat ábécéjében
    return out


def select(columns: list[Column], rows: list[dict[str, Any]], q: Query) -> list[dict[str, Any]]:
    """A szűrt és rendezett sorok (lapozás nélkül) — a lekérdezés és a letöltés közös része."""
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
    for s in reversed(q.sort):  # stabil, többszintű: a legkevésbé fontos kulcs előbb
        kind = cols[s.col].kind
        col = cols[s.col]
        keyed = [(_sort_value(shown(col, r.get(s.col)), kind), r) for r in out if not _empty(r.get(s.col))]
        blank = [r for r in out if _empty(r.get(s.col))]
        # számoszlopban a nem számként olvasható érték a számok után, az üres a legvégén — mindkét irányban
        nums = sorted((p for p in keyed if isinstance(p[0], Decimal)), key=lambda p: p[0], reverse=s.desc)
        rest = sorted((p for p in keyed if not isinstance(p[0], Decimal)), key=lambda p: p[0], reverse=s.desc)
        out = [r for _, r in nums] + [r for _, r in rest] + blank
    return list(out)


def run_query(columns: list[Column], rows: list[dict[str, Any]], q: Query) -> dict[str, Any]:
    """Egy lap a szűrt, rendezett sorokból; `total` az összes, `matched` a szűrés utáni darabszám."""
    matched = select(columns, rows, q)
    return {"columns": [c.spec() for c in columns], "rows": matched[q.offset: q.offset + q.limit], "total": len(rows),
            "matched": len(matched), "offset": q.offset, "limit": q.limit, "facets": facets(columns, rows)}


__all__ = ["Column", "Filter", "Query", "Sort", "facets", "fold", "run_query", "select", "shown", "to_number"]
