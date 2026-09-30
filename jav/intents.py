"""Email intent registry for M3 intent identification — the content comes from `configs/intents.json` (config as data).

The 11 classes and their keys come VERBATIM from the active rows of the legacy 10_AIFLOW_V4
`flows/registry/intent_types.json` (Hungarian keys), so that the legacy 96-case golden set, approved by two labellers,
stays directly measurable. The axis is the SENDER'S PURPOSE (purpose axis, legacy decision of 2026-07-05), not the
type of the attached document.

Schema v2 (2026-09-20): `what` (the content of the intent, in English), `not_for` (the NOT rules, pointing to sibling
intents), `examples` (verbatim subject lines - only examples consistent with the golden set may stay: the 4 errors of
M3 round 1 were caused by one inconsistent example), `parent` (family). The Choice criterion is the
`{what, not_for, examples}` object (`jav/registry.py`). `next_flow` is NOT a JEV question: level 1 of the decision
hierarchy (code) provides it (`policy.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jav import cfg
from jav.registry import criterion

_CFG = cfg.load("intents")
OTHER: str = _CFG["other_key"]
PARENTS: dict[str, str] = dict(_CFG["parents"])  # family -> description


@dataclass(frozen=True)
class Intent:
    key: str
    display_name: str  # Hungarian display name (from the legacy registry)
    what: str  # English, the content of the intent - the `what` field of the Choice criterion
    not_for: str  # the NOT rules (pointing to sibling intents)
    examples: tuple[str, ...] = ()  # verbatim example subject lines
    parent: str = "other"
    document_bearing: bool = False  # the attachment is what the email is about (invoice, receipt) -> may go to M2

    @property
    def description(self) -> str:  # compatibility name (v1: a single description)
        return self.what

    @property
    def few_shot(self) -> tuple[str, ...]:  # compatibility name (v1)
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
    """The criteria of the JEV Choice: key -> `{what, not_for, examples}`."""
    return {i.key: i.criterion() for i in INTENTS}
