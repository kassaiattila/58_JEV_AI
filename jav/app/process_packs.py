"""Process packs (231, plan stage A, A4; DECISIONS 231): one kind of business process described as data.

Plain-language summary: the owner's decisions of 2026-10-24: what the owner calls a workflow is described by a process
pack, and one running instance of it is a case; a developer builds each pack, only from the registered general
capabilities. A pack (`configs/processes/<id>.json`) says what a case belongs to (its scope), what may start one (its
intake), the values it takes from the shared library (its resources; for now plain values), its steps (each names a
capability and its version, the steps it follows, whether a person starts it, and the capability's parameters), its
screens (tabs built from the registered screen elements, `configs/screen_elements.json`), its outputs and its golden
sets. It holds no code: a string naming a Python module is refused. The check refuses a pack whose step names an
unknown capability or parameters that do not fit it, a paid step that would start without a person (the rule of
2026-09-28), an email intake that names no intent or (231 C1b) that starts a case by itself without a record to start
from (a record scope part and a step whose capability reads it), an unknown screen element, scope part or output, and a
reference to a step or a resource that is not there. Stage D0 (D0-a): a step whose capability cannot run (it is described
only), a step parameter naming another step that is not there or that the step does not wait for (directly or through
another), a screen element the catalogue lists as planned, and an element that shows nothing: no data is registered for
its type and its step's capability (or, without a step, for its type alone). A refused pack starts no case. D0-b: a
capability whose state belongs to the whole case (`Capability.state`) stands once in a pack. D0-c: a step reference
reads only fields the other step's result form gives, in a version of the form it takes (`capabilities.reference_problem`).
Stage D (D-a; the reassessment after D0, P02): a reference names a step of the kind it reads (`step_ref(of=)`); one
left out reads the pack's only step of that kind, which the step must wait for, and is refused where there are several,
so the step's source, the step it waits for and its approval's basis are the same step. `needs_at_start`: the resources
a case cannot start without a version of to keep (`process_settings.at_start` refuses the start). Stage U (U0): its
`summary` (what the process is for, when a person picks one) and its `examples` (its example material: the sets of
things it installs, and a file of invented documents, which the check requires to be there; `jav/app/examples.py`).
U2c: what a step reads from the whole pack (a sub-case's scope parts, the steps it waits for) is checked by its
capability (`Capability.pack_check`).

- `load(pack_id)`, `packs()`: a pack read and checked (`PackError` with every problem).
- `definition(pack)`: the process core's definition of the pack's current version: one step per pack step, its kind
  the capability's step kind, its parameters with the resources filled in; a case keeps the definition it started with.

Layer: application; it reads the config, the capability registry, the scope parts and the output contracts.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jav.app import capabilities, scopes
from jav.core import cfg
from jav.core.process.definition import NAME, ProcessDef, StepDef

__all__ = ["Adopt", "Choice", "Element", "ExampleSet", "Examples", "FollowUp", "Intake", "Option", "PackError", "PartnerLink",
           "ProcessPack", "Replaced", "Step", "Tab", "UnknownPack", "chosen", "definition", "load", "packs", "picked",
           "variants"]

ELEMENTS = "screen_elements"
EXAMPLE_DOCUMENTS = "examples_"  # 231 (U0): `configs/examples_<name>.json`, a pack's invented documents
PLANNED = "planned"  # D0-a: a screen element the catalogue lists before it is built; no pack may use it


def _data_table_problems(where: str, name: Any) -> list[str]:
    """261 (B1f): a shared data table names a registered dataset whose mandatory scope a case gives."""
    from jav.app import case_views, datasets  # lazy: the datasets read the packages, which read the packs

    if not isinstance(name, str):
        return [f"{where}: element 'data_table' names no dataset"]
    try:
        dataset = datasets.get(name)
    except datasets.UnknownDataset:
        return [f"{where}: element 'data_table' names an unknown dataset {name!r}"]
    if not set(dataset.scope) <= case_views.CASE_SCOPE:
        return [f"{where}: dataset {name!r} needs a scope a case does not give: {sorted(set(dataset.scope) - case_views.CASE_SCOPE)}"]
    return []
_MODULE = re.compile(r"\bjav\.[a-z_]+")


class PackError(ValueError):
    """A process pack that cannot be read or does not pass the check; the message lists every problem."""


class UnknownPack(PackError):
    """231 (B2): no process pack of this id."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Intake(_Model):
    """What may start a case: an email read with an intent (`offer`: the email offers to start one; 231 C1b, `case`: it
    starts one by itself, `jav/app/intake.py`), (C1c) a work package of one of `package_kinds` (its page offers a case
    that reads it, scope part `sources`), or a person."""

    on: Literal["email_intent", "package", "manual"]
    intent: str | None = None
    package_kinds: tuple[str, ...] = ()
    starts: Literal["offer", "case", "manual"]


