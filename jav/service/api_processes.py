"""The process packs and their own settings on the local service (231, plan stage B, B2; DECISIONS 231).

Plain-language summary: the processes the system runs (each a process pack, `configs/processes/`), and each one's own
values over its file's resources (which price list, how its letters are sent, which letter frame and output
template; `jav/app/process_settings.py`). These addresses list the processes, show one's resources with their versions
and the rule of who may make a value active, save a value as a draft, make a version active and set the process's own
value aside (the file's counts again). A person the rule does not let make a value active is refused (403). 231
(B3): the same for a rule key its capabilities let a process set (`/rules/...`; the value a whole number or one of
the key's options), and its preview on the decision trace (nothing is written).

231 (U3f): the letter frames of the shared library (`/library/letter-frames`): their texts and versions, a changed text
saved as a draft, a version made active, the file's text brought back (`jav/app/letter_frames.py`).

231 (U4): the installation's defaults (`/defaults`): the keys a person may set with their versions, a value saved as
a draft, tried on the earlier decisions, made active, and set aside (`jav/app/rule_defaults.py`).

Layer: UI/CLI (the local service) → `jav.app.process_settings`, `jav.app.process_packs`, `jav.app.letter_frames`,
`jav.app.rule_defaults`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query, Request
from fastapi import Path as PathParam
from pydantic import Field

from jav.app import (document_processing, examples, intake, letter_frames, process_packs, process_settings, rule_defaults,
                     scopes, sub_cases, work_views)
from jav.core import identity
from jav.core.user_messages import message_fields
from jav.service.api_cases import Source, _source
from jav.service.service_shared import Empty, In, IsoDay, PartyId, error, human_actor

PackId = Annotated[str, PathParam(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
SettingKey = Annotated[str, PathParam(pattern=r"^[a-z][a-z0-9_:]{0,79}$")]
RuleKey = Annotated[str, PathParam(pattern=r"^[a-z][A-Za-z0-9_:.]{0,119}$")]  # 231 (B3): <rule file>.<dotted key>
Version = Annotated[int, PathParam(ge=1)]
PacketId = Annotated[str, PathParam(pattern=r"^[a-z][a-z0-9_]{0,63}$")]  # 231 (U0): an example packet
LibraryKind = Annotated[str, PathParam(pattern=r"^[a-z][a-z_]{0,39}$")]  # 231 (U3d): a shared library kind
FrameId = Annotated[str, PathParam(pattern=r"^[a-z][a-z0-9_]{0,63}$")]  # 231 (U3f): a letter frame
DefaultId = Annotated[str, PathParam(pattern=r"^[a-z][a-z0-9_]*\.[A-Za-z0-9_.]{1,159}$")]  # 231 (U4c): <file>.<key>
DefaultValue = (bool | int | float | Annotated[str, Field(max_length=200)]
                | Annotated[list[Annotated[str, Field(max_length=80)]], Field(max_length=200)]
                | Annotated[dict[Annotated[str, Field(max_length=80)], Annotated[str, Field(max_length=80)]], Field(max_length=100)])


class SettingIn(In):
    value: Annotated[str, Field(min_length=1, max_length=200)]
    note: Annotated[str | None, Field(max_length=2000)] = None


class RuleIn(In):
    value: int | Annotated[str, Field(min_length=1, max_length=200)]
    note: Annotated[str | None, Field(max_length=2000)] = None


class DefaultIn(In):
    """231 (U4c): an installation default's value (a number, yes or no, a text, a list or a map) and its note."""

    value: DefaultValue
    note: Annotated[str | None, Field(max_length=2000)] = None


class DefaultTry(In):
    value: DefaultValue


class FrameIn(In):
    """231 (U3f): the fields of a letter frame a person changed, by their path in the frame (a text, or paragraphs)."""

    values: Annotated[dict[Annotated[str, Field(max_length=80)], str | list[Annotated[str, Field(max_length=6000)]]],
                      Field(min_length=1, max_length=40)]
    note: Annotated[str | None, Field(max_length=2000)] = None


