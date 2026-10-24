"""A process pack's cases (231, plan stage A, A5; DECISIONS 231): starting one and finding it.

Plain-language summary: a process pack describes one kind of business process; one running instance of it is a case of
the process core. Starting a case makes its container (a general work package that holds the case's rows, so everything
keyed by a package keeps working: drafts, approvals, versions, decisions, template choices), then, in one write
transaction, the container's scope and the process core's case of the pack's current version under the same id. From there the
process core moves the case on, step by step, each step through its capability (`jav/app/capabilities.py`); a step a
person starts waits for that person's start task.

- `start_case(pack_id, scope, name, actor)`: the case's id (its container's).
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

from jav.app import capabilities, logic_packs, package_release, package_scope, process_packs, scopes, work
import json

from jav.core import identity, rulebook, store
from jav.core.process import cases
from jav.core.user_messages import explained

__all__ = ["CONTAINER", "CONTAINER_PACK", "outputs_of", "pack_for", "pack_of", "register", "start_case"]

CONTAINER = "case"  # the container work package's kind


def start_case(pack_id: str, scope: dict[str, Any], *, name: str, actor: identity.Who) -> str:
    """Starts a case of the pack's current version with this scope (checked by its parts); returns its id. 231 (B2):
    with the process's own active values over the file's resources, kept in the case's data (a later change reaches
    only the cases started after it); (B3) and its own active rule values, which the case's work reads over the rule
    files (`capabilities.case_rules`)."""
    from jav.app import process_settings

    pack = process_packs.load(pack_id)
    checked = scopes.check(pack.scope.parts, scope)
    resources = process_settings.effective_resources(pack)
    rules, rule_refs = process_settings.effective_rules(pack)
    definition = process_packs.definition(pack.model_copy(update={"resources": resources}))
    wp = work.create_workpackage(name=name, source_kind=CONTAINER, source_ref=f"pack:{pack.id}@{pack.version}", owner=actor)
    case_id = wp["id"]
    data = {"pack": pack.id, "pack_version": pack.version, "container": case_id, "name": wp["name"], "scope": checked,
            "resources": resources, capabilities.RULES: rules, capabilities.RULE_REFS: rule_refs}
    with cases.transaction() as c:
        package_scope.save(c, case_id, parts=checked, actor=actor)
        cases.start_in(c, case_id, definition, data, identity.who(actor))
    return case_id


def resource_of(c: Any, case_id: str, key: str) -> str | None:
    """231 (B2): a resource of the case as it started (its pack's, with the process's own values then); None for a
    package that is no case or a resource it does not have. `c`: an open connection."""
    row = cases.find_case_in(c, case_id)
    if row is None:
        return None
    value = (json.loads(row["data"]) if isinstance(row["data"], str) else row["data"] or {}).get("resources", {}).get(key)
    return str(value) if value is not None else None


def pack_of(case_id: str) -> tuple[str, str] | None:
    """(the pack id, its version) a case runs on, or None for a case that is no pack's."""
    with store.connect() as c:
        row = cases.find_case_in(c, case_id)
    data = (row or {}).get("data") or {}
    return (data["pack"], data["pack_version"]) if "pack" in data else None


def pack_for(case_id: str) -> process_packs.ProcessPack | None:
    """The version of its pack a case runs on: the current one when it is that version, else the one its start's
    calculation snapshot holds (`process_packs.PackError` when neither has it)."""
    pinned = pack_of(case_id)
    if pinned is None:
        return None
    current = process_packs.load(pinned[0])
    if current.version == pinned[1]:
        return current
    with store.connect() as c:
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
        return {**{k: v for k, v in nxt.items() if k != "tab"}, "stage": "process"}
    done = row is not None and row["status"] != cases.OPEN
    return {"code": "case_closed" if done else "case_open", "label": "The case is closed" if done else "Open the case",
            "stage": "process"}


def _approved(case_id: str) -> bool:
    return package_release.own_approval(case_id)["active"] is not None


def _release_refusal() -> Exception:
    return explained(package_release.ReleaseError, "a case's result is approved on its own page, step by step")


def _delete_guard(c: Any, case_id: str) -> None:
    if cases.find_case_in(c, case_id) is not None:
        raise explained(work.NotReady, "a case's container is not deleted while its case exists")


CONTAINER_PACK = logic_packs.LogicPack(
    kind=CONTAINER, module=__name__,
    roles=(logic_packs.InputRole("record", "linked_package", "the package item the case starts from"),), has_runs=False, page=_page, approved=_approved, next_step=_next,
    list_next=_next, outputs=(), release_refusal=_release_refusal, delete_guard=_delete_guard,
    approval_what="Approval of a case's result", list_mark=lambda: _list_mark())


def _list_mark() -> list[Any]:
    """231 (A3d): what a case's row in the package list reads: the process core's cases, steps and tasks, and the data
    its page's elements show (their next step comes from it)."""
    from jav.app import case_views

    return [cases.marks(), case_views.marks()]


def register() -> None:
    """231 (A6): the container kind in the work package registry (`registrations.load_all`)."""
    logic_packs.register_container(CONTAINER_PACK)