class Adopt(_Model):
    """231 (C1c): a kind of work package made before the process was a pack (its own kind until then) that is taken over
    as its case (`process_runtime.adopt_all`): the kind, and which of its stored scope parts gives each scope part of
    the case ({case part: stored part})."""

    kind: str = Field(min_length=1)
    scope: dict[str, str] = Field(default_factory=dict)


class Wrap(_Model):
    """231 (C3b4): a kind of work package made before the process was a pack whose package becomes the package of one
    of its steps: a new case is made around it (`process_runtime.wrap_case`; its id, items, runs and approvals stay),
    with the scope its stored scope parts give ({case part: stored part}) and the scope part `package_part` naming the
    package (`{"kind": "package", "workpackage_id"}`). The step's capability binds it (`Capability.bind`). 231 (C3b5a):
    the packages are named by their `kind` or by the package `rule` they run by (`work.RULE_PART`), exactly one."""

    kind: str | None = None
    rule: str | None = None
    step: str = Field(pattern=NAME)
    package_part: str = Field(pattern=NAME)
    scope: dict[str, str] = Field(default_factory=dict)


class Serves(_Model):
    """231 (C3b5b): the workflow step kind a pack serves (`configs/workflows.json` `kinds`): a workflow's step of the
    kind is the pack's (its step kind is made by the process runtime, `process_runtime.pack_step_kind`), its new package
    wrapped by a case of the pack: `step`, the pack's step that takes the package, and `package_part`, the scope part
    naming it."""

    kind: str = Field(pattern=NAME)
    step: str = Field(pattern=NAME)
    package_part: str = Field(pattern=NAME)


class Step(_Model):
    id: str = Field(pattern=NAME)
    uses: str = Field(pattern=r"^[a-z][a-z0-9_]*@[1-9][0-9]*$")
    title: str | None = None
    after: tuple[str, ...] = ()
    gates: tuple[str, ...] = ()
    start: Literal["auto", "person"] = "auto"
    params: dict[str, Any] = Field(default_factory=dict)
    optional: bool = False  # 231 (C2c): a step a person may leave unstarted; the case closes without it


class Element(BaseModel):
    """One element of a tab: its type and, for most, the step it shows; an element's own settings are kept as given."""

    model_config = ConfigDict(extra="allow", frozen=True)
    type: str = Field(min_length=1)
    step: str | None = None


class Tab(_Model):
    id: str = Field(pattern=NAME)
    label: str = Field(min_length=1)
    elements: tuple[Element, ...] = Field(min_length=1)


class Screens(_Model):
    tabs: tuple[Tab, ...] = Field(min_length=1)


class Scope(_Model):
    """The parts a case's scope has; 231 (C3a-2): `optional` ones may be left out, and then stay out (the
    reconciliation's party: without one it reconciles its accounts alone, every invoice its own, as a package could)."""

    parts: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()

    def needs(self) -> tuple[str, ...]:
        return tuple(p for p in self.parts if p not in self.optional)


PARTNER_FIELDS = ("name", "tax_number", "email", "phone", "address")


