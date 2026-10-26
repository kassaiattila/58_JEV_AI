"""231 (plan stage C, C3a-2): a reconciliation package of the kind made before the reconciliation became a process pack, for
the tests of its takeover (`process_runtime.adopt_all`) and of what reads such a package until then.

`reconcile_package.create` starts the reconciliation process's case since C3a-2; a package of the retired kind is made
here as `reconcile_package.create` made it until then: the package, its scope and its owner's approval task.
"""

from __future__ import annotations

from typing import Any

from jav.app import human_tasks, package_scope, work
from jav.core import store
from jav.domains.finance import reconcile_package


def old_package(*, name: str, accounts: list[str], period_start: str, period_end: str, actor: str,
                party_id: str | None = None) -> str:
    wp = work.create_workpackage(name=name, source_kind=reconcile_package.KIND, source_ref=f"{period_start}..{period_end}",
                                 owner=actor)
    with store.connect() as c:
        store.begin_immediate(c)
        package_scope.save(c, wp["id"], party_id=party_id, period_start=period_start, period_end=period_end,
                           parts={reconcile_package.ACCOUNTS: sorted(set(accounts))}, actor=actor)
        human_tasks.own_approval_waits(c, wp["id"])
    return wp["id"]


def scope_of(wp_id: str) -> dict[str, Any]:
    return package_scope.stored(wp_id) or {}
