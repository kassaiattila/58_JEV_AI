"""A step that runs a case of another process (231, stage U, U2c; the owner's decision of 2026-10-28: a chain is a
multi-step process): the general `run_case` capability of every process pack.

Plain-language summary: a process of several steps (the monthly reconciliation: the invoices, the statements, then
their reconciliation) is one case whose steps each run a case of another process, a sub-case. The step starts its
sub-case with what the case's scope holds that the other process needs (the own party, the period), the step's own
documents (each step its own source, given when the case starts) and, where the step says so, the document batches
that the sub-cases of earlier steps made (the email routing reads the downloaded emails); then it waits until the
sub-case closes. A sub-case closed as done makes the step done, and the steps after it start; one closed otherwise (it
was cancelled) stops the step with why, and a person's retry starts a new sub-case. A sub-case is a case like any
other: it is in the case list, its paid runs wait for a person's start with their cost cap, and its page names the
case it is part of. The process core tells the step at once: the sub-case's closing sends the step an event in the
same transaction.

- `RunCase`: what a process pack sets: the process of the sub-case (`pack`), and the earlier steps whose sub-cases'
  batches it reads as its scope part `sources` (`sources_from`).
- `STEP_SOURCES`: the scope part holding each step's own documents ({step: source}, each checked as the `source` part).
- `step_sources(pack)`: the steps of a pack whose sub-case takes its own documents, for the start form.
- The pack check refuses a step whose process is missing, is the pack itself or runs it, whose sub-case needs a scope
  part the pack does not hold (and cannot be filled), or whose `sources_from` names a step it does not wait for; the
  start is refused when a step's documents are missing.

Layer: application; it uses the process runtime, the process packs, the scope parts and the process core's events.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jav.app import capabilities, document_processing, process_packs, process_runtime, scopes, work
from jav.core import cfg, identity, store
from jav.core.process import cases, kinds
from jav.core.process.definition import NAME
from jav.core.process.engine import StepContext
from jav.core.user_messages import explained, said

__all__ = ["CAPABILITY", "CLOSED", "RunCase", "STEP_SOURCES", "register", "step_sources"]

CLOSED = "case_closed"  # the event a sub-case's closing sends the step that runs it
STEP_SOURCES = "step_sources"
DONE = "done"
KEY = "run_case@1"
_OWNER = __name__
_TAKEN = (document_processing.SOURCE_PART, scopes.SOURCES, STEP_SOURCES)  # parts a sub-case gets by its step, not as such


class RunCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pack: str = Field(pattern=NAME)
    sources_from: tuple[str, ...] = ()


class CaseRunResult(capabilities.Result):
    """The sub-case the step ran and the outcome it closed with."""

    case_id: str
    outcome: str


# --- the scope part of each step's own documents ------------------------------------------------------------------------


def _step_sources(value: Any, error: type[Exception]) -> dict[str, Any]:
    if not (isinstance(value, Mapping) and value and all(isinstance(k, str) and re.fullmatch(NAME, k) for k in value)):
        raise explained(error, "each step's documents are named by the step")
    source = scopes.of(document_processing.SOURCE_PART, error)
    return {str(k): source.check(v, error) for k, v in sorted(value.items())}


def _step_sources_words(value: Mapping[str, Any]) -> str:
    source = scopes.of(document_processing.SOURCE_PART)
    return ", ".join(f"{k}: {source.label(v)}" for k, v in value.items())


def _no_step_sources(error: type[Exception]) -> Exception:
    return explained(error, "choose the documents of each step")


STEP_SOURCES_PART = scopes.Part(STEP_SOURCES, __name__, _step_sources, _step_sources_words, _no_step_sources)


# --- the pack's steps of it ----------------------------------------------------------------------------------------------


def _steps(pack: Any) -> list[tuple[Any, RunCase]]:
    """The pack's steps of this capability with their parameters (one whose parameters do not fit is left to the
    general check, which names it)."""
    out = []
    for step in pack.steps:
        if step.uses == KEY:
            try:
                out.append((step, RunCase.model_validate(step.params)))
            except ValidationError:
                continue
    return out


def _scope_of(pack_id: str) -> tuple[set[str], set[str]]:
    """A pack's scope parts and those it needs, read from its file (its own check would read this pack again)."""
    scope = cfg.load(f"process:{pack_id}").get("scope", {})
    parts = set(scope.get("parts", ()))
    return parts, parts - set(scope.get("optional", ()))


