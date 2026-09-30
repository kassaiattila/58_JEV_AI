"""Kompatibilitási visszahivatkozás: a tartalom 2026-09-27 óta a `jav/grounded_claims.py`-ban van (040, K0).

A régi kísérleti driverek és a lezárt mérések reprodukciója ezt az útvonalat importálja; új kód a
`jav.grounded_claims`-t használja. A mérés-kori pontos forrás a `baseline-039` git-címkén érhető el.
"""
from jav.grounded_claims import GroundedClaim, protected_boundaries, verify_claim

__all__ = ["GroundedClaim", "protected_boundaries", "verify_claim"]
