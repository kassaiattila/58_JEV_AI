"""The finance domain's capabilities (231, plan stage C, C2b; DECISIONS 231): the pairing of two lists as a step.

Plain-language summary: a pairing step proposes, by code and without any AI call, which item of one list settles which
item of the other under the rules it names, and a person decides: confirms or rejects a pair, splits an amount over
several, or marks an item that needs no pair. The step is done when the person approves the result as the case's own
version (the approved reconciliation statement); until then it waits. The only rules so far are the invoices against
the bank and card statement lines (`invoice_statement`: the reconciliation engine, `jav/domains/finance/reconcile.py`,
and its package's decisions, `reconcile_package.py`). A reconciliation package made before is taken over as such a case
with its decisions: its step is done when a version of its statement is approved, otherwise it waits.

- `pairing@1` (human): the pairing step. The monthly reconciliation's process pack names it (C2d), with the pairing
  cards as its screen element; until then no pack uses it.

Layer: the finance domain's registrations of general capabilities (`jav/app/capabilities.py`).
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from jav.app import package_release
from jav.app.capabilities import Capability
from jav.core.process import cases, kinds

POLL_S = 5.0  # how soon a waiting pairing step looks again for the person's approval
WAITING_FOR = "pairing"


class Pairing(BaseModel):
    """`rules`: what is paired with what. `invoice_statement`: the invoices and the bank and card statement lines of the
    case's scope (its party, accounts and period), under `configs/reconcile.json` and `configs/finance.json`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rules: Literal["invoice_statement"]


def _approved(wp_id: str) -> dict[str, Any] | None:
    """The approved version that holds (not reopened), or None: the same rule as a workflow's reconciliation step."""
    return package_release.own_approval(wp_id)["active"]


def _pair(ctx: Any, _params: Pairing) -> kinds.StepOutcome:
    version = _approved(str(ctx.data["container"]))
    if version is not None:
        return kinds.Done({"version": version["version"]})
    return ctx.wait(WAITING_FOR, timer=("check", time.time() + POLL_S))


def _adopt(wp_id: str, _params: dict[str, Any]) -> cases.Adopted:
    """A reconciliation package taken over: done when a version of its statement is approved, else waiting for it."""
    version = _approved(wp_id)
    if version is not None:
        return cases.Adopted(cases.DONE, result={"version": version["version"]})
    return cases.Adopted(cases.RUNNING, waiting_for=WAITING_FOR, timer=("check", time.time() + POLL_S))


_OWNER = __name__
CAPABILITY = Capability(
    name="pairing", version=1, module=_OWNER, run=_pair, kind="human", params=Pairing, effects="store",
    rule_files=("reconcile", "finance"), adopt=_adopt, own_version=True,  # C2d: reopening the statement reopens it
    summary=("Proposes by code which item of one list settles which item of the other; a person confirms, rejects, splits"
             " or marks, and approves the result."))


# 231 (C2d): where each stage of the reconciliation's next step is done: its element's `show` on the case's tabs
_SHOWN_AT = {"process": "lines", "review": "decide", "result": "result"}


def _view(case_id: str, _step: str | None, shared: dict[str, Any]) -> dict[str, Any]:
    """The pairing element's data, read once per page view: the scope, the counts, the approval and the next step with
    the `show` it is done on. The element reads the whole workspace itself; this is what the tabs' lines and the page's
    next step need (with the package list's safety bound, as the list asks a case's next step too)."""
    from jav.domains.finance import reconcile_package

    if "pairing" not in shared:
        view = reconcile_package.package_view(case_id, keep_seconds=reconcile_package.LIST_KEEP_SECONDS)
        nxt = view["next"]
        shared["pairing"] = {"scope": view["scope"], "counts": view["counts"], "approval": view["approval"],
                             "next": {**nxt, "element": "pairing", "show": _SHOWN_AT.get(nxt.get("stage"), "decide")}}
    return shared["pairing"]


def _mark() -> Any:
    from jav.domains.finance import reconcile_package

    return reconcile_package._list_mark()


def register() -> None:
    from jav.app import capabilities, case_views

    capabilities.register(CAPABILITY)
    case_views.register(case_views.ElementData("pairing", CAPABILITY.name, _OWNER, _view, mark=_mark))


__all__ = ["CAPABILITY", "Pairing", "register"]