def _runs(pack_id: str, seen: set[str]) -> set[str]:
    """The processes whose cases a pack's steps run, directly or through another, read from their files."""
    try:
        steps = cfg.load(f"process:{pack_id}").get("steps", ())
    except FileNotFoundError:
        return set()
    found: set[str] = set()
    for step in steps:
        target = (step.get("params") or {}).get("pack") if step.get("uses") == KEY else None
        if isinstance(target, str) and target not in seen:
            found.add(target)
            found |= _runs(target, seen | {target})
    return found


def _waited_for(pack: Any, step_id: str) -> set[str]:
    needs = {s.id: (*s.after, *s.gates) for s in pack.steps}
    seen: set[str] = set()
    todo = list(needs.get(step_id, ()))
    while todo:
        s = todo.pop()
        if s not in seen:
            seen.add(s)
            todo += needs.get(s, ())
    return seen


def _pack_check(pack: Any) -> list[str]:
    problems: list[str] = []
    ours = {step.id for step, _ in _steps(pack)}
    for step, params in _steps(pack):
        where = f"step {step.id!r}"
        if params.pack == pack.id or pack.id in _runs(params.pack, {params.pack}):
            problems.append(f"{where}: a process does not run a case of itself")
            continue
        try:
            _parts, needs = _scope_of(params.pack)
        except FileNotFoundError:
            problems.append(f"{where}: no process pack {params.pack!r}")
            continue
        for part in sorted(needs):
            if part == document_processing.SOURCE_PART:
                if not {STEP_SOURCES, part} & set(pack.scope.parts):
                    problems.append(f"{where}: its sub-case takes its own documents, so the pack's scope holds {STEP_SOURCES}")
            elif part == scopes.SOURCES:
                if not params.sources_from:
                    problems.append(f"{where}: its sub-case reads document batches: sources_from names the steps that make them")
            elif part not in pack.scope.parts and not scopes.fillable(part):
                problems.append(f"{where}: its sub-case needs the scope part {part!r}, which the pack does not hold")
        waited = _waited_for(pack, step.id)
        for ref in params.sources_from:
            if ref not in ours:
                problems.append(f"{where}: sources_from names {ref!r}, which is no step that runs a case")
            elif ref not in waited:
                problems.append(f"{where}: sources_from names {ref!r}, a step it does not wait for")
    return problems


def _taking(pack: Any) -> list[Any]:
    """The pack's steps whose sub-case takes its own documents."""
    out = []
    for step, params in _steps(pack):
        try:
            _parts, needs = _scope_of(params.pack)
        except FileNotFoundError:
            continue
        if document_processing.SOURCE_PART in needs:
            out.append(step)
    return out


def _scope_check(pack: Any, scope: dict[str, Any]) -> None:
    """Each step whose sub-case takes its own documents has them (or the case's own documents serve), and no other step
    is given any."""
    given = scope.get(STEP_SOURCES) or {}
    taking = _taking(pack)
    if unknown := sorted(set(given) - {s.id for s in taking}):
        raise explained(scopes.ScopeError, "no step of the process takes documents named {{steps}}", steps=", ".join(unknown))
    for step in taking:
        if step.id not in given and document_processing.SOURCE_PART not in scope:
            raise explained(scopes.ScopeError, "choose the documents of the step {{step}}", step=step.title or step.id)


def step_sources(pack: Any) -> list[dict[str, Any]]:
    """The steps of the pack whose sub-case takes its own documents, in the pack's order, for the start form: each
    {step, title, pack, process, source_kinds, examples} (the sub-case's process, its title, the kinds of source it
    takes, and whether it has invented documents to start on)."""
    out = []
    for step in _taking(pack):
        target = process_packs.load(RunCase.model_validate(step.params).pack)
        out.append({"step": step.id, "title": step.title or step.id, "pack": target.id, "process": target.title,
                    "source_kinds": document_processing.source_kinds(target),
                    "examples": target.examples is not None and target.examples.documents is not None})
    return out


