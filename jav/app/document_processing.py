"""Document processing as a capability (231, plan stage C, C3b2; DECISIONS 231): `process_documents@1`.

Plain-language summary: the processing of a folder's or some chosen files' documents is a step any process pack may
have, as the strict rule asks (every process only from general capabilities; the owner's decisions of 2026-10-25 make
the documents, the bank statements and the mailbox download process packs too). The step makes its own processing
package from the case's source, by the package maker the pack names (the documents' by default; a domain registers
others by name, the bank statements' with its survey), and binds it to itself; a step that finds no document is done
without a package. The live run of the package may call AI, so a person starts it (the step's action), within the
package's own estimate; the step waits until a live run of its package is approved and is done with it. The package
keeps every feature of a work package (its items, runs, review and result); the rule it runs by is named in its scope
(`work.RULE_PART`, C3b1).

- `SOURCE_PART`: the scope part of a case's documents: `{"kind": "folder", "folder", "recursive"}` or
  `{"kind": "files", "files"}`; 231 (C3d) a domain's source kind (`workflow_steps.SourceKind`: a mailbox download,
  `{"kind": "mailbox", "request"}`), checked and named by that kind; 231 (C3b4) `{"kind": "package", "workpackage_id"}`: a package made before, which the
  step takes as its own (a case wrapped around it, `process_runtime.wrap_case`).
- `Maker`, `register_maker`, `maker_of`, `maker_names`: how a step's package is made from the case's scope.
- `package_of(case_id, step_id)`: the package a case's step made (bound by its scope part `owner_step`); `bind`
  (C3b4): an existing package bound to a case's step.
- `CAPABILITY`: the step kind; its action `start_run` starts the package's live run.
- `register_workflow_steps()` (231, C3b5b): the workflow step kind of each pack that serves one (its `workflow` block),
  made by the process runtime from the pack and its maker's workflow hooks; its start wraps the step's new package by
  a case of the pack (the owner's decision of 2026-10-26) and starts its live run within the step's budget.

Layer: application; it uses the work packages, their runs and readiness, the package scopes and the process core.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from jav.app import capabilities, package_scope, scopes, work, work_readiness, work_runs, workflow_steps
from jav.core import identity, store
from jav.core.process import cases, kinds
from jav.core.process.engine import StepContext
from jav.core.user_messages import explained

SOURCE_PART = "source"
PACKAGE = "package"  # C3b4: the source kind of a package made before
OWNER_PART = "owner_step"  # the scope part of a package a case's step made: "<case id>:<step id>"
DOCUMENTS = "documents"
POLL_S = 5.0  # how soon a waiting step looks again for its run's start or approval
CANCELLED = "cancelled"  # C3b4: the case's outcome when its step's package was deleted
_OWNER = __name__


class ProcessingError(ValueError):
    """A step's package or run that cannot be made."""


# --- the source part ---------------------------------------------------------------------------------------------------


def _source(value: Any, error: type[Exception]) -> dict[str, Any]:
    if isinstance(value, dict) and (domain := workflow_steps.source_kind(str(value.get("kind")))) is not None:
        try:  # C3d: a domain's source kind (a mailbox download), checked by its own module
            return domain.check(value)
        except (ValueError, ValidationError) as exc:
            raise explained(error, "the source does not fit: {{why}}", why=str(exc)[:300]) from exc
    if isinstance(value, dict) and value.get("kind") == PACKAGE:  # C3b4: a package made before, wrapped by its case
        wp_id = str(value.get("workpackage_id") or "")
        try:
            known = work.get(wp_id)["status"] != "deleted"
        except KeyError:
            known = False
        if not known:
            raise explained(error, "no such work package: {{wp_id}}", wp_id=wp_id)
        return {"kind": PACKAGE, "workpackage_id": wp_id}
    if not isinstance(value, dict) or value.get("kind") not in ("folder", "files"):
        raise explained(error, "choose a folder or files")
    if value["kind"] == "folder":
        folder = Path(str(value.get("folder") or ""))
        if not folder.is_dir():
            raise explained(error, "no such folder: {{folder}}", folder=str(folder))
        return {"kind": "folder", "folder": str(folder), "recursive": bool(value.get("recursive"))}
    files = [str(f) for f in value.get("files") or []]
    if not files or any(not Path(f).is_file() for f in files):
        raise explained(error, "choose files that exist")
    return {"kind": "files", "files": files}


