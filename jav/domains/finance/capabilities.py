"""The finance domain's capabilities (231, plan stage C, C2b; DECISIONS 231): the pairing of two lists as a step.

Plain-language summary: a pairing step proposes, by code and without any AI call, which item of one list settles which
item of the other under the rules it names, and a person decides: confirms or rejects a pair, splits an amount over
several, or marks an item that needs no pair. The step is done when the person approves the result as the case's own
version (the approved reconciliation statement); until then it waits. The only rules so far are the invoices against
the bank and card statement lines (`invoice_statement`: the reconciliation engine, `jav/domains/finance/reconcile.py`,
and its package's decisions, `reconcile_package.py`). A reconciliation package made before is taken over as such a case
with its decisions: its step is done when a version of its statement is approved, otherwise it waits.

- `pairing@1` (human): the pairing step. The reconciliation's process pack names it (C2d), with the pairing element.
- `pairing_proposal@1` (machine, paid; C2c): the AI proposal a person starts (`pairing_proposal.py`): JEV's answers for
  the lines still to decide, under the run's cap; its element `pairing_proposal` shows the button with the cap.

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
PROPOSING = "proposal"  # 231 (C2c): what the AI proposal step waits for while its run is queued or running


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


def _reopen(wp_id: str, note: str, actor: Any) -> Any:
    """C3a-1: the approved statement reopened with a reason, as a person's reopening does (a workflow's chain, 218)."""
    from jav.domains.finance import reconcile_statement  # lazy: it builds on the reconciliation package

    return reconcile_statement.reopen(wp_id, note=note, actor=actor)


_OWNER = __name__
CAPABILITY = Capability(
    name="pairing", version=1, module=_OWNER, run=_pair, kind="human", params=Pairing, effects="store",
    rule_files=("reconcile", "finance"), adopt=_adopt, own_version=True,  # C2d: reopening the statement reopens it
    reopen=_reopen, approval_what="Reconciliation statement",  # C3a-1: its case waits for the approval as a task
    summary=("Proposes by code which item of one list settles which item of the other; a person confirms, rejects, splits"
             " or marks, and approves the result."))


class PairingProposal(BaseModel):
    """231 (C2c): `rules`: what is paired (as the pairing step's); `engine`: the AI asked (JEV only: the owner's decision
    of 2026-10-25; the GPT path is a separate decision and a new version)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rules: Literal["invoice_statement"]
    engine: Literal["jev"] = "jev"


def _propose(ctx: Any, _params: PairingProposal) -> kinds.StepOutcome:
    """231 (C2c): the AI proposal's run of this round, queued once; done with its counts, failed with its reason (once:
    the step started again asks a new round)."""
    from jav.domains.finance import pairing_proposal

    case_id, step_id = str(ctx.data["container"]), ctx.step.id
    run = pairing_proposal.latest(case_id, step_id)
    if run is None or (run["state"] == "failed" and run["reported"]):
        pairing_proposal.request(case_id, step_id, (run["round"] + 1) if run else 1, actor=ctx.actor)
        return ctx.wait(PROPOSING, timer=("check", time.time() + POLL_S))
    if run["state"] in ("queued", "running"):
        return ctx.wait(PROPOSING, timer=("check", time.time() + POLL_S))
    if run["state"] == "failed":
        pairing_proposal.mark_reported(case_id, step_id, run["round"])
        return kinds.Fail(run["error"] or "the AI proposal failed")
    return kinds.Done({"round": run["round"], "lines": run["lines"], "counts": run["counts"]})


def _proposal_view(case_id: str, step: str | None, _shared: dict[str, Any]) -> dict[str, Any]:
    """The AI proposal element's data: the step's latest run and the cap a run reserves."""
    from jav.domains.finance import pairing_proposal

    engines, limits = pairing_proposal.cap()
    return {"run": pairing_proposal.latest(case_id, step) if step else None, "engines": engines,
            "cap_usd": {k: str(v) for k, v in limits.items()}}


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


PROPOSAL = Capability(
    name="pairing_proposal", version=1, module=_OWNER, run=_propose, kind="machine", params=PairingProposal,
    effects="store", providers=("jev",), rule_files=("callsite:reconcile_line", "finance", "reconcile"),
    summary=("Asks the AI which item of the other list each undecided item settles and what kind it is, under a cap;"
             " a person still decides."))


def register() -> None:
    from jav.app import capabilities, case_views

    capabilities.register(CAPABILITY)
    capabilities.register(PROPOSAL)  # 231 (C2c)
    case_views.register(case_views.ElementData("pairing", CAPABILITY.name, _OWNER, _view, mark=_mark))
    case_views.register(case_views.ElementData("pairing_proposal", PROPOSAL.name, _OWNER, _proposal_view))


__all__ = ["CAPABILITY", "PROPOSAL", "Pairing", "PairingProposal", "register"]
