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
  `{"kind": "files", "files"}`.
- `Maker`, `register_maker`, `maker_of`, `maker_names`: how a step's package is made from the case's scope.
- `package_of(case_id, step_id)`: the package a case's step made (bound by its scope part `owner_step`).
- `CAPABILITY`: the step kind; its action `start_run` starts the package's live run.

Layer: application; it uses the work packages, their runs and readiness, the package scopes and the process core.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from jav.app import capabilities, package_scope, scopes, work, work_readiness, work_runs
from jav.core import identity, store
from jav.core.process import kinds
from jav.core.process.engine import StepContext
from jav.core.user_messages import explained

SOURCE_PART = "source"
OWNER_PART = "owner_step"  # the scope part of a package a case's step made: "<case id>:<step id>"
DOCUMENTS = "documents"
POLL_S = 5.0  # how soon a waiting step looks again for its run's start or approval
_OWNER = __name__


class ProcessingError(ValueError):
    """A step's package or run that cannot be made."""


# --- the source part ---------------------------------------------------------------------------------------------------


def _source(value: Any, error: type[Exception]) -> dict[str, Any]:
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
    return Path(value["folder"]).name if value["kind"] == "folder" else f"{len(value['files'])} files"


def _no_source(error: type[Exception]) -> Exception:
    return explained(error, "choose a folder or files")


SOURCE = scopes.Part(SOURCE_PART, __name__, _source, _source_words, _no_source)


def paths_of(source: dict[str, Any]) -> list[Path]:
    """The source's folder or files as paths."""
    return [Path(source["folder"])] if source["kind"] == "folder" else [Path(f) for f in source["files"]]


# --- package makers ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Maker:
    """How a step's package is made: `make(scope, name, owner)` returns the new package's id, or None when the source
    holds nothing new for it (the step is then done without a package). `rule`: the package rule its package runs by
    (`work.register_rule`), named in its scope; None: none."""

    name: str
    module: str
    make: Callable[[dict[str, Any], str, identity.Who | None], str | None]
    rule: str | None = None


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


def _run(ctx: StepContext, params: Process) -> kinds.StepOutcome:
    case_id, step_id = ctx.case_id, ctx.step.id
    wp_id = package_of(case_id, step_id)
    if wp_id is None:
        maker = maker_of(params.maker)
        owner = work.get(str(ctx.data["container"])).get("owner")
        made = maker.make(ctx.data["scope"], str(ctx.data["name"]), owner)
        if made is None:
            return kinds.Done({"documents": 0})
        _bind(made, case_id, step_id, ctx.data["scope"], maker.rule, owner or ctx.actor)
        wp_id = made
    runs = _live_runs(wp_id)
    if not runs:
        return ctx.wait("run_start", timer=("check", time.time() + POLL_S), detail={"workpackage_id": wp_id})
    if not any(r["approval"] for r in runs) or work_runs.open_live_runs(wp_id):
        return ctx.wait("run_approval", timer=("check", time.time() + POLL_S), detail={"workpackage_id": wp_id})
    return kinds.Done({"package": wp_id, "runs": sorted(r["run_id"] for r in runs if r["approval"])})


def _can_start(case_id: str, step_id: str) -> bool:
    wp_id = package_of(case_id, step_id)
    return wp_id is not None and not _live_runs(wp_id)


def start_run(case_id: str, step_id: str, actor: identity.Who, _note: str | None = None) -> str:
    """A person starts the live run of the step's package within its own estimate; returns the run's id."""
    wp_id = package_of(case_id, step_id)
    if wp_id is None or _live_runs(wp_id):
        raise explained(ProcessingError, "the step has no package waiting for its run")
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
    actions=(capabilities.Action("start_run", "Start the live run", _can_start, start_run),))


def register() -> None:
    """The source part, the documents' maker and the capability (`registrations.load_all`)."""
    scopes.register(SOURCE)
    register_maker(Maker(DOCUMENTS, __name__, _documents))
    capabilities.register(CAPABILITY)


__all__ = ["CAPABILITY", "DOCUMENTS", "Maker", "OWNER_PART", "Process", "ProcessingError", "SOURCE", "SOURCE_PART",
           "maker_names", "maker_of", "package_of", "paths_of", "register", "register_maker", "start_run"]