class FollowUp(_Model):
    """231 (U1; the owner's decision of 2026-10-28): what may follow a case closed with an outcome: another process a
    person starts from the case's own scope (its documents), offered on the closed case's page."""

    on: str = Field(pattern=NAME)  # the outcome the case closed with
    pack: str = Field(pattern=NAME)
    title: str = Field(min_length=1)  # the button's text, English (the interface translates it)


class PartnerLink(_Model):
    """231 (B1): a partner a case is about: its role (`configs/partners.json`), the step whose result holds the record's
    fields, and which of them give the partner's values (`name` at least)."""

    role: str = Field(min_length=1)
    from_step: str = Field(pattern=NAME)
    fields: dict[str, str] = Field(min_length=1)


class ExampleSet(_Model):
    """231 (stage U, U0): a set of versioned things a process's examples install: its kind (the module that keeps such
    things registers how a set of them is installed, `jav/app/examples.py`) and its name."""

    kind: str = Field(pattern=NAME)
    name: str = Field(pattern=NAME)


class Examples(_Model):
    """231 (U0): a process's invented example material: the sets of things it installs, and the invented documents
    (`configs/examples_<documents>.json`, packets of printed pages or texts) a case of it can start on; (U1e) a
    sentence on how the material is tried, shown with it."""

    sets: tuple[ExampleSet, ...] = ()
    documents: str | None = Field(default=None, pattern=NAME)
    note: str | None = Field(default=None, min_length=1)


class Option(_Model):
    """277 (O3; the owner's decision of 2026-11-02: one case type in place of several alike): one answer to a choice a
    case is started with: the steps it leaves out (a step that waited for one waits for the rest), the resources and
    the step parameters it sets over the pack's, and its own example material in place of the pack's."""

    id: str = Field(pattern=NAME)
    title: str = Field(min_length=1)  # English; the interface translates it
    summary: str | None = Field(default=None, min_length=1)
    leaves_out: tuple[str, ...] = ()
    resources: dict[str, str] = Field(default_factory=dict)
    params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    examples: Examples | None = None


class Choice(_Model):
    """277 (O3): a choice a person makes when a case starts, its options and the one taken when nothing is chosen."""

    id: str = Field(pattern=NAME)
    title: str = Field(min_length=1)
    default: str = Field(pattern=NAME)
    options: tuple[Option, ...] = Field(min_length=2)


class Replaced(_Model):
    """277 (O3): a process pack this one took the place of, and the choices that make a case of this one what a case of
    that one was (the next period of an earlier case, the case list's folding of the old cases)."""

    pack: str = Field(pattern=NAME)
    choices: dict[str, str] = Field(default_factory=dict)


class ProcessPack(_Model):
    meta: dict[str, Any]
    id: str = Field(pattern=NAME)
    title: str = Field(min_length=1)
    summary: str | None = Field(default=None, min_length=1)  # 231 (U0): what the process is for, when a person picks one
    examples: Examples | None = None  # 231 (U0)
    scope: Scope = Scope()
    intake: tuple[Intake, ...] = ()
    adopts: tuple[Adopt, ...] = ()
    wraps: tuple[Wrap, ...] = ()  # 231 (C3b4)
    workflow: Serves | None = None  # 231 (C3b5b)
    resources: dict[str, str] = Field(default_factory=dict)
    steps: tuple[Step, ...] = Field(min_length=1)
    screens: Screens
    outputs: tuple[str, ...] = ()
    goldens: tuple[str, ...] = ()
    partners: tuple[PartnerLink, ...] = ()  # 231 (B1)
    follow_ups: tuple[FollowUp, ...] = ()  # 231 (U1): a process a closed case's person may start from its scope
    # 261 (the owner's decision of 2026-10-29): a case of it may be repeated for its next period (its page offers it)
    repeats: bool = False
    # stage D (D-a, P04): the resources a case cannot start without a version of to keep (a tariff); none: it may start
    needs_at_start: tuple[str, ...] = ()
    # 231 (U3c; the owner's decision of 2026-10-28): a resource that follows from another ({resource: source}): the
    # source's thing brings it (a product its tariff), and a process does not set it on its own
    derived: dict[str, str] = Field(default_factory=dict)
    # 277 (O3): the choices a case starts with (`chosen`), and the packs this one took the place of
    choices: tuple[Choice, ...] = ()
    replaces: tuple[Replaced, ...] = ()

    @property
    def version(self) -> str:
        return str(self.meta["version"])


