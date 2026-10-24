"""The quote package's addresses (191, plan F-quote-package B3, DECISIONS 191).

- `GET /quote-requests?q=`: the requests a quote can start from (an email or a document already processed and read as
  a quote request, in any package), newest first, each with the quotes already made from it;
- `POST /quote-packages`: a quote package from one of them (422 when the item is no quote request);
- `POST /workpackages/{id}/quote/proposal`: queues the quote's proposal for the worker (B4c; 422 when it cannot be
  asked: no readable request, no item, no active price list);
- (192, B5) `POST /workpackages/{id}/quote/draft/start`: the quote's draft from the proposal or the requested items;
  `PUT /workpackages/{id}/quote/draft`: the draft after a change (409 from a stale page, 422 for a number that cannot
  be read or an item the price list does not have); `POST .../quote/approve` (409 when it changed or is not ready),
  `POST .../quote/reopen` (422 without a reason), each returning the draft's view; `GET .../quote/versions/{n}`: an
  approved version as it was approved (404 without one). `jav.domains.quotes.quote_draft` answers a package that is not a quote's
  with 404 itself.
- (196) `GET .../quote/versions/{n}/quote.docx`: an approved version's Word document as it was stored;
  `GET .../quote/draft/quote.docx`: the draft's, marked as a draft (422 while a line is not priced);
  `GET .../quote/letter`: the reply letter of the approved version (`jav.domains.quotes.quote_letter`); `POST .../quote/letter/paragraph`:
  queues GPT's paragraph for the worker (422 without an approved version); `PUT .../quote/letter`: the body a person
  accepts (409 from a stale page); `GET .../quote/versions/{n}/letter.eml`: the letter file (422 before it is accepted).

The package's own part of its page comes with the work package's view (`LogicPack.page`).

Layer: UI/CLI gateway → `jav.domains.quotes.quote_package`, `jav.domains.quotes.quote_proposal`, `jav.domains.quotes.quote_draft` (application operations of the
quotes domain).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI
from fastapi import Path as PathParam
from fastapi import Query as QueryParam
from fastapi.responses import Response
from pydantic import Field

from jav.core import identity
from jav.app import package_release, work, work_views
from jav.domains.quotes import quote_draft, quote_letter, quote_package, quote_proposal
from jav.service.service_shared import Empty, In, WpId, attachment_header, human_actor


class QuoteDraftStartIn(In):
    source: Literal["proposal", "request"]
    expected_state: Annotated[int, Field(ge=0)]
    replace: bool = False


class QuoteDraftIn(In):
    draft: quote_draft.DraftIn
    expected_state: Annotated[int, Field(ge=0)]


class QuoteApproveIn(In):
    fingerprint: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class QuoteReopenIn(In):
    note: Annotated[str, Field(max_length=2000)]


class QuoteLetterIn(In):
    body: Annotated[str, Field(max_length=20000)]
    expected_state: Annotated[int, Field(ge=0)]


def _quote(wp_id: str) -> None:
    # a package that holds no quote: 404; 231 (A6, A3d): a case's container holds it
    if work.get(wp_id)["source_kind"] != quote_package.CONTAINER:
        raise KeyError(wp_id)


def routes(app: FastAPI, r: str) -> None:
    """The quote package's addresses under the service's prefix `r`."""

    @app.get(r + "/quote-requests")
    def quote_requests(q: Annotated[str | None, QueryParam(max_length=200)] = None) -> dict[str, Any]:
        return work_views.jsonable({"requests": quote_package.candidates(q)})

    # 231 (A6c): a quote starts as a case of the IT quote's process pack (`POST /api/cases`), no longer as a package

    @app.post(r + "/workpackages/{wp_id}/quote/proposal", status_code=202)
    def request_quote_proposal(wp_id: WpId, _body: Empty, who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        _quote(wp_id)
        return work_views.jsonable(quote_proposal.request(wp_id, actor=who))

    @app.post(r + "/workpackages/{wp_id}/quote/draft/start")
    def start_quote_draft(wp_id: WpId, body: QuoteDraftStartIn, who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(quote_draft.start(wp_id, source=body.source, actor=who,
                                                     expected_state=body.expected_state, replace=body.replace))

    @app.put(r + "/workpackages/{wp_id}/quote/draft")
    def save_quote_draft(wp_id: WpId, body: QuoteDraftIn, who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(quote_draft.save(wp_id, body.draft, actor=who, expected_state=body.expected_state))

    @app.post(r + "/workpackages/{wp_id}/quote/approve")
    def approve_quote(wp_id: WpId, body: QuoteApproveIn, who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        quote_draft.approve(wp_id, fingerprint=body.fingerprint, actor=who)
        return work_views.jsonable(quote_draft.view(wp_id))

    @app.post(r + "/workpackages/{wp_id}/quote/reopen")
    def reopen_quote(wp_id: WpId, body: QuoteReopenIn, who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(quote_draft.reopen(wp_id, note=body.note, actor=who))

    @app.get(r + "/workpackages/{wp_id}/quote/versions/{version}")
    def quote_version(wp_id: WpId, version: Annotated[int, PathParam(ge=1, le=100000)]) -> dict[str, Any]:
        return work_views.jsonable(quote_draft.approved_version(wp_id, version))

    @app.get(r + "/workpackages/{wp_id}/quote/versions/{version}/quote.docx")
    def quote_version_docx(wp_id: WpId, version: Annotated[int, PathParam(ge=1, le=100000)]) -> Response:
        content, name = quote_draft.version_docx(wp_id, version)
        return Response(content, media_type=package_release.DOCX, headers={"Content-Disposition": attachment_header(name)})

    @app.get(r + "/workpackages/{wp_id}/quote/draft/quote.docx")
    def quote_draft_docx(wp_id: WpId) -> Response:
        content, name = quote_draft.draft_docx(wp_id)
        return Response(content, media_type=package_release.DOCX, headers={"Content-Disposition": attachment_header(name)})

    @app.get(r + "/workpackages/{wp_id}/quote/letter")
    def quote_letter_view(wp_id: WpId) -> dict[str, Any]:
        _quote(wp_id)
        return work_views.jsonable(quote_letter.view(wp_id))

    @app.post(r + "/workpackages/{wp_id}/quote/letter/paragraph", status_code=202)
    def request_quote_letter(wp_id: WpId, _body: Empty, who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        _quote(wp_id)
        return work_views.jsonable(quote_letter.request(wp_id, actor=who))

    @app.put(r + "/workpackages/{wp_id}/quote/letter")
    def accept_quote_letter(wp_id: WpId, body: QuoteLetterIn, who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        _quote(wp_id)
        return work_views.jsonable(quote_letter.accept(wp_id, body.body, actor=who, expected_state=body.expected_state))

    @app.get(r + "/workpackages/{wp_id}/quote/versions/{version}/letter.eml")
    def quote_letter_eml(wp_id: WpId, version: Annotated[int, PathParam(ge=1, le=100000)]) -> Response:
        _quote(wp_id)
        content, name = quote_letter.eml(wp_id, version)
        return Response(content, media_type="message/rfc822", headers={"Content-Disposition": attachment_header(name)})


__all__ = ["routes"]
