"""The capability registry (231, plan stage A, A2; DECISIONS 231): the general building blocks of every process pack.

Plain-language summary: the owner's rule of 2026-10-24 is that every process is built only from general capabilities.
A capability is one registered thing the system can do (read documents, match requested items with a price list, fill
a Word template, send), with a typed description of what a process sets for it (its parameters), whether it may call
a paid service, which rule files it reads and what effect it has. A process pack's step names a capability and its
version; the process core runs the step through the capability's own step kind (`cap.<name>.v<version>`), so a case
that started on one version keeps running on it, and a step that names a capability the running code does not know
waits instead of running (the process core's rule for an unknown kind).

- `Capability`: the description. `register(cap)` adds it (its owner may register it again); a capability that can run
  (`run` given) also gets its step kind in the process core, which checks the step's parameters before it runs.
- `step_budget(case_id, step_id, round_, limits)`: the budget a paid step spends from outside a work run: one scope per
  case, step and round (`case:<case>:<step>:<round>`) with the step's cap per provider; every call goes into the call
  log and may reuse an earlier answer to the same question, and it is business work, not a measurement.
- `of(key)`, `catalogue()`: one capability (`name@version`) and every registered one.

Layer: application; it uses the process core, the call log and the shared registries' completion. The capabilities
themselves live in the domains and register from their `register()`.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from jav.core import calls, completion, identity
from jav.core.process import cases, kinds, tasks
from jav.core.process.engine import StepContext

__all__ = ["Capability", "CapabilityError", "PROVIDERS", "catalogue", "of", "register", "step_budget"]

PROVIDERS = ("jev", "openai", "azure_di")
STEP_START = "step_start"  # 231 (A5): the human task of a step a person starts (a paid one, `_start: person`)
AWAITING_START, STARTED = "awaiting_start", "started"  # the step's phases while it waits for a person's start
MACHINE = "process-core"  # the machine that runs a step a person started, for that person
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class CapabilityError(ValueError):
    """A capability that does not fit the registry's rules, or one that is not registered."""


@dataclass(frozen=True)
class Capability:
    """One general building block.

    - `name` (a general noun, never a process's name) and `version` (a change that would move an older case another way
      is a new version); `module`: the registering module.
    - `kind`: `machine` (it works by itself), `human` (it waits for a person's decision) or `wait` (it waits for an
      event or a time).
    - `summary`: one English line (the interface translates it).
    - `params`: the pydantic model of what a process pack sets for the step (it must forbid other fields).
    - `providers`: the paid services it may call (empty: free); `rule_files`: the rule files it reads.
    - `effects`: `pure` (computes only), `store` (writes the store) or `external` (reaches another system; only through
      the process core's handover record).
    - `run(ctx, params)`: the step's work (`kinds.StepOutcome`); None while the capability is described but not yet usable
      by a process pack. `events`, `on_event`, `on_timer`: as the process core's step kinds have them.
    """

    name: str
    version: int
    module: str
    kind: Literal["machine", "human", "wait"]
    summary: str
    params: type[BaseModel]
    providers: tuple[str, ...] = ()
    rule_files: tuple[str, ...] = ()
    effects: Literal["pure", "store", "external"] = "store"
    run: Callable[[StepContext, Any], kinds.StepOutcome] | None = None
    events: tuple[str, ...] = ()
    on_event: Callable[..., str] | None = None
    on_timer: Callable[..., str] | None = None
    described: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def step_kind(self) -> str:
        return f"cap.{self.name}.v{self.version}"

    @property
    def invocable(self) -> bool:
        return self.run is not None


_CAPS: dict[str, Capability] = {}


def _check(cap: Capability) -> None:
    problems = []
    if not _NAME.match(cap.name):
        problems.append("the name is lowercase letters, digits and underscores")
    if cap.version < 1:
        problems.append("the version starts at 1")
    if cap.kind not in ("machine", "human", "wait"):
        problems.append(f"unknown kind {cap.kind!r}")
    if not (isinstance(cap.params, type) and issubclass(cap.params, BaseModel)) or cap.params.model_config.get("extra") != "forbid":
        problems.append("its parameters are a pydantic model that forbids other fields")
    if unknown := set(cap.providers) - set(PROVIDERS):
        problems.append(f"unknown providers {sorted(unknown)}")
    if cap.effects not in ("pure", "store", "external"):
        problems.append(f"unknown effect {cap.effects!r}")
    if not cap.summary.strip():
        problems.append("it needs a summary")
    if problems:
        raise CapabilityError(f"capability {cap.key}: " + "; ".join(problems))


