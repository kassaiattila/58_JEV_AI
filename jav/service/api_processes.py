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

from fastapi import Depends, FastAPI, Query, Request
from fastapi import Path as PathParam
from pydantic import Field

from jav.app import document_processing, examples, intake, process_packs, process_settings, scopes, sub_cases, work_views
from jav.core import identity
from jav.core.user_messages import message_fields
from jav.service.service_shared import Empty, In, error, human_actor

PackId = Annotated[str, PathParam(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
SettingKey = Annotated[str, PathParam(pattern=r"^[a-z][a-z0-9_:]{0,79}$")]
RuleKey = Annotated[str, PathParam(pattern=r"^[a-z][A-Za-z0-9_:.]{0,119}$")]  # 231 (B3): <rule file>.<dotted key>
Version = Annotated[int, PathParam(ge=1)]
PacketId = Annotated[str, PathParam(pattern=r"^[a-z][a-z0-9_]{0,63}$")]  # 231 (U0): an example packet


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
        # 231 (C1c): what a case of each needs (its scope parts) and the kinds of package that offer one; (C2d) which of
        # the parts a person gives (the others take their default)
        # 231 (U0): whether a person may start a case by hand, what the process is for, what a case of it cannot start
        # without now, and whether it has example material
        return {"processes": [{"id": p.id, "title": p.title, "version": p.version, "scope": list(p.scope.parts),
                               "asks": scopes.asks(p.scope.parts),
                               "package_kinds": sorted({k for i in p.intake if i.on == "package" for k in i.package_kinds}),
                               "source_kinds": document_processing.source_kinds(p),  # 231 (C3d)
                               # 231 (U2c): the steps whose case of another process takes its own documents
                               "step_sources": sub_cases.step_sources(p) if sub_cases.STEP_SOURCES in p.scope.parts else [],
                               "manual": any(i.on == intake.MANUAL for i in p.intake), "summary": p.summary,
                               "missing_at_start": process_settings.missing_at_start(p),
                               "examples": p.examples is not None and bool(p.examples.sets or p.examples.documents
                                                                            or p.examples.note)}
                              for p in process_packs.packs()]}

    @app.exception_handler(examples.ExampleInUse)
    async def example_in_use(_request: Request, exc: examples.ExampleInUse):
        return error(409, "example_in_use", str(exc), **message_fields(exc))

    @app.get(r + "/processes/{pack_id}/examples")
    def process_examples(pack_id: PackId) -> dict[str, Any]:
        """231 (U0): the process's example material: the sets it installs, each with its state, and its packets of
        invented documents."""
        return work_views.jsonable(examples.of(pack_id))

    @app.post(r + "/processes/{pack_id}/examples/install")
    def process_examples_install(pack_id: PackId, _body: Empty,
                                 who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(examples.install(pack_id, who))

    @app.post(r + "/processes/{pack_id}/examples/remove")
    def process_examples_remove(pack_id: PackId, _body: Empty,
                                who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(examples.remove(pack_id, who))

    @app.post(r + "/processes/{pack_id}/examples/packets/{packet_id}/files")
    def process_example_files(pack_id: PackId, packet_id: PacketId, _body: Empty,
                              _who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        """The packet's invented documents written as PDFs beside the store, for a case to start on."""
        return {"files": examples.packet_files(pack_id, packet_id)}

    @app.get(r + "/processes/{pack_id}/records")
    def process_records(pack_id: PackId, q: Annotated[str | None, Query(max_length=200)] = None) -> dict[str, Any]:
        """231 (C3c): the records a case of the pack may start from, matching `q` (its record step's capability, the
        general form's record chooser); none for a pack whose steps read no record."""
        return work_views.jsonable({"records": process_packs.records(pack_id, q)})

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
