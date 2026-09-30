"""E-mail szándék-regiszter az M3 szándék-azonosításhoz — a tartalom a `configs/intents.json`-ból jön (konfig mint adat).

A 11 osztály és a kulcsaik a régi 10_AIFLOW_V4 `flows/registry/intent_types.json` aktív soraiból jönnek VERBATIM
(magyar kulcsok), hogy a régi 96 esetes, két címkéző által jóváhagyott golden közvetlenül mérhető maradjon. A tengely
a KÜLDŐ CÉLJA (purpose axis, 2026-07-05-ös régi döntés), nem a csatolt dokumentum típusa.

Séma v2 (2026-09-20): `what` (a szándék tartalma, angolul), `not_for` (a NOT-szabályok, testvér-szándékokra mutatva),
`examples` (verbatim tárgysorok - csak a goldennel konzisztens példa maradhat: az M3 1. körének 4 hibáját egy
inkonzisztens példa okozta), `parent` (család). A Choice-kritérium a `{what, not_for, examples}` objektum
(`jav/registry.py`). A `next_flow` NEM Jev-kérdés: a döntési hierarchia 1. szintje (kód) adja (`policy.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jav import cfg
from jav.registry import criterion

_CFG = cfg.load("intents")
OTHER: str = _CFG["other_key"]
PARENTS: dict[str, str] = dict(_CFG["parents"])  # család -> leírás


@dataclass(frozen=True)
class Intent:
    key: str
    display_name: str  # magyar megjelenítő név (a régi regiszterből)
    what: str  # angol, a szándék tartalma - a Choice kritérium `what` mezője
    not_for: str  # a NOT-szabályok (testvér-szándékokra mutatva)
    examples: tuple[str, ...] = ()  # verbatim tárgysor-példák
    parent: str = "other"
    document_bearing: bool = False  # a csatolmány maga a küldemény tárgya (számla, nyugta) -> M2 felé mehet

    @property
    def description(self) -> str:  # kompatibilis név (v1: egyetlen leírás)
        return self.what

    @property
    def few_shot(self) -> tuple[str, ...]:  # kompatibilis név (v1)
        return self.examples

    def criterion(self) -> dict[str, Any]:
        return criterion(self.what, self.not_for, self.examples)


INTENTS: tuple[Intent, ...] = tuple(
    Intent(i["key"], i["display_name"], i["what"], i["not_for"], tuple(i.get("examples", ())), i["parent"], bool(i.get("document_bearing", False)))
    for i in _CFG["intents"]
)
BY_KEY: dict[str, Intent] = {i.key: i for i in INTENTS}
INTENT_KEYS: tuple[str, ...] = tuple(i.key for i in INTENTS)
PARENT_OF: dict[str, str] = {i.key: i.parent for i in INTENTS}
DOCUMENT_BEARING: frozenset[str] = frozenset(i.key for i in INTENTS if i.document_bearing)
CONFIG_HASH = cfg.config_hash("intents")


def choice_criteria() -> dict[str, dict[str, Any]]:
    """A Jev Choice kritériumai: kulcs -> `{what, not_for, examples}`."""
    return {i.key: i.criterion() for i in INTENTS}
