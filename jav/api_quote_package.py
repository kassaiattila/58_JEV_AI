"""The quote package's addresses (191, plan F-quote-package B3, DECISIONS 191).

- `GET /quote-requests?q=`: the requests a quote can start from (an email or a document already processed and read as
  a quote request, in any package), newest first, each with the quotes already made from it;
- `POST /quote-packages`: a quote package from one of them (422 when the item is no quote request).

The package's own part of its page comes with the work package's view (`LogicPack.page`).

Layer: UI/CLI gateway → `jav.quote_package` (application operation of the quotes domain).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI
from fastapi import Query as QueryParam
from pydantic import Field

from jav import quote_package, work_views
from jav.api import _In, human_actor


class QuotePackageIn(_In):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    source: Annotated[str, Field(pattern=r"^wp-[0-9a-f]{12}$")]
    item_id: Annotated[str, Field(min_length=1, max_length=128)]


def routes(app: FastAPI, r: str) -> None:
    """The quote package's addresses under the service's prefix `r`."""

    @app.get(r + "/quote-requests")
    def quote_requests(q: Annotated[str | None, QueryParam(max_length=200)] = None) -> dict[str, Any]:
        return work_views.jsonable({"requests": quote_package.candidates(q)})

    @app.post(r + "/quote-packages", status_code=201)
    def create_quote_package(body: QuotePackageIn, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(quote_package.create(name=body.name, source=body.source, item_id=body.item_id, actor=who))


__all__ = ["routes"]