def _source_words(value: dict[str, Any]) -> str:
    if (domain := workflow_steps.source_kind(str(value["kind"]))) is not None:  # C3d
        return domain.words(value) if domain.words is not None else str(value["kind"])
    if value["kind"] == PACKAGE:
        return str(work.get(value["workpackage_id"])["name"])
    return Path(value["folder"]).name if value["kind"] == "folder" else f"{len(value['files'])} files"


def _no_source(error: type[Exception]) -> Exception:
    return explained(error, "choose a folder or files")


SOURCE = scopes.Part(SOURCE_PART, __name__, _source, _source_words, _no_source)


def paths_of(source: dict[str, Any]) -> list[Path]:
    """The source's folder or files as paths (a package source has none: its step takes the package itself)."""
    if source["kind"] == PACKAGE:
        raise explained(ProcessingError, "a package source is taken as it is, not read again")
    return [Path(source["folder"])] if source["kind"] == "folder" else [Path(f) for f in source["files"]]


# --- package makers ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Maker:
    """How a step's package is made: `make(scope, name, owner)` returns the new package's id, or None when the source
    holds nothing new for it (the step is then done without a package). `rule`: the package rule its package runs by
    (`work.register_rule`), named in its scope; None: none.

    231 (C3d): an asynchronous maker (a mailbox download) has no `make` but `fetch(scope, name, owner, taker)`, which
    starts the fetch and returns its id, and `collect(fetch_id)`, where it stands (`Collected`); `sources`: the source
    kinds it takes (the general form asks for one of them).

    231 (C3b5b): what a workflow's step of a pack with this maker is (`register_workflow_steps`): `package_kinds`, the
    kinds of an existing package the step may take; `only_new` and `subfolders`, whether its folder may leave out what a
    live run has processed and take its subfolders; `step_offer(ctx)`, the step's package made from the workflow step's
    source (`workflow_steps.StepStart`; None when nothing new, the maker having said so); `repeat_from(wp_id)` and
    `estimate(...)`, as a step kind has them."""

    name: str
    module: str
    make: Callable[[dict[str, Any], str, identity.Who | None], str | None] | None = None
    rule: str | None = None
    package_kinds: tuple[str, ...] = ()
    only_new: bool = False
    subfolders: bool = False
    step_offer: Callable[[workflow_steps.StepStart], str | None] | None = None
    repeat_from: Callable[[str], dict[str, Any] | None] | None = None
    estimate: Callable[..., dict[str, Any]] | None = None
    fetch: Callable[[dict[str, Any], str, identity.Who | None, str], str] | None = None
    collect: Callable[[str], "Collected"] | None = None
    sources: tuple[str, ...] = ("folder", "files")
    step_poll: Callable[[workflow_steps.StepStart], str | None] | None = None


@dataclass(frozen=True)
class Collected:
    """231 (C3d): where an asynchronous maker's fetch stands: `running`; `done` with its package (None: the source held
    nothing new; `note`: what went wrong when the package holds only what arrived before it did); `failed` (`note`)."""

    state: str
    workpackage_id: str | None = None
    note: str | None = None


_MAKERS: dict[str, Maker] = {}


def register_maker(maker: Maker) -> None:
    """A package maker by its name; the same one again adds nothing, another one of the same name is an error."""
    known = _MAKERS.get(maker.name)
    if known is not None and known != maker:
        raise ValueError(f"a package maker named {maker.name!r} is registered already by {known.module}")
    _MAKERS[maker.name] = maker


def maker_of(name: str) -> Maker:
    try:
        return _MAKERS[name]
    except KeyError:
        raise KeyError(f"no package maker named {name!r}") from None


def maker_names() -> list[str]:
    return sorted(_MAKERS)


