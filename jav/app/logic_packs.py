"""The logic packs: the kinds of work package that do a piece of work of their own (176, plan 170 L3).

Plain-language summary: a work package either only processes documents and emails (a folder, a mailbox, chosen
files), or it runs a logic pack: a piece of real work on processed results, such as the reconciliation of bank
statements with invoices, or the statement package of one own party and a period. A logic pack is the counterpart
of a type pack: a type pack describes a kind of document, a logic pack a kind of work. Each one is described here
once, by its own module (its `register()`, called by `registrations.load_all`), and the shared code asks this registry
instead of naming the kind: whether the package has runs, how documents are added to it, what it adds to a run, what
its deletion must check, its part of the package's page and, for a package without runs, its own next step and
approval.

A logic pack names its input roles (plan 170, 9.2, the mixed model): what it expects and where each comes from - its
own items, a linked package, a period of the store's results, or master data.

A kind the registry does not know and that is not one of the plain processing kinds is refused (`UnknownKind`): a
process that missed `load_all` stops, instead of treating a reconciliation package as an ordinary one.

Layer: business module (the registry; no rule of its own). The modules that register are application operations; this
module imports none of them.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

from jav.app import item_kinds

# the work package kinds (`workpackages.source_kind`) that only process their own documents and emails: the source
# kinds (177, `jav/app/item_kinds.py`)
DATA_KINDS = item_kinds.source_names()
# where an input role's documents come from
ROLE_SOURCES = ("own_items", "linked_package", "period", "master_data")
# 178 (plan 170 L4): the output every package that processes its items has (`configs/outputs.json`); 180: a domain's
# own outputs follow it (`processing_outputs`)
PACKAGE_RESULT = "package_result"


def processing_outputs() -> tuple[str, ...]:
    """The outputs of a package that processes its items: its result, then each domain's own output (180: the utility
    cost, `jav/app/outputs/parts.py`)."""
    from jav.app.outputs import parts

    return (PACKAGE_RESULT, *(own.output for own in parts.own_outputs()))


class UnknownKind(LookupError):
    """A work package kind that is neither a plain processing kind nor a registered logic pack."""


@dataclass(frozen=True)
class InputRole:
    """What a logic pack expects (`name`), where it comes from (`source`, one of `ROLE_SOURCES`) and, in a few words,
    what it is."""

    name: str
    source: str
    what: str


@dataclass(frozen=True)
class LogicPack:
    """One logic pack, as its module registers it.

    - `kind`: the work package kind it runs (`workpackages.source_kind`); `module`: the registering module.
    - `roles`: its input roles.
    - `has_runs`: False for a package whose items are not processed by runs (a reconciliation: a scope, no files, no
      runs); it then answers for its own approval and next step (`approved`, `next_step`, `list_next`) and is not
      released the shared way (`release_refusal()`: the error that says why, `package_release.ReleaseError`).
    - `add_refusal`: why the shared adding of documents refuses the package (it adds in its own way); None: it adds
      like any package.
    - `take_files(wp_id, paths, *, expected_revision, actor)`: 204 (R1j): adds files to one of its packages in its own
      way (the pair of `add_refusal`), so another domain (the email routing) adds through this registry instead of
      importing the pack's module.
    - `create_with_files(*, name, paths, scope, actor)`: 204 (R1j): makes one of its packages from files and a scope
      ({party_id, period_start, period_end}); returns the new package's id.
    - `rule`: what it adds to the processing of its items (`work.PackageRule`, asked by the worker).
    - `delete_guard(c, wp_id)`: checks a deletion of one of its packages inside the deleting transaction: raises
      `work.NotReady` to refuse it, or deletes its own rows.
    - `page(wp_id)`: its part of the package's page (`work_views.workpackage_view`): extra parts for a package with
      runs; for one without, its readiness, its next step and its own part.
    - `list_mark()`: its part of the package list's cache mark (what its next steps in the list read).
    - `outputs`: the outputs of its packages (178: `configs/outputs.json`; a template is chosen for each of them).
    - `scope(wp_id)`: 181: its package's own scope ({party_id, period_start, period_end, role}, `jav/app/package_scope.py`),
      which a person cannot replace; None: a person may give one.
    - `service`: 185: the module of its own addresses of the local service, by name (a module with a
      `routes(app, prefix)`; `jav.service.api.service_modules`), so this registry imports no service code.
    - `own_approval`: 215 (plan G-process-core P2d): a person approves its package's result as the package's own
      version (`package_release.record_own`: a reconciliation's statement, a quote), so each of its packages waits
      for that approval as a human task (`jav/app/human_tasks.py`); only a pack without runs. A pack whose work is
      done without such an approval (the email routing: every attachment decided) leaves it False.
    - `approval_what`: 229 (plan structure stage 1, MD2): what its own approval is about in a person's "Waiting for me"
      list (English source text the interface translates; until 229 the list named the kinds).
    - `reopen(wp_id, *, note, actor)`: 218 (plan P3 P3l): reopens the package's approved own version with a reason in
      the pack's own way (its event, its version's file), as a person's reopening does; needed with `own_approval`. A
      workflow's chain calls it when the step built on another one is approved again (`jav/app/workflows.py`).

    188: a logic pack's golden sets (named `<kind>:<name>`) are measured by the shared measurement command like a type
    pack's; 204 (plan G-process-core R1h): its domain names the module that describes them (`GOLDENS` in `jav/domains/`, read by
    `jav/evals/goldens.py`), so the pack's own module never imports the measurement layer.
    """

    kind: str
    module: str
    roles: tuple[InputRole, ...]
    has_runs: bool = True
    add_refusal: str | None = None
    take_files: Callable[..., Any] | None = None
    create_with_files: Callable[..., str] | None = None
    release_refusal: Callable[[], Exception] | None = None
    rule: Any = None
    delete_guard: Callable[[sqlite3.Connection, str], None] | None = None
    page: Callable[[str], dict[str, Any]] | None = None
    approved: Callable[[str], bool] | None = None
    next_step: Callable[[str], dict[str, Any]] | None = None
    list_next: Callable[[str], dict[str, Any]] | None = None
    list_mark: Callable[[], Any] | None = None
    outputs: tuple[str, ...] | None = None  # None: a processing package's (`processing_outputs`)
    scope: Callable[[str], dict[str, Any]] | None = None
    service: str | None = None
    own_approval: bool = False
    reopen: Callable[..., Any] | None = None
    approval_what: str = "Approval"

    def __post_init__(self) -> None:
        if self.kind in DATA_KINDS:
            raise ValueError(f"{self.kind!r} is a plain processing kind, not a logic pack")
        if not self.roles or any(r.source not in ROLE_SOURCES for r in self.roles):
            raise ValueError(f"logic pack {self.kind!r}: every input role needs a source of {ROLE_SOURCES}")
        own = (self.approved, self.next_step, self.list_next, self.release_refusal, self.page)
        if not self.has_runs and any(x is None for x in own):
            raise ValueError(f"logic pack {self.kind!r} without runs needs its approval, next steps and page")
        if not self.has_runs and self.rule is not None:
            raise ValueError(f"logic pack {self.kind!r} has no runs, so no rule in a run")
        if self.own_approval and self.has_runs:
            raise ValueError(f"logic pack {self.kind!r} has runs: its result is released, not approved as its own")
        if self.own_approval and self.reopen is None:
            raise ValueError(f"logic pack {self.kind!r} approves its own version, so it needs its reopening")


_PACKS: dict[str, LogicPack] = {}
_CONTAINERS: dict[str, LogicPack] = {}  # 231 (A6): the general container kinds (a process pack's case)


def register(pack: LogicPack) -> None:
    """Registers a logic pack; the same one again adds nothing, another one of the same kind is an error."""
    known = _PACKS.get(pack.kind)
    if known is not None and known != pack:
        raise ValueError(f"logic pack {pack.kind!r} is registered already by {known.module}")
    _PACKS[pack.kind] = pack


def of(kind: str) -> LogicPack | None:
    """The logic pack a work package of this kind runs; None for a plain processing kind; `UnknownKind` otherwise."""
    if kind in DATA_KINDS:
        return None
    if kind in _CONTAINERS:
        return _CONTAINERS[kind]
    try:
        return _PACKS[kind]
    except KeyError:
        raise UnknownKind(f"unknown work package kind {kind!r}: not a processing kind and no logic pack "
                          "(was registrations.load_all called?)") from None


def register_container(pack: LogicPack) -> None:
    """231 (A6): a general container kind (a process pack's case): known by `of` like a logic pack, but not one of the
    logic packs (`packs`), which are the process-specific kinds of work."""
    prior = _CONTAINERS.get(pack.kind)
    if prior is not None and prior.module != pack.module:
        raise ValueError(f"container kind {pack.kind!r} is registered by {prior.module}")
    _CONTAINERS[pack.kind] = pack


def has_runs(kind: str) -> bool:
    """Whether a package of this kind is processed by runs (every plain processing kind is)."""
    pack = of(kind)
    return pack is None or pack.has_runs


def packs() -> list[LogicPack]:
    """Every registered logic pack, in the order they were registered."""
    return list(_PACKS.values())


def kinds_without_runs() -> tuple[str, ...]:
    return tuple(p.kind for p in _PACKS.values() if not p.has_runs)


def kinds_with_own_approval() -> tuple[str, ...]:
    """215: the kinds whose packages a person approves as their own version (`LogicPack.own_approval`)."""
    return tuple(p.kind for p in _PACKS.values() if p.own_approval)


def outputs_of(kind: str) -> tuple[str, ...]:
    """178: the outputs of a work package of this kind (a plain processing kind, or a logic pack naming none: the package
    result and the domains' own outputs)."""
    pack = of(kind)
    return pack.outputs if pack and pack.outputs is not None else processing_outputs()


__all__ = ["DATA_KINDS", "PACKAGE_RESULT", "ROLE_SOURCES", "InputRole", "LogicPack", "UnknownKind", "has_runs",
           "kinds_with_own_approval", "kinds_without_runs", "of", "outputs_of", "packs", "processing_outputs", "register",
           "register_container"]
