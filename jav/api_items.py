"""One item's addresses of the local service (195, plan G-tidy R4; until then in `jav/api.py` `create_app`).

Plain-language summary: the addresses the review page uses for one document of a run: its result, the document formats
the native reader knows, the native reader's source elements and the resolving of its citations, the word layer for
selecting on the page image, and saving a person's correction. They moved here from `jav/api.py` as they were: the
same paths, request models and answers, in the same order. `jav.api.create_app` adds this module after the results'
one.

Layer: UI/CLI (the local service) → `jav.app.corrections`, `jav.documents.native_results`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Query
from pydantic import Field

from jav.app import corrections, work_views
from jav.service_shared import In, ItemId, RunId, Text, human_actor


_Cell = Annotated[str, Field(max_length=500)] | int | None
_Row = Annotated[dict[Annotated[str, Field(max_length=64)], _Cell], Field(max_length=50)]


class SaveCorrection(In):
    # 048: an itemised list = a list of rows (item field -> value) or a list of plain values; the kind-based check is in
    # `jav.app.corrections` (that is where the rows' content is compared with the pack's item description)
    fields: dict[Annotated[str, Field(max_length=64)], _Cell | Annotated[list[_Row | _Cell], Field(max_length=2000)]] = Field(max_length=100)
    expected_revision: Annotated[int, Field(ge=0)]
    note: Text | None = None
    # 045: per field, the ids of the words selected on the image (from the item's word layer)
    sources: dict[Annotated[str, Field(max_length=64)], Annotated[list[Annotated[int, Field(ge=0)]], Field(min_length=1, max_length=200)]] | None = Field(
        default=None, max_length=100)
    # 083: the simple fields a person checked (the tick next to the field): recorded as confirmed, their to-dos resolved
    confirm: list[Annotated[str, Field(max_length=64)]] | None = Field(default=None, max_length=100)


class NativeCitationRequest(In):
    occurrence_id: str = Field(min_length=1, max_length=256)
    element_id: str = Field(min_length=1, max_length=256)
    quote: str = Field(min_length=1, max_length=10000)


class SaveNativeCorrection(In):
    kind: Literal["native"]
    values: dict[Annotated[str, Field(max_length=256)], Annotated[str, Field(max_length=100000)] | None] = Field(max_length=200)
    native_sources: dict[Annotated[str, Field(max_length=256)], Annotated[list[NativeCitationRequest], Field(max_length=20)]] = Field(default_factory=dict, max_length=200)
    expected_revision: Annotated[int, Field(ge=0)]
    expected_result_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirm: list[Annotated[str, Field(max_length=256)]] = Field(default_factory=list, max_length=200)
    note: Text | None = None


class ResolveNativeCitations(In):
    expected_result_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    citations: list[NativeCitationRequest] = Field(max_length=20)


def routes(app: FastAPI, r: str) -> None:
    """One item's addresses under the service's prefix `r`."""

    @app.get(r + "/runs/{run_id}/items/{item_id}")
    def item(run_id: RunId, item_id: ItemId) -> dict[str, Any]:
        return work_views.jsonable(corrections.item_result(run_id, item_id))

    @app.get(r + "/document-formats")
    def document_formats() -> dict[str, Any]:
        from jav.documents.native_contracts import DOCUMENT_FORMATS
        from jav.ai.native_processing import estimate_limits

        limits = estimate_limits({"jev": "off"})
        return {"formats": [item.model_dump(mode="json") for item in DOCUMENT_FORMATS],
                "native_limits": limits.model_dump(mode="json", exclude={"provider_limits_usd"})}

    @app.get(r + "/runs/{run_id}/items/{item_id}/sources")
    def native_sources(run_id: RunId, item_id: ItemId, offset: Annotated[int, Query(ge=0)] = 0,
                       limit: Annotated[int, Query(ge=1, le=500)] = 100,
                       occurrence_id: Annotated[str | None, Query(max_length=256)] = None,
                       expected_result_version: Annotated[str | None, Query(pattern=r"^[0-9a-f]{64}$")] = None) -> dict[str, Any]:
        from jav.documents import native_results

        publication = corrections.native_publication(run_id, item_id, expected_result_version=expected_result_version)
        return native_results.source_elements(publication, offset=offset, limit=limit,
                                              occurrence_id=occurrence_id).model_dump(mode="json")

    @app.post(r + "/runs/{run_id}/items/{item_id}/citations/resolve")
    def resolve_native_citations(run_id: RunId, item_id: ItemId, body: ResolveNativeCitations) -> dict[str, Any]:
        from jav.documents import native_results

        publication = corrections.native_publication(run_id, item_id, expected_result_version=body.expected_result_version)
        return {"result_version": publication.result_version,
                "citations": [cite.model_dump(mode="json") for cite in native_results.resolve_citations(
                    publication, [citation.model_dump() for citation in body.citations])]}

    @app.get(r + "/runs/{run_id}/items/{item_id}/words")
    def item_words(run_id: RunId, item_id: ItemId) -> dict[str, Any]:
        """The item's word layer (045): pages and words with 0–1 boxes — for selecting on the image."""
        corrections.item_result(run_id, item_id)  # unknown run/item → 404
        layer = corrections.layer_for(corrections.datapoints_row(run_id, item_id))
        if layer is None:
            raise KeyError(f"no source layer for {item_id[:12]}")
        return work_views.jsonable({"layer_id": layer.layer_id, "text_source": layer.text_source,
                                    "pages": [p.model_dump() for p in layer.pages],
                                    "words": [w.model_dump() for w in layer.words]})

    @app.post(r + "/runs/{run_id}/items/{item_id}/correction")
    def save_correction(run_id: RunId, item_id: ItemId, body: SaveCorrection | SaveNativeCorrection,
                        who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        corrections.item_result(run_id, item_id)  # unknown item → 404
        if isinstance(body, SaveNativeCorrection):
            citations = {key: [cite.model_dump() for cite in refs] for key, refs in body.native_sources.items()}
            corrections.save_native(run_id, item_id, values=body.values, native_sources=citations,
                                     expected_revision=body.expected_revision, expected_result_version=body.expected_result_version,
                                     actor=who, note=body.note, confirm=body.confirm)
        else:
            corrections.save(run_id, item_id, fields=dict(body.fields), expected_revision=body.expected_revision,
                             actor=who, note=body.note, sources=dict(body.sources) if body.sources else None, confirm=body.confirm)
        return work_views.jsonable(corrections.item_result(run_id, item_id))
