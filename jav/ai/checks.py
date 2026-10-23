"""The checks a document's result goes through, in one registry with stages (175, plan 170 E3).

Plain-language summary: after a document is read, its result goes through checks in four stages. The record stage
checks the record itself: sums, dates, tax and account numbers, a statement's balances, the two parties (the type
pack's `validators` list names which ones). The decision stage turns the AI's judgements and the failed record checks
into to-dos. The cross-document stage compares the document with the other documents in the store: a duplicate
invoice, an own tax number as the supplier's, a statement booking the same days as another one. The after-save stage
looks over the stored results and opens the same to-dos afterwards (the duplicate and own-tax scans of the command
line). Until now the record checks were a closed table in `jav/ai/validators.py`, the decision steps a fixed list of calls
in `policy.decide`, and the rule that the store is read only in a worker run was written out in three modules. Now each
check is one entry here, and that rule is one gate (`store_readable`).

An entry (`Check`) names its stage and how it runs:
- record: `run(inv, spec, *, doc_id, doc_type)` returns a check result, or None when the check does not apply; `kind`
  says what the pack's entry names: the whole record (`record`), one field (`field`), or two fields (`pair`);
- decision: `run(state)` adds its to-dos to the flow state; `arms` names the paths it runs on (S or G); 218 (plan P3
  P3b): `rule(inputs)` is the pure rule `run` applies, the to-dos for the decision's traced inputs (`policy.
  decision_inputs`), so the extraction's decision trace replays the checks in this registry's order;
- cross-document: `run(subject)` returns its to-dos for the document (`Subject`);
- after-save: `run(write=...)` scans the stored results and returns counts; `producer` names who opens its to-dos and
  `opens` the cross-document check whose to-do it opens;
- saved (185, plan G-full-move T1f): `run(state)` looks at a document's flow state once its record is saved (the
  finance domain's: the own parties' direction settles an uncertain detailed type between an outgoing and an incoming
  invoice, 149; until 185 the extraction flow's own code). As before, it runs in every flow, not only in a worker run.

A check that reads other documents (`reads_store`) runs only in a worker run, so a measurement and the command line
give results that do not depend on what the store holds. The stored order of to-dos is part of a result: the checks
of a stage run in the order they are registered (the order `policy.decide` had; `tests/test_characterisation_171.py`).
The built-in checks are registered by the modules that own them (`jav/ai/validators.py`: record; `jav/ai/policy.py`:
decision) when they are imported; 180 (plan 170 E7): the cross-document and after-save checks are the finance domain's
(`jav/domains/finance/__init__.py`), registered by `registrations.load_all`. The registry imports the first two and calls
`load_all` the first time it is read, so it is complete whichever module asks first.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from jav.core import calls

Stage = Literal["record", "decision", "cross_document", "after_save", "saved"]
STAGES: tuple[Stage, ...] = ("record", "decision", "cross_document", "after_save", "saved")
KINDS = ("record", "field", "pair")

_OWNERS = ("jav.ai.validators", "jav.ai.policy")  # the modules that register the record and decision checks on import


class UnknownCheck(KeyError):
    """No check is registered under the name."""


@dataclass(frozen=True)
class Check:
    name: str
    stage: Stage
    run: Callable[..., Any]
    kind: str | None = None
    arms: tuple[str, ...] = ()
    reads_store: bool = False
    producer: str | None = None
    opens: str | None = None
    rule: Callable[..., list[str]] | None = None


@dataclass(frozen=True)
class Subject:
    """The document a cross-document check looks at: its id and type, its record (None when nothing was extracted)
    and its record checks' results in their stored form."""
    doc_id: str | None
    doc_type: str | None
    record: Any
    validation: list[dict[str, Any]] = field(default_factory=list)


_CHECKS: dict[str, Check] = {}
_loaded = False


def register(check: Check) -> None:
    if check.stage not in STAGES:
        raise ValueError(f"check {check.name}: unknown stage {check.stage!r}")
    if check.stage == "record" and check.kind not in KINDS:
        raise ValueError(f"check {check.name}: a record check names its kind, one of {KINDS}")
    if check.stage == "decision" and check.rule is None:  # 218: the extraction's decision trace replays it
        raise ValueError(f"check {check.name}: a decision check names its pure rule")
    if check.name in _CHECKS:
        raise ValueError(f"check {check.name} is registered twice")
    _CHECKS[check.name] = check


def _load() -> None:
    global _loaded
    if not _loaded:
        from jav.app import registrations

        for module in _OWNERS:
            importlib.import_module(module)
        registrations.load_all()  # 180: the domains' checks (`jav/domains/`)
        _loaded = True


def get(name: str) -> Check:
    _load()
    try:
        return _CHECKS[name]
    except KeyError:
        raise UnknownCheck(f"no check is registered as {name!r}") from None


def stage(name: Stage) -> list[Check]:
    """The checks of a stage, in the order they run."""
    _load()
    return [c for c in _CHECKS.values() if c.stage == name]


def store_readable() -> bool:
    """The one gate of the checks that read other documents: only inside a worker run. A budgeted measurement has a
    budget scope too, but it is not a worker run (127); the command line and the local service have no run at all."""
    ctx = calls.current()
    return ctx is not None and ctx.budget_scope is not None and not ctx.measurement


def runs(check: Check) -> bool:
    """Whether a check may run here: one that reads the store only in a worker run."""
    return not check.reads_store or store_readable()


def saved(state: Any) -> None:
    """185 (plan G-full-move T1f): each check of the saved stage on a document's flow state, in order."""
    for check in stage("saved"):
        if runs(check):
            check.run(state)


def cross_document(subject: Subject) -> list[list[str]]:
    """Each cross-document check's to-dos for the document, in order (one list per check that ran)."""
    return [list(check.run(subject)) for check in stage("cross_document") if runs(check)]


__all__ = ["Check", "KINDS", "STAGES", "Stage", "Subject", "UnknownCheck", "cross_document", "get", "register", "runs", "saved",
           "stage", "store_readable"]
