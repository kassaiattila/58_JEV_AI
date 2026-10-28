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
  `adopt_all(actor, write=)` (C1c): every package of a kind a pack takes over (`adopts`), with its stored scope;
  (C3b4) and every package of a kind it wraps (`wraps`).
- `pack_step_kind(pack, start, ...)` and `wrap_into(pack_id, wp_id, scope, actor)` (231, C3b5b): the workflow step
  kind a pack serves (its `workflow` block), and its new package wrapped by a case of the pack.
- `wrap_case(pack_id, wp_id, rule, actor)` (231, plan stage C, C3b4): a new case made around a package made before (a
  package with runs cannot be a case's container): the package keeps its id, items, runs and approvals and becomes the
  package of the case's step, which starts in the state its capability reads from the package's runs.
- `pack_of(case_id)`: the pack id and version a case runs on; `pack_for(case_id)`: that version of the pack itself (A7a:
  an older version comes back from the calculation snapshot the case was linked to when it started, so a case keeps
  the screens and outputs it started with after its pack changes).
- `own_version_steps(case_id)`, `approval_steps(case_id)`, `step_using(case_id, capability)` (stage D0, D0-b): the
  case's steps done with an approved own version of theirs, those of them it waits for from its start (each its own
  person's task, `own_approval:<case>:<step>`), and its step that uses a capability.
- `basis_of(case_id, step_id)`, `outdated(case_id, step_id)` (D0-d): the result versions of the steps a step builds on
  (an approval records them), and why the step's approved version is out of date (one of them changed since); the
  approving capability reopens it then, with that reason, and a person approves it again.
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
from jav.core import activity_kinds, identity, rulebook, store
from jav.core.process import cases
from jav.core.user_messages import explained

__all__ = ["CONTAINER", "CONTAINER_PACK", "adopt_all", "adopt_case", "approval_steps", "basis_of", "kept_of", "outdated",
           "outputs_of", "own_version_steps", "unfit_cases", "FollowUpError", "follow_up", "follow_ups",
           "owns_approval", "pack_for", "pack_of", "pack_step_kind", "register", "start_case", "step_using", "wrap_case",
           "wrap_into"]

CONTAINER = "case"  # the container work package's kind
activity_kinds.register_events("package", ("case_wrapped",), __name__)  # C3b4: a wrapped package's log names its case


def start_case(pack_id: str, scope: dict[str, Any], *, name: str, actor: identity.Who, follows: str | None = None) -> str:
    """Starts a case of the pack's current version with this scope (checked by its parts); returns its id. 231 (B2):
    with the process's own active values over the file's resources, kept in the case's data (a later change reaches
    only the cases started after it); (B3) and its own active rule values, which the case's work reads over the rule
    files (`capabilities.case_rules`). Stage D0 (D0-e): it keeps the versions current at its start to its end: its
    resources naming a versioned thing (a price list, a template) at their version then, and the rule files its steps
    read as its calculation snapshot holds them (`capabilities.KEPT_RULES`)."""
    from jav.app import process_settings

    pack = process_packs.load(pack_id)
    checked = scopes.check(pack.scope.needs(), scope, optional=pack.scope.optional)
    kept = process_settings.at_start(pack)  # D-a: before anything is made, so a refused start leaves nothing
    resources = kept.resources
    rules, rule_refs = process_settings.effective_rules(pack)
    definition = process_packs.definition(kept)
    wp = work.create_workpackage(name=name, source_kind=CONTAINER, source_ref=f"pack:{pack.id}@{pack.version}", owner=actor)
    case_id = wp["id"]
    data = {"pack": pack.id, "pack_version": pack.version, "container": case_id, "name": wp["name"], "scope": checked,
            "resources": resources, capabilities.RULES: rules, capabilities.RULE_REFS: rule_refs,
            capabilities.KEPT_RULES: _kept_rule_files(pack)} | ({"follows": follows} if follows else {})
    with cases.transaction() as c:
        package_scope.save(c, case_id, parts=checked, actor=actor, **_scope_columns(checked))
        cases.start_in(c, case_id, definition, data, identity.who(actor))
        for step_id in _approving(pack, from_start=True):  # C3a-1: it waits for that approval as a person's task
            human_tasks.own_approval_waits(c, case_id, step_id)  # D0-b: each approving step for its own
    return case_id


class FollowUpError(ValueError):
    """No such follow-up of the case now: it is open, closed otherwise, or the follow-up was started already."""


FOLLOWED = "followed_up"  # 231 (U1): the history row of a follow-up started from a closed case


def follow_ups(case_id: str) -> list[dict[str, Any]]:
    """231 (U1; the owner's decision of 2026-10-28): what may follow the case now: its pack's follow-ups for the outcome
    it closed with ({pack, title, case_id}: the case started from it, None until one was); none while it is open."""
    pack = pack_for(case_id)
    with store.connect() as c:
        row = cases.find_case_in(c, case_id) or {}
        started = {h["detail"].get("pack"): h["detail"].get("case") for h in cases.history_in(c, case_id, FOLLOWED)}
    if pack is None or row.get("status") != cases.CLOSED:
        return []
    return [{"pack": f.pack, "title": f.title, "case_id": started.get(f.pack)} for f in pack.follow_ups
            if f.on == row.get("outcome")]


def follow_up(case_id: str, pack_id: str, *, actor: identity.Who) -> str:
    """231 (U1): a case of the follow-up process `pack_id` started from the closed case's own scope (its documents),
    named as it is and knowing the case it follows (`follows` in its data); recorded on the closed case. Refused
    (`FollowUpError`) when the case offers no such follow-up now or it was started already."""
    offered = next((f for f in follow_ups(case_id) if f["pack"] == pack_id), None)
    if offered is None:
        raise explained(FollowUpError, "the case offers no follow-up {{pack}} now", pack=pack_id)
    if offered["case_id"] is not None:
        raise explained(FollowUpError, "the follow-up was started already: {{case}}", case=offered["case_id"])
    with store.connect() as c:
        data = (cases.find_case_in(c, case_id) or {}).get("data") or {}
    target = process_packs.load(pack_id)
    scope = {k: v for k, v in (data.get("scope") or {}).items() if k in target.scope.parts}
    new = start_case(pack_id, scope, name=str(data.get("name") or case_id), actor=actor, follows=case_id)
    with cases.transaction() as c:
        cases.record(c, case_id, None, FOLLOWED, identity.who(actor), {"pack": pack_id, "case": new})
    return new


def _kept_rule_files(pack: process_packs.ProcessPack) -> list[str]:
    """D0-e: the rule files a case of the pack reads as it started: those its steps' capabilities read. D-d1: and those a
    step reads by its parameters (a fact catalogue a parameter names; a parameter naming a resource reads its value)."""
    names: set[str] = set()
    for step in pack.steps:
        cap = capabilities.of(step.uses)
        names |= set(cap.rule_files)
        if cap.reads is not None:
            params = {k: pack.resources.get(v[1:], v) if isinstance(v, str) and v.startswith("@") else v
                      for k, v in (step.params or {}).items()}
            names |= set(cap.reads(params))
    return sorted(names)


def kept_of(case_id: str) -> dict[str, Any] | None:
    """D0-e: what a case keeps from its start, as its history shows it: its resources at their versions ({key, label,
    name, version}) and the rule files at the versions its calculation snapshot holds ({file, version}); None for a
    case started before D0-e, which reads the files and the active versions."""
    from jav.app import process_settings

    with store.connect() as c:
        row = cases.find_case_in(c, case_id)
        data = (row or {}).get("data") or {}
        if capabilities.KEPT_RULES not in data:
            return None
        snapshot = rulebook.get_in(c, rulebook.of_in(c, rulebook.CASE, case_id) or "")
    files = (snapshot or {}).get("files", {})
    pack = pack_for(case_id)
    return {"resources": process_settings.kept_view(pack, data.get("resources") or {}) if pack else [],
            "rules": [{"file": name, "version": (files.get(_config_path(name)) or {}).get("version")}
                      for name in data[capabilities.KEPT_RULES]]}


def _config_path(name: str) -> str:
    from jav.core import cfg

    return cfg.path_of(name).relative_to(cfg.CONFIG_DIR).as_posix()


def unfit_cases() -> list[dict[str, Any]]:
    """D0-e, before a release: the open cases whose kept copy of a rule file the code running now does not read
    (another main version), each {case, name, file, why}; their steps that read it stop with why until a person
    decides (an empty list: every open case goes on)."""
    out = []
    with store.connect() as c:
        rows = [cases.find_case_in(c, case_id) for case_id in cases.open_ids_in(c)]
    for row in rows:
        data = (row or {}).get("data") or {}
        names = tuple(sorted(data.get(capabilities.KEPT_RULES) or ()))
        if not names:
            continue
        _base, unfit = capabilities.kept_rules(row["case_id"], names)
        out += [{"case": row["case_id"], "name": data.get("name"), "file": name, "why": why} for name, why in sorted(unfit.items())]
    return out


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
    kept = process_settings.at_start(pack)  # D0-e, D-a
    resources = kept.resources
    rules, rule_refs = process_settings.effective_rules(pack)
    definition = process_packs.definition(kept)
    states = {}
    for step in pack.steps:
        cap = capabilities.of(step.uses)
        if cap.adopt is not None and (state := cap.adopt(wp_id, definition.step(step.id).params)) is not None:
            states[step.id] = state
    data = {"pack": pack.id, "pack_version": pack.version, "container": wp_id, "name": wp["name"], "scope": checked,
            "resources": resources, capabilities.RULES: rules, capabilities.RULE_REFS: rule_refs,
            capabilities.KEPT_RULES: _kept_rule_files(pack),
            "adopted_from": {"source_kind": wp["source_kind"], "source_ref": wp.get("source_ref")}}
    who = identity.who(actor)
    with cases.transaction() as c:
        if cases.find_case_in(c, wp_id) is not None:
            return "exists"
        work.retype_in(c, wp_id, source_kind=CONTAINER, source_ref=f"pack:{pack.id}@{pack.version}", actor=actor)
        package_scope.save(c, wp_id, parts=checked, actor=actor, **_scope_columns(checked))
        rulebook.link_in(c, rulebook.CASE, wp_id)  # the code and the rules the case was taken over with
        owner = identity.who(wp["owner"]) if wp.get("owner") else who
        adopted = cases.adopt(c, wp_id, definition, data, owner, who, states)
        human_tasks.case_adopted(c, wp_id, _approving(pack))  # D0-b: the package's approval task is its step's now
        return adopted


class _Bound(Exception):
    """The package belongs to a step already: the wrapping's transaction is undone."""


def _wrapping_step(pack: process_packs.ProcessPack, rule: process_packs.Wrap) -> tuple[Any, capabilities.Capability]:
    step = next(s for s in pack.steps if s.id == rule.step)
    cap = capabilities.of(step.uses)
    if cap.bind is None or cap.bound is None:
        raise explained(ValueError, "step {{step}} takes no package", step=step.id)
    return step, cap


def wrap_into(pack_id: str, wp_id: str, *, scope: dict[str, Any], actor: identity.Who) -> str:
    """231 (C3b5b): a workflow step's new package wrapped by a new case of the pack that serves the step (its `workflow`
    block: the step that takes the package and the scope part naming it), with the workflow's `scope` (its party and
    period, as the pack takes them). "wrapped"; "exists" for a package a step has already."""
    pack = process_packs.load(pack_id)
    serves = pack.workflow
    if serves is None:
        raise explained(ValueError, "process pack {{pack}} serves no workflow step", pack=pack_id)
    return _wrap(pack, wp_id, step_id=serves.step, package_part=serves.package_part, scope=scope, actor=actor)


def pack_step_kind(pack: process_packs.ProcessPack, *, start: Any, package_kinds: tuple[str, ...], rule: str | None = None,
                   only_new: bool = False, subfolders: bool = False, repeat_from: Any = None, estimate: Any = None,
                   poll: Any = None) -> Any:
    """231 (C3b5b): the workflow step kind the pack serves (`ProcessPack.workflow`), with the facts its step's capability
    gives (`start`, the kinds and the rule of a package the step may take, whether it leaves out what a live run has
    processed or takes subfolders, its repeat source and estimate; C3d: its `poll`, for a step whose source is fetched
    first, a mailbox download): a paid step that runs its own package, so it may have
    its own AI engine, needing the parts of the workflow's scope the pack takes (its party and period). A kind of the
    general process runtime, not a domain's."""
    from jav.app import workflow_steps

    assert pack.workflow is not None
    return workflow_steps.StepKind(pack.workflow.kind, __name__, package_kinds, start=start, poll=poll, paid=True, own_engine=True,
                                   only_new=only_new, subfolders=subfolders, repeat_from=repeat_from, estimate=estimate,
                                   needs=tuple(p for p in (scopes.PARTY, scopes.PERIOD) if p in pack.scope.parts),
                                   rule=rule)


def wrap_case(pack_id: str, wp_id: str, rule: process_packs.Wrap, *, actor: identity.Who) -> str:
    """231 (plan stage C, C3b4): a new case of the pack's current version made around the existing package `wp_id`
    (`rule`: one of the pack's `wraps`), in one write transaction: its container (the package's name, owner and
    archive state), its scope (the parts the package's stored scope gives, the rule's package part naming the package),
    the step's binding of the package (`Capability.bind`) and the case, its step in the state its capability reads from
    the package's runs (`Capability.adopt`). The package keeps its id, kind, items, runs, approvals and versions; its log
    names the case. "wrapped"; "exists" for a package a step has already (nothing changes). KeyError: no package;
    `scopes.ScopeError`: its stored scope does not give the case's."""
    pack = process_packs.load(pack_id)
    stored = package_scope.stored(wp_id) or {}
    return _wrap(pack, wp_id, step_id=rule.step, package_part=rule.package_part,
                 scope={part: _stored_value(stored, key) for part, key in rule.scope.items()}, actor=actor)


def _wrap(pack: process_packs.ProcessPack, wp_id: str, *, step_id: str, package_part: str, scope: dict[str, Any],
          actor: identity.Who) -> str:
    """The wrapping itself (`wrap_case`, `wrap_into`): the case's scope is `scope` with `package_part` naming the
    package."""
    from jav.app import process_settings

    step = next(s for s in pack.steps if s.id == step_id)
    cap = capabilities.of(step.uses)
    if cap.bind is None or cap.bound is None:
        raise explained(ValueError, "step {{step}} takes no package", step=step.id)
    wp = work.get(wp_id)
    scope = {**scope, package_part: {"kind": "package", "workpackage_id": wp_id}}
    checked = scopes.check(pack.scope.needs(), scope, optional=pack.scope.optional)
    kept = process_settings.at_start(pack)  # D0-e, D-a
    resources = kept.resources
    rules, rule_refs = process_settings.effective_rules(pack)
    definition = process_packs.definition(kept)
    params = definition.step(step.id).params
    who = identity.who(actor)
    owner = identity.who(wp["owner"]) if wp.get("owner") else who
    try:
        with store.session(), cases.transaction() as c:
            case_id = work.create_workpackage(name=wp["name"], source_kind=CONTAINER,
                                              source_ref=f"pack:{pack.id}@{pack.version}", owner=owner)["id"]
            if not cap.bind(wp_id, case_id, step.id, params, checked, actor):
                raise _Bound
            package_scope.save(c, case_id, parts=checked, actor=actor, **_scope_columns(checked))
            rulebook.link_in(c, rulebook.CASE, case_id)  # the code and the rules the case was made with
            state = cap.adopt(wp_id, params) if cap.adopt is not None else None
            data = {"pack": pack.id, "pack_version": pack.version, "container": case_id, "name": wp["name"],
                    "scope": checked, "resources": resources, capabilities.RULES: rules,
                    capabilities.RULE_REFS: rule_refs, capabilities.KEPT_RULES: _kept_rule_files(pack),
                    "wrapped": {"workpackage_id": wp_id, "source_kind": wp["source_kind"]}}
            cases.adopt(c, case_id, definition, data, owner, who, {step.id: state} if state is not None else {})
            if wp["status"] == "archived":  # an archived package's case is archived too
                c.execute("UPDATE workpackages SET status='archived' WHERE id=?", (case_id,))
            work.record_event(c, wp_id, "case_wrapped", actor, {"case": case_id, "pack": pack.id, "step": step.id})
    except _Bound:
        return "exists"
    return "wrapped"


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
        for wrap in pack.wraps:  # 231 (C3b4): a package with runs gets a new case around it
            _step, cap = _wrapping_step(pack, wrap)
            for wp in work.list_workpackages(include_archived=True):
                named = wp.get("source_kind") == wrap.kind if wrap.kind else work.rule_name(wp["id"]) == wrap.rule
                if not named or wp.get("status") == "deleted" or cap.bound(wp["id"]):
                    continue  # (C3b5a: by its kind or its rule) a step's package already (made by a case, or wrapped before)
                stored = package_scope.stored(wp["id"]) or {}
                scope = {part: _stored_value(stored, key) for part, key in wrap.scope.items()}
                row = {"pack": pack.id, "workpackage_id": wp["id"], "name": wp["name"], "scope": scope}
                try:
                    result = wrap_case(pack.id, wp["id"], wrap, actor=actor) if write else "to wrap"
                except scopes.ScopeError as exc:
                    out.append({**row, "result": "refused", "error": str(exc)})
                    continue
                out.append({**row, "result": result})
    return out


def own_version_reopened(c: Any, wp_id: str, actor: Any, reason: str, *, step: str | None = None) -> list[str]:
    """231 (C2d): the approved own version of a case's container was reopened, in that change's transaction: each done
    step whose capability is done with that version (`Capability.own_version`) opens again (a case closed as done opens
    too) and the steps built on it go out of date; returns them. Nothing for a package that is no case's, or a case
    closed otherwise. D0-b: only the approving `step` whose version it was (None: every such step, as for a version
    recorded before D0-b)."""
    case = cases.find_case_in(c, wp_id)
    if case is None or (case["status"] == cases.CLOSED and case["outcome"] != "done"):
        return []
    out: list[str] = []
    for s in cases.definition_of(case).steps:
        cap = capabilities.of_step_kind(s.kind)
        row = cases.find_step_in(c, wp_id, s.id)
        if (cap is not None and cap.own_version and row is not None and row["state"] == cases.DONE
                and (step is None or s.id == step)):
            out += cases.reopen_in(c, wp_id, s.id, actor, reason=reason)
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


def _approving(pack: process_packs.ProcessPack, *, from_start: bool = False) -> list[str]:
    """D0-b: the pack's steps done with an approved own version of theirs (`Capability.own_version`); `from_start`:
    only those the case waits for from its start, as a person's task (their capability says how a version is
    reopened), not those whose step opens its task itself (the quote's line composition, once its draft is made)."""
    out = []
    for step in pack.steps:
        cap = capabilities.of(step.uses)
        if cap.own_version and (cap.reopen is not None or not from_start):
            out.append(step.id)
    return out


def _pack_or_none(case_id: str, c: Any) -> process_packs.ProcessPack | None:
    try:
        return _pack_for_in(c, case_id)
    except (KeyError, process_packs.PackError):
        return None


def own_version_steps(case_id: str, c: Any = None) -> list[str]:
    """D0-b: the case's steps done with an approved own version of theirs, in the pack's order ([] for a package that is
    no case's). On the caller's connection `c` when given (a store's schema change asks it while it runs)."""
    if c is None:
        with store.connect() as own:
            return own_version_steps(case_id, own)
    pack = _pack_or_none(case_id, c)
    return _approving(pack) if pack is not None else []


def approval_steps(case_id: str, c: Any = None) -> list[str]:
    """D0-b: the case's approving steps it waits for from its start, each as a person's task of its own."""
    if c is None:
        with store.connect() as own:
            return approval_steps(case_id, own)
    pack = _pack_or_none(case_id, c)
    return _approving(pack, from_start=True) if pack is not None else []


def step_using(case_id: str, capability: str, c: Any = None) -> str | None:
    """D0-b: the case's first step that uses the capability named `capability` (any version); None for a package that
    is no case's, or a case without one. A capability whose state belongs to the case stands once in its pack."""
    if c is None:
        with store.connect() as own:
            return step_using(case_id, capability, own)
    pack = _pack_or_none(case_id, c)
    return next((s.id for s in pack.steps if s.uses.split("@", 1)[0] == capability), None) if pack is not None else None


def basis_of(case_id: str, step_id: str, c: Any = None) -> dict[str, int]:
    """D0-d: the result versions of the steps the case's step builds on, now ({} for a package that is no case's)."""
    if c is None:
        with store.connect() as own:
            return basis_of(case_id, step_id, own)
    case = cases.find_case_in(c, case_id)
    if case is None:
        return {}
    rows = cases.step_rows(c, case_id)
    return {n: int(rows[n]["result_version"]) for n in cases.definition_of(case).step(step_id).needs()}


def outdated(case_id: str, step_id: str, c: Any = None) -> str | None:
    """D0-d: why the step's approved version is out of date: the steps it builds on whose result changed since it was
    approved, by their titles (D0-z: a person reads them; the step's id where it has none); None when it holds on what is
    there now (or nothing holds, or it was approved before D0-d)."""
    if c is None:
        with store.connect() as own:
            return outdated(case_id, step_id, own)
    active = package_release.own_approval(case_id, c, step=step_id)["active"]
    if active is None or active.get("basis") is None:
        return None
    now = basis_of(case_id, step_id, c)
    changed = sorted(s for s, v in active["basis"].items() if now.get(s) != v)
    if not changed:
        return None
    pack = _pack_for_in(c, case_id)
    titles = {s.id: s.title or s.id for s in pack.steps} if pack else {}
    return f"{package_release.OUTDATED}an earlier step it builds on changed: {', '.join(titles.get(s, s) for s in changed)}"


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


def _approval_what(subject: str) -> str | None:
    """What a case's approval is about in "Waiting for me": its approving capability's words. D0-b: `subject` is the
    case, or its approving step's task subject (`<case>:<step>`), whose capability's words count then."""
    case_id, _, step_id = subject.partition(":")
    if step_id:
        with store.connect() as c:
            pack = _pack_or_none(case_id, c)
        uses = next((s.uses for s in pack.steps if s.id == step_id), None) if pack is not None else None
        cap = capabilities.of(uses) if uses else None
        if cap is not None and cap.approval_what:
            return cap.approval_what
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
    the email routing, once every document is decided). D0-b: every approving step of the case holds a version."""
    steps = own_version_steps(case_id)
    if steps and all(package_release.own_approval(case_id, step=s)["active"] is not None for s in steps):
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
    add_refusal="a case's documents are in the packages its scope names",  # C3a-2: as a reconciliation package's were
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
