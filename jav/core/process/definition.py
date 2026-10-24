"""The process definition (213, P1a; rules 1 and 2 of plan 212 P0): the versioned description of a kind of case.

Plain-language summary: a definition lists a case's steps in order. Each step has a kind (what it does, registered in
`jav.core.process.kinds`) and may name earlier steps in two ways: `after` is the usual order, which a person may
override (the override is recorded); `gates` must be done first, and nothing overrides them. A case keeps the
definition it started with, as a copy and with its fingerprint, so a later version of the definition never changes a
running case.

A step may only name steps listed before it, so a definition has no cycle and its order is its list's order.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [  # 229 (SZ1b): what code outside the process core may use; the rest is the core's own
    "NAME", "StepDef", "ProcessDef", "load",
]

NAME = r"^[a-z][a-z0-9_]*$"


class StepDef(BaseModel):
    """One step: its id, its kind, the steps it follows by order (`after`) or by gate (`gates`), and its parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=NAME)
    kind: str = Field(min_length=1)
    title: str | None = None
    after: tuple[str, ...] = ()
    gates: tuple[str, ...] = ()
    params: dict[str, Any] = Field(default_factory=dict)

    def needs(self) -> tuple[str, ...]:
        """Every step this one waits for, by order or by gate."""
        return (*self.after, *self.gates)


class ProcessDef(BaseModel):
    """A kind of case in one version: its id, version, title and steps in order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=NAME)
    version: str = Field(min_length=1)
    title: str = Field(min_length=1)
    steps: tuple[StepDef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _references(self) -> ProcessDef:
        seen: set[str] = set()
        for step in self.steps:
            if step.id in seen:
                raise ValueError(f"step {step.id!r} is listed twice")
            unknown = [s for s in step.needs() if s not in seen]
            if unknown:
                raise ValueError(f"step {step.id!r} names {unknown}, which are not listed before it")
            if len(set(step.needs())) != len(step.needs()):
                raise ValueError(f"step {step.id!r} names a step twice in its order and gates")
            seen.add(step.id)
        return self

    def step(self, step_id: str) -> StepDef:
        for step in self.steps:
            if step.id == step_id:
                return step
        raise KeyError(step_id)

    def dependants(self, step_id: str) -> tuple[str, ...]:
        """The steps that follow this one, directly or through others, in the definition's order."""
        out: list[str] = []
        reached = {step_id}
        for step in self.steps:
            if reached.intersection(step.needs()):
                out.append(step.id)
                reached.add(step.id)
        return tuple(out)

    def canonical(self) -> str:
        """The definition as canonical JSON (sorted keys, no spaces): the form that is stored and fingerprinted."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()


def load(text: str) -> ProcessDef:
    """A definition from its stored canonical JSON."""
    return ProcessDef.model_validate_json(text)
