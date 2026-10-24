"""A process pack's cases (231, plan stage A, A5; DECISIONS 231): starting one and finding it.

Plain-language summary: a process pack describes one kind of business process; one running instance of it is a case of
the process core. Starting a case makes its container (a general work package that holds the case's rows, so everything
keyed by a package keeps working: drafts, approvals, versions, decisions, template choices), then, in one write
transaction, the container's scope and the process core's case of the pack's current version under the same id. From there the
process core moves the case on, step by step, each step through its capability (`jav/app/capabilities.py`); a step a
person starts waits for that person's start task.

- `start_case(pack_id, scope, name, actor)`: the case's id (its container's).
- `pack_of(case_id)`: the pack id and version a case runs on.

Layer: application; it uses the process packs, the scope parts, the work packages, the package scopes and the process
core's public operations.
"""

from __future__ import annotations

from typing import Any

from jav.app import package_scope, process_packs, scopes, work
from jav.core import identity, store
from jav.core.process import cases

__all__ = ["CONTAINER", "start_case", "pack_of"]

CONTAINER = "case"  # the container work package's kind


def start_case(pack_id: str, scope: dict[str, Any], *, name: str, actor: identity.Who) -> str:
    """Starts a case of the pack's current version with this scope (checked by its parts); returns its id."""
    pack = process_packs.load(pack_id)
    checked = scopes.check(pack.scope.parts, scope)
    definition = process_packs.definition(pack)
    wp = work.create_workpackage(name=name, source_kind=CONTAINER, source_ref=f"pack:{pack.id}@{pack.version}", owner=actor)
    case_id = wp["id"]
    data = {"pack": pack.id, "pack_version": pack.version, "container": case_id, "name": wp["name"], "scope": checked}
    with cases.transaction() as c:
        package_scope.save(c, case_id, parts=checked, actor=actor)
        cases.start_in(c, case_id, definition, data, identity.who(actor))
    return case_id


def pack_of(case_id: str) -> tuple[str, str] | None:
    """(the pack id, its version) a case runs on, or None for a case that is no pack's."""
    with store.connect() as c:
        row = cases.find_case_in(c, case_id)
    data = (row or {}).get("data") or {}
    return (data["pack"], data["pack_version"]) if "pack" in data else None
