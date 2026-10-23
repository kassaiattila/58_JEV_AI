"""The email routing's addresses of the local service (181, plan 170 L5; each logic pack its own, 176).

Plain-language summary: the addresses the interface uses to make a routing package over email packages and to decide
its attachments: accept the proposals (one, several, or every clear one), put an attachment into a package a person
chose, leave it unrouted, or take a decision back. `jav.api.create_app` adds them (185: by its logic pack's
`service`, `jav.api.service_modules`).

Layer: UI/CLI (the local service) → `jav.domains.email.email_routing`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI
from pydantic import Field

from jav.domains.email import email_routing
from jav import work_views
from jav.service_shared import DecisionState, In, WpId, human_actor

WpIdField = Annotated[str, Field(pattern=r"^wp-[0-9a-f]{12}$")]  # a work package named in a request's body
ItemId = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]  # an attachment: its content hash


class CreateRouting(In):
    """A routing package over email packages."""
    name: Annotated[str, Field(min_length=1, max_length=200)]
    sources: Annotated[list[WpIdField], Field(min_length=1, max_length=50)]


# the roles' titles in the interface's language, for the names of the packages the routing makes
Titles = dict[Annotated[str, Field(pattern=r"^[a-z_]{1,40}$")], Annotated[str, Field(min_length=1, max_length=100)]]


class RoutingTitles(In):
    titles: Titles | None = None


class RoutingItems(RoutingTitles):
    """The attachments a decision is about and, when a person chooses it, the package they go to; 187: each one's
    `decision_state` as the page read it."""
    items: Annotated[list[ItemId], Field(min_length=1, max_length=500)]
    target: WpIdField | None = None
    expected_states: dict[ItemId, DecisionState] | None = None


class RoutingItem(In):
    item: ItemId
    expected_state: DecisionState | None = None


def routes(app: FastAPI, r: str) -> None:
    """The email routing's addresses under the service's prefix `r`."""

    @app.post(r + "/email-routing/packages", status_code=201)
    def create_routing(body: CreateRouting, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """A routing package over email packages; the new package's view."""
        made = email_routing.create(name=body.name, sources=body.sources, actor=who)
        return work_views.workpackage_view(made["workpackage_id"])

    @app.post(r + "/workpackages/{wp_id}/routing/accept")
    def routing_accept(wp_id: WpId, body: RoutingItems, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """The attachments go to their proposed packages, or to the package a person chose."""
        return work_views.jsonable(email_routing.accept(wp_id, body.items, actor=who, target=body.target, titles=body.titles,
                                                        expected_states=body.expected_states))

    @app.post(r + "/workpackages/{wp_id}/routing/accept-clear")
    def routing_accept_clear(wp_id: WpId, body: RoutingTitles, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """Every proposal without a blocker that is not decided yet."""
        return work_views.jsonable(email_routing.accept_clear(wp_id, actor=who, titles=body.titles))

    @app.post(r + "/workpackages/{wp_id}/routing/reject")
    def routing_reject(wp_id: WpId, body: RoutingItems, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """The attachments are not routed."""
        return work_views.jsonable(email_routing.reject(wp_id, body.items, actor=who, expected_states=body.expected_states))

    @app.post(r + "/workpackages/{wp_id}/routing/undo")
    def routing_undo(wp_id: WpId, body: RoutingItem, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """A decision taken back (an accepted document stays in its package)."""
        return work_views.jsonable(email_routing.undo(wp_id, body.item, actor=who, expected_state=body.expected_state))


__all__ = ["routes"]
