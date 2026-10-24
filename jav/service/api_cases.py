"""The process packs' cases on the local service (231, plan stage A, A6; DECISIONS 231).

Plain-language summary: a case is one running instance of a process pack. These addresses start a case from the record
it belongs to (an email or a document read as the pack's record, e.g. a quote request), give its page as data (its
tabs and elements from the pack, each element with what its step's capability shows, `jav/app/case_views.py`), and let
a person start a step that waits for its start (a paid one). The service never runs a step itself: the worker moves the
case on.

Layer: UI/CLI (the local service) → `jav.app.process_runtime`, `jav.app.case_views`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI
from fastapi import Path as PathParam
from pydantic import Field

from jav.app import case_views, process_runtime, work_views
from jav.core import identity
from jav.service.service_shared import Empty, In, human_actor

CaseId = Annotated[str, PathParam(pattern=r"^wp-[0-9a-f]{12}$")]  # a case's id is its container's
CaseStep = Annotated[str, PathParam(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class Record(In):
    workpackage_id: Annotated[str, Field(pattern=r"^wp-[0-9a-f]{12}$")]
    item_id: Annotated[str, Field(min_length=1, max_length=200)]


class CaseIn(In):
    pack: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    record: Record
    name: Annotated[str, Field(min_length=1, max_length=200)]


def routes(app: FastAPI, r: str) -> None:
    """The cases' addresses under the service's prefix `r`."""

    @app.post(r + "/cases", status_code=201)
    def start_case(body: CaseIn, who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        case_id = process_runtime.start_case(body.pack, {"record": body.record.model_dump()}, name=body.name, actor=who)
        return {"case_id": case_id}

    @app.get(r + "/cases/{case_id}")
    def case_page(case_id: CaseId) -> dict[str, Any]:
        return work_views.jsonable(case_views.view(case_id))

    @app.post(r + "/cases/{case_id}/steps/{step_id}/start")
    def start_case_step(case_id: CaseId, step_id: CaseStep, _body: Empty,
                        who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(case_views.start_step(case_id, step_id, who))