def picked(pack: ProcessPack, choices: dict[str, str] | None) -> dict[str, str]:
    """277 (O3): the pack's choices as a case starts with them, each one not given at its default; `PackError` for a
    choice the pack does not ask or an option it does not have."""
    given = dict(choices or {})
    asked = {c.id: c for c in pack.choices}
    unknown = sorted(set(given) - set(asked))
    if unknown:
        raise PackError(f"process pack {pack.id!r} has no choice {unknown[0]!r}")
    out: dict[str, str] = {}
    for choice in pack.choices:
        option = given.get(choice.id, choice.default)
        if option not in {o.id for o in choice.options}:
            raise PackError(f"process pack {pack.id!r} has no option {option!r} of the choice {choice.id!r}")
        out[choice.id] = option
    return out


def variants(pack: ProcessPack) -> list[dict[str, str]]:
    """277 (O3): every combination of the pack's options, in the options' order ([{}] for a pack without choices)."""
    out: list[dict[str, str]] = [{}]
    for choice in pack.choices:
        out = [{**v, choice.id: o.id} for v in out for o in choice.options]
    return out


def chosen(pack: ProcessPack, choices: dict[str, str] | None = None) -> ProcessPack:
    """277 (O3): the pack as a case started with `choices` runs it, before its definition is made: the steps its options
    leave out are gone (and from what the other steps wait for, the screens, the partners, the wraps and the workflow
    kind), their resources and step parameters are set over the pack's, an option's examples take the place of the
    pack's, and it asks no choice any more. A pack without choices is returned as it is (`PackError` for a choice
    given to it)."""
    if not pack.choices:
        if choices:
            picked(pack, choices)  # refuses the choice it does not ask
        return pack
    picks = picked(pack, choices)
    options = [next(o for o in c.options if o.id == picks[c.id]) for c in pack.choices]
    left = {s for o in options for s in o.leaves_out}
    resources = dict(pack.resources)
    params: dict[str, dict[str, Any]] = {}
    for option in options:
        resources.update(option.resources)
        for step_id, values in option.params.items():
            params.setdefault(step_id, {}).update(values)
    steps = tuple(s.model_copy(update={"after": tuple(a for a in s.after if a not in left),
                                       "gates": tuple(g for g in s.gates if g not in left),
                                       "params": {**s.params, **params.get(s.id, {})}})
                  for s in pack.steps if s.id not in left)
    tabs = tuple(t.model_copy(update={"elements": kept}) for t in pack.screens.tabs
                 if (kept := tuple(e for e in t.elements if e.step not in left)))
    examples = next((o.examples for o in options if o.examples is not None), pack.examples)
    return pack.model_copy(update={
        "resources": resources, "steps": steps, "screens": pack.screens.model_copy(update={"tabs": tabs}),
        "examples": examples, "partners": tuple(p for p in pack.partners if p.from_step not in left),
        "wraps": tuple(w for w in pack.wraps if w.step not in left),
        "workflow": pack.workflow if pack.workflow is None or pack.workflow.step not in left else None,
        "choices": ()})


