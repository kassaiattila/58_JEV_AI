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
            "parties": data["parties"]}


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


def same_party(first: object, second: object) -> bool:
    """Whether two role values name one party. Tax numbers compare by their stem; names by significant words."""
    if first in (None, "") or second in (None, ""):
        return False
    rules = _rules()["parties"]
    a, b = (re.sub(r"[^0-9A-Za-z]", "", str(v)).upper() for v in (first, second))
    digits_a, digits_b = re.sub(r"\D", "", a), re.sub(r"\D", "", b)
    stem = int(rules["domestic_tax_stem_digits"])
    if len(digits_a) >= stem and len(digits_b) >= stem:
        prefix_a, prefix_b = (re.match(r"[A-Z]*", v).group() for v in (a, b))
        domestic = set(rules["domestic_tax_prefixes"])
        if prefix_a in domestic and prefix_b in domestic:
            return digits_a[:stem] == digits_b[:stem]
        return prefix_a == prefix_b and digits_a == digits_b
    ignore = set(rules["ignore_tokens"])
    words_a = {w for w in _ascii_words(str(first)) if w not in ignore}
    words_b = {w for w in _ascii_words(str(second)) if w not in ignore}
    if not words_a or not words_b:
        return False
    if words_a == words_b:
        return True
    small, large = sorted((words_a, words_b), key=len)
    return len(small) >= int(rules["min_subset_tokens"]) and small <= large