def _documents(scope: dict[str, Any], name: str, owner: identity.Who | None) -> str | None:
    """The documents' maker: the folder's or the files' documents; none, no package (an empty one is not kept)."""
    source = scope[SOURCE_PART]
    if source["kind"] == "folder":
        wp = work.create_from_folder(Path(source["folder"]), name=name, owner=owner, recursive=source["recursive"])
    else:
        wp = work.create_from_files([Path(f) for f in source["files"]], name=name, owner=owner)
    if not work.get(wp["id"])["items"]:
        work.delete_workpackage(wp["id"], actor=owner or "machine")
        return None
    return wp["id"]


# --- a step's package -----------------------------------------------------------------------------------------------


def _owner_ref(case_id: str, step_id: str) -> str:
    return f"{case_id}:{step_id}"


def package_of(case_id: str, step_id: str) -> str | None:
    """The package the case's step made (None: none yet, or the source held nothing)."""
    with store.connect() as c:
        row = c.execute("SELECT s.workpackage_id FROM workpackage_scopes s JOIN workpackages w ON w.id = s.workpackage_id"
                        " WHERE json_extract(s.parts, ?) = ? AND w.status != 'deleted' ORDER BY w.created_at LIMIT 1",
                        (f"$.{OWNER_PART}", _owner_ref(case_id, step_id))).fetchone()
    return row["workpackage_id"] if row else None


def owned_packages() -> set[str]:
    """231 (C3b3): the packages a case's step made: the work package list leaves them out (the owner's decision of
    2026-10-25: the cases are the main list; such a package opens from its case's page)."""
    with store.connect() as c:
        return {r["workpackage_id"] for r in c.execute(
            "SELECT workpackage_id FROM workpackage_scopes WHERE json_extract(parts, ?) IS NOT NULL", (f"$.{OWNER_PART}",))}


def bind(wp_id: str, case_id: str, step_id: str, params: dict[str, Any], scope: dict[str, Any], actor: identity.Who) -> bool:
    """231 (C3b4): an existing package bound to a case's step (a case wrapped around a package made before its process
    was a pack), with the rule of the step's maker and the case's party and period, in the caller's write transaction
    when there is one; False when the package belongs to a step already (nothing changes)."""
    if bound(wp_id):
        return False
    _bind(wp_id, case_id, step_id, scope, maker_of(Process.model_validate({k: v for k, v in (params or {}).items() if not k.startswith("_")}).maker).rule, actor)
    return True


def bound(wp_id: str) -> bool:
    """231 (C3b4): whether the package belongs to a case's step (made by it, or bound to it)."""
    return OWNER_PART in ((package_scope.stored(wp_id) or {}).get("parts") or {})


def _bind(wp_id: str, case_id: str, step_id: str, scope: dict[str, Any], rule: str | None, actor: identity.Who) -> None:
    """The package's scope names the step that made it and the rule it runs by; the case's party and period go with
    them (a scope the maker gave stays, with these parts added)."""
    period = scope.get(scopes.PERIOD) or [None, None]
    with store.connect() as c:
        store.begin_immediate(c)
        stored = package_scope.stored(wp_id, c) or {}
        parts = {**(stored.get("parts") or {}), OWNER_PART: _owner_ref(case_id, step_id),
                 **({work.RULE_PART: rule} if rule else {})}
        package_scope.save(c, wp_id, party_id=stored.get("party_id") or scope.get(scopes.PARTY),
                           period_start=stored.get("period_start") or period[0],
                           period_end=stored.get("period_end") or period[1], role=stored.get("role"), parts=parts,
                           actor=actor, expected_revision=stored.get("revision"))


def _live_runs(wp_id: str) -> list[dict[str, Any]]:
    return [r for r in work_runs.run_rows(wp_id) if r["mode"] == "apply" and r["status"] != "cancelled"]


# --- the capability ------------------------------------------------------------------------------------------------


class Process(BaseModel):
    """A process pack's document processing step: the package maker by its name (the documents' by default)."""

    model_config = ConfigDict(extra="forbid")
    maker: str = DOCUMENTS


def _result(ctx: StepContext) -> dict[str, Any]:
    """The step's result while it runs (C3b4: its package; C3d: its fetch)."""
    result = ctx.row().get("result")
    result = json.loads(result) if isinstance(result, str) else result
    return result if isinstance(result, dict) else {}


