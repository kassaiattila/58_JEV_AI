"""The reconciliation's golden sets in the shared measurement command (204, plan G-process-core R1h; until 204 in
`jav/reconcile_package.py`).

Plain-language summary: the reconciliation has two golden sets, lists of cases whose right answer is known in advance:
the pairs, exclusions and statuses its code proposes on synthetic cases, and the kind of incoming money on invented
statement lines. The shared measurement command (`python -m jav.cli measure`, `jav/goldens.py`) measures them with every
other golden set. They are described here, beside the reconciliation, so the reconciliation itself never imports the
measurement layer; the finance domain names this module (`jav/domains/finance.py` `GOLDENS`) and the shared command
finds it from there.

Layer: measurement of the finance domain: it imports the reconciliation and the shared measurement registry; no
business module imports it.
"""

from __future__ import annotations

from jav import cfg, goldens, reconcile
from jav.reconcile_package import KIND


def _measure_pairs(options: goldens.Options) -> goldens.Outcome:
    """As `reconcile --golden` measures them: code only, free."""
    score = reconcile.golden_score()
    reconcile.print_golden_score(score)
    return goldens.Outcome(cases=score["total"], answered=score["total"], right=score["passed"], scored=score["total"],
                           failures=tuple(f"{case}: {'; '.join(p)}" for case, p in score["failures"].items()))


def _measure_credit_kinds(options: goldens.Options) -> goldens.Outcome:
    """As `reconcile-ai --golden` measures them, with the round's engine; without a budget from earlier answers only."""
    from jav import reconcile_ai

    budget, refused = options.answering_budget("the incoming money kinds")
    if refused:
        return goldens.Outcome(refused=refused)
    limits = {reconcile_ai.PROVIDERS[options.engine]: budget} if budget is not None else {}
    g = reconcile_ai.golden(engines=[options.engine], limits=limits, use_cache=options.use_cache,
                            **({} if limits else {"earlier_only": True}))
    reconcile_ai.print_golden(g)
    s = g["engines"][options.engine]
    answered = s["cases"] - s["failed"]
    return goldens.Outcome(cases=s["cases"], answered=answered, right=s["right"], scored=answered)


# 188 (plan 185 T3a): the reconciliation's golden sets, measured by the shared measurement command (`jav/goldens.py`)
GOLDENS = (
    goldens.Golden(key=f"{KIND}:pairs", layer="logic_pack", owner=KIND, engines=(), module=__name__,
                   what="the pairs, exclusions and statuses the code proposes on the synthetic reconciliation cases "
                        "(configs/golden_reconcile.json)",
                   count=lambda: len(cfg.load("golden_reconcile")["cases"]), measure=_measure_pairs),
    goldens.Golden(key=f"{KIND}:credit_kinds", layer="logic_pack", owner=KIND, engines=goldens.ENGINES,
                   module=__name__, what="the kind of incoming money on the invented statement lines "
                                         "(configs/golden_credit_kinds.json)",
                   count=lambda: len(cfg.load("golden_credit_kinds")["cases"]), measure=_measure_credit_kinds),
)


__all__ = ["GOLDENS"]