def _choice_problems(pack: ProcessPack, known: list[str]) -> list[str]:
    """277 (O3): what is wrong with the pack's choices and what it replaces; then every combination of its options
    checked as a pack of its own, each problem named by the combination (one the whole pack has, `known`, only once)."""
    problems: list[str] = []
    ids = {s.id for s in pack.steps}
    names = [c.id for c in pack.choices]
    problems += [f"a choice is listed twice: {n}" for n in sorted({n for n in names if names.count(n) > 1})]
    for choice in pack.choices:
        options = [o.id for o in choice.options]
        problems += [f"choice {choice.id!r}: an option is listed twice: {n}" for n in sorted({n for n in options if options.count(n) > 1})]
        if choice.default not in options:
            problems.append(f"choice {choice.id!r}: its default {choice.default!r} is none of its options")
        for option in choice.options:
            where = f"choice {choice.id!r}: option {option.id!r}"
            problems += [f"{where} leaves out no step {s!r}" for s in option.leaves_out if s not in ids]
            problems += [f"{where} sets parameters of no step {s!r}" for s in option.params if s not in ids]
            problems += [f"{where} sets the pack's own parameter {k!r}" for values in option.params.values()
                         for k in values if k.startswith("_")]
            problems += [f"{where} sets {k!r}, which is no resource of the pack" for k in option.resources
                         if k not in pack.resources]
    for old in pack.replaces:
        if old.pack == pack.id:
            problems.append(f"the pack replaces itself ({old.pack!r})")
            continue
        try:
            picked(pack, old.choices)
        except PackError as exc:
            problems.append(f"replaces {old.pack!r}: " + str(exc).replace(f"process pack {pack.id!r} has ", ""))
    if problems:
        return problems  # the combinations are only built from a sound set of choices
    for picks in variants(pack):
        if not picks:
            continue
        where = "with " + ", ".join(f"{k}={v}" for k, v in picks.items())
        variant = chosen(pack, picks)
        if not variant.steps:
            problems.append(f"{where}: it leaves out every step")
            continue
        problems += [f"{where}: {p}" for p in _problems(variant) if p not in known]
    return problems


def _resolved(params: dict[str, Any], resources: dict[str, str], problems: list[str], where: str) -> dict[str, Any]:
    """The parameters with `@name` replaced by the pack's resource of that name."""
    out = {}
    for key, value in params.items():
        if isinstance(value, str) and value.startswith("@"):
            if value[1:] not in resources:
                problems.append(f"{where}: unknown resource {value}")
                continue
            value = resources[value[1:]]
        out[key] = value
    return out


def _capability(key: str) -> capabilities.Capability | None:
    try:
        return capabilities.of(key)
    except capabilities.CapabilityError:
        return None


def records(pack_id: str, q: str | None = None) -> list[dict[str, Any]]:
    """231 (C3c): the records a case of the pack may start from, matching `q`: those of its first step whose capability
    finds them (`Capability.records`), with the step's parameters as its case would have them; none when no step
    does. `UnknownPack` for an unknown pack."""
    pack = load(pack_id)
    defn = definition(pack)
    for step in pack.steps:
        cap = _capability(step.uses)
        if cap is not None and cap.records is not None:
            params = {k: v for k, v in (defn.step(step.id).params or {}).items() if not k.startswith("_")}
            return cap.records(q, params)
    return []


def _waited_for(step_id: str, needs: dict[str, tuple[str, ...]]) -> set[str]:
    """D0-a: the steps a step waits for, directly or through another."""
    seen: set[str] = set()
    todo = list(needs.get(step_id, ()))
    while todo:
        s = todo.pop()
        if s not in seen:
            seen.add(s)
            todo += needs.get(s, ())
    return seen


def _implicit_source(pack: ProcessPack, step_id: str, name: str, of: str | None, needs: dict[str, tuple[str, ...]],
                     where: str) -> list[str]:
    """D-a: what is wrong with a step reference left out: several steps of the kind it reads (nothing says which), or
    the only one is a step the step does not wait for (its approval would not build on what it read)."""
    if of is None:
        return []
    found = [s.id for s in pack.steps if s.uses.split("@", 1)[0] == of and s.id != step_id]
    if len(found) > 1:
        return [f"{where}: {name} names no step, and the pack has several {of} steps ({', '.join(found)}): name the one it reads"]
    if found and found[0] not in _waited_for(step_id, needs):
        return [f"{where}: {name} names no step, and the step does not wait for the only {of} step {found[0]!r}"]
    return []