def _held(ctx: StepContext) -> str | None:
    """The package the step made or took before (its result while it runs, C3b4)."""
    return _result(ctx).get("workpackage_id")


def _fetched(ctx: StepContext, maker: Maker, owner: identity.Who | None) -> kinds.StepOutcome | str:
    """231 (C3d): an asynchronous maker's package: its fetch started once (its id kept in the step's result, so a
    restart goes on with it), the step waiting while it runs; a failed fetch fails the step, and a person's retry starts
    a new one; nothing new: done without a package; else the package (a fetch interrupted after some of it arrived
    gives that part, its note recorded)."""
    assert maker.fetch is not None and maker.collect is not None
    fetch_id = _result(ctx).get("fetch_id")
    if fetch_id is None:
        fetch_id = maker.fetch(ctx.data["scope"], str(ctx.data["name"]), owner, f"case:{ctx.case_id}:{ctx.step.id}")
        with ctx.transaction() as c:
            cases.set_result(c, ctx.case_id, ctx.step.id, {"fetch_id": fetch_id})
    got = maker.collect(fetch_id)
    if got.state == "running":
        return ctx.wait("fetching", timer=("check", time.time() + POLL_S), detail={"fetch_id": fetch_id})
    if got.state == "failed":
        with ctx.transaction() as c:  # a retry starts a new fetch
            cases.set_result(c, ctx.case_id, ctx.step.id, {})
        return kinds.Fail(got.note or "the fetch failed")
    if got.workpackage_id is None:
        return kinds.Done({"documents": 0})
    if got.note:
        ctx.record("fetch_interrupted", {"fetch_id": fetch_id, "note": got.note[:1000]})
    return got.workpackage_id


def _run(ctx: StepContext, params: Process) -> kinds.StepOutcome:
    case_id, step_id = ctx.case_id, ctx.step.id
    wp_id = package_of(case_id, step_id)
    if wp_id is None and (gone := _held(ctx)) is not None:
        # C3b4: its package was deleted (a package without runs may be): the case has nothing left to do; before, the
        # step would have made the package again from its source
        ctx.record("package_deleted", {"workpackage_id": gone})
        return kinds.Close(CANCELLED)
    if wp_id is None:
        maker = maker_of(params.maker)
        owner = work.get(str(ctx.data["container"])).get("owner")
        source = ctx.data["scope"].get(SOURCE_PART) or {}
        if source.get("kind") == PACKAGE:  # C3b4: the case's own package, made before; bound unless another step has it
            if not bind(source["workpackage_id"], case_id, step_id, params.model_dump(), ctx.data["scope"],
                        owner or ctx.actor):
                raise explained(ProcessingError, "the package belongs to another case's step")
            made: str | None = source["workpackage_id"]
        elif maker.fetch is not None:  # C3d: an asynchronous maker (a mailbox download)
            got = _fetched(ctx, maker, owner)
            if not isinstance(got, str):
                return got
            made = got
        else:
            assert maker.make is not None
            made = maker.make(ctx.data["scope"], str(ctx.data["name"]), owner)
        if made is None:
            return kinds.Done({"documents": 0})
        if source.get("kind") != PACKAGE:
            _bind(made, case_id, step_id, ctx.data["scope"], maker.rule, owner or ctx.actor)
        wp_id = made
        with ctx.transaction() as c:  # the step remembers its package while it runs
            cases.set_result(c, case_id, step_id, {"workpackage_id": wp_id})
    found = _state_of(wp_id)
    if isinstance(found, str):
        return ctx.wait(found, timer=("check", time.time() + POLL_S), detail={"workpackage_id": wp_id})
    return kinds.Done(found)


def _state_of(wp_id: str) -> str | dict[str, Any]:
    """What the step's package waits for (C3b4: `run_start` for a person's start, `run_end` while a live run works,
    `run_approval` for a person's approval), or the step's result once a live run of it is approved and none is open."""
    runs = _live_runs(wp_id)
    if not runs:
        return "run_start"
    if any(r["status"] in work_runs.STOPPABLE for r in runs):
        return "run_end"
    if not any(r["approval"] for r in runs) or work_runs.open_live_runs(wp_id):
        return "run_approval"
    return {"package": wp_id, "runs": sorted(r["run_id"] for r in runs if r["approval"])}


