"""Document-type registry for M1 categorisation — the content comes from `configs/doc_types.json` (config as data).

Schema v2 (2026-09-20): every type has `what` (what the category covers, in English), `not_for` (what it does NOT cover,
pointing to the sibling types), `examples` (short examples consistent with the golden set), `parent` (family:
invoice_like / contract_like / bank_like / official_like / other) + anchor patterns (ported from the legacy
10_AIFLOW_V4 `detect.json` files). The Choice criterion is the `{what, not_for, examples}` object (`jav/registry.py`).
The anchors are NOT gates here: they go into the JEV state as hit counts (`anchor_hits`), and JEV makes the decision
with a calibrated confidence.

The 23 legacy types were merged into 11 to suit the corpus (`OLD_TYPE_MAP` for the legacy golden labels). The
descriptions are edited in the JSON (version + changelog); the module is only the mechanism (compiled regexes,
criteria).
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
PARENTS: dict[str, str] = dict(_CFG["parents"])  # family -> description


@dataclass(frozen=True)
class DocType:
    key: str
    what: str  # English, what the category covers - the `what` field of the Choice criterion
    not_for: str  # what it does NOT cover (pointing to the sibling types)
    examples: tuple[str, ...]
    parent: str
    required_any: tuple[str, ...] = ()
    supporting: tuple[str, ...] = ()
    excluders: tuple[str, ...] = ()
    flows: tuple[str, ...] = field(default_factory=tuple)  # the M2 flow(s) that accept it

    @property
    def description(self) -> str:  # compatibility name (v1: a single description)
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
OLD_TYPE_MAP: dict[str, str] = dict(_CFG["old_type_map"])  # legacy golden label -> our key
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
    """How many anchor patterns match the (case-folded) text, per type. A feature for the JEV state, not a gate."""
    low = text.casefold()
    out: dict[str, dict[str, int]] = {}
    for key, groups in _COMPILED.items():
        counts = {g: sum(1 for rx in rxs if rx.search(low)) for g, rxs in groups.items()}
        if any(counts.values()):
            out[key] = {g: n for g, n in counts.items() if n}
    return out


def choice_criteria() -> dict[str, dict[str, Any]]:
    """The criteria of the JEV Choice: key -> `{what, not_for, examples}` (`unknown` also comes from the JSON)."""
    crit = {t.key: t.criterion() for t in DOC_TYPES}
    u = _CFG["unknown"]
    crit[UNKNOWN] = criterion(u["what"], u["not_for"], u.get("examples", ()))
    return crit