# --- the step ------------------------------------------------------------------------------------------------------------


def _gathered(row: Mapping[str, Any]) -> dict[str, Any]:
    return dict(row.get("result") or {})


def _batches(ctx: StepContext, step_ids: tuple[str, ...]) -> list[str]:
    """The batches the sub-cases of the named earlier steps made, in their order."""
    out: list[str] = []
    for step_id in step_ids:
        sub = (ctx.result_of(step_id)[1] or {}).get("case_id")
        if sub:
            out += [wp for wp in document_processing.case_packages(sub) if wp not in out]
    return out


def _start(ctx: StepContext, params: RunCase, gathered: dict[str, Any]) -> None:
    """The sub-case started with what the case's scope holds that its process takes, the step's own documents and the
    batches of the earlier steps it reads; it is named as the case, belongs to the case's owner, and is noted on the step
    in its start's transaction."""
    target = process_packs.load(params.pack)
    scope = ctx.data.get("scope") or {}
    given = {k: v for k, v in scope.items() if k in target.scope.parts and k not in _TAKEN}
    if document_processing.SOURCE_PART in target.scope.parts:
        own = (scope.get(STEP_SOURCES) or {}).get(ctx.step.id) or scope.get(document_processing.SOURCE_PART)
        if own is not None:
            given[document_processing.SOURCE_PART] = own
    if params.sources_from:
        given[scopes.SOURCES] = _batches(ctx, params.sources_from)
    container = work.get(ctx.case_id)

    def note(c: Any, sub: str) -> None:
        cases.set_result(c, ctx.case_id, ctx.step.id, {**gathered, "pack": params.pack, "case_id": sub})

    process_runtime.start_case(params.pack, given, name=str(ctx.data.get("name") or container["name"]), actor=ctx.actor,
                               owner=work.person_owner(container), parent=(ctx.case_id, ctx.step.id), then=note)


def _closed_as(case_id: str) -> str | None:
    """The outcome a sub-case closed with; None while it is open."""
    with store.connect() as c:
        row = cases.find_case_in(c, case_id)
    if row is None:
        return "gone"
    return None if row["status"] == cases.OPEN else str(row["outcome"])


def _run(ctx: StepContext, params: RunCase) -> kinds.StepOutcome:
    """The sub-case started the first time (and after one that closed otherwise than done); done once it closed as
    done, stopped with why once it closed otherwise; until then the step waits for its closing."""
    gathered = _gathered(ctx.row())
    sub = gathered.get("case_id")
    if sub is None:
        try:
            _start(ctx, params, gathered)
        except (scopes.ScopeError, process_packs.PackError) as exc:
            why = said("the sub-case cannot start: {{why}}", why=str(exc)[:300])
            return kinds.Fail(str(why), reasons=(why,))
        return ctx.wait(CLOSED)
    outcome = gathered.get("outcome") or _closed_as(sub)
    if outcome is None:
        return ctx.wait(CLOSED)
    if outcome == DONE:
        return kinds.Done({**gathered, "outcome": outcome})
    earlier = [*gathered.get("earlier", ()), {"case_id": sub, "outcome": outcome}]
    with ctx.transaction() as c:  # the next try starts a new sub-case
        cases.set_result(c, ctx.case_id, ctx.step.id, {"pack": params.pack, "earlier": earlier})
    why = said("the sub-case {{case}} closed as {{outcome}}; trying again starts a new one", case=sub, outcome=outcome)
    return kinds.Fail(str(why), reasons=(why,))


def _on_event(ctx: StepContext, c: Any, event: cases.Event) -> str:
    """The sub-case closed: its outcome kept with the step (the step then decides); a closing of an earlier one is
    refused."""
    if event.kind != CLOSED:
        return kinds.APPLIED
    gathered = _gathered(cases.step_row(c, ctx.case_id, ctx.step.id))
    if event.payload.get("case_id") != gathered.get("case_id"):
        return kinds.REFUSED
    cases.set_result(c, ctx.case_id, ctx.step.id, {**gathered, "outcome": str(event.payload.get("outcome"))})
    return kinds.APPLIED


