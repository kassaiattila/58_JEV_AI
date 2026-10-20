"""The step kinds of a workflow (181, plan 170 L5 = plan 160-E S6).

Plain-language summary: a workflow's steps are kinds of work: the documents of a folder or of chosen files, a
mailbox's new emails, one party's bank statements, their reconciliation. Each kind is registered once, by the code it
belongs to (its `register()`, called by `registrations.load_all`), and the workflow (`jav/workflows.py`) asks this
registry instead of naming the kind: which existing packages a step of the kind can take, how it starts, whether its
source is fetched first (a mailbox download), whether it may have an AI engine of its own, where a repeated step takes
its source from, what it would cost, which parts of the workflow's scope it needs, and what its package's next step
means for the workflow.

What a kind's start does goes through `StepStart`: the shared operations of the workflow (note the step's package,
start its live run within the step's budget, mark it started, found nothing new, fetching, failed, an event). A start
that raises an error fails the step with that error, as before; the workflow catches it.

A kind the registry does not know is refused (`UnknownStepKind`): a process that missed `load_all` stops instead of
starting nothing.

185 (plan G-full-move T1c): a step's source is a folder, chosen files, an existing package or none, or a kind a domain
adds (`SourceKind`; the email domain's mailbox download): how it is checked, shown, moved on to the next period and
counted for the estimate is the source kind's own.

Layer: business module (the registry; no rule of its own). The modules that register are application operations; this
module imports none of them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# the shared source kinds a step makes its own package from, so its run may have its own AI engine (160-D); 185: a
# domain's source kind adds itself (`SourceKind.own`, `own_sources`)
SHARED_OWN_SOURCES = ("folder", "files")


class UnknownStepKind(LookupError):
    """A workflow step kind no module registered."""


@dataclass(frozen=True)
class StepStart:
    """What a step kind's start (and its fetch check) gets from the workflow.

    - `workflow`: the workflow's row (its id, maker `actor`, `party_id`, `period_start`, `period_end`);
    - `step`: the step's definition in the template (`id`, `kind`, `title`, `after`);
    - `state`: the step's stored row (`source`, `budget`, `name`, `engine`, `pull_id`);
    - `actor`: who the start is recorded for;
    - `packages`: 181: every step's package by step id (None: none yet), so a step can take the packages of the steps
      it waits for (the email routing);
    - `package(wp_id)`: notes the step's package as soon as it exists, so an interrupted start goes on with it (160,
      review R-2);
    - `run(wp_id)`: the package's live run when its estimate fits the step's budget, otherwise the step waits for a
      person;
    - `made(wp_id)`: a package without runs is the step's, and the step has started;
    - `nothing_new(note)`: the source held nothing new: the step is done without a package;
    - `fetching(fetch_id)`: the step's source is being fetched (a mailbox download); `poll` goes on with it;
    - `claim()`: claims a fetched source for going on (one process at a time); False: another process has it;
    - `failed(note)`: the step failed with the reason, for a person to retry;
    - `event(action, detail)`: an event of the step in the workflow's log.
    """

    workflow: Mapping[str, Any]
    step: Mapping[str, Any]
    state: Mapping[str, Any]
    actor: str
    packages: Mapping[str, str | None]
    package: Callable[[str], None]
    run: Callable[[str], None]
    made: Callable[[str], None]
    nothing_new: Callable[[str], None]
    fetching: Callable[[str], None]
    claim: Callable[[], bool]
    failed: Callable[[str], None]
    event: Callable[[str, dict[str, Any]], None]

    @property
    def source(self) -> dict[str, Any]:
        return self.state["source"]


@dataclass(frozen=True)
class StepKind:
    """One step kind, as its module registers it.

    - `kind`: its key in the workflow templates (`configs/workflows.json` `kinds`); `module`: the registering module.
    - `package_kinds`: the work package kinds (`workpackages.source_kind`) an existing package of the step may have.
    - `start(ctx)`: makes the step's package (or starts fetching its source) and starts what follows.
    - `poll(ctx)`: for a kind whose source is fetched first: goes on once the fetch has finished (nothing while it runs).
    - `paid`: whether its run may call AI, so a person approves its budget in the wizard.
    - `own_engine`: whether a step making its own package from a folder, files or a mailbox may have its own AI engine.
    - `only_new`: whether its folder or files may leave out the documents a live run has processed (147).
    - `subfolders`: whether its folder may include the subfolders.
    - `repeat_from(wp_id)`: the source a step linked to this package is repeated from in the next period; None: it
      cannot be told (the wizard asks).
    - `estimate(source, party_id, period_start, period_end, per_item)`: its own estimate of a folder or files (the items
      and the budget per provider); None: the documents are counted.
    - `needs`: the parts of the workflow's scope the step needs (`party`, `period`).
    - `statuses`: its package's own next step codes and what each means for the workflow's step.
    """

    kind: str
    module: str
    package_kinds: tuple[str, ...]
    start: Callable[[StepStart], None]
    poll: Callable[[StepStart], None] | None = None
    paid: bool = True
    own_engine: bool = True
    only_new: bool = False
    subfolders: bool = False
    repeat_from: Callable[[str], dict[str, Any] | None] | None = None
    estimate: Callable[..., dict[str, Any]] | None = None
    needs: tuple[str, ...] = ()
    statuses: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.package_kinds:
            raise ValueError(f"step kind {self.kind!r} names no package kind")
        if self.own_engine and not self.paid:
            raise ValueError(f"step kind {self.kind!r}: an AI engine of its own needs a paid step")


_KINDS: dict[str, StepKind] = {}


def register(kind: StepKind) -> None:
    """Registers a step kind; the same one again adds nothing, another one of the same kind is an error."""
    known = _KINDS.get(kind.kind)
    if known is not None and known != kind:
        raise ValueError(f"step kind {kind.kind!r} is registered already by {known.module}")
    _KINDS[kind.kind] = kind


def of(kind: str) -> StepKind:
    try:
        return _KINDS[kind]
    except KeyError:
        raise UnknownStepKind(f"unknown workflow step kind {kind!r} (was registrations.load_all called?)") from None


def kinds() -> list[StepKind]:
    """Every registered step kind, in the order they were registered."""
    return list(_KINDS.values())


@dataclass(frozen=True)
class SourceKind:
    """185 (plan G-full-move T1c): a kind of a step's source a domain adds to the shared ones.

    - `check(raw)`: the source as stored, from what the wizard gave (a named error for a bad one);
    - `shown(source)`: what a workflow's view shows of it;
    - `repeated(source, period, workflow)`: its source for the next period (`period`: the next period, or None);
    - `count(source)`: the items it would bring at most (None: unknown), their item kind and a note, for the estimate;
    - `own`: a step makes its own package from it, so its run may have its own AI engine (160-D).
    """

    kind: str
    module: str
    check: Callable[[Mapping[str, Any]], dict[str, Any]]
    shown: Callable[[Mapping[str, Any]], dict[str, Any]]
    repeated: Callable[[Mapping[str, Any], tuple[str, str] | None, Mapping[str, Any]], dict[str, Any]]
    count: Callable[[Mapping[str, Any]], tuple[int | None, str, str | None]]
    own: bool = True


_SOURCES: dict[str, SourceKind] = {}


def register_source(kind: SourceKind) -> None:
    """Registers a domain's source kind; the same one again adds nothing, another one of the same kind is an error."""
    known = _SOURCES.get(kind.kind)
    if known is not None and known != kind:
        raise ValueError(f"source kind {kind.kind!r} is registered already by {known.module}")
    _SOURCES[kind.kind] = kind


