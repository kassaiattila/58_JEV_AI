"""A process pack's cases (231, plan stage A, A5; DECISIONS 231): starting one and finding it.

Plain-language summary: a process pack describes one kind of business process; one running instance of it is a case of
the process core. Starting a case makes its container (a general work package that holds the case's rows, so everything
keyed by a package keeps working: drafts, approvals, versions, decisions, template choices), then, in one write
transaction, the container's scope and the process core's case of the pack's current version under the same id. From there the
process core moves the case on, step by step, each step through its capability (`jav/app/capabilities.py`); a step a
person starts waits for that person's start task.

- `start_case(pack_id, scope, name, actor)`: the case's id (its container's).
- `adopt_case(pack_id, wp_id, scope, actor)` (231, plan stage C, C0): an existing work package taken over as a case
  under its own id, each step in the state its capability reads from the package's work (`Capability.adopt`);
  `adopt_all(actor, write=)` (C1c): every package of a kind a pack takes over (`adopts`), with its stored scope.
- `pack_of(case_id)`: the pack id and version a case runs on; `pack_for(case_id)`: that version of the pack itself (A7a:
  an older version comes back from the calculation snapshot the case was linked to when it started, so a case keeps
  the screens and outputs it started with after its pack changes).
- `CONTAINER_PACK`: how the work package registry knows a container (A6): a package without runs whose page names its
  case (the interface opens the case's page), whose next step is the case's state, whose outputs are its pack's, and
  which is neither released the shared way nor deleted while its case exists. It is general, the same for every pack.

Layer: application; it uses the process packs, the scope parts, the work packages, the package scopes and the process
core's public operations.
"""

from __future__ import annotations

from typing import Any

import json
from functools import cache

from jav.app import capabilities, human_tasks, logic_packs, package_release, package_scope, process_packs, scopes, work
from jav.core import identity, rulebook, store
from jav.core.process import cases
from jav.core.user_messages import explained

__all__ = ["CONTAINER", "CONTAINER_PACK", "adopt_all", "adopt_case", "outputs_of", "owns_approval", "pack_for", "pack_of",
           "register", "start_case"]

CONTAINER = "case"  # the container work package's kind


def start_case(pack_id: str, scope: dict[str, Any], *, name: str, actor: identity.Who) -> str:
    """Starts a case of the pack's current version with this scope (checked by its parts); returns its id. 231 (B2):
    with the process's own active values over the file's resources, kept in the case's data (a later change reaches
    only the cases started after it); (B3) and its own active rule values, which the case's work reads over the rule
    files (`capabilities.case_rules`)."""
    from jav.app import process_settings

    pack = process_packs.load(pack_id)
    checked = scopes.check(pack.scope.needs(), scope, optional=pack.scope.optional)
    resources = process_settings.effective_resources(pack)
    rules, rule_refs = process_settings.effective_rules(pack)
    definition = process_packs.definition(pack.model_copy(update={"resources": resources}))
    wp = work.create_workpackage(name=name, source_kind=CONTAINER, source_ref=f"pack:{pack.id}@{pack.version}", owner=actor)
    case_id = wp["id"]
    data = {"pack": pack.id, "pack_version": pack.version, "container": case_id, "name": wp["name"], "scope": checked,
            "resources": resources, capabilities.RULES: rules, capabilities.RULE_REFS: rule_refs}
    with cases.transaction() as c:
        package_scope.save(c, case_id, parts=checked, actor=actor, **_scope_columns(checked))
        cases.start_in(c, case_id, definition, data, identity.who(actor))
        if _approval_capability(pack) is not None:  # C3a-1: it waits for that approval as a person's task
            human_tasks.own_approval_waits(c, case_id)
    return case_id


def _scope_columns(checked: dict[str, Any]) -> dict[str, Any]:
    """231 (C2d): a case's party and period in the shared scope's own columns too, beside its parts, as every package's
    scope keeps them: a party's merge moves them, and a domain reads them as it reads its own packages'."""
    period = checked.get(scopes.PERIOD)
    return {"party_id": checked.get(scopes.PARTY), "period_start": period[0] if period else None,
            "period_end": period[1] if period else None}


