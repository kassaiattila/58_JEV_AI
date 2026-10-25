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
- `of(key)`, `catalogue()`: one capability (`name@version`) and every registered one; `of_step_kind(kind)`: the one
  behind a step kind.
- `Action` (A7d): what a person may do on a step of the capability from the case's page or the "Waiting for me" list
  (say whether a message arrived, record a reply), each available only while the step waits for it.
- `step_scopes(case_id, step_id, uses)` (A7e): the budget scopes a case's step spent from: its own per round
  (`step_budget`), or those its capability names (`spent`, for a step whose paid work runs as a job of its domain).
- `RuleKey` (231, plan stage B, B3): a key of a rule file the capability reads that a process may set for its own
  cases (`rule_keys`). A case keeps the values active when it started (in its data, `RULES`); its steps, events and
  timers run with them over the files (`cfg.overlay`), and `case_rules(case_id)` binds them for other work on the case
  (the worker's jobs, the service's requests about it).

Layer: application; it uses the process core, the call log and the shared registries' completion. The capabilities
themselves live in the domains and register from their `register()`.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from jav.core import calls, cfg, completion, identity, store
from jav.core.process import cases, kinds, tasks
from jav.core.process.engine import StepContext

__all__ = ["Action", "Capability", "CapabilityError", "PROVIDERS", "RULES", "RULE_REFS", "RuleKey", "case_overlay",
           "case_rules", "catalogue", "of", "of_step_kind", "register", "step_budget", "step_scopes"]

PROVIDERS = ("jev", "openai", "azure_di")
STEP_START = "step_start"  # 231 (A5): the human task of a step a person starts (a paid one, `_start: person`)
AWAITING_START, STARTED = "awaiting_start", "started"  # the step's phases while it waits for a person's start
MACHINE = "process-core"  # the machine that runs a step a person started, for that person
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
RULES, RULE_REFS = "rules", "rule_settings"  # 231 (B3): a case's own rule values in its data, and where they came from


class CapabilityError(ValueError):
    """A capability that does not fit the registry's rules, or one that is not registered."""


@dataclass(frozen=True)
class Action:
    """231 (A7d): a person's action on a step: its `name`, its English `label` (the interface translates it),
    `available(case_id, step_id)` (whether the step waits for it now) and `run(case_id, step_id, actor, note)`."""

    name: str
    label: str
    available: Callable[[str, str], bool]
    run: Callable[[str, str, identity.Who, str | None], None]


@dataclass(frozen=True)
class RuleKey:
    """231 (B3): a key of a rule file the capability reads that a process may set for its own cases.

    - `file`: a config name among the capability's `rule_files`; `key`: dotted, from the file's top.
    - `kind`: `int` (a whole number between `least` and `most`) or `choice` (one of `options`, as the file writes it).
    - `what`: one English line (the interface translates it).

    A key that would change what is asked from a paid service, or a budget, is never one: those stay changes of the
    file, measured and decided.
    """

    file: str
    key: str
    kind: Literal["int", "choice"]
    what: str
    least: int | None = None
    most: int | None = None
    options: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return f"{self.file}.{self.key}"

    def file_value(self) -> Any:
        """The value the file holds (`KeyError` when it has none)."""
        with cfg.overlay(None):
            node: Any = cfg.load(self.file)
        for part in self.key.split("."):
            node = node[part]
        return node

    def problems(self, value: Any) -> list[str]:
        """What is wrong with `value` for this key (empty: it fits)."""
        if self.kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                return [f"{self.id} is a whole number"]
            if (self.least is not None and value < self.least) or (self.most is not None and value > self.most):
                return [f"{self.id} is between {self.least} and {self.most}"]
            return []
        return [] if value in self.options else [f"{self.id} is one of {', '.join(self.options)}"]


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
    - `actions`: what a person may do on its step (A7d); `spent(case_id, step_id)`: the budget scopes its step spent
      from when they are not the step's own (A7e).
    - `rule_keys`: the keys of its rule files a process may set for its own cases (B3).
    - `choices` (B4): for a parameter a process may set through a resource of its pack, the values it may take, each
      with an English label (a function, as they may live in the store: the active price lists). A process's own value
      of such a resource is one of them; the parameter's field title names the resource.
    - `adopt(wp_id, params)` (C0): the state its step is in when an existing work package is taken over as a case
      (`process_runtime.adopt_case`), read from the work the package already holds; None: the step has not run. A
      capability without it: its step has not run.
    - `preview(record, params)` (C1a): for a step that reads its record from the case's scope, what it would read
      from `record` before a case starts (`jav/app/intake.py`): {"record": the record as the step reads it, "gaps":
      [{"code", "message"}], "list_field": the field of its list, "record_type": its type (the field labels')}; None
      when `record` holds none.
    - `own_version` (C2d): its step is done with the case's own approved version (a person's approval of the result),
      so reopening that version reopens the step (`process_runtime.own_version_reopened`).
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
    actions: tuple[Action, ...] = ()
    spent: Callable[[str, str], list[str]] | None = None
    rule_keys: tuple[RuleKey, ...] = ()
    choices: Mapping[str, Callable[[], list[tuple[str, str]]]] = field(default_factory=dict)
    adopt: Callable[[str, Any], cases.Adopted | None] | None = None
    preview: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | None] | None = None
    own_version: bool = False

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
    names = [a.name for a in cap.actions]
    if len(set(names)) != len(names) or not all(_NAME.match(n) for n in names):
        problems.append("its actions have distinct lowercase names")
    for rule in cap.rule_keys:
        if rule.file not in cap.rule_files:
            problems.append(f"its rule key {rule.id} is not in a rule file it reads")
            continue
        if rule.kind not in ("int", "choice") or (rule.kind == "choice") != bool(rule.options):
            problems.append(f"its rule key {rule.id} is a whole number or a choice of options")
            continue
        try:
            problems += [f"the file's value does not fit: {p}" for p in rule.problems(rule.file_value())]
        except (KeyError, TypeError):
            problems.append(f"its rule file has no {rule.id}")
    if len({r.id for r in cap.rule_keys}) != len(cap.rule_keys):
        problems.append("its rule keys are distinct")
    if unknown := sorted(set(cap.choices) - set(cap.params.model_fields)):
        problems.append(f"it offers choices for parameters it does not have: {unknown}")
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