def source_kind(name: str) -> SourceKind | None:
    """A domain's source kind; None for a shared one (a folder, files, a package, none)."""
    return _SOURCES.get(name)


def own_sources() -> tuple[str, ...]:
    """The source kinds a step makes its own package from: the shared ones, then each domain's that does."""
    return (*SHARED_OWN_SOURCES, *(k.kind for k in _SOURCES.values() if k.own))


def paths_of(source: Mapping[str, Any]) -> list[Path]:
    """The paths of a folder or files source (a folder is one path)."""
    return [Path(source["folder"])] if source["kind"] == "folder" else [Path(p) for p in source["paths"]]


def folder_source(wp: Mapping[str, Any] | None, kinds: tuple[str, ...]) -> dict[str, Any] | None:
    """A repeated step's source from its linked package: the package's folder, when the package was made from one (its
    kind among `kinds`) and the folder is still there; None otherwise (the wizard asks)."""
    ref = wp.get("source_ref") if wp else None
    if wp is not None and wp["source_kind"] in kinds and ref and Path(ref).is_dir():
        return {"kind": "folder", "folder": ref, "recursive": False}
    return None


def described() -> dict[str, dict[str, Any]]:
    """What the interface needs of each kind (the wizard and the control view): the packages it takes, whether it is
    paid, has an engine of its own, may leave out processed documents or take the subfolders, and the scope it needs."""
    return {k.kind: {"package_kinds": list(k.package_kinds), "paid": k.paid, "own_engine": k.own_engine,
                     "only_new": k.only_new, "subfolders": k.subfolders, "needs": list(k.needs)} for k in _KINDS.values()}


__all__ = ["SHARED_OWN_SOURCES", "SourceKind", "StepKind", "StepStart", "UnknownStepKind", "described", "folder_source",
           "kinds", "of", "own_sources", "paths_of", "register", "register_source", "source_kind"]
