"""231 (plan stage C, C2b): the reconciliation engine's rule readers, split out of `reconcile.py`.

Plain-language summary: where the engine reads its rules: `configs/reconcile.json` (`_conf`, read once; every module
of the engine reads it through this module, so a test changes it in one place) and the bands of the finance domain's
own rule file (`configs/finance.json` `reconcile`). The engine itself is described in `reconcile.py`.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Any

from jav.core import cfg


# --- the rule readers ----------------------------------------------------------------------------------------------


@lru_cache(maxsize=None)
def _conf() -> dict[str, Any]:
    return dict(cfg.load("reconcile"))


def _bands() -> dict[str, Any]:
    """224: the reconciliation's bands, in the finance domain's own rule file: outside `reconcile.json`, whose
    fingerprint a statement prints, so moving them changed no approved statement."""
    return cfg.load("finance")["reconcile"]


def fx_tolerance() -> tuple[Decimal, Decimal]:
    """130 (DECISIONS 130): how far below and above the invoice amount converted at the MNB rate a forint card line may
    be for the pair to be proposed, as fractions (0.02, 0.05: -2% ... +5%). A proposal only; a person decides. 224:
    `configs/finance.json` `reconcile.fx_tolerance` (until then in `policy.json`)."""
    band = _bands()["fx_tolerance"]
    return Decimal(str(band["below"])), Decimal(str(band["above"]))


def fx_bank_tolerance(basis: str) -> tuple[Decimal, Decimal]:
    """149: how far below and above the invoice amount converted at the MNB rate of the `basis` day (fulfilment or
    booking) a forint bank line may be for the pair to be proposed, as fractions. A proposal only; a person decides.
    224: `configs/finance.json` `reconcile.fx_bank_tolerance`."""
    band = _bands()["fx_bank_tolerance"][basis]
    return Decimal(str(band["below"])), Decimal(str(band["above"]))


def ai_sure_probability() -> float:
    """147 (the owner's decision: 0.95): in the quick review, the AI's kind of payment counts as sure when both engines
    give the same kind and JEV's probability is at least this. 224: `configs/finance.json` `reconcile.ai_sure`."""
    return float(_bands()["ai_sure"]["min_jev_probability"])


@lru_cache(maxsize=None)
def _ignore_tokens() -> frozenset[str]:
    """The legal forms and filler words a party name is compared without (shared with `fact_checks.same_party`)."""
    return frozenset(cfg.load("fact_checks")["parties"]["ignore_tokens"])