def case_overlay(data: dict[str, Any] | None) -> cfg.Overlay | None:
    """231 (B3): a case's own rule values, from its data (None: it has none, the files alone count)."""
    values = (data or {}).get(RULES) or {}
    return cfg.Overlay(values, (data or {}).get(RULE_REFS) or {}) if values else None


@contextmanager
def case_rules(case_id: str | None) -> Iterator[None]:
    """231 (B3): the work inside runs with the case's own rule values over the files; a package that is no case (or
    None) runs with the files alone."""
    over = None
    if case_id:
        with store.connect() as c:
            row = cases.find_case_in(c, case_id)
        over = case_overlay(row.get("data")) if row else None
    with cfg.overlay(over):
        yield


def _with_rules(fn: Callable[..., str] | None) -> Callable[..., str] | None:
    """An event or timer handler run with its case's own rule values (B3)."""
    if fn is None:
        return None

    def handle(ctx: StepContext, *args: Any) -> str:
        with cfg.overlay(case_overlay(ctx.data)):
            return fn(ctx, *args)

    return handle


def _runner(cap: Capability) -> Callable[[StepContext], kinds.StepOutcome]:
    """The capability's step kind: the step's parameters checked first (keys starting with `_` are the process pack's
    own, e.g. how the step starts, and are not the capability's); 231 (B3): it runs with the case's own rule values."""
    def run(ctx: StepContext) -> kinds.StepOutcome:
        with cfg.overlay(case_overlay(ctx.data)):
            return _run(ctx)

    def _run(ctx: StepContext) -> kinds.StepOutcome:
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
                                      on_event=_with_rules(cap.on_event), on_timer=_with_rules(cap.on_timer),
                                      described={"capability": cap.key, "summary": cap.summary, **cap.described}))


def of(key: str) -> Capability:
    """The capability registered as `name@version`; `CapabilityError` if there is none."""
    if key not in _CAPS:
        completion.complete("capabilities")
    try:
        return _CAPS[key]
    except KeyError:
        raise CapabilityError(f"no capability {key} is registered") from None


def of_step_kind(kind: str) -> Capability | None:
    """The capability whose step kind this is (`cap.<name>.v<version>`); None for another kind."""
    m = re.fullmatch(r"cap\.([a-z][a-z0-9_]*)\.v([0-9]+)", kind)
    return of(f"{m.group(1)}@{m.group(2)}") if m else None


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


def step_scopes(case_id: str, step_id: str, uses: str) -> list[str]:
    """231 (A7e): the budget scopes the case's step spent from, oldest first: those its capability names, or its own
    rounds' (`case:<case>:<step>:<round>`)."""
    cap = of(uses)
    if cap.spent is not None:
        return cap.spent(case_id, step_id)
    return calls.scopes_under(f"case:{case_id}:{step_id}:")


tasks.register_kind(tasks.TaskKind(STEP_START, __name__))