def _starter(ctx: StepContext) -> identity.Actor | None:
    """231 (A5): the person who started the step (`_start: person`), or None while nobody has. The first time it opens
    the step's start task, which the step waits for; the decided task starts it."""
    subject = f"{ctx.case_id}:{ctx.step.id}"
    with ctx.transaction() as c:
        task = tasks.task_in(c, tasks.task_id(STEP_START, subject))
        if task is not None and task.status == tasks.DECIDED:
            if cases.step_row(c, ctx.case_id, ctx.step.id).get("phase") != STARTED:
                cases.set_phase(c, ctx.case_id, ctx.step.id, STARTED)
            return task.closed_by
        if task is None or task.status != tasks.OPEN:
            tasks.open_in(c, STEP_START, subject, ctx.actor, case_id=ctx.case_id, step_id=ctx.step.id)
        cases.set_phase(c, ctx.case_id, ctx.step.id, AWAITING_START)
    return None


def _runner(cap: Capability) -> Callable[[StepContext], kinds.StepOutcome]:
    """The capability's step kind: the step's parameters checked first (keys starting with `_` are the process pack's
    own, e.g. how the step starts, and are not the capability's)."""
    def run(ctx: StepContext) -> kinds.StepOutcome:
        if (ctx.step.params or {}).get("_start") == "person":
            starter = _starter(ctx)
            if starter is None:
                return kinds.WAIT
            # 229 (SZ2c-3): the machine works for the person who started it, under that person's name
            ctx = dataclasses.replace(ctx, actor=identity.acting_for(MACHINE, starter.name, starter))
        try:
            params = cap.params.model_validate({k: v for k, v in (ctx.step.params or {}).items() if not k.startswith("_")})
        except ValidationError as exc:
            fields = ", ".join(".".join(str(p) for p in e["loc"]) or "-" for e in exc.errors()[:5])
            return kinds.Fail(f"the step's parameters do not fit {cap.key}: {fields}")
        return cap.run(ctx, params)

    return run


def register(cap: Capability) -> None:
    """Adds a capability; its owner may register it again (a module loaded twice), another module may not. One that can
    run gets its step kind in the process core."""
    _check(cap)
    prior = _CAPS.get(cap.key)
    if prior is not None and prior.module != cap.module:
        raise CapabilityError(f"capability {cap.key} is registered by {prior.module}, not by {cap.module}")
    _CAPS[cap.key] = cap
    if cap.run is not None:
        kinds.register(kinds.StepKind(name=cap.step_kind, owner=cap.module, run=_runner(cap),
                                      events=tuple(dict.fromkeys((*cap.events, tasks.EVENT))),
                                      on_event=cap.on_event, on_timer=cap.on_timer,
                                      described={"capability": cap.key, "summary": cap.summary, **cap.described}))


def of(key: str) -> Capability:
    """The capability registered as `name@version`; `CapabilityError` if there is none."""
    if key not in _CAPS:
        completion.complete("capabilities")
    try:
        return _CAPS[key]
    except KeyError:
        raise CapabilityError(f"no capability {key} is registered") from None


def catalogue() -> list[Capability]:
    """Every registered capability, by name and version."""
    completion.complete("capabilities")
    return sorted(_CAPS.values(), key=lambda c: (c.name, c.version))


@contextmanager
def step_budget(case_id: str, step_id: str, round_: int, limits: dict[str, Decimal]) -> Iterator[str]:
    """The budget scope of one round of a case's step, with its cap per provider (a provider without a cap cannot be
    called); the step's paid calls run inside it, through the call log, and may reuse an earlier answer. A round run
    again keeps the scope and what it has spent, so a retried step cannot spend its cap twice."""
    with calls.outside_run(f"case:{case_id}:{step_id}:{round_}", limits) as scope:
        yield scope


tasks.register_kind(tasks.TaskKind(STEP_START, __name__))