def adopt_case(pack_id: str, wp_id: str, scope: dict[str, Any], *, actor: identity.Who) -> str:
    """231 (plan stage C, C0; the owner's decision of 2026-10-25): the existing work package `wp_id` taken over as a case of
    the pack's current version under its own id, so its decisions, versions, locks and approved statements stay where
    they are. Its kind becomes the container's (the kind it had is kept in the case's data and its log), its scope is the
    pack's (checked by its parts), it takes the process's active values as a new case does, and each step starts in the
    state its capability reads from the work the package already holds (`Capability.adopt`; without one, or None: the
    step has not run). "adopted"; "exists" for a package already taken over (nothing changes). KeyError: no package."""
    from jav.app import process_settings

    pack = process_packs.load(pack_id)
    checked = scopes.check(pack.scope.needs(), scope, optional=pack.scope.optional)
    wp = work.get(wp_id)
    resources = process_settings.effective_resources(pack)
    rules, rule_refs = process_settings.effective_rules(pack)
    definition = process_packs.definition(pack.model_copy(update={"resources": resources}))
    states = {}
    for step in pack.steps:
        cap = capabilities.of(step.uses)
        if cap.adopt is not None and (state := cap.adopt(wp_id, definition.step(step.id).params)) is not None:
            states[step.id] = state
    data = {"pack": pack.id, "pack_version": pack.version, "container": wp_id, "name": wp["name"], "scope": checked,
            "resources": resources, capabilities.RULES: rules, capabilities.RULE_REFS: rule_refs,
            "adopted_from": {"source_kind": wp["source_kind"], "source_ref": wp.get("source_ref")}}
    who = identity.who(actor)
    with cases.transaction() as c:
        if cases.find_case_in(c, wp_id) is not None:
            return "exists"
        work.retype_in(c, wp_id, source_kind=CONTAINER, source_ref=f"pack:{pack.id}@{pack.version}", actor=actor)
        package_scope.save(c, wp_id, parts=checked, actor=actor, **_scope_columns(checked))
        rulebook.link_in(c, rulebook.CASE, wp_id)  # the code and the rules the case was taken over with
        owner = identity.who(wp["owner"]) if wp.get("owner") else who
        return cases.adopt(c, wp_id, definition, data, owner, who, states)


def adopt_all(*, actor: identity.Who, write: bool = False) -> list[dict[str, Any]]:
    """231 (C1c): every work package of a kind a process pack takes over (`adopts`), each with the scope its stored scope
    parts give: [{pack, workpackage_id, name, scope, result}]; `result` is "adopted" or "exists" when `write`, else
    "to adopt" (nothing changes). 231 (C3a-1): a package whose scope its pack refuses (no party given or implied) is
    "refused" with the reason in `error`, without a change, and the others go on, so a release never stops half-way."""
    out = []
    for pack in process_packs.packs():
        for rule in pack.adopts:
            for wp in work.list_workpackages(include_archived=True):
                if wp.get("source_kind") != rule.kind:
                    continue
                stored = package_scope.stored(wp["id"]) or {}
                scope = {part: _stored_value(stored, key) for part, key in rule.scope.items()}
                row = {"pack": pack.id, "workpackage_id": wp["id"], "name": wp["name"], "scope": scope}
                try:
                    scopes.check(pack.scope.needs(), scope, optional=pack.scope.optional)
                except scopes.ScopeError as exc:
                    out.append({**row, "result": "refused", "error": str(exc)})
                    continue
                out.append({**row, "result": adopt_case(pack.id, wp["id"], scope, actor=actor) if write else "to adopt"})
    return out


def own_version_reopened(c: Any, wp_id: str, actor: Any, reason: str) -> list[str]:
    """231 (C2d): the approved own version of a case's container was reopened, in that change's transaction: each done
    step whose capability is done with that version (`Capability.own_version`) opens again (a case closed as done opens
    too) and the steps built on it go out of date; returns them. Nothing for a package that is no case's, or a case
    closed otherwise."""
    case = cases.find_case_in(c, wp_id)
    if case is None or (case["status"] == cases.CLOSED and case["outcome"] != "done"):
        return []
    out: list[str] = []
    for step in cases.definition_of(case).steps:
        cap = capabilities.of_step_kind(step.kind)
        row = cases.find_step_in(c, wp_id, step.id)
        if cap is not None and cap.own_version and row is not None and row["state"] == cases.DONE:
            out += cases.reopen_in(c, wp_id, step.id, actor, reason=reason)
    return out


def _stored_value(stored: dict[str, Any], key: str) -> Any:
    """A stored scope's value by its key: a further part, or (231, C2d) the party and the period from their own columns,
    where a logic pack's package keeps them."""
    parts = stored.get("parts") or {}
    if key in parts:
        return parts[key]
    if key == scopes.PARTY:
        return stored.get("party_id")
    if key == scopes.PERIOD and stored.get("period_start") and stored.get("period_end"):
        return [stored["period_start"], stored["period_end"]]
    return None