def _problems(pack: ProcessPack) -> list[str]:
    from jav.app import case_views  # it reads the packs, so it is imported when a pack is checked

    problems: list[str] = []
    if _MODULE.search(json.dumps(pack.model_dump(), ensure_ascii=False)):
        problems.append("a process pack holds no code: it names a Python module")
    known_parts = {p.name for p in scopes.parts()}
    problems += [f"unknown scope part {p!r}" for p in pack.scope.parts if p not in known_parts]
    for follow in pack.follow_ups:  # 231 (U1): the process that follows takes what this one's scope holds
        try:
            needs = cfg.load(f"process:{follow.pack}").get("scope", {})
        except FileNotFoundError:
            problems.append(f"a follow-up names no process pack {follow.pack!r}")
            continue
        wanted = set(needs.get("parts", ())) - set(needs.get("optional", ()))
        if not wanted <= set(pack.scope.parts):
            problems.append(f"the follow-up {follow.pack!r} needs scope parts this pack does not hold: "
                            + ", ".join(sorted(wanted - set(pack.scope.parts))))
    problems += [f"optional scope part {p!r} is not one of its parts" for p in pack.scope.optional if p not in pack.scope.parts]
    if pack.repeats and scopes.PERIOD not in pack.scope.parts:  # 261: its next case is the next period's
        problems.append("a process repeated for its next period needs a period in its scope")
    if any(i.on == "email_intent" and not i.intent for i in pack.intake):
        problems.append("an email intake names its intent")
    for i in pack.intake:  # 231 (C1c): a package offers a case that reads it
        if i.on == "package" and (not i.package_kinds or i.starts != "offer" or scopes.SOURCES not in pack.scope.parts):
            problems.append("a package intake names its package kinds, offers the case and reads its sources")
    if any(i.starts == "case" for i in pack.intake):  # 231 (C1b): a case started by itself starts from the email's record
        if any(i.on != "email_intent" for i in pack.intake if i.starts == "case"):
            problems.append("only an email intake starts a case by itself")
        reads = any(_capability(s.uses) is not None and _capability(s.uses).preview is not None for s in pack.steps)
        if scopes.RECORD not in pack.scope.parts or not reads:
            problems.append("an intake that starts a case by itself needs a record scope part and a step that reads it")
    ids = [s.id for s in pack.steps]
    needs = {s.id: (*s.after, *s.gates) for s in pack.steps}
    uses = {s.id: s.uses for s in pack.steps}
    for step in pack.steps:
        where = f"step {step.id!r}"
        try:
            cap = capabilities.of(step.uses)
        except capabilities.CapabilityError:
            problems.append(f"{where}: no capability {step.uses} is registered")
            continue
        if not cap.invocable:  # D0-a: the case would stop at this step
            problems.append(f"{where}: {step.uses} cannot run: it is described only")
        for name in capabilities.step_refs(cap.params):  # D0-a: the step reads that step's result
            ref = step.params.get(name)
            of = capabilities.step_ref_of(cap.params, name)
            if ref is None:  # D-a: the pack's only such step; D-d1: or none, for an optional reference
                if not capabilities.step_ref_optional(cap.params, name):
                    problems += _implicit_source(pack, step.id, name, of, needs, where)
                continue
            if ref not in ids:
                problems.append(f"{where}: {name} names no step {ref!r}")
            elif ref not in _waited_for(step.id, needs):
                problems.append(f"{where}: {name} names step {ref!r}, which it does not wait for")
            elif of is not None and uses[ref].split("@", 1)[0] != of:
                problems.append(f"{where}: {name} names step {ref!r}, a {uses[ref].split('@', 1)[0]} step, not a {of} step")
            elif (giver := _capability(uses[ref])) is not None and (wrong := capabilities.reference_problem(cap, name, giver)):
                problems.append(f"{where}: {wrong}")  # D0-c: it reads what the other step's result form gives
        try:
            cap.params.model_validate(_resolved(step.params, pack.resources, problems, where))
        except ValidationError as exc:
            problems.append(f"{where}: its parameters do not fit {step.uses}: "
                            + ", ".join(".".join(map(str, e["loc"])) or "-" for e in exc.errors()[:5]))
        if cap.providers and step.start != "person":
            problems.append(f"{where}: a paid step ({step.uses}) is started by a person")
        if step.optional and step.start != "person":
            problems.append(f"{where}: only a step a person starts may be optional")
    for key in dict.fromkeys(s.uses for s in pack.steps):  # 231 (U2c): what a capability reads from the whole pack
        if (cap := _capability(key)) is not None and cap.pack_check is not None:
            problems += cap.pack_check(pack)
    case_owned = [s.uses for s in pack.steps if (c := _capability(s.uses)) is not None and c.state == "case"]
    for key in sorted({k for k in case_owned if case_owned.count(k) > 1}):  # D0-b: two steps would share one state
        problems.append(f"{key} keeps its state for the whole case: a pack uses it once")
    problems += [f"derived {key!r} from {source!r}: both are resources of the pack, and differ" for key, source in
                 pack.derived.items() if key not in pack.resources or source not in pack.resources or key == source]  # U3c
    problems += [f"needs_at_start names {key!r}, which is no resource of the pack" for key in pack.needs_at_start
                 if key not in pack.resources]  # D-a
    kept_keys = {value[1:] for step in pack.steps if (cap := _capability(step.uses)) is not None
                 for name, value in (step.params or {}).items()
                 if isinstance(value, str) and value.startswith("@") and name in cap.at_start}
    problems += [f"needs_at_start names {key!r}, which no step keeps at a version" for key in pack.needs_at_start
                 if key in pack.resources and key not in kept_keys and not key.startswith("template:")]  # D-c4
    if pack.examples is not None and pack.examples.documents is not None:  # 231 (U0): the invented documents are there
        try:
            cfg.load(EXAMPLE_DOCUMENTS + pack.examples.documents)
        except FileNotFoundError:
            problems.append(f"examples: no invented documents {pack.examples.documents!r}")
    for wrap in pack.wraps:  # 231 (C3b4): the step that takes the package binds it, and its parts are the scope's
        if (wrap.kind is None) == (wrap.rule is None):
            problems.append(f"wrap {wrap.kind or wrap.rule!r}: names its packages by a kind or by a rule, one of them")
        step = next((s for s in pack.steps if s.id == wrap.step), None)
        cap = _capability(step.uses) if step is not None else None
        if cap is None or cap.bind is None or cap.bound is None:
            problems.append(f"wrap {wrap.kind or wrap.rule!r}: step {wrap.step!r} takes no package (its capability binds none)")
        if wrap.package_part not in pack.scope.parts or set(wrap.scope) - set(pack.scope.parts):
            problems.append(f"wrap {wrap.kind or wrap.rule!r}: its parts are scope parts of the pack")
    if (serves := pack.workflow) is not None:  # 231 (C3b5b): its step takes the package, its part is the scope's
        step = next((s for s in pack.steps if s.id == serves.step), None)
        cap = _capability(step.uses) if step is not None else None
        if cap is None or cap.bind is None:
            problems.append(f"workflow {serves.kind!r}: step {serves.step!r} takes no package (its capability binds none)")
        if serves.package_part not in pack.scope.parts:
            problems.append(f"workflow {serves.kind!r}: {serves.package_part!r} is not a scope part of the pack")
    elements = cfg.load(ELEMENTS)["elements"]
    for tab in pack.screens.tabs:
        for element in tab.elements:
            where = f"tab {tab.id!r}"
            if element.type not in elements:
                problems.append(f"{where}: unknown screen element {element.type!r}")
                continue
            if elements[element.type].get("status") == PLANNED:  # D0-a: the interface has no component for it yet
                problems.append(f"{where}: screen element {element.type!r} is planned, not built")
                continue
            if element.step is not None and element.step not in ids:
                problems.append(f"{where}: element {element.type!r} shows no step {element.step!r}")
                continue
            cap = _capability(uses[element.step]) if element.step is not None else None
            if element.step is not None and cap is None:
                continue  # its step's unknown capability is named above
            if not case_views.gives(element.type, cap.name if cap is not None else None):  # D0-a: it would stay empty
                problems.append(f"{where}: element {element.type!r} shows nothing "
                                + (f"for a step of {uses[element.step]}" if element.step is not None else "without a step"))
            if element.type == "data_table":  # 261 (B1f): a registered dataset the case gives the scope of
                problems += _data_table_problems(where, (element.model_extra or {}).get("dataset"))
    known_roles = set(cfg.load("partners")["roles"])
    for link in pack.partners:  # 231 (B1)
        where = f"partner {link.role!r}"
        if link.role not in known_roles:
            problems.append(f"{where}: unknown partner role")
        if link.from_step not in ids:
            problems.append(f"{where}: no step {link.from_step!r}")
        if "name" not in link.fields or set(link.fields) - set(PARTNER_FIELDS):
            problems.append(f"{where}: its fields give a name and only {', '.join(PARTNER_FIELDS)}")
    if len({link.role for link in pack.partners}) != len(pack.partners):
        problems.append("a partner role is listed twice")
    tabs = [t.id for t in pack.screens.tabs]
    if len(tabs) != len(set(tabs)):
        problems.append("a tab is listed twice")
    outputs = cfg.load("outputs").get("outputs", {})
    problems += [f"unknown output {o!r}" for o in pack.outputs if o not in outputs]
    try:
        definition(pack)
    except (ValidationError, ValueError) as exc:
        problems.append(f"the steps do not make a process definition: {exc}")
    if pack.choices or pack.replaces:  # 277 (O3)
        problems += _choice_problems(pack, problems)
    return problems


