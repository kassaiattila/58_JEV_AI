"""Compatibility back-reference: since 2026-09-27 the content lives in `jav/grounded_claims.py` (040, K0).

The old experimental drivers and the reproduction of closed measurements import this path; new code uses
`jav.grounded_claims`. The exact source at measurement time is available at the `baseline-039` git tag.
"""
from jav.grounded_claims import GroundedClaim, protected_boundaries, verify_claim

__all__ = ["GroundedClaim", "protected_boundaries", "verify_claim"]