def resource_of(c: Any, case_id: str, key: str) -> str | None:
    """231 (B2): a resource of the case as it started (its pack's, with the process's own values then); None for a
    package that is no case or a resource it does not have. `c`: an open connection."""
    row = cases.find_case_in(c, case_id)
    if row is None:
        return None
    value = (json.loads(row["data"]) if isinstance(row["data"], str) else row["data"] or {}).get("resources", {}).get(key)
    return str(value) if value is not None else None


def _pack_of_in(c: Any, case_id: str) -> tuple[str, str] | None:
    row = cases.find_case_in(c, case_id)
    data = (row or {}).get("data") or {}
    return (data["pack"], data["pack_version"]) if "pack" in data else None


def pack_of(case_id: str) -> tuple[str, str] | None:
    """(the pack id, its version) a case runs on, or None for a case that is no pack's."""
    with store.connect() as c:
        return _pack_of_in(c, case_id)


def pack_for(case_id: str) -> process_packs.ProcessPack | None:
    """The version of its pack a case runs on: the current one when it is that version, else the one its start's
    calculation snapshot holds (`process_packs.PackError` when neither has it)."""
    with store.connect() as c:
        return _pack_for_in(c, case_id)


def _pack_for_in(c: Any, case_id: str) -> process_packs.ProcessPack | None:
    """`pack_for` on the caller's connection (C3a-1: a store's schema change reads it while it runs)."""
    pinned = _pack_of_in(c, case_id)
    if pinned is None:
        return None
    current = process_packs.load(pinned[0])
    if current.version == pinned[1]:
        return current
    snapshot = rulebook.get_in(c, rulebook.of_in(c, rulebook.CASE, case_id) or "")
    entry = (snapshot or {}).get("files", {}).get(f"processes/{pinned[0]}.json")
    content = rulebook.content_in(c, entry["sha256"]) if entry else None
    if content is None:
        raise process_packs.PackError(f"process pack {pinned[0]!r} {pinned[1]} of case {case_id} is not stored")
    return process_packs.ProcessPack.model_validate(json.loads(content))


def outputs_of(case_id: str) -> tuple[str, ...]:
    """The outputs a case's container has: its pack's (a template is chosen for each of them)."""
    pack = pack_for(case_id)
    return pack.outputs if pack else ()


def _page(case_id: str) -> dict[str, Any]:
    pinned = pack_of(case_id)
    return {"case": {"id": case_id, "pack": pinned[0], "version": pinned[1]} if pinned else None, "next": _next(case_id)}


def _next(case_id: str) -> dict[str, Any]:
    """The container's next step: the case page's (its elements name it), else whether the case is open."""
    from jav.app import case_views  # the case page reads this module

    with store.connect() as c:
        row = cases.find_case_in(c, case_id)
    if row is not None and row["status"] == cases.OPEN and (nxt := case_views.next_of(case_id)):
        return {"params": {}, **{k: v for k, v in nxt.items() if k != "tab"}, "stage": "process"}
    done = row is not None and row["status"] != cases.OPEN
    # 231 (C1c): every next step names its parameters (none here), as the package list reads them
    return {"code": "case_closed" if done else "case_open", "label": "The case is closed" if done else "Open the case",
            "stage": "process", "params": {}}


def _approval_capability(pack: process_packs.ProcessPack) -> capabilities.Capability | None:
    """C3a-1: the capability of the pack's step that is done with the case's own approved version and says how that
    version is reopened (`Capability.reopen`), or None: a case of the pack owns no approval."""
    for step in pack.steps:
        cap = capabilities.of(step.uses)
        if cap.own_version and cap.reopen is not None:
            return cap
    return None


def _case_approval(case_id: str, c: Any = None) -> capabilities.Capability | None:
    if c is None:
        with store.connect() as own:
            return _case_approval(case_id, own)
    try:
        pack = _pack_for_in(c, case_id)
    except (KeyError, process_packs.PackError):
        return None
    return _approval_capability(pack) if pack is not None else None


def owns_approval(case_id: str, c: Any = None) -> bool:
    """231 (C3a-1): whether the case approves its result as its own version (the reconciliation's statement): it waits
    for that approval as a person's task, and a workflow's chain reopens it (rule 218). False for no case. On the
    caller's connection `c` when given (a store's schema change asks it while it runs)."""
    return _case_approval(case_id, c) is not None