_CHECKED: dict[str, ProcessPack] = {}
"""265 (code review APPW-05): the packs checked once while the configs are frozen (the service, the worker); a case page
loaded a pack seven to ten times, each a full check. Emptied when the configs are read again (`cfg.reload`)."""
cfg.on_reload(_CHECKED.clear)


def load(pack_id: str) -> ProcessPack:
    """The process pack `pack_id`, read and checked; `PackError` with every problem. 265 (code review APPW-05): with the
    configs frozen (they cannot change in the process) a pack is checked once (`_CHECKED`); a pack model is frozen too."""
    if cfg.frozen() and (kept := _CHECKED.get(pack_id)) is not None:
        return kept
    try:
        data = cfg.load(f"process:{pack_id}")
    except FileNotFoundError as exc:
        raise UnknownPack(f"no process pack {pack_id!r}") from exc
    try:
        pack = ProcessPack.model_validate(data)
    except ValidationError as exc:
        raise PackError(f"process pack {pack_id!r} does not fit the format: {exc}") from exc
    if pack.id != pack_id:
        raise PackError(f"process pack file {pack_id!r} names another id: {pack.id!r}")
    problems = _problems(pack)
    if problems:
        raise PackError(f"process pack {pack_id!r}: " + "; ".join(problems))
    if cfg.frozen():
        _CHECKED[pack_id] = pack
    return pack


def packs() -> list[ProcessPack]:
    """Every process pack, read and checked."""
    return [load(name.split(":", 1)[1]) for name in cfg.all_names() if name.startswith("process:")]


def definition(pack: ProcessPack) -> ProcessDef:
    """The process core's definition of the pack's version: each step's kind is its capability's step kind, its
    parameters have the resources filled in, and how it starts is kept as the pack's own `_start` parameter (231, C2c:
    an optional step's `_optional` too, only on such a step, so the other definitions stay as they were)."""
    problems: list[str] = []
    steps = tuple(StepDef(id=s.id, kind=f"cap.{s.uses.replace('@', '.v')}", title=s.title, after=s.after, gates=s.gates,
                          params={**_resolved(s.params, pack.resources, problems, s.id), "_start": s.start,
                                  **({"_optional": True} if s.optional else {})})
                  for s in pack.steps)
    if problems:
        raise ValueError("; ".join(problems))
    return ProcessDef(id=f"pack_{pack.id}", version=pack.version, title=pack.title, steps=steps)
