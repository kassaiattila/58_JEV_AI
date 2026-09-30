"""Dokumentumtípus-regiszter az M1 kategorizáláshoz — a tartalom a `configs/doc_types.json`-ból jön (konfig mint adat).

Séma v2 (2026-09-20): minden típus `what` (a kategória tartalma, angolul), `not_for` (amit NEM fed, a testvér-típusokra
mutatva), `examples` (goldennel konzisztens rövid példák), `parent` (család: invoice_like / contract_like / bank_like /
official_like / other) + anchor-minták (a régi 10_AIFLOW_V4 `detect.json`-okból portolva). A Choice-kritérium a
`{what, not_for, examples}` objektum (`jav/registry.py`). Az anchorok itt NEM kapuk: találat-számként kerülnek a Jev
state-be (`anchor_hits`), a döntést a Jev hozza kalibrált confidence-szel.

A 23 régi típus a korpusz igényei szerint 11-re vonva össze (`OLD_TYPE_MAP` a régi golden címkéihez). A leírások
szerkesztése a JSON-ban történik (verzió + changelog), a modul csak a mechanizmus (fordított regexek, kritériumok).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from jav import cfg
from jav.registry import criterion

_CFG = cfg.load("doc_types")
UNKNOWN: str = _CFG["unknown_key"]
UNKNOWN_PARENT: str = _CFG["unknown_parent"]
PARENTS: dict[str, str] = dict(_CFG["parents"])  # család -> leírás


@dataclass(frozen=True)
class DocType:
    key: str
    what: str  # angol, a kategória tartalma - a Choice kritérium `what` mezője
    not_for: str  # amit NEM fed (testvér-típusokra mutatva)
    examples: tuple[str, ...]
    parent: str
    required_any: tuple[str, ...] = ()
    supporting: tuple[str, ...] = ()
    excluders: tuple[str, ...] = ()
    flows: tuple[str, ...] = field(default_factory=tuple)  # M2 flow(k), amelyek fogadják

    @property
    def description(self) -> str:  # kompatibilis név (v1: egyetlen leírás)
        return self.what

    def criterion(self) -> dict[str, Any]:
        return criterion(self.what, self.not_for, self.examples)


DOC_TYPES: tuple[DocType, ...] = tuple(
    DocType(
        t["key"], t["what"], t["not_for"], tuple(t.get("examples", ())), t["parent"], tuple(t.get("required_any", ())),
        tuple(t.get("supporting", ())), tuple(t.get("excluders", ())), tuple(t.get("flows", ())),
    )
    for t in _CFG["types"]
)
DOC_TYPE_KEYS: tuple[str, ...] = tuple(t.key for t in DOC_TYPES) + (UNKNOWN,)
BY_KEY: dict[str, DocType] = {t.key: t for t in DOC_TYPES}
PARENT_OF: dict[str, str] = {t.key: t.parent for t in DOC_TYPES} | {UNKNOWN: UNKNOWN_PARENT}
OLD_TYPE_MAP: dict[str, str] = dict(_CFG["old_type_map"])  # régi golden-címke -> a mi kulcsunk
CONFIG_HASH = cfg.config_hash("doc_types")

_COMPILED: dict[str, dict[str, list[re.Pattern[str]]]] = {
    t.key: {
        "required_any": [re.compile(p) for p in t.required_any],
        "supporting": [re.compile(p) for p in t.supporting],
        "excluders": [re.compile(p) for p in t.excluders],
    }
    for t in DOC_TYPES
}


def anchor_hits(text: str) -> dict[str, dict[str, int]]:
    """Típusonként hány anchor-minta talál a (kisbetűs) szövegben. Feature a Jev state-be, nem kapu."""
    low = text.casefold()
    out: dict[str, dict[str, int]] = {}
    for key, groups in _COMPILED.items():
        counts = {g: sum(1 for rx in rxs if rx.search(low)) for g, rxs in groups.items()}
        if any(counts.values()):
            out[key] = {g: n for g, n in counts.items() if n}
    return out


def choice_criteria() -> dict[str, dict[str, Any]]:
    """A Jev Choice kritériumai: kulcs -> `{what, not_for, examples}` (az `unknown` is a JSON-ból)."""
    crit = {t.key: t.criterion() for t in DOC_TYPES}
    u = _CFG["unknown"]
    crit[UNKNOWN] = criterion(u["what"], u["not_for"], u.get("examples", ()))
    return crit
