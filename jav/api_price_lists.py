"""The price lists' addresses (191, plan F-quote-package B2, DECISIONS 191).

- `GET /price-lists`: every price list with its versions, and the settings page's choices (the currencies offered,
  the default VAT rate, the columns a file needs and the headers they are known by);
- `POST /price-lists`: an upload, read by the service from a file the operating system's picker chose (the request
  carries its path, as an output template's upload does); checked, and stored as a draft version (422
  `price_list_refused` with the check's problems when it has any);
- `GET /price-lists/{id}/versions/{n}`: a version with its items and the categories its rules may name;
- `POST /price-lists/{id}/versions/{n}/settings`: the rules, the currency and the VAT rate, as a new draft version;
- `POST /price-lists/{id}/versions/{n}/activate`, `POST /price-lists/{id}/retire`;
- `GET /price-lists/{id}/versions/{n}/file`: the file a version was read from.

Layer: UI/CLI gateway → `jav.price_lists` (business module of the quotes domain).
"""

from __future__ import annotations

from pathlib import PurePath
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi import Path as PathParam
from fastapi.responses import Response
from pydantic import Field

from jav import price_lists, work_views
from jav.api import Empty, _error, _In, attachment_header, checked_path, human_actor

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PriceListId = Annotated[str, PathParam(pattern=r"^pl-[0-9a-f]{10}$")]
Version = Annotated[int, PathParam(ge=1, le=100000)]
Number = Annotated[str, Field(min_length=1, max_length=20)]


class PriceListUpload(_In):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    path: Annotated[str, Field(min_length=1, max_length=2000)]
    price_list: Annotated[str | None, Field(pattern=r"^pl-[0-9a-f]{10}$")] = None
    currency: Annotated[str | None, Field(min_length=1, max_length=3)] = None
    vat_percent: Number | None = None


class Rule(_In):
    category: Annotated[str, Field(min_length=1, max_length=120)]
    min_quantity: Number
    percent: Number


class PriceListSettings(_In):
    discounts: Annotated[list[Rule], Field(max_length=200)]
    currency: Annotated[str, Field(min_length=1, max_length=3)]
    vat_percent: Number


def _file(content: bytes, name: str) -> Response:
    media = "text/csv; charset=utf-8" if PurePath(name).suffix.lower() == ".csv" else XLSX
    return Response(content, media_type=media, headers={"Content-Disposition": attachment_header(name),
                                                        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


def routes(app: FastAPI, r: str) -> None:
    """The price lists' addresses under the service's prefix `r`, and the answers to their errors."""

    @app.exception_handler(price_lists.PriceListRefused)
    async def price_list_refused(_request: Request, exc: price_lists.PriceListRefused):
        return _error(422, "price_list_refused", str(exc), check=exc.check)

    @app.exception_handler(price_lists.PriceListStateError)
    async def price_list_state(_request: Request, exc: price_lists.PriceListStateError):
        return _error(409, "price_list_state", str(exc))

    @app.get(r + "/price-lists")
    def price_list_listing() -> dict[str, Any]:
        conf = price_lists.config()
        return work_views.jsonable({"price_lists": price_lists.listing(), "currencies": conf["currency"]["offered"],
                                    "currency": conf["currency"]["default"], "vat_percent": conf["vat_percent"],
                                    "columns": conf["columns"]})

    @app.post(r + "/price-lists", status_code=201)
    def upload_price_list(body: PriceListUpload, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        path = checked_path(body.path, want_dir=False)
        if path.stat().st_size > price_lists.config()["max_bytes"]:
            raise price_lists.PriceListRefused({"ok": False, "warnings": [], "sheet": None, "columns": {}, "items": 0,
                                                "categories": [], "problems": [{"code": "too_large", "where": "",
                                                                                "detail": str(path.stat().st_size)}]})
        return work_views.jsonable(price_lists.add(body.name, path.name, path.read_bytes(), actor=who,
                                                   price_list=body.price_list, currency=body.currency,
                                                   vat_percent=body.vat_percent))

    @app.get(r + "/price-lists/{price_list}/versions/{version}")
    def price_list_version(price_list: PriceListId, version: Version) -> dict[str, Any]:
        return work_views.jsonable(price_lists.detail(price_list, version))

    @app.post(r + "/price-lists/{price_list}/versions/{version}/settings", status_code=201)
    def price_list_settings(price_list: PriceListId, version: Version, body: PriceListSettings,
                            who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(price_lists.change_settings(
            price_list, version, discounts=[rule.model_dump() for rule in body.discounts], currency=body.currency,
            vat_percent=body.vat_percent, actor=who))

    @app.post(r + "/price-lists/{price_list}/versions/{version}/activate")
    def activate_price_list(price_list: PriceListId, version: Version, _body: Empty,
                            who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(price_lists.activate(price_list, version, actor=who))

    @app.post(r + "/price-lists/{price_list}/retire")
    def retire_price_list(price_list: PriceListId, _body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(price_lists.retire(price_list, actor=who))

    @app.get(r + "/price-lists/{price_list}/versions/{version}/file")
    def price_list_file(price_list: PriceListId, version: Version) -> Response:
        return _file(*price_lists.content(price_list, version))


__all__ = ["routes"]