def _adopt(wp_id: str, _params: Any) -> cases.Adopted:
    """231 (C3b4): a package made before its process was a pack, taken over as its case's step package: done with its
    approved live runs, else waiting as `_run` would."""
    found = _state_of(wp_id)
    if isinstance(found, str):
        return cases.Adopted(cases.RUNNING, waiting_for=found, timer=("check", time.time() + POLL_S),
                             result={"workpackage_id": wp_id})
    return cases.Adopted(cases.DONE, result=found)


def _workflow_starts(wp_id: str) -> bool:
    """231 (C3b4): whether the package is a workflow step's: its workflow starts its live run within the budget a
    person approved there (rule 146), so its case page offers no start of its own."""
    from jav.app import workflows  # lazy: the workflows build on the work packages this module makes

    return workflows.workflow_of(wp_id) is not None


def _can_start(case_id: str, step_id: str) -> bool:
    wp_id = package_of(case_id, step_id)
    return wp_id is not None and not _live_runs(wp_id) and not _workflow_starts(wp_id)


def start_run(case_id: str, step_id: str, actor: identity.Who, _note: str | None = None) -> str:
    """A person starts the live run of the step's package within its own estimate; returns the run's id."""
    wp_id = package_of(case_id, step_id)
    if wp_id is None or _live_runs(wp_id):
        raise explained(ProcessingError, "the step has no package waiting for its run")
    if _workflow_starts(wp_id):
        raise explained(ProcessingError, "its workflow starts the package's live run")
    ready = work_readiness.readiness(wp_id)
    if not ready["ready"]:
        raise ProcessingError("; ".join(b["message"] for b in ready["blockers"]) or "the package cannot start")
    return work_runs.start_run(wp_id, mode="apply", expected_assignment_revision=ready["assignment_revision"],
                               input_hash=ready["input_hash"], actor=actor)["run_id"]


CAPABILITY = capabilities.Capability(
    name="process_documents", version=1, module=_OWNER, run=_run, kind="human", params=Process, effects="store",
    # no provider of its own: making the package is free, and its live run, which may call AI, is a person's action
    # (`start_run`) within the package's own estimate and budget, as any live run
    summary=("Makes a processing package of the case's documents; a person starts its live run within the package's "
             "estimate, and the step is done once a live run is approved."),
    actions=(capabilities.Action("start_run", "Start the live run", _can_start, start_run),),
    # C3b4: the case list says a person's start while the package waits for its live run, the machine's work while it
    # runs, a person's decision while it waits for its approval (`_state_of`)
    waits={"run_start": "person_start", "run_end": "work", "run_approval": "person", "fetching": "work"}, adopt=_adopt, bind=bind, bound=bound)


def _package_view(case_id: str, step_id: str | None, _shared: dict[str, Any]) -> dict[str, Any]:
    """231 (C3b3): what the step shows on its case's page (the element `package_work`): its package (its name, its
    items, its runs) and, while its live run waits for a person, whether it can start and its estimate (the button's
    cost cap); `package` is None before the step made one or when the source held nothing."""
    wp_id = package_of(case_id, str(step_id))
    if wp_id is None:
        return {"package": None}
    wp = work.get(wp_id)
    runs = [{"run_id": r["run_id"], "mode": r["mode"], "status": r["status"], "approval": r["approval"]}
            for r in work_runs.run_rows(wp_id)]
    out: dict[str, Any] = {"package": {"id": wp_id, "name": wp["name"], "items": len(wp["items"]),
                                       "kind": wp["source_kind"]}, "runs": runs, "can_start": False}
    if _workflow_starts(wp_id):
        out["blockers"] = [explained(ProcessingError, "its workflow starts the package's live run").args[0]]
    elif not _live_runs(wp_id):
        ready = work_readiness.readiness(wp_id)
        out.update(can_start=bool(ready["ready"]), estimate={p: str(v) for p, v in (ready.get("budget") or {}).items()},
                   blockers=[b["message"] for b in ready["blockers"]])
    return out


