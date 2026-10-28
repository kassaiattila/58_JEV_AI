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
- `step_ref(...)`, `step_refs(params)` (stage D0, D0-a): a parameter that names another step of the case (whose result
  the step reads) is declared one, so the pack check can see that the step is there and that the step waits for it.
- `step_ref(of=)`, `step_ref_of` (stage D, D-a; the reassessment after D0, P02): the capability the named step uses,
  so the pack check refuses a step of another kind, and a reference left out where the pack has several such steps.
- `step_ref(expects=)`, `expected_result` (D-b2; P05, T03): the form the reader expects of the other step's result;
  the pack check refuses a field the giver does not give, gives as another type or may leave empty where the reader
  needs a value (a subclass fits), and the result read is checked against it before any effect.
- `Result`, `Capability.output` (D0-c): the form of a step's result; `step_ref(reads=, versions=)` says which fields of
  the other step's result a step reads and which versions of its form it takes (`reference_problem`, the pack check);
  `read_result(ctx, params, name)` reads that result checked against its form (`ResultMismatch` otherwise), and the
  step kind checks its own result before it is kept. `DatasetRef` is the form a large list is handed on in.
- `KEPT_RULES`, `AtStart` (D0-e; the owner's decision of 2026-10-26): a case runs to its end with the rule files and
  the versions it started with. A case started since D0-e names in its data the rule files its pack's capabilities read;
  where one changed since, its steps, events, timers and other work read the copy its start's calculation snapshot holds
  (`case_overlay`), and a copy of another main version stops the step with the file and both versions (`RulesUnfit`).
  A parameter naming a resource of which a case keeps the version current at its start (a price list) says so in
  `Capability.at_start`.

Layer: application; it uses the process core, the call log and the shared registries' completion. The capabilities
themselves live in the domains and register from their `register()`.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import re
import time
import types
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jav.core import calls, cfg, completion, identity, rulebook, store
from jav.core.process import cases, kinds, tasks
from jav.core.process.engine import StepContext

__all__ = ["KEPT_RULES", "Action", "AtStart", "Capability", "CapabilityError", "DatasetRef", "OwnVersionResult", "PROVIDERS",
           "RULES", "RULE_REFS", "Result", "ResultMismatch", "RuleKey", "case_overlay", "case_rules", "catalogue", "kept_rules",
           "of", "of_step_kind",
           "expected_result", "read_result", "reference_problem", "register", "step_budget", "step_reads", "step_ref",
           "step_ref_expects", "step_ref_of", "step_ref_optional", "step_refs",
           "step_scopes"]

PROVIDERS = ("jev", "openai", "azure_di")
STEP_START = "step_start"  # 231 (A5): the human task of a step a person starts (a paid one, `_start: person`)
AWAITING_START, STARTED = "awaiting_start", "started"  # the step's phases while it waits for a person's start
MACHINE = "process-core"  # the machine that runs a step a person started, for that person
SKIPPED = "skipped"  # 231 (C2c): the phase of an optional step nobody started, done as the case's other steps were
OPTIONAL_CHECK_S = 60.0  # how soon an optional step nobody started looks again whether the case's other steps are done
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
RULES, RULE_REFS = "rules", "rule_settings"  # 231 (B3): a case's own rule values in its data, and where they came from
KEPT_RULES = "kept_rule_files"  # D0-e: the rule files a case reads as it started (its data; none: it reads the files)


class CapabilityError(ValueError):
    """A capability that does not fit the registry's rules, or one that is not registered."""


class ResultMismatch(CapabilityError):
    """D0-c: a step's result, or the result of a step it reads, does not fit the form its capability gives."""


class Result(BaseModel):
    """D0-c: the base of a capability's result form: the fields it promises; others may come with it, kept as they are."""

    model_config = ConfigDict(extra="allow")


class OwnVersionResult(Result):
    """D0-c: a step done with an approved version of its own (the quote's composition, the reconciliation's pairing)."""

    version: int


class DatasetRef(BaseModel):
    """D0-c: how a large list is handed to another step: the dataset, its scope and the version of what it lists, not
    its rows (no capability gives one yet; the form is fixed here so a step result never has to carry ten thousand rows)."""

    model_config = ConfigDict(extra="forbid")
    dataset: str
    scope: dict[str, str]
    version: str


_STEP_REF = "step_ref"  # D0-a: the mark of a parameter that names another step, in its field's JSON schema extras


_EXPECTED: dict[str, type[BaseModel]] = {}  # D-b2: the forms readers expect, by the name their reference carries


def step_ref(default: Any = ..., *, reads: tuple[str, ...] = (), versions: tuple[int, ...] | None = None,
             of: str | None = None, expects: type[BaseModel] | None = None, optional: bool = False, **field: Any) -> Any:
    """D0-a: a parameter that names another step of the case, whose result the step reads (`Field` otherwise). D0-c:
    `reads`, the fields of that result it reads, and `versions`, the versions of the other capability's result form it
    takes (None: any). D-a: `of`, the capability (by name) the named step uses; a reference that may be left out reads
    the pack's only such step, so the pack check refuses one left out where there are several. D-b2: `expects`, the
    form the reader expects of that result (its fields are what it reads, typed). D-d1: `optional`, a reference that,
    left out, names no step (the step reads none), never the pack's only step of its kind."""
    token = None
    if expects is not None:
        token = f"{expects.__module__}.{expects.__qualname__}"
        _EXPECTED[token] = expects
        reads = reads or tuple(expects.model_fields)
    extra = {_STEP_REF: True, "reads": list(reads), "versions": list(versions) if versions is not None else None, "of": of,
             "expects": token, "optional": optional}
    return Field(default, json_schema_extra=extra, **field)


def step_ref_expects(params: type[BaseModel], name: str) -> type[BaseModel] | None:
    """D-b2: the form a step reference expects of the other step's result; None: only the fields it reads."""
    extra = params.model_fields[name].json_schema_extra
    token = extra.get("expects") if isinstance(extra, dict) else None
    return _EXPECTED.get(token) if isinstance(token, str) else None


def _parts(annotation: Any) -> tuple[Any, bool]:
    """(the type without None, whether it may be None)."""
    if get_origin(annotation) in (Union, types.UnionType):
        args = get_args(annotation)
        rest = tuple(a for a in args if a is not type(None))
        return (rest[0] if len(rest) == 1 else Union[rest]), len(rest) < len(args)  # noqa: UP007 - built from parts
    return annotation, False


def _type_name(t: Any) -> str:
    return getattr(t, "__name__", None) or str(t)


def _type_problem(name: str, field: str, giver_key: str, gives: Any, expects: Any) -> str | None:
    """D-b2: what is wrong with a field the giver gives as `gives` where the reader expects `expects`."""
    g, g_empty = _parts(gives)
    e, e_empty = _parts(expects)
    if g_empty and not e_empty:
        return f"{name} reads {field!r} as {_type_name(e)}, and {giver_key} may leave it empty"
    if g == e or (inspect.isclass(g) and inspect.isclass(e) and issubclass(g, e)):
        return None
    return f"{name} reads {field!r} as {_type_name(e)}, and {giver_key} gives {_type_name(g)}"


def step_ref_of(params: type[BaseModel], name: str) -> str | None:
    """D-a: the capability (by name) the step a reference names uses; None: any."""
    extra = params.model_fields[name].json_schema_extra
    return extra.get("of") if isinstance(extra, dict) else None


def step_ref_optional(params: type[BaseModel], name: str) -> bool:
    """D-d1: whether a reference left out names no step (rather than the pack's only step of its kind)."""
    extra = params.model_fields[name].json_schema_extra
    return bool(extra.get("optional")) if isinstance(extra, dict) else False


def step_refs(params: type[BaseModel]) -> tuple[str, ...]:
    """D0-a: the parameters of a capability's model that name another step (`step_ref`), in field order."""
    return tuple(name for name, f in params.model_fields.items()
                 if isinstance(f.json_schema_extra, dict) and f.json_schema_extra.get(_STEP_REF))


def step_reads(params: type[BaseModel], name: str) -> tuple[tuple[str, ...], tuple[int, ...] | None]:
    """D0-c: (the fields read, the result form's versions taken or None) of a step reference parameter."""
    extra = params.model_fields[name].json_schema_extra
    extra = extra if isinstance(extra, dict) else {}
    versions = extra.get("versions")
    return tuple(extra.get("reads") or ()), (tuple(versions) if versions is not None else None)


def reference_problem(cap: Capability, name: str, giver: Capability) -> str | None:
    """D0-c: what is wrong with `cap`'s step reference `name` naming a step of `giver`: a field read that its result
    form does not have, or a version of the form it does not take; None when it fits."""
    reads, versions = step_reads(cap.params, name)
    if giver.output is None:
        return f"{name} names a step of {giver.key}, which gives no result form" if reads else None
    if missing := [f for f in reads if f not in giver.output.model_fields]:
        return f"{name} reads {missing[0]!r}, which {giver.key} does not give"
    if (expects := step_ref_expects(cap.params, name)) is not None:  # D-b2: of the type the reader expects
        for field, info in expects.model_fields.items():
            if field not in giver.output.model_fields:
                return f"{name} reads {field!r}, which {giver.key} does not give"
            if wrong := _type_problem(name, field, giver.key, giver.output.model_fields[field].annotation, info.annotation):
                return wrong
    if versions is not None and giver.output_version not in versions:
        return (f"{name} takes the form of version {', '.join(map(str, versions))} of {giver.key}'s result, not version"
                f" {giver.output_version}")
    return None


def _fields(exc: ValidationError) -> str:
    return ", ".join(".".join(str(p) for p in e["loc"]) or "-" for e in exc.errors()[:5])


def read_result(ctx: StepContext, params: BaseModel, name: str) -> dict[str, Any]:
    """D0-c: the result of the step the parameter `name` names, checked against its capability's result form and the
    fields the parameter reads, before the step uses it. `ResultMismatch` when it does not fit (the step stops before
    any effect)."""
    ref = getattr(params, name)
    _version, result = ctx.result_of(ref)
    giver = of_step_kind(ctx.definition.step(ref).kind)
    reads, _versions = step_reads(type(params), name)
    if giver is not None and giver.output is not None:
        try:
            giver.output.model_validate(result or {})
        except ValidationError as exc:
            raise ResultMismatch(f"the result of step {ref!r} does not fit the form {giver.key} gives: {_fields(exc)}") from None
    if missing := [f for f in reads if (result or {}).get(f) is None]:
        raise ResultMismatch(f"the result of step {ref!r} does not fit: it has no {missing[0]!r}")
    expected_result(type(params), name, result or {}, ref)
    return dict(result or {})


def expected_result(params: type[BaseModel], name: str, result: dict[str, Any], ref: str | None = None) -> BaseModel | None:
    """D-b2: the result read as the form the reference expects (None: it names none); `ResultMismatch` when it does not
    fit, before the step does anything with it."""
    expects = step_ref_expects(params, name)
    if expects is None:
        return None
    try:
        return expects.model_validate(result)
    except ValidationError as exc:
        where = f"of step {ref!r} " if ref else ""
        raise ResultMismatch(f"the result {where}does not fit the form the step expects: {_fields(exc)}") from None


@dataclass(frozen=True)
class Action:
    """231 (A7d): a person's action on a step: its `name`, its English `label` (the interface translates it),
    `available(case_id, step_id)` (whether the step waits for it now) and `run(case_id, step_id, actor, note)`. D-f2:
    an action with a `form` (a pydantic model forbidding other fields) takes its values instead of a note, checked by
    the form, and `submit(case_id, step_id, actor, values)` does it; its step's own element offers it, not a button.
    `on_done`: offered on a done step too (a reopening); otherwise only while the step runs."""

    name: str
    label: str
    available: Callable[[str, str], bool]
    run: Callable[[str, str, identity.Who, str | None], None]
    form: type[BaseModel] | None = None
    submit: Callable[[str, str, identity.Who, Any], Any] | None = None
    on_done: bool = False


def _takes_values(case_id: str, step_id: str, _actor: identity.Who, _note: str | None) -> None:
    raise ValueError("this action takes values")


def form_action(name: str, label: str, available: Callable[[str, str], bool], form: type[BaseModel],
                submit: Callable[[str, str, identity.Who, Any], Any]) -> Action:
    """D-f2: an action whose values a form checks (a freeze with the day cover starts, a decision with its choice)."""
    return Action(name, label, available, _takes_values, form=form, submit=submit)


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
class AtStart:
    """Stage D0 (D0-e): a parameter naming a resource of which a case keeps the version current at its start.
    `kept(value)`: the value then, naming a concrete version (a price list's `newest_active` -> `<list>@<version>`;
    unchanged when there is none, so the step says so when it runs); `named(value)`: how a kept value reads to a person,
    {"name": ..., "version": n or None}."""

    kept: Callable[[str], str]
    named: Callable[[str], dict[str, Any]]
    # D-a: whether a value names a version a case keeps (`<id>@<n>`); a pack's `needs_at_start` refuses one that does not
    resolved: Callable[[str], bool] = field(default=lambda value: "@" in value)


@dataclass(frozen=True)
class Capability:
    """One general building block.

    - `name` (a general noun, never a process's name) and `version` (a change that would move an older case another way
      is a new version); `module`: the registering module.
    - `kind`: `machine` (it works by itself), `human` (it waits for a person's decision) or `wait` (it waits for an
      event or a time).
    - `summary`: one English line (the interface translates it).
    - `params`: the pydantic model of what a process pack sets for the step (it must forbid other fields).
    - `providers`: the paid services it may call (empty: free); `rule_files`: the rule files it reads; D-d1: `reads`,
      the rule files a step of it reads by its parameters (a fact catalogue a parameter names), kept at the case's
      start beside `rule_files`.
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
    - `reopen(wp_id, note, actor)` and `approval_what` (C3a-1), for an `own_version` capability whose case waits for that
      approval as a person's task: how the approved version is reopened with a reason (a workflow's chain reopens it,
      rule 218) and what the approval is about in "Waiting for me" (English; the interface translates it). A case of a
      pack with such a step owns its approval (`process_runtime.owns_approval`).
    - `statuses` (C3a-1): what its case's next step codes mean for a workflow's step that runs its pack (`process`),
      as a retired step kind's statuses did (the pairing: `reconcile_pair` is "pairing").
    - `waits` (C3b4): what its step waits for, by the event it waits for, in the case list's words (`person_start`,
      `person`, `reply`, `work`; `jav/app/case_lists.py`): the document processing's `run_start` is a person's start.
      An event not named: as the case list reads it.
    - `bind(wp_id, case_id, step_id, params, scope, actor)` and `bound(wp_id)` (C3b4): for a step that owns a work
      package, an existing package bound to the step of a case wrapped around it (`process_runtime.wrap_case`; False
      when the package belongs to a step already), and whether it does.
    - `records(q, params)` (C3c): for a step that reads its record from the case's scope (a `preview` one), the records
      a person may start a case from, newest first, matching `q`: each {workpackage_id, workpackage_name, item_id,
      label, detail, name, cases: [{id, name}]} (`detail`: plain values, no words; `name`: what a case started from it
      is called by default; `cases`: those already started from it).
    - `state` (stage D0, D0-b): what the state it keeps belongs to: `step` (the rule: its proposal, draft, approval,
      task and budget are the step's, so the capability may stand twice in a case) or `case` (one for the whole case,
      as the reconciliation's pairing; a pack uses such a capability once). A capability that can run says which.
    - `output`, `output_version` (stage D0, D0-c): the form of its step's result (a `Result` model: the fields it
      promises) and its version; a capability that can run names it. Its result is checked against it before it is
      kept, and before another step reads it (`read_result`).
    - `at_start` (stage D0, D0-e): its parameters that name a resource of which a case keeps the version current at its
      start (`AtStart`), by parameter.
    - `pack_check(pack)` (stage U, U2c): what is wrong with the pack's steps of it beyond their parameters' form, read
      from the whole pack (the steps they wait for, the scope parts they need), checked with the pack (`process_packs`).
    - `scope_check(pack, scope)` (U2c): raises `scopes.ScopeError` when a case's checked scope lacks what the pack's
      steps of it need (a step's own documents), at the case's start before anything is made.
    """

    name: str
    version: int
    module: str
    kind: Literal["machine", "human", "wait"]
    summary: str
    params: type[BaseModel]
    providers: tuple[str, ...] = ()
    rule_files: tuple[str, ...] = ()
    reads: Callable[[dict[str, Any]], tuple[str, ...]] | None = None
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
    reopen: Callable[[str, str, identity.Who], Any] | None = None
    approval_what: str | None = None
    statuses: Mapping[str, str] = field(default_factory=dict)
    waits: Mapping[str, str] = field(default_factory=dict)
    bind: Callable[[str, str, str, dict[str, Any], dict[str, Any], identity.Who], bool] | None = None
    bound: Callable[[str], bool] | None = None
    records: Callable[[str | None, dict[str, Any]], list[dict[str, Any]]] | None = None
    state: Literal["case", "step"] | None = None
    output: type[BaseModel] | None = None
    output_version: int = 1
    at_start: Mapping[str, AtStart] = field(default_factory=dict)
    pack_check: Callable[[Any], list[str]] | None = None
    scope_check: Callable[[Any, dict[str, Any]], None] | None = None

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
    if cap.state not in (None, "case", "step") or (cap.run is not None and cap.state is None):  # D0-b
        problems.append("a capability that can run says whether its state belongs to the case or to its step")
    if cap.run is not None and not (isinstance(cap.output, type) and issubclass(cap.output, BaseModel)):  # D0-c
        problems.append("a capability that can run names the form of its result (a pydantic model)")
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
    if unknown := sorted(set(cap.at_start) - set(cap.params.model_fields)):  # D0-e
        problems.append(f"it keeps the start's version of parameters it does not have: {unknown}")
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


def _optional_wait(ctx: StepContext) -> kinds.StepOutcome:
    """231 (C2c): an optional step nobody started: once every other step of its case is done, its start task is
    withdrawn and it is done as skipped (the case can close); until then it looks again every `OPTIONAL_CHECK_S`."""
    with ctx.transaction() as c:
        others = [row for step_id, row in cases.step_rows(c, ctx.case_id).items() if step_id != ctx.step.id]
        skip = all(row["state"] == cases.DONE for row in others)
        if skip:
            tasks.withdraw_in(c, tasks.task_id(STEP_START, f"{ctx.case_id}:{ctx.step.id}"), ctx.actor,
                              note="the case's other steps are done", notify=False)
            cases.set_phase(c, ctx.case_id, ctx.step.id, SKIPPED)
    if skip:
        return kinds.Done({"skipped": True})
    return ctx.wait(tasks.EVENT, timer=("check", time.time() + OPTIONAL_CHECK_S))


def case_overlay(data: dict[str, Any] | None, case_id: str | None = None) -> cfg.Overlay | None:
    """231 (B3): a case's own rule values, from its data (None: it has none, the files alone count); D0-e: with
    `case_id`, the kept copies of the rule files it names (`KEPT_RULES`) that changed since it started."""
    data = data or {}
    values = data.get(RULES) or {}
    names = tuple(sorted(data.get(KEPT_RULES) or ()))
    base, unfit = kept_rules(case_id, names) if case_id and names else ({}, {})
    if not (values or base or unfit):
        return None
    return cfg.Overlay(values, data.get(RULE_REFS) or {}, base=base, unfit=unfit)


def kept_rules(case_id: str, names: tuple[str, ...]) -> tuple[dict[str, cfg.Kept], dict[str, str]]:
    """D0-e: of the rule files `names`, those that changed since the case started: ({name: its kept copy}, {name: why
    it does not fit}); both empty for a case without a calculation snapshot."""
    with store.connect() as c:
        start = rulebook.of_in(c, rulebook.CASE, case_id)
    if start is None:
        return {}, {}
    now = rulebook.current()
    return _kept(start, now.snapshot_id, names)


@lru_cache(maxsize=256)
def _kept(start: str, now: str, names: tuple[str, ...]) -> tuple[dict[str, cfg.Kept], dict[str, str]]:
    """`kept_rules` by the two calculation snapshots (a snapshot's id names its contents, so the answer keeps)."""
    current = rulebook.current().files
    base: dict[str, cfg.Kept] = {}
    unfit: dict[str, str] = {}
    with store.connect() as c:
        files = (rulebook.get_in(c, start) or {}).get("files", {})
        for name in names:
            path = cfg.path_of(name).relative_to(cfg.CONFIG_DIR).as_posix()
            was, is_ = files.get(path), current.get(path)
            if was is None or (is_ is not None and was["sha256"] == is_.sha256):
                continue  # not there at the start (it reads the file), or unchanged
            if is_ is not None and cfg.major(was["version"]) != cfg.major(is_.version):
                unfit[name] = (f"the case started with the rule file {name} {was['version']}, and the code now runs "
                               f"{is_.version}: another main version, which this code does not read")
                continue
            content = rulebook.content_in(c, was["sha256"])
            if content is None:
                unfit[name] = f"the rule file {name} {was['version']} the case started with is not stored"
                continue
            # D-a: a key added since takes the value of the first later version that had it (a later change of its
            # value does not reach the case), then the file now
            data = json.loads(content)
            for later in rulebook.later_in(c, path, was["sha256"]):
                text = json.loads(later)
                if cfg.major(str((text.get("meta") or {}).get("version"))) == cfg.major(was["version"]):
                    data = cfg.filled(data, text)
            with cfg.overlay(None):
                newer = cfg.load(name) if is_ is not None else {}
            base[name] = cfg.Kept(cfg.filled(data, newer), was["sha256"], was["version"])
    return base, unfit


@contextmanager
def case_rules(case_id: str | None) -> Iterator[None]:
    """231 (B3): the work inside runs with the case's own rule values over the files; a package that is no case (or
    None) runs with the files alone. D0-e: and with the rule files as the case started, where it keeps them."""
    over = None
    if case_id:
        with store.connect() as c:
            row = cases.find_case_in(c, case_id)
        over = case_overlay(row.get("data"), case_id) if row else None
    with cfg.overlay(over):
        yield


def _with_rules(fn: Callable[..., str] | None) -> Callable[..., str] | None:
    """An event or timer handler run with its case's own rule values (B3) and kept rule files (D0-e). A kept file that
    does not fit raises: the event or timer is left for the next round (logged), and the step itself stops with why."""
    if fn is None:
        return None

    def handle(ctx: StepContext, *args: Any) -> str:
        with cfg.overlay(case_overlay(ctx.data, ctx.case_id)):
            return fn(ctx, *args)

    return handle


def _runner(cap: Capability) -> Callable[[StepContext], kinds.StepOutcome]:
    """The capability's step kind: the step's parameters checked first (keys starting with `_` are the process pack's
    own, e.g. how the step starts, and are not the capability's); 231 (B3): it runs with the case's own rule values;
    D0-e: and with the rule files as the case started, where it keeps them (one that does not fit stops the step)."""
    def run(ctx: StepContext) -> kinds.StepOutcome:
        with cfg.overlay(case_overlay(ctx.data, ctx.case_id)):
            try:
                return _run(ctx)
            except cfg.RulesUnfit as exc:  # D0-e: the file and both versions, instead of reading it differently
                return kinds.Fail(str(exc))

    def _run(ctx: StepContext) -> kinds.StepOutcome:
        if (ctx.step.params or {}).get("_start") == "person":
            starter = _starter(ctx)
            if starter is None:
                return _optional_wait(ctx) if (ctx.step.params or {}).get("_optional") else kinds.WAIT
            # 229 (SZ2c-3): the machine works for the person who started it, under that person's name
            ctx = dataclasses.replace(ctx, actor=identity.acting_for(MACHINE, starter.name, starter))
        try:
            params = cap.params.model_validate({k: v for k, v in (ctx.step.params or {}).items() if not k.startswith("_")})
        except ValidationError as exc:
            return kinds.Fail(f"the step's parameters do not fit {cap.key}: {_fields(exc)}")
        try:
            outcome = cap.run(ctx, params)
        except ResultMismatch as exc:  # D0-c: a result it reads does not fit: it stops before any effect
            return kinds.Fail(str(exc))
        if isinstance(outcome, kinds.Done) and cap.output is not None:  # D0-c: its result fits its form, or is not kept
            try:
                cap.output.model_validate(outcome.result if outcome.result is not None else {})
            except ValidationError as exc:
                return kinds.Fail(f"the step's result does not fit the form {cap.key} gives: {_fields(exc)}")
        return outcome

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
