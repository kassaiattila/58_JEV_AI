"""Deterministic content checks shared by the extraction paths (120).

The rules are data in `configs/fact_checks.json`. A check never changes a value
or a model answer: it only names a reason for human review. Model probabilities
are not used here; matching text is code's job.

- `placeholder_issue`: an unfilled template field (`[Name]`, `....`, a date mask)
  is not a stated fact.
- `quantity_issue`: the kind of a value (money, percentage, date, time) conflicts
  with the meaning of its property and unit. This generalises the 119 money/time
  warning; a property that names both kinds (an hourly rate) is no conflict.
- `same_party`: two role fields name one party (the same tax-number stem, or one
  name's significant words contained in the other's).
- `tax_party_key` (121): the identity of a party by its tax number, so that the
  domestic and the EU form of one Hungarian number are one party.
- `orientation_issue` (121): a pair of parties standing the other way round than on
  most earlier documents of the same type (`jav/party_history.py` counts them).
"""
from __future__ import annotations

from functools import lru_cache
import re
import unicodedata
from typing import Any

from jav import cfg

CONFIG = "fact_checks"


@lru_cache(maxsize=None)
def _rules() -> dict[str, Any]:
    data = cfg.load(CONFIG)
    kinds = {}
    for name, kind in data["quantities"]["kinds"].items():
        kinds[name] = {**kind, "value_patterns": [re.compile(p) for p in kind["value_patterns"]],
                       "words": frozenset(kind["words"]), "stems": tuple(kind["stems"])}
    return {"placeholders": [re.compile(p) for p in data["placeholders"]["patterns"]],
            "placeholder_reason": data["placeholders"]["reason"],
            "kinds": kinds, "quantity_reason": data["quantities"]["reason"],
            "compatible": {tuple(pair) for pair in data["quantities"]["compatible"]},
            "parties": data["parties"], "orientation": data["party_orientation"]}


def config_hash() -> str:
    return cfg.config_hash(CONFIG)


def placeholder_issue(value: str | None) -> str | None:
    """The review reason when the value contains an unfilled template field."""
    rules = _rules()
    if value and any(p.search(value) for p in rules["placeholders"]):
        return rules["placeholder_reason"]
    return None


def _meaning_kinds(prop: str | None, unit: str | None) -> list[str]:
    tokens = re.findall(r"\w+", " ".join(filter(None, (prop, unit))).lower())
    return [name for name, kind in _rules()["kinds"].items()
            if any(t in kind["words"] or any(stem in t for stem in kind["stems"]) for t in tokens)]


def quantity_issue(value: str | None, prop: str | None, unit: str | None = None) -> str | None:
    """The review reason when the value's kind conflicts with the property and unit; None when either is unknown."""
    if not value:
        return None
    rules = _rules()
    found = [name for name, kind in rules["kinds"].items() if any(p.search(value) for p in kind["value_patterns"])]
    meant = _meaning_kinds(prop, unit)
    if not found or not meant or set(found) & set(meant):
        return None
    if any((v, m) in rules["compatible"] for v in found for m in meant):
        return None
    kinds = rules["kinds"]
    return rules["quantity_reason"].format(value=kinds[found[0]]["value_label"], meaning=kinds[meant[0]]["meaning_label"])


def _ascii_words(value: str) -> list[str]:
    plain = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
    return re.findall(r"\w+", plain.lower())


def significant_words(value: object) -> list[str]:
    """133: a party name's words in their order, without the legal forms and filler words (`parties.ignore_tokens`);
    shared by `same_party` and the own parties (`jav.parties`)."""
    ignore = set(_rules()["parties"]["ignore_tokens"])
    return [w for w in _ascii_words(str(value or "")) if w not in ignore]


def tax_party_key(value: object) -> str | None:
    """121: a party's identity by its tax number, or None when the value has fewer digits than a domestic stem. A
    domestic number (no prefix or a domestic one) is its stem, so `12345678-2-41` and `HU12345678` are one party;
    a foreign one is its prefix with all its digits. 120's `same_party` compares tax numbers by this key."""
    if value in (None, ""):
        return None
    rules = _rules()["parties"]
    plain = re.sub(r"[^0-9A-Za-z]", "", str(value)).upper()
    digits = re.sub(r"\D", "", plain)
    stem = int(rules["domestic_tax_stem_digits"])
    if len(digits) < stem:
        return None
    prefix = re.match(r"[A-Z]*", plain).group()
    if prefix in set(rules["domestic_tax_prefixes"]):
        return "domestic:" + digits[:stem]
    return f"{prefix}:{digits}"


def orientation_issue(other: int, alike: int) -> bool:
    """121: whether the earlier documents of the same type stand the other way round by a clear majority: at least
    `min_documents` of them, and at least `min_ratio` times as many as stand alike (two-way business stays quiet)."""
    rules = _rules()["orientation"]
    return other >= int(rules["min_documents"]) and other >= float(rules["min_ratio"]) * alike


def same_party(first: object, second: object) -> bool:
    """Whether two role values name one party. Tax numbers compare by their stem; names by significant words."""
    if first in (None, "") or second in (None, ""):
        return False
    rules = _rules()["parties"]
    key_a, key_b = tax_party_key(first), tax_party_key(second)
    if key_a is not None and key_b is not None:
        return key_a == key_b
    words_a, words_b = set(significant_words(first)), set(significant_words(second))
    if not words_a or not words_b:
        return False
    if words_a == words_b:
        return True
    small, large = sorted((words_a, words_b), key=len)
    return len(small) >= int(rules["min_subset_tokens"]) and small <= large