def _approval_what(case_id: str) -> str | None:
    cap = _case_approval(case_id)
    return cap.approval_what if cap is not None else None


def _reopen(case_id: str, *, note: str, actor: identity.Who) -> Any:
    """C3a-1: the case's approved version reopened with a reason, in its capability's own way."""
    cap = _case_approval(case_id)
    if cap is None or cap.reopen is None:
        raise explained(package_release.ReleaseError, "the case approves no version of its own")
    return cap.reopen(case_id, note, actor)


def _approved(case_id: str) -> bool:
    """Its result's version is approved, or (231 C1c) its case closed as done (a process without an approval of its own:
    the email routing, once every document is decided)."""
    if package_release.own_approval(case_id)["active"] is not None:
        return True
    with store.connect() as c:
        row = cases.find_case_in(c, case_id)
    return row is not None and row["status"] == cases.CLOSED and row.get("outcome") == "done"


def _release_refusal() -> Exception:
    return explained(package_release.ReleaseError, "a case's result is approved on its own page, step by step")


def _delete_guard(c: Any, case_id: str) -> None:
    if cases.find_case_in(c, case_id) is not None:
        raise explained(work.NotReady, "a case's container is not deleted while its case exists")


CONTAINER_PACK = logic_packs.LogicPack(
    kind=CONTAINER, module=__name__,
    roles=(logic_packs.InputRole("record", "linked_package", "the package item the case starts from"),), has_runs=False, page=_page, approved=_approved, next_step=_next,
    list_next=_next, outputs=(), release_refusal=_release_refusal, delete_guard=_delete_guard,
    approval_what="Approval of a case's result", list_mark=lambda: _list_mark(),
    owns_approval=owns_approval, approval_what_of=_approval_what, reopen=_reopen)  # C3a-1


@cache
def _process_step() -> Any:
    """The process packs' workflow step kind, made once (registering it again adds nothing)."""
    from jav.app import workflow_steps

    return workflow_steps.StepKind("process", __name__, (CONTAINER,), start=_workflow_start, paid=False, own_engine=False,
                                   repeat_from=lambda _wp_id: {"kind": "none"},
                                   statuses={"case_closed": "approved", "case_open": "review"},
                                   needs_of=_process_needs, statuses_of=_process_statuses)  # C3a-1


def _process_needs(step: Any) -> tuple[str, ...]:
    """231 (C3a-1): the parts of the workflow's scope a process step's pack takes (its party and period)."""
    pack = process_packs.load(str(step["pack"]))
    return tuple(p for p in (scopes.PARTY, scopes.PERIOD) if p in pack.scope.parts)


def _process_statuses(step: Any) -> dict[str, str]:
    """231 (C3a-1): what a process step's case's next step codes mean for the workflow: its capabilities' words."""
    out: dict[str, str] = {}
    for s in process_packs.load(str(step["pack"])).steps:
        out.update(capabilities.of(s.uses).statuses)
    return out


def _list_mark() -> list[Any]:
    """231 (A3d): what a case's row in the package list reads: the process core's cases, steps and tasks, and the data
    its page's elements show (their next step comes from it)."""
    from jav.app import case_views

    return [cases.marks(), case_views.marks()]


def _workflow_start(ctx: Any) -> None:
    """231 (C1c): a workflow's step of a process pack (`kind: process`, `pack`): a case of the pack that reads the
    packages of the steps it waits for (scope part `sources`), with the workflow's party and period when the pack
    needs them."""
    pack = process_packs.load(str(ctx.step["pack"]))
    given: dict[str, Any] = {}
    if scopes.SOURCES in pack.scope.parts:
        given[scopes.SOURCES] = [wp for step, wp in ctx.packages.items() if step in (ctx.step.get("after") or []) and wp]
    if scopes.PARTY in pack.scope.parts:
        given[scopes.PARTY] = ctx.workflow["party_id"]
    if scopes.PERIOD in pack.scope.parts:
        given[scopes.PERIOD] = [ctx.workflow["period_start"], ctx.workflow["period_end"]]
    # C3a-2: the workflow's maker owns the case, as they owned the package a retired step made (decision 065)
    ctx.made(start_case(pack.id, given, name=ctx.state["name"], actor=ctx.workflow["actor"]))


def register() -> None:
    """231 (A6): the container kind in the work package registry (`registrations.load_all`); (C1c) the workflows' step
    of a process pack."""
    from jav.app import workflow_steps

    logic_packs.register_container(CONTAINER_PACK)
    workflow_steps.register(_process_step())
