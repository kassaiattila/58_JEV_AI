"""The email domain's capabilities (231, plan stage C, C1c; DECISIONS 231): the routing of emailed documents as a step.

Plain-language summary: a case of the email routing process (`configs/processes/mail_routing.json`) reads the email
packages its scope names (`sources`); every PDF attachment that arrived in them is proposed for the package of its
party, period and role (`jav/domains/email/email_routing.py`, unchanged), and a person accepts, rejects or redirects
each one. The step is done once every attachment it can route is decided; until then it waits for the person. A
routing package made before (until C1c its own kind of package) is taken over as such a case with its decisions: its
step is done if every one is decided, otherwise it waits.

- `file_placement@1` (human): the routing step; its element `file_placement` shows the email packages, the decisions to
  make and what went where (the routing view).

Layer: the email domain's registrations of general capabilities (`jav/app/capabilities.py`).
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, ConfigDict

from jav.app.capabilities import Capability
from jav.core.process import cases, kinds

POLL_S = 5.0  # how soon a waiting routing step looks again at the person's decisions
WAITING_FOR = "routing"


class FilePlacement(BaseModel):
    """Nothing to set: the step routes the attachments of the email packages its case's scope names."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _counts(case_id: str) -> dict[str, int]:
    from jav.domains.email import email_routing

    return email_routing.view(case_id)["counts"]


def _decided(counts: dict[str, int]) -> bool:
    return counts["routable"] > 0 and counts["decided"] == counts["routable"]


def _route(ctx: Any, _params: FilePlacement) -> kinds.StepOutcome:
    counts = _counts(str(ctx.data["container"]))
    if _decided(counts):
        return kinds.Done({"counts": counts})
    return ctx.wait(WAITING_FOR, timer=("check", time.time() + POLL_S))


def _adopt(wp_id: str, _params: dict[str, Any]) -> cases.Adopted:
    """A routing package taken over: done when every attachment it can route is decided, else waiting for them."""
    counts = _counts(wp_id)
    if _decided(counts):
        return cases.Adopted(cases.DONE, result={"counts": counts})
    return cases.Adopted(cases.RUNNING, waiting_for=WAITING_FOR, timer=("check", time.time() + POLL_S))


def _view(case_id: str, _step: str | None, shared: dict[str, Any]) -> dict[str, Any]:
    """The routing view, read once per page view."""
    from jav.domains.email import email_routing

    if "routing" not in shared:
        shared["routing"] = email_routing.view(case_id)
    return shared["routing"]


def _mark() -> Any:
    from jav.domains.email import email_routing

    return email_routing._list_mark()


_OWNER = __name__
CAPABILITY = Capability(
    name="file_placement", version=1, module=_OWNER, run=_route, kind="human", params=FilePlacement, effects="store",
    summary="Proposes the package each emailed document belongs to; a person accepts, rejects or redirects each one.",
    adopt=_adopt, state="case")  # D0-b: the routing decides the case's email packages


def register() -> None:
    from jav.app import capabilities, case_views

    capabilities.register(CAPABILITY)
    case_views.register(case_views.ElementData("file_placement", CAPABILITY.name, _OWNER, _view, mark=_mark))


__all__ = ["CAPABILITY", "FilePlacement", "register"]