def _workflow_start(pack_id: str, ctx: workflow_steps.StepStart) -> None:
    """231 (C3b5b): a workflow's step of a pack that serves one: its maker makes the step's package from the step's source
    (`Maker.step_offer`; nothing new: done without a package), a case of the pack is made around it with the workflow's
    party and period (`process_runtime.wrap_into`; the case's page offers no start of its own, `_workflow_starts`), and
    the package is noted on the step and its live run starts within the step's budget, as the step kind's own start did."""
    from jav.app import process_packs, process_runtime  # lazy: the process runtime builds on this capability's registry

    pack = process_packs.load(pack_id)
    serves = pack.workflow
    assert serves is not None
    step = next(s for s in pack.steps if s.id == serves.step)
    maker = maker_of(Process.model_validate(step.params).maker)
    assert maker.step_offer is not None
    wp_id = maker.step_offer(ctx)
    if wp_id is None:
        return
    scope: dict[str, Any] = {}
    if scopes.PARTY in pack.scope.parts:
        scope[scopes.PARTY] = ctx.workflow["party_id"]
    if scopes.PERIOD in pack.scope.parts:
        scope[scopes.PERIOD] = [ctx.workflow["period_start"], ctx.workflow["period_end"]]
    process_runtime.wrap_into(pack.id, wp_id, scope=scope, actor=ctx.workflow["actor"])
    ctx.package(wp_id)  # 160 (review R-2): an interrupted start goes on with this package
    ctx.run(wp_id)


def register_workflow_steps() -> None:
    """231 (C3b5b): the workflow step kind of every pack that serves one (`ProcessPack.workflow`) whose step is this
    capability's, made by the process runtime from the pack and its maker's workflow hooks (`process_runtime.pack_step_kind`).
    Last in `registrations.load_all`, once every domain registered its makers."""
    from functools import partial

    from jav.app import process_packs, process_runtime  # lazy, as above

    for pack in process_packs.packs():
        if pack.workflow is None:
            continue
        step = next(s for s in pack.steps if s.id == pack.workflow.step)
        if capabilities.of(step.uses) is not CAPABILITY:
            continue
        try:
            known = workflow_steps.of(pack.workflow.kind)
        except workflow_steps.UnknownStepKind:
            known = None
        if known is not None and known.module == process_runtime.__name__:
            continue  # made already: a repeated registration adds nothing
        maker = maker_of(Process.model_validate(step.params).maker)
        if maker.step_offer is None:
            raise ValueError(f"process pack {pack.id!r} serves a workflow step, but its maker {maker.name!r} makes none")
        workflow_steps.register(process_runtime.pack_step_kind(
            pack, start=partial(_workflow_start, pack.id), package_kinds=maker.package_kinds, rule=maker.rule,
            only_new=maker.only_new, subfolders=maker.subfolders, repeat_from=maker.repeat_from, estimate=maker.estimate))


def register() -> None:
    """The source part, the documents' maker, the capability and its element's data (`registrations.load_all`); 231
    (C3b5b) the documents maker with its workflow hooks (a workflow's documents step is the documents pack's)."""
    from jav.app import case_views, workflows  # lazy: the case page reads the registered capabilities

    scopes.register(SOURCE)
    register_maker(Maker(DOCUMENTS, __name__, _documents, package_kinds=workflows.DOCUMENT_PACKAGES, only_new=True,
                         subfolders=True, step_offer=workflows.documents_offer, repeat_from=workflows.repeat_from_folder))
    capabilities.register(CAPABILITY)
    case_views.register(case_views.ElementData("package_work", CAPABILITY.name, _OWNER, _package_view))


__all__ = ["CAPABILITY", "DOCUMENTS", "OWNER_PART", "PACKAGE", "SOURCE", "SOURCE_PART", "Collected", "Maker", "Process",
           "ProcessingError", "bind", "bound", "maker_names", "maker_of", "owned_packages", "package_of", "paths_of",
           "register", "register_maker", "register_workflow_steps", "start_run"]