class EstimateIn(In):
    """261: what a new case's form asks the estimate of: each step's documents, with the own party and the period."""

    party_id: PartyId | None = None
    period_start: IsoDay | None = None
    period_end: IsoDay | None = None
    step_sources: Annotated[dict[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")], Source],
                            Field(min_length=1, max_length=20)]


def routes(app: FastAPI, r: str) -> None:
    """The process packs' addresses under the service's prefix `r`."""

    @app.exception_handler(process_settings.SettingRefused)
    async def setting_refused(_request: Request, exc: process_settings.SettingRefused):
        return error(403, "setting_refused", str(exc), **message_fields(exc))

    @app.exception_handler(process_packs.UnknownPack)
    async def unknown_pack(_request: Request, exc: process_packs.UnknownPack):
        return error(404, "not_found", str(exc))

    @app.post(r + "/processes/{pack_id}/estimate")
    def step_estimates(pack_id: PackId, body: EstimateIn) -> dict[str, Any]:
        """261: what each step's sub-case's live run would cost at most (the start form's caps); nothing is written."""
        period = (body.period_start, body.period_end) if body.period_start and body.period_end else None
        return sub_cases.estimates(pack_id, {k: _source(v) for k, v in body.step_sources.items()}, party_id=body.party_id,
                                   period=period)

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
                               "only_new": document_processing.takes_only_new(p),  # 261
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

    @app.get(r + "/library/used-by/{kind}")
    def library_used_by(kind: LibraryKind) -> dict[str, Any]:
        """231 (U3d): for each thing of a shared library kind (a product, a tariff, a price list, a letter frame, an
        output template, a partner role), the processes that use it now."""
        return {"used_by": process_settings.used_by(kind)}

    @app.get(r + "/defaults")
    def default_list() -> dict[str, Any]:
        """231 (U4): every rule key the installation may keep its own value of, with the file's value, the active
        default and its versions; the values that stay the file's, with why; the rule of who may make one active."""
        return work_views.jsonable({**rule_defaults.view(), "fixed": rule_defaults.fixed()})

    @app.post(r + "/defaults/{rule_id}", status_code=201)
    def default_propose(rule_id: DefaultId, body: DefaultIn,
                        who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        file, key = rule_id.split(".", 1)
        return work_views.jsonable(rule_defaults.propose(file, key, body.value, who, note=body.note))

    @app.post(r + "/defaults/{rule_id}/preview")
    def default_preview(rule_id: DefaultId, body: DefaultTry) -> dict[str, Any]:
        """What the value would have changed on the earlier decisions that read the key (nothing is written)."""
        file, key = rule_id.split(".", 1)
        return work_views.jsonable(rule_defaults.preview(file, key, body.value))

    @app.post(r + "/defaults/{rule_id}/versions/{version}/activate")
    def default_activate(rule_id: DefaultId, version: Version, _body: Empty,
                         who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        file, key = rule_id.split(".", 1)
        return work_views.jsonable(rule_defaults.activate(file, key, version, who))

    @app.post(r + "/defaults/{rule_id}/retire")
    def default_retire(rule_id: DefaultId, _body: Empty,
                       who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        file, key = rule_id.split(".", 1)
        return work_views.jsonable(rule_defaults.retire(file, key, who))

    @app.get(r + "/library/letter-frames")
    def letter_frame_list() -> dict[str, Any]:
        """231 (U3f): the letter frames of the shared library, each with its file's text, the text in effect and its
        versions; the rule of who may make a version active."""
        return work_views.jsonable(letter_frames.listing())

    @app.post(r + "/library/letter-frames/{kind}/{ident}", status_code=201)
    def letter_frame_propose(kind: LibraryKind, ident: FrameId, body: FrameIn,
                             who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(letter_frames.propose(kind, ident, body.values, who, note=body.note))

    @app.post(r + "/library/letter-frames/{kind}/{ident}/versions/{version}/activate")
    def letter_frame_activate(kind: LibraryKind, ident: FrameId, version: Version, _body: Empty,
                              who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(letter_frames.activate(kind, ident, version, who))

    @app.post(r + "/library/letter-frames/{kind}/{ident}/retire")
    def letter_frame_retire(kind: LibraryKind, ident: FrameId, _body: Empty,
                            who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(letter_frames.retire(kind, ident, who))

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
