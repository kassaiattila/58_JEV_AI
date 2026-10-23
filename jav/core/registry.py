"""Registry schema (framework layer): the structured form of a Choice criterion and the parent-family summary.

Two registries (document type, email intent) spelt out the same thing by hand, so the shared part lives here:
- **criterion** = a `{what, not_for, examples}` object (the docs' recommendation for confusable options: what the
  category covers, what it does NOT cover - pointing at the sibling options - and examples consistent with the golden
  set). The value of a JEV Choice `criteria` may be JSON content, not only a string.
- **parent family**: every key belongs to one family (the `parents` block in the JSON). The family probability is
  summed IN CODE from the raw Choice distribution (no extra call): with low type confidence the family can still be
  certain ("invoice_like 0.9, but invoice_hu / invoice_foreign 0.45 / 0.45") - that is the parent label; the policy
  decides on it.
"""

from __future__ import annotations

from typing import Any, Mapping


def criterion(what: str, not_for: str, examples: list[str] | tuple[str, ...]) -> dict[str, Any]:
    return {"what": what, "not_for": not_for, "examples": list(examples)}


def parent_summary(probabilities: Mapping[str, float] | None, parent_of: Mapping[str, str]) -> tuple[str | None, float]:
    """The family of the most likely option and the family's total probability (from the raw distribution, no call)."""
    if not probabilities:
        return None, 0.0
    top = max(probabilities.items(), key=lambda kv: kv[1])[0]
    parent = parent_of.get(top)
    if parent is None:
        return None, 0.0
    total = sum(float(p) for k, p in probabilities.items() if parent_of.get(k) == parent)
    return parent, round(total, 4)
