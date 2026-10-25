"""The process packs and their own settings on the local service (231, plan stage B, B2; DECISIONS 231).

Plain-language summary: the processes the system runs (each a process pack, `configs/processes/`), and each one's own
values over its file's resources (which price list, how its letters are sent, which letter frame and output
template; `jav/app/process_settings.py`). These addresses list the processes, show one's resources with their versions
and the rule of who may make a value active, save a value as a draft, make a version active and set the process's own
value aside (the file's counts again). A person the rule does not let make a value active is refused (403). 231
(B3): the same for a rule key its capabilities let a process set (`/rules/...`; the value a whole number or one of
the key's options), and its preview on the decision trace (nothing is written).

Layer: UI/CLI (the local service) → `jav.app.process_settings`, `jav.app.process_packs`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi import Path as PathParam
from pydantic import Field

from jav.app import process_packs, process_settings, work_views
from jav.core import identity
from jav.core.user_messages import message_fields
from jav.service.service_shared import Empty, In, error, human_actor

PackId = Annotated[str, PathParam(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
SettingKey = Annotated[str, PathParam(pattern=r"^[a-z][a-z0-9_:]{0,79}$")]
RuleKey = Annotated[str, PathParam(pattern=r"^[a-z][A-Za-z0-9_:.]{0,119}$")]  # 231 (B3): <rule file>.<dotted key>
Version = Annotated[int, PathParam(ge=1)]


class SettingIn(In):
    value: Annotated[str, Field(min_length=1, max_length=200)]
    note: Annotated[str | None, Field(max_length=2000)] = None


class RuleIn(In):
    value: int | Annotated[str, Field(min_length=1, max_length=200)]
    note: Annotated[str | None, Field(max_length=2000)] = None


def routes(app: FastAPI, r: str) -> None:
    """The process packs' addresses under the service's prefix `r`."""

    @app.exception_handler(process_settings.SettingRefused)
    async def setting_refused(_request: Request, exc: process_settings.SettingRefused):
        return error(403, "setting_refused", str(exc), **message_fields(exc))

    @app.exception_handler(process_packs.UnknownPack)
    async def unknown_pack(_request: Request, exc: process_packs.UnknownPack):
        return error(404, "not_found", str(exc))

    @app.get(r + "/processes")
    def process_list() -> dict[str, Any]:
        return {"processes": [{"id": p.id, "title": p.title, "version": p.version} for p in process_packs.packs()]}

    @app.get(r + "/processes/{pack_id}/settings")
    def process_settings_page(pack_id: PackId) -> dict[str, Any]:
        return work_views.jsonable(process_settings.view(pack_id))

    @app.post(r + "/processes/{pack_id}/settings/{key}", status_code=201)
    def process_setting_propose(pack_id: PackId, key: SettingKey, body: SettingIn,
                                who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(process_settings.propose(pack_id, key, body.value, who, note=body.note))

    @app.post(r + "/processes/{pack_id}/settings/{key}/versions/{version}/activate")
    def process_setting_activate(pack_id: PackId, key: SettingKey, version: Version, _body: Empty,
                                 who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(process_settings.activate(pack_id, key, version, who))

    @app.post(r + "/processes/{pack_id}/settings/{key}/retire")
    def process_setting_retire(pack_id: PackId, key: SettingKey, _body: Empty,
                               who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(process_settings.retire(pack_id, key, who))

    @app.post(r + "/processes/{pack_id}/rules/{key}", status_code=201)
    def process_rule_propose(pack_id: PackId, key: RuleKey, body: RuleIn,
                             who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(process_settings.propose(pack_id, key, body.value, who, kind=process_settings.RULE,
                                                            note=body.note))

    @app.post(r + "/processes/{pack_id}/rules/{key}/versions/{version}/activate")
    def process_rule_activate(pack_id: PackId, key: RuleKey, version: Version, _body: Empty,
                              who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(process_settings.activate(pack_id, key, version, who, kind=process_settings.RULE))

    @app.post(r + "/processes/{pack_id}/rules/{key}/retire")
    def process_rule_retire(pack_id: PackId, key: RuleKey, _body: Empty,
                            who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(process_settings.retire(pack_id, key, who, kind=process_settings.RULE))

    @app.post(r + "/processes/{pack_id}/rules/{key}/preview")
    def process_rule_preview(pack_id: PackId, key: RuleKey, body: RuleIn) -> dict[str, Any]:
        """What the value would have changed in the process's traced decisions (nothing is written)."""
        return work_views.jsonable(process_settings.preview(pack_id, key, body.value))
