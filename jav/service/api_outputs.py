"""The output layer's addresses (178, plan 170 L4, DECISIONS 178): own templates and a package's choice of them.

- `GET /output-templates`: every template with its versions, and every output's names with their labels and (179) the
  markers a template may use, ready to copy;
- `POST /output-templates`: an upload, read by the service from a file the operating system's picker chose (the
  request carries its path, as adding documents does; a template can be larger than a request's body); checked, and
  stored as a draft version (422 `template_refused` with the check's problems when it has any);
- `POST /output-templates/{template}/versions/{n}/activate`, `POST /output-templates/{template}/retire`;
- `GET /output-templates/{template}/versions/{n}/file` and `/preview.xlsx` (filled with made-up data; 196: a Word
  template's `/preview.docx`, each file with its own media type);
- `GET /workpackages/{id}/output-templates` and `PUT /workpackages/{id}/output-templates/{output}`: the choice;
- `GET /workpackages/{id}/result/utility-cost.xlsx`: the utility cost of the package's current result.

Layer: UI/CLI gateway → `jav.app.outputs.templates` (application operation).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi import Path as PathParam
from fastapi.responses import Response
from pydantic import Field

from jav.core import identity
from jav.app import package_release, work_views
from jav.service.service_shared import DecisionState, Empty, In, WpId, attachment_header, checked_path, error, human_actor
from jav.app.outputs import contract, samples, templates

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TemplateId = Annotated[str, PathParam(pattern=r"^tpl-[0-9a-f]{10}$")]
OutputName = Annotated[str, PathParam(pattern=r"^[a-z_]{1,40}$")]
Version = Annotated[int, PathParam(ge=1, le=100000)]


class TemplateUpload(In):
    output: Annotated[str, Field(pattern=r"^[a-z_]{1,40}$")]
    name: Annotated[str, Field(min_length=1, max_length=120)]
    path: Annotated[str, Field(min_length=1, max_length=2000)]
    template: Annotated[str | None, Field(pattern=r"^tpl-[0-9a-f]{10}$")] = None


class TemplateChoice(In):
    template: Annotated[str | None, Field(pattern=r"^tpl-[0-9a-f]{10}$")] = None
    expected_state: DecisionState | None = None  # 187: the choice's `decision_state` as the page read it


def _file(content: bytes, name: str) -> Response:
    media = package_release.DOCX if name.lower().endswith(".docx") else XLSX  # 196: a Word template's file
    return Response(content, media_type=media, headers={"Content-Disposition": attachment_header(name), "Cache-Control": "no-store",
                                                       "X-Content-Type-Options": "nosniff"})


def routes(app: FastAPI, r: str) -> None:
    """The output layer's addresses under the service's prefix `r`, and the answers to its errors."""

    @app.exception_handler(templates.TemplateRefused)
    async def template_refused(_request: Request, exc: templates.TemplateRefused):
        return error(422, "template_refused", str(exc), check=exc.check)

    @app.exception_handler(templates.TemplateStateError)
    async def template_state(_request: Request, exc: templates.TemplateStateError):
        return error(409, "template_state", str(exc))

    @app.get(r + "/output-templates")
    def output_templates() -> dict[str, Any]:
        # 179: with each output's markers ready to copy (the settings page's list)
        return work_views.jsonable({"templates": templates.listing(),
                                    "outputs": {o: samples.labels(o) | {"markers": samples.markers(o),  # 196: its format
                                                                        "format": contract.spec(o)["format"]}
                                                for o in contract.outputs()}})

    @app.post(r + "/output-templates", status_code=201)
    def upload_output_template(body: TemplateUpload, who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        contract.spec(body.output)  # an unknown output: 422
        path = checked_path(body.path, want_dir=False)
        if path.stat().st_size > contract.templates()["max_bytes"]:
            raise templates.TemplateRefused({"output": body.output, "ok": False, "warnings": [], "values": [], "tables": {},
                                             "problems": [{"code": "too_large", "where": "", "detail": str(path.stat().st_size)}]})
        return work_views.jsonable(templates.add(body.output, body.name, path.name, path.read_bytes(), actor=who,
                                                 template=body.template))

    @app.post(r + "/output-templates/{template}/versions/{version}/activate")
    def activate_output_template(template: TemplateId, version: Version, _body: Empty,
                                 who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(templates.activate(template, version, actor=who))

    @app.post(r + "/output-templates/{template}/retire")
    def retire_output_template(template: TemplateId, _body: Empty, who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(templates.retire(template, actor=who))

    @app.get(r + "/output-templates/{template}/versions/{version}/file")
    def output_template_file(template: TemplateId, version: Version) -> Response:
        return _file(*templates.content(template, version))

    @app.get(r + "/output-templates/{template}/versions/{version}/preview.xlsx")
    @app.get(r + "/output-templates/{template}/versions/{version}/preview.docx")  # 196: a Word template's
    def output_template_preview(template: TemplateId, version: Version) -> Response:
        return _file(*templates.preview(template, version))

    @app.get(r + "/workpackages/{wp_id}/output-templates")
    def package_output_templates(wp_id: WpId) -> dict[str, Any]:
        return work_views.jsonable(templates.choices(wp_id))

    @app.put(r + "/workpackages/{wp_id}/output-templates/{output}")
    def choose_output_template(wp_id: WpId, output: OutputName, body: TemplateChoice,
                               who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(templates.choose(wp_id, output, body.template, actor=who, expected_state=body.expected_state))

    @app.get(r + "/workpackages/{wp_id}/result/utility-cost.xlsx")
    def package_utility_cost_xlsx(wp_id: WpId) -> Response:
        """178 (DECISIONS 178): the utility cost of the package's current result, with its chosen template."""
        return _file(*package_release.current_output_workbook(wp_id, "utility_cost"))


__all__ = ["routes"]
