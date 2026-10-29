"""The partner register on the local service (231, plan stage B, B1; DECISIONS 231).

Plain-language summary: the shared register of the outside parties the processes deal with (`jav/app/partners.py`).
These addresses list the partners and the roles they may play, show one with its versions, record a new one or a new
version of one (a page that shows an older version is refused), retire and restore one, and list the domains'
proposals not yet recorded. A partner with the same tax number or name as another one is refused with that one's
identifier (409), so the interface can lead the person to it.

Layer: UI/CLI (the local service) → `jav.app.partners`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query, Request
from fastapi import Path as PathParam
from pydantic import Field

from jav.app import partners, work_views
from jav.core import identity
from jav.core.user_messages import message_fields
from jav.service.service_shared import Empty, error, human_actor

PartnerId = Annotated[str, PathParam(pattern=r"^partner-[0-9a-f]{12}$")]


class PartnerUpdate(partners.PartnerIn):
    expected_version: Annotated[int, Field(ge=1)]


def routes(app: FastAPI, r: str) -> None:
    """The partner register's addresses under the service's prefix `r`."""

    @app.exception_handler(partners.PartnerConflict)
    async def partner_conflict(_request: Request, exc: partners.PartnerConflict):
        # the existing thing the conflict names (`other_id`, a general field the interface leads the person to)
        return error(409, "partner_conflict", str(exc), other_id=exc.partner_id, **message_fields(exc))

    @app.get(r + "/partners")
    def partner_list(q: Annotated[str | None, Query(max_length=200)] = None,
                     role: Annotated[str | None, Query(max_length=40)] = None, retired: bool = False) -> dict[str, Any]:
        # 231 (U3e): the own parties beside them, with the role "own" (edited in their own register)
        return {"partners": partners.listing(q, role, retired=retired), "roles": partners.roles(),
                "own": partners.own_listing(q, role)}

    @app.get(r + "/partners/suggestions")
    def partner_suggestions() -> dict[str, Any]:
        return {"suggestions": partners.suggestions()}

    @app.get(r + "/partners/{partner_id}")
    def partner_page(partner_id: PartnerId) -> dict[str, Any]:
        return work_views.jsonable(partners.get(partner_id))

    @app.post(r + "/partners", status_code=201)
    def partner_create(body: partners.PartnerIn, who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(partners.create(body, who))

    @app.put(r + "/partners/{partner_id}")
    def partner_update(partner_id: PartnerId, body: PartnerUpdate,
                       who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        values = partners.PartnerIn(**body.model_dump(exclude={"expected_version"}))
        return work_views.jsonable(partners.update(partner_id, values, who, expected_version=body.expected_version))

    @app.post(r + "/partners/{partner_id}/retire")
    def partner_retire(partner_id: PartnerId, _body: Empty,
                       who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(partners.retire(partner_id, who))

    @app.post(r + "/partners/{partner_id}/restore")
    def partner_restore(partner_id: PartnerId, _body: Empty,
                        who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(partners.restore(partner_id, who))
