"""The own parties' addresses of the local service (185, plan G-full-move T1a; 133: until then in `jav/api.py`).

Plain-language summary: the addresses the settings page uses for the own parties: the overview with the proposals
from the data, accepting proposals, a new party, giving an identity (a tax number, a buyer name, an account) to a party
or taking it back, renaming, merging and deleting a party, an account or card registered with its details (138), and
a party's data month by month. Every change answers with the whole overview, as the settings page shows it. They moved
here from `jav/api.py` as they were: the same paths, request models and answers. The finance domain names this module
(`jav/domains/finance.py` `SERVICE`), and `jav.api.create_app` adds it.

Layer: UI/CLI (the local service) → `jav.parties`, `jav.party_views`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Query
from pydantic import Field

from jav import parties, party_views, work_views
from jav.service_shared import Empty, In, IsoDay, PartyId, human_actor
from jav.user_messages import explained

PartyName = Annotated[str, Field(min_length=1, max_length=200)]


# 133 (F-own-parties): the own parties (`jav/parties.py`, `jav/party_views.py`)
class PartyIdentity(In):
    kind: Literal["tax", "name", "account"]
    key: Annotated[str, Field(min_length=1, max_length=300)]
    label: Annotated[str, Field(min_length=1, max_length=300)]


class AcceptPartySuggestions(In):
    ids: Annotated[list[Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")]], Field(min_length=1, max_length=200)]
    names: dict[str, PartyName] = Field(default_factory=dict)  # by suggestion id: the name a person gave it


class CreateParty(In):
    name: PartyName
    identities: Annotated[list[PartyIdentity], Field(max_length=500)] = Field(default_factory=list)


class RenameParty(In):
    name: PartyName


class MergeParty(In):
    into: PartyId


class SetPartyIdentity(PartyIdentity):
    action: Literal["assign", "dismiss", "release"]  # give it to a party | no own party's | unassigned again
    party_id: PartyId | None = None  # required for "assign"


# 138 (DECISIONS 137): an own account or card registered with its details (`jav/parties.py` `own_accounts`)
class AccountDetails(In):
    kind: Literal["account", "card"]
    currencies: Annotated[list[Annotated[str, Field(pattern=r"^[A-Za-z]{3}$")]], Field(min_length=1, max_length=10)]
    bank: Annotated[str, Field(max_length=100)] | None = None
    valid_from: IsoDay | None = None  # the day it was opened; None: since its first statement
    valid_to: IsoDay | None = None  # the day it was closed; None: still open


class RegisterPartyAccount(AccountDetails):
    number: Annotated[str, Field(min_length=1, max_length=80)]  # an IBAN or a domestic account number, as printed


class SetPartyAccount(AccountDetails):
    key: Annotated[str, Field(min_length=1, max_length=80)]  # the account's key (an identity of kind "account")


Month = Annotated[str, Query(pattern=r"^\d{4}-\d{2}$")]


def routes(app: FastAPI, r: str) -> None:
    """The own parties' addresses under the service's prefix `r`."""

    @app.get(r + "/parties")
    def own_parties() -> dict[str, Any]:
        return work_views.jsonable(party_views.overview())

    @app.post(r + "/parties/accept")
    def accept_party_suggestions(body: AcceptPartySuggestions, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        party_views.accept(body.ids, names=body.names, actor=who)
        return work_views.jsonable(party_views.overview())

    @app.post(r + "/parties", status_code=201)
    def create_party(body: CreateParty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        parties.create(body.name, identities=[(i.kind, i.key, i.label) for i in body.identities], actor=who)
        return work_views.jsonable(party_views.overview())

    @app.post(r + "/parties/identities")
    def set_party_identity(body: SetPartyIdentity, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        if body.action == "release":
            parties.release(body.kind, body.key, actor=who)
        elif body.action == "dismiss":
            parties.assign(body.kind, body.key, body.label, None, actor=who)
        elif body.party_id is None:
            raise explained(ValueError, "assigning an identity needs a party")
        else:
            parties.assign(body.kind, body.key, body.label, body.party_id, actor=who)
        return work_views.jsonable(party_views.overview())

    @app.post(r + "/parties/{party_id}/rename")
    def rename_party(party_id: PartyId, body: RenameParty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        parties.rename(party_id, body.name, actor=who)
        return work_views.jsonable(party_views.overview())

    @app.post(r + "/parties/{party_id}/merge")
    def merge_party(party_id: PartyId, body: MergeParty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        parties.merge(party_id, body.into, actor=who)
        return work_views.jsonable(party_views.overview())

    @app.post(r + "/parties/{party_id}/delete")
    def delete_party(party_id: PartyId, body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        parties.delete(party_id, actor=who)
        return work_views.jsonable(party_views.overview())

    # 138: accounts and cards registered with their details, and a party's data month by month

    @app.post(r + "/parties/{party_id}/accounts")
    def register_party_account(party_id: PartyId, body: RegisterPartyAccount,
                               who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(party_views.register_account(
            party_id, body.number, kind=body.kind, currencies=body.currencies, bank=body.bank, valid_from=body.valid_from,
            valid_to=body.valid_to, actor=who))

    @app.post(r + "/parties/accounts/details")
    def set_party_account(body: SetPartyAccount, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        parties.set_account(body.key, kind=body.kind, currencies=body.currencies, bank=body.bank, valid_from=body.valid_from,
                            valid_to=body.valid_to, actor=who)
        return work_views.jsonable(party_views.overview())

    @app.get(r + "/parties/{party_id}/months")
    def party_months(party_id: PartyId, start: Month | None = None, end: Month | None = None) -> dict[str, Any]:
        return work_views.jsonable(party_views.months(party_id, start, end))


__all__ = ["routes"]
