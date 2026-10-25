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
reference to a step or a resource that is not there.

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

__all__ = ["Element", "Intake", "PackError", "PartnerLink", "ProcessPack", "Step", "Tab", "UnknownPack", "definition", "load",
           "packs"]

ELEMENTS = "screen_elements"
_MODULE = re.compile(r"\bjav\.[a-z_]+")


class PackError(ValueError):
    """A process pack that cannot be read or does not pass the check; the message lists every problem."""


class UnknownPack(PackError):
    """231 (B2): no process pack of this id."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Intake(_Model):
    """What may start a case: an email read with an intent (`offer`: the email offers to start one; 231 C1b, `case`: it
    starts one by itself, `jav/app/intake.py`) or a person."""

    on: Literal["email_intent", "manual"]
    intent: str | None = None
    starts: Literal["offer", "case", "manual"]


class Step(_Model):
    id: str = Field(pattern=NAME)
    uses: str = Field(pattern=r"^[a-z][a-z0-9_]*@[1-9][0-9]*$")
    title: str | None = None
    after: tuple[str, ...] = ()
    gates: tuple[str, ...] = ()
    start: Literal["auto", "person"] = "auto"
    params: dict[str, Any] = Field(default_factory=dict)


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
    parts: tuple[str, ...] = ()


PARTNER_FIELDS = ("name", "tax_number", "email", "phone", "address")


class PartnerLink(_Model):
    """231 (B1): a partner a case is about: its role (`configs/partners.json`), the step whose result holds the record's
    fields, and which of them give the partner's values (`name` at least)."""

    role: str = Field(min_length=1)
    from_step: str = Field(pattern=NAME)
    fields: dict[str, str] = Field(min_length=1)


class ProcessPack(_Model):
    meta: dict[str, Any]
    id: str = Field(pattern=NAME)
    title: str = Field(min_length=1)
    scope: Scope = Scope()
    intake: tuple[Intake, ...] = ()
    resources: dict[str, str] = Field(default_factory=dict)
    steps: tuple[Step, ...] = Field(min_length=1)
    screens: Screens
    outputs: tuple[str, ...] = ()
    goldens: tuple[str, ...] = ()
    partners: tuple[PartnerLink, ...] = ()  # 231 (B1)

    @property
    def version(self) -> str:
        return str(self.meta["version"])


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


def _problems(pack: ProcessPack) -> list[str]:
    problems: list[str] = []
    if _MODULE.search(json.dumps(pack.model_dump(), ensure_ascii=False)):
        problems.append("a process pack holds no code: it names a Python module")
    known_parts = {p.name for p in scopes.parts()}
    problems += [f"unknown scope part {p!r}" for p in pack.scope.parts if p not in known_parts]
    if any(i.on == "email_intent" and not i.intent for i in pack.intake):
        problems.append("an email intake names its intent")
    if any(i.starts == "case" for i in pack.intake):  # 231 (C1b): a case started by itself starts from the email's record
        if any(i.on != "email_intent" for i in pack.intake if i.starts == "case"):
            problems.append("only an email intake starts a case by itself")
        reads = any(_capability(s.uses) is not None and _capability(s.uses).preview is not None for s in pack.steps)
        if scopes.RECORD not in pack.scope.parts or not reads:
            problems.append("an intake that starts a case by itself needs a record scope part and a step that reads it")
    ids = [s.id for s in pack.steps]
    for step in pack.steps:
        where = f"step {step.id!r}"
        try:
            cap = capabilities.of(step.uses)
        except capabilities.CapabilityError:
            problems.append(f"{where}: no capability {step.uses} is registered")
            continue
        try:
            cap.params.model_validate(_resolved(step.params, pack.resources, problems, where))
        except ValidationError as exc:
            problems.append(f"{where}: its parameters do not fit {step.uses}: "
                            + ", ".join(".".join(map(str, e["loc"])) or "-" for e in exc.errors()[:5]))
        if cap.providers and step.start != "person":
            problems.append(f"{where}: a paid step ({step.uses}) is started by a person")
    elements = cfg.load(ELEMENTS)["elements"]
    for tab in pack.screens.tabs:
        for element in tab.elements:
            if element.type not in elements:
                problems.append(f"tab {tab.id!r}: unknown screen element {element.type!r}")
            if element.step is not None and element.step not in ids:
                problems.append(f"tab {tab.id!r}: element {element.type!r} shows no step {element.step!r}")
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
    return problems


def load(pack_id: str) -> ProcessPack:
    """The process pack `pack_id`, read and checked; `PackError` with every problem."""
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
    return pack


def packs() -> list[ProcessPack]:
    """Every process pack, read and checked."""
    return [load(name.split(":", 1)[1]) for name in cfg.all_names() if name.startswith("process:")]


def definition(pack: ProcessPack) -> ProcessDef:
    """The process core's definition of the pack's version: each step's kind is its capability's step kind, its
    parameters have the resources filled in, and how it starts is kept as the pack's own `_start` parameter."""
    problems: list[str] = []
    steps = tuple(StepDef(id=s.id, kind=f"cap.{s.uses.replace('@', '.v')}", title=s.title, after=s.after, gates=s.gates,
                          params={**_resolved(s.params, pack.resources, problems, s.id), "_start": s.start})
                  for s in pack.steps)
    if problems:
        raise ValueError("; ".join(problems))
    return ProcessDef(id=f"pack_{pack.id}", version=pack.version, title=pack.title, steps=steps)
