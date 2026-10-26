"""The product registry on the local service (231, stage D, D-c6).

Plain-language summary: the products, their condition documents and rules, and the tariffs the premiums are computed
from (`jav/app/product_rules.py`), each kept as versions. These addresses list every one of them with its versions (a
draft with what keeps it from being made active, each problem a sentence in the interface's language) and the fact
catalogues their rules read, make a version active (a product's by another person than its maker) and retire one.
Making a version active that does not hold is refused with every problem (422 `manifest_refused`); one by its own maker,
409 `second_person_needed`.

- `GET /product-registry`: the products, documents, rules, tariffs and catalogues;
- `POST /product-registry/{kind}/{ident}/versions/{n}/activate`, `POST /product-registry/{kind}/{ident}/retire`.

Layer: UI/CLI (the local service) → `jav.app.product_rules`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi import Path as PathParam

from jav.app import product_rules, work_views
from jav.core import identity, versions
from jav.core.user_messages import message_fields, said_fields
from jav.service.service_shared import Empty, error, human_actor

Kind = Annotated[str, PathParam(pattern=r"^(document|rule|product|tariff)$")]
Ident = Annotated[str, PathParam(pattern=r"^[A-Za-z0-9_.-]{1,120}$")]
Version = Annotated[int, PathParam(ge=1, le=100000)]


def routes(app: FastAPI, r: str) -> None:
    """The product registry's addresses under the service's prefix `r`, and the answers to its errors."""

    @app.exception_handler(product_rules.ManifestRefused)
    async def manifest_refused(_request: Request, exc: product_rules.ManifestRefused):
        return error(422, "manifest_refused", str(exc), problems=[said_fields(p) for p in exc.problems])

    @app.exception_handler(product_rules.SecondPersonNeeded)
    async def second_person_needed(_request: Request, exc: product_rules.SecondPersonNeeded):
        return error(409, "second_person_needed", str(exc), **message_fields(exc))

    @app.exception_handler(versions.VersionStateError)
    async def version_state(_request: Request, exc: versions.VersionStateError):
        return error(409, "version_state", str(exc), **message_fields(exc))

    @app.get(r + "/product-registry")
    def product_registry() -> dict[str, Any]:
        return work_views.jsonable(product_rules.overview())

    @app.post(r + "/product-registry/{kind}/{ident}/versions/{version}/activate")
    def activate_registry_version(kind: Kind, ident: Ident, version: Version, _body: Empty,
                                  who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(product_rules.activate(kind, ident, version, actor=who))

    @app.post(r + "/product-registry/{kind}/{ident}/retire")
    def retire_registry_thing(kind: Kind, ident: Ident, _body: Empty,
                              who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(product_rules.retire(kind, ident, actor=who))
