"""The workflows' addresses of the local service (195, plan G-tidy R4; 146: until then in `jav/api.py` `create_app`).

Plain-language summary: a workflow chains the work packages of one job. These are the addresses of the workflow pages:
the templates, the cost estimate of a step, the list, creating and changing a workflow, the draft for the next period,
and starting or linking a step. A step's folder or files are checked like any typed path. They moved here from
`jav/api.py` as they were: the same paths, request models and answers, in the same order. `jav.api.create_app` adds
this module after the output layer's one.

Layer: UI/CLI (the local service) → `jav.app.workflows`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI
from fastapi import Path as PathParam
from pydantic import Field

from jav.app import work_views, workflows
from jav.service_shared import In, IsoDay, PartyId, checked_path, human_actor


WfId = Annotated[str, PathParam(pattern=r"^wf-[0-9a-f]{12}$")]  # 146: a workflow
StepId = Annotated[str, PathParam(pattern=r"^[a-z_]{1,40}$")]  # 146: a workflow step


StepKey = Annotated[str, Field(pattern=r"^[a-z_]{1,40}$")]
Budget = dict[Literal["jev", "openai", "azure_di"], Annotated[str, Field(pattern=r"^\d{1,4}(\.\d{1,6})?$")]]


class WorkflowSource(In):
    """146: a workflow step's source: a folder or files, an existing work package, none, or (185) a domain's source kind
    (the email domain's mailbox request). Which kinds a step takes, and a domain kind's own check, are the workflow's
    (`workflows._source`, `workflow_steps.SourceKind.check`)."""
    kind: Annotated[str, Field(pattern=r"^[a-z_]{1,40}$")]
    folder: Annotated[str, Field(min_length=1, max_length=1024)] | None = None
    recursive: bool = False
    paths: Annotated[list[Annotated[str, Field(min_length=1, max_length=1024)]], Field(max_length=500)] | None = None
    request: dict[str, Any] | None = None  # a domain source kind's request, checked by its kind
    workpackage_id: Annotated[str, Field(pattern=r"^wp-[0-9a-f]{12}$")] | None = None
    only_new: bool = False  # 147: a documents step takes only the documents no live run has processed yet


class WorkflowStepInput(In):
    source: WorkflowSource
    budget: Budget | None = None  # 146: the most an automatic start may reserve, per provider (USD)
    engine: Literal["jev", "gpt"] | None = None  # 160-D: the step's own AI engine; None: the application's


class CreateWorkflow(In):
    template: Annotated[str, Field(pattern=r"^[a-z_]{1,60}$")]
    # 181: the party and the period are needed only when the template's steps need them (`workflows.template_needs`)
    party_id: PartyId | None = None
    period_start: IsoDay | None = None
    period_end: IsoDay | None = None
    name: Annotated[str, Field(max_length=200)] | None = None
    names: dict[StepKey, Annotated[str, Field(min_length=1, max_length=200)]] | None = None  # the steps' package names
    auto: bool = True
    steps: Annotated[dict[StepKey, WorkflowStepInput], Field(min_length=1, max_length=10)]
    previous: Annotated[str, Field(pattern=r"^wf-[0-9a-f]{12}$")] | None = None  # 147: the workflow this one repeats


class WorkflowEstimate(In):
    kind: Annotated[str, Field(pattern=r"^[a-z_]{1,40}$")]  # 181: a registered step kind (`jav/app/workflow_steps.py`)
    source: WorkflowSource
    party_id: PartyId | None = None
    period_start: IsoDay | None = None
    period_end: IsoDay | None = None
    engine: Literal["jev", "gpt"] | None = None  # 160-D: the step's own AI engine; None: the application's


class StartWorkflowStep(In):
    budget: Budget | None = None  # a person's new budget for the step (recorded)


class LinkWorkflowStep(In):
    workpackage_id: Annotated[str, Field(pattern=r"^wp-[0-9a-f]{12}$")]


class UpdateWorkflow(In):
    auto: bool | None = None
    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    archived: bool | None = None


def routes(app: FastAPI, r: str) -> None:
    """The workflows' addresses under the service's prefix `r`."""

    def workflow_source(src: WorkflowSource) -> dict[str, Any]:
        """A step's source with its paths checked like a typed path (existing, under the allowed roots)."""
        out = src.model_dump(exclude_none=True)
        if src.kind == "folder":
            out["folder"] = str(checked_path(src.folder or "", want_dir=True))
        elif src.kind == "files":
            out["paths"] = [str(checked_path(p, want_dir=False)) for p in src.paths or []]
        return out

    @app.get(r + "/workflow-templates")
    def workflow_templates() -> dict[str, Any]:
        return workflows.templates_view()  # 181: each kind with its registered step kind

    @app.post(r + "/workflows/estimate")
    def workflow_estimate(body: WorkflowEstimate) -> dict[str, Any]:
        return work_views.jsonable(workflows.estimate(kind=body.kind, source=workflow_source(body.source),
                                                      party_id=body.party_id, period_start=body.period_start,
                                                      period_end=body.period_end, engine=body.engine))

    @app.get(r + "/workflows")
    def workflow_list(include_archived: bool = False) -> dict[str, Any]:
        return {"workflows": work_views.jsonable(workflows.workflows(include_archived=include_archived))}

    @app.post(r + "/workflows", status_code=201)
    def create_workflow(body: CreateWorkflow, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        steps = {sid: {"source": workflow_source(s.source), "budget": s.budget or {}, "engine": s.engine}
                 for sid, s in body.steps.items()}
        return work_views.jsonable(workflows.create(template_id=body.template, party_id=body.party_id,
                                                    period_start=body.period_start, period_end=body.period_end,
                                                    steps=steps, actor=who, name=body.name, names=body.names,
                                                    auto=body.auto, previous=body.previous))

    @app.get(r + "/workflows/{wf_id}")
    def workflow_view(wf_id: WfId) -> dict[str, Any]:
        return work_views.jsonable(workflows.view(wf_id))

    @app.get(r + "/workflows/{wf_id}/repeat")
    def workflow_repeat(wf_id: WfId) -> dict[str, Any]:
        """147: the workflow for the next period, as the wizard shows it filled in (nothing is written)."""
        return work_views.jsonable(workflows.repeat_draft(wf_id))

    @app.patch(r + "/workflows/{wf_id}")
    def update_workflow(wf_id: WfId, body: UpdateWorkflow, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(workflows.update(wf_id, actor=who, auto=body.auto, name=body.name,
                                                    archived=body.archived))

    @app.post(r + "/workflows/{wf_id}/steps/{step}/start")
    def start_workflow_step(wf_id: WfId, step: StepId, body: StartWorkflowStep,
                            who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(workflows.start_step(wf_id, step, actor=who, budget=body.budget))

    @app.post(r + "/workflows/{wf_id}/steps/{step}/link")
    def link_workflow_step(wf_id: WfId, step: StepId, body: LinkWorkflowStep,
                           who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(workflows.link(wf_id, step, body.workpackage_id, actor=who))
