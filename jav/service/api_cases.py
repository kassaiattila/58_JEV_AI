"""The process packs' cases on the local service (231, plan stage A, A6; DECISIONS 231).

Plain-language summary: a case is one running instance of a process pack. These addresses start a case from the record
it belongs to (an email or a document read as the pack's record, e.g. a quote request), give its page as data (its
tabs and elements from the pack, each element with what its step's capability shows, `jav/app/case_views.py`), let
a person start a step that waits for its start (a paid one), and (A7d) take an action a step's capability offers (say
whether a message arrived, record a reply). The service never runs a step itself: the worker moves the case on.

Layer: UI/CLI (the local service) → `jav.app.process_runtime`, `jav.app.case_views`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI
from fastapi import Path as PathParam
from pydantic import Field

from jav.app import case_views, process_runtime, work_views
from jav.core import identity
from jav.service.service_shared import Empty, In, IsoDay, PartyId, checked_path, human_actor

CaseId = Annotated[str, PathParam(pattern=r"^wp-[0-9a-f]{12}$")]  # a case's id is its container's
CaseStep = Annotated[str, PathParam(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
ActionName = Annotated[str, PathParam(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class Record(In):
    workpackage_id: Annotated[str, Field(pattern=r"^wp-[0-9a-f]{12}$")]
    item_id: Annotated[str, Field(min_length=1, max_length=200)]


class PartnerLinkIn(In):
    role: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
    partner_id: Annotated[str, Field(pattern=r"^partner-[0-9a-f]{12}$")]


class ActionIn(In):
    note: Annotated[str | None, Field(max_length=2000)] = None
    values: dict[str, Any] | None = None  # D-f2: an action with a form takes its values (the form checks them)


class ReturnIn(In):
    """D0-d: why a person returns a step's result instead of approving it."""

    reason: Annotated[str, Field(min_length=1, max_length=2000)]


class Source(In):
    """231 (C3b3): the documents of a document processing case: a folder (with its subfolders when asked) or files; (C3d)
    or a mailbox download (its request, checked by the email domain's source kind)."""

    kind: Literal["folder", "files", "mailbox"]
    folder: Annotated[str, Field(min_length=1, max_length=1000)] | None = None
    recursive: bool = False
    files: Annotated[list[Annotated[str, Field(min_length=1, max_length=1000)]], Field(min_length=1, max_length=10000)] | None = None
    request: dict[str, Any] | None = None


class CaseIn(In):
    """The pack, the case's name and its scope: the record it starts from, or (231 C1c) the work packages it reads, or
    (C2d) the own party and the period it is about."""

    pack: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    record: Record | None = None
    sources: Annotated[list[Annotated[str, Field(pattern=r"^wp-[0-9a-f]{12}$")]], Field(min_length=1, max_length=100)] | None = None
    party_id: PartyId | None = None
    period_start: IsoDay | None = None
    period_end: IsoDay | None = None
    source: Source | None = None
    name: Annotated[str, Field(min_length=1, max_length=200)]


def _source(source: Source) -> dict[str, Any]:
    """The source's paths checked as the service checks every path a person gives (the allowed roots)."""
    if source.kind == "folder":
        return {"kind": "folder", "folder": str(checked_path(source.folder or "", want_dir=True)), "recursive": source.recursive}
    if source.kind == "files":
        return {"kind": "files", "files": [str(checked_path(f, want_dir=False)) for f in source.files or []]}
    return {"kind": source.kind, "request": source.request or {}}  # C3d: a domain's (no path); the scope's part checks it


def routes(app: FastAPI, r: str) -> None:
    """The cases' addresses under the service's prefix `r`."""

    @app.post(r + "/cases", status_code=201)
    def start_case(body: CaseIn, who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        scope = {**({"record": body.record.model_dump()} if body.record else {}),
                 **({"sources": body.sources} if body.sources else {}),
                 **({"party": body.party_id} if body.party_id else {}),
                 **({"period": [body.period_start, body.period_end]} if body.period_start or body.period_end else {}),
                 **({"source": _source(body.source)} if body.source else {})}
        case_id = process_runtime.start_case(body.pack, scope, name=body.name, actor=who)
        return {"case_id": case_id}

    @app.get(r + "/cases/{case_id}")
    def case_page(case_id: CaseId) -> dict[str, Any]:
        return work_views.jsonable(case_views.view(case_id))

    @app.post(r + "/cases/{case_id}/steps/{step_id}/start")
    def start_case_step(case_id: CaseId, step_id: CaseStep, _body: Empty,
                        who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(case_views.start_step(case_id, step_id, who))

    @app.post(r + "/cases/{case_id}/steps/{step_id}/actions/{name}")
    def case_step_action(case_id: CaseId, step_id: CaseStep, name: ActionName, body: ActionIn,
                         who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(case_views.act(case_id, step_id, name, who, body.note, body.values))

    @app.get(r + "/cases/{case_id}/steps/{step_id}/approval")
    def case_step_approval(case_id: CaseId, step_id: CaseStep) -> dict[str, Any]:
        """D0-d: the approval's state of the case's approving step."""
        from jav.app import package_release

        return work_views.jsonable(package_release.approval_state(case_id, step=step_id))

    @app.post(r + "/cases/{case_id}/steps/{step_id}/approval/return")
    def case_step_return(case_id: CaseId, step_id: CaseStep, body: ReturnIn,
                         who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        """D0-d: a person returns the step's result with a reason instead of approving it (409 while a version holds)."""
        return work_views.jsonable(case_views.return_step(case_id, step_id, body.reason, who))

    @app.post(r + "/cases/{case_id}/partners")
    def case_partner_link(case_id: CaseId, body: PartnerLinkIn,
                          who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        """231 (B1): a person links a partner to the case in one of its pack's partner roles."""
        return work_views.jsonable(case_views.link_partner(case_id, body.role, body.partner_id, who))
