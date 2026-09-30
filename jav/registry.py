"""Regiszter-séma (keret-réteg): a Choice-kritérium strukturált alakja és a szülő-család összegzése.

Két regiszter (dokumentumtípus, e-mail-szándék) írta le ugyanazt kézzel, ezért itt a közös rész:
- **kritérium** = `{what, not_for, examples}` objektum (a doksi ajánlása az összetéveszthető opciókra: a kategória
  tartalma, amit NEM fed - a testvér-opciókra mutatva -, és goldennel konzisztens példák). A Jev Choice `criteria`
  értéke JSON-tartalom lehet, nem csak string.
- **szülő-család**: minden kulcs egy családban van (`parents` blokk a JSON-ban). A család valószínűsége a nyers
  Choice-eloszlásból KÓDBAN összegződik (nincs plusz hívás): alacsony típus-confidence mellett a család lehet biztos
  („invoice_like 0,9, de invoice_hu / invoice_foreign 0,45 / 0,45”) - ez a szülő-címke, a policy dönt róla.
"""

from __future__ import annotations

from typing import Any, Mapping


def criterion(what: str, not_for: str, examples: list[str] | tuple[str, ...]) -> dict[str, Any]:
    return {"what": what, "not_for": not_for, "examples": list(examples)}


def parent_summary(probabilities: Mapping[str, float] | None, parent_of: Mapping[str, str]) -> tuple[str | None, float]:
    """A legvalószínűbb opció családja és a család összesített valószínűsége (a nyers eloszlásból, hívás nélkül)."""
    if not probabilities:
        return None, 0.0
    top = max(probabilities.items(), key=lambda kv: kv[1])[0]
    parent = parent_of.get(top)
    if parent is None:
        return None, 0.0
    total = sum(float(p) for k, p in probabilities.items() if parent_of.get(k) == parent)
    return parent, round(total, 4)
