"""The product registry on the local service (231, stage D, D-c6).

Plain-language summary: the products, their condition documents and rules, and the tariffs the premiums are computed
from (`jav/app/product_rules.py`), each kept as versions. These addresses list every one of them with its versions (a
draft with what keeps it from being made active, each problem a sentence in the interface's language) and the fact
catalogues their rules read, make a version active (a product's by another person than its maker) and retire one.
Making a version active that does not hold is refused with every problem (422 `manifest_refused`); one by its own maker,
409 `second_person_needed`.

- `GET /product-registry`: the products, documents, rules, tariffs and catalogues;
- `POST /product-registry/{kind}/{ident}/versions/{n}/activate`, `POST /product-registry/{kind}/{ident}/retire`.
- D-c7f: `GET /rule-proposals` (the runs, of one document version with `?document=`), `GET /rule-proposals/{run}`
  (a run with its proposals), `POST /rule-proposals` (a run queued: the document version, the file the operating
  system's picker chose, the catalogue, the product, the proposer and its budget), `POST /rule-proposals/items/{id}/
  accept|correct|reject` (a person's decision; 422 `proposal_refused` with every problem, 409 on a stale page).

Layer: UI/CLI (the local service) → `jav.app.product_rules`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi import Path as PathParam
from pydantic import Field

from jav.app import product_rules, rule_proposal_runs, work_views
from jav.core import identity, versions
from jav.core.user_messages import message_fields, said_fields
from jav.service.service_shared import DecisionState, Empty, In, checked_path, error, human_actor

Kind = Annotated[str, PathParam(pattern=r"^(document|rule|product|tariff)$")]
Ident = Annotated[str, PathParam(pattern=r"^[A-Za-z0-9_.-]{1,120}$")]
Version = Annotated[int, PathParam(ge=1, le=100000)]
RunId = Annotated[str, PathParam(pattern=r"^rpr-[0-9a-f]{10}$")]
ProposalId = Annotated[int, PathParam(ge=1)]
Usd = Annotated[Decimal, Field(ge=0, le=100)]
Values = Annotated[list[Annotated[str, Field(max_length=60)]], Field(max_length=200)]


class ProposalRun(In):
    document: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,120}@[1-9][0-9]{0,5}$")]
    path: Annotated[str, Field(min_length=1, max_length=2000)]
    catalogue: Annotated[str, Field(pattern=r"^[a-z0-9_]{1,40}$")]
    product: Annotated[str | None, Field(pattern=r"^[A-Za-z0-9_.-]{1,120}$")] = None
    proposer: Annotated[str, Field(pattern=r"^(gpt|stand_in:[a-z0-9_]{1,60})$")]
    limits: dict[Literal["openai", "jev"], Usd] = Field(default_factory=dict)
    verify: bool = False


class ProposalAccept(In):
    expected_state: DecisionState
    confirmed: Values = Field(default_factory=list)
    ident: Annotated[str | None, Field(pattern=r"^[A-Za-z0-9_.-]{1,120}$")] = None


class ProposalCorrect(ProposalAccept):
    rule: dict[str, Any]


class ProposalReject(In):
    expected_state: DecisionState
    reason: Annotated[str, Field(min_length=1, max_length=2000)]


def routes(app: FastAPI, r: str) -> None:
    """The product registry's addresses under the service's prefix `r`, and the answers to its errors."""

    @app.exception_handler(product_rules.ManifestRefused)
    async def manifest_refused(_request: Request, exc: product_rules.ManifestRefused):
        return error(422, "manifest_refused", str(exc), problems=[said_fields(p) for p in exc.problems])

    @app.exception_handler(product_rules.SecondPersonNeeded)
    async def second_person_needed(_request: Request, exc: product_rules.SecondPersonNeeded):
        return error(409, "second_person_needed", str(exc), **message_fields(exc))

    @app.exception_handler(rule_proposal_runs.ProposalRefused)
    async def proposal_refused(_request: Request, exc: rule_proposal_runs.ProposalRefused):
        return error(422, "proposal_refused", str(exc), problems=[said_fields(p) for p in exc.problems])

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

    @app.get(r + "/rule-proposals")
    def rule_proposal_runs_list(document: Annotated[str | None, Query(max_length=130)] = None) -> dict[str, Any]:
        return work_views.jsonable({"runs": rule_proposal_runs.runs(document)})

    @app.get(r + "/rule-proposals/{run_id}")
    def rule_proposal_run(run_id: RunId) -> dict[str, Any]:
        return work_views.jsonable(rule_proposal_runs.run(run_id))

    @app.post(r + "/rule-proposals", status_code=201)
    def start_rule_proposals(body: ProposalRun, who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        path = checked_path(body.path, want_dir=False)
        return work_views.jsonable(rule_proposal_runs.start(body.document, path, catalogue=body.catalogue, actor=who,
                                                            product=body.product, proposer=body.proposer,
                                                            limits=dict(body.limits), verify=body.verify))

    @app.post(r + "/rule-proposals/items/{proposal_id}/accept")
    def accept_rule_proposal(proposal_id: ProposalId, body: ProposalAccept,
                             who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(rule_proposal_runs.accept(proposal_id, actor=who, expected_state=body.expected_state,
                                                             confirmed=body.confirmed, ident=body.ident))

    @app.post(r + "/rule-proposals/items/{proposal_id}/correct")
    def correct_rule_proposal(proposal_id: ProposalId, body: ProposalCorrect,
                              who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(rule_proposal_runs.correct(proposal_id, body.rule, actor=who, expected_state=body.expected_state,
                                                              confirmed=body.confirmed, ident=body.ident))

    @app.post(r + "/rule-proposals/items/{proposal_id}/reject")
    def reject_rule_proposal(proposal_id: ProposalId, body: ProposalReject,
                             who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(rule_proposal_runs.reject(proposal_id, body.reason, actor=who, expected_state=body.expected_state))