def _left(c: Any, case_id: str, step_id: str | None, actor: identity.Actor) -> None:
    """A closing case that is a sub-case sends the step that runs it its outcome, in the closing's transaction; a step
    that cannot take it (its case is gone) is noted in the closing case's history instead."""
    if step_id is not None:
        return
    row = cases.find_case_in(c, case_id)
    parent = ((row or {}).get("data") or {}).get(process_runtime.PARENT)
    if not parent:
        return
    n = len(cases.history_in(c, case_id, "closed"))
    try:
        cases.send_event_in(c, parent["case"], f"{case_id}:closed:{n}", CLOSED,
                            {"case_id": case_id, "outcome": row["outcome"]}, actor, step_id=parent["step"])
    except (cases.UnknownCase, cases.UnknownEvent) as exc:
        cases.record(c, case_id, None, "parent_not_told", actor, {"why": str(exc)[:300]})


def _spent(case_id: str, step_id: str) -> list[str]:
    """The budget scopes the step's sub-cases spent from, the earlier ones first: each one's steps' own, so the case's
    cost shows what its sub-cases spent."""
    with store.connect() as c:
        gathered = _gathered(cases.find_step_in(c, case_id, step_id) or {})
    subs = [str(e["case_id"]) for e in gathered.get("earlier") or ()] + ([gathered["case_id"]] if gathered.get("case_id") else [])
    out: list[str] = []
    for sub in subs:
        pack = process_runtime.pack_for(sub)
        for step in pack.steps if pack is not None else ():
            out += [s for s in capabilities.step_scopes(sub, step.id, step.uses) if s not in out]
    return out


def _sub_case_view(case_id: str, step_id: str | None, _shared: dict[str, Any]) -> dict[str, Any]:
    """What a step that runs a sub-case shows on its case's page (the element `sub_case`): the sub-case's process, the
    sub-case (its name, state, outcome and, while it is open, its own next step) and the earlier ones that closed
    otherwise; while the step waits for it, the case's next step is the sub-case's."""
    from jav.app import case_views  # lazy: the case page reads the registered capabilities

    step = str(step_id)
    pack = process_runtime.pack_for(case_id)
    pstep = next(s for s in pack.steps if s.id == step) if pack is not None else None
    params = RunCase.model_validate(pstep.params) if pstep is not None else None
    with store.connect() as c:
        row = cases.find_step_in(c, case_id, step) or {}
    gathered = _gathered(row)
    target = process_packs.load(params.pack) if params is not None else None
    out: dict[str, Any] = {"state": row.get("state"), "pack": target.id if target else None,
                           "process": target.title if target else None, "case": None,
                           "earlier": gathered.get("earlier") or [], "next": None}
    sub = gathered.get("case_id")
    if sub:
        with store.connect() as c:
            sub_row = cases.find_case_in(c, sub) or {}
        is_open = sub_row.get("status") == cases.OPEN
        out["case"] = {"id": sub, "name": work.get(sub)["name"], "status": sub_row.get("status"),
                       "outcome": sub_row.get("outcome"), "next": case_views.next_of(sub) if is_open else None}
        if row.get("state") == cases.RUNNING and is_open:
            out["next"] = {"code": "case_sub_case", "label": "Continue in its sub-case", "stage": "process",
                           "element": "sub_case"}
    return out


CAPABILITY = capabilities.Capability(
    name="run_case", version=1, module=_OWNER, run=_run, kind="wait", params=RunCase, effects="store", state="step",
    output=CaseRunResult, events=(CLOSED,), on_event=_on_event, waits={CLOSED: "sub_case"}, spent=_spent,
    summary="Runs a case of another process with this case's scope and the step's own documents, and waits until it closes.",
    pack_check=_pack_check, scope_check=_scope_check)


def register() -> None:
    from jav.app import case_views

    scopes.register(STEP_SOURCES_PART)
    capabilities.register(CAPABILITY)
    cases.on_leave(_left)
    case_views.register(case_views.ElementData("sub_case", CAPABILITY.name, _OWNER, _sub_case_view))
