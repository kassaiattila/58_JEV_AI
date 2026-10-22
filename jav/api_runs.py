"""The runs' addresses of the local service (195, plan G-tidy R4; until then in `jav/api.py` `create_app`).

Plain-language summary: the addresses for a package's processing setting and its readiness, starting a run (a trial or
a live one), and following the runs: the package's runs and every run, one run's view and journal, cancelling, the
superseding of an older live run and the approval. They moved here from `jav/api.py` as they were: the same paths,
request models and answers, in the same order. `jav.api.create_app` adds this module after the work packages' one.

Layer: UI/CLI (the local service) → `jav.work`, `jav.work_views`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Query
from pydantic import Field

from jav import work_readiness, work_recipes, work_runs, work_views
from jav.service_shared import Empty, In, JavJSONResponse, RunId, Text, WpId, human_actor


class SaveWorkflow(In):
    recipe_id: Annotated[str, Field(min_length=1, max_length=100)]
    params: dict[Annotated[str, Field(max_length=64)], Annotated[str, Field(max_length=200)]] = Field(default_factory=dict, max_length=20)
    expected_revision: Annotated[int, Field(ge=0)]
    note: Text | None = None


class StartRun(In):
    mode: Literal["shadow", "apply"] = "shadow"
    expected_revision: Annotated[int, Field(ge=0)]
    input_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")]
    rerun_of: Annotated[str, Field(pattern=r"^run-[0-9a-f]{12}$")] | None = None  # 057: rerun
    scope: Literal["all", "pending"] = "all"  # 160-C S3: "pending" = only the package's pending items


class Approve(In):
    """085 (re-audit A01): `review_version` is the run view's `review_version` the approver saw; if a correction changed
    the result since, 409. Without it (the command line) the current result is approved."""
    review_version: str | None = Field(default=None, max_length=64)
    # 160-C (decision 163 D7): how many removed items the approver saw (the run view's `removed_items`)
    confirm_removed: int | None = Field(default=None, ge=0)


def routes(app: FastAPI, r: str) -> None:
    """The runs' addresses under the service's prefix `r`."""

    # --- workflow (recipe) and readiness ---

    @app.get(r + "/workpackages/{wp_id}/workflow")
    def workflow(wp_id: WpId) -> dict[str, Any]:
        return work_views.assignment_view(wp_id)

    @app.post(r + "/workpackages/{wp_id}/workflow")
    def save_workflow(wp_id: WpId, body: SaveWorkflow, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        work_recipes.assign_recipe(wp_id, body.recipe_id, params=dict(body.params), expected_revision=body.expected_revision,
                           actor=who, note=body.note)
        return work_views.assignment_view(wp_id)

    @app.get(r + "/workpackages/{wp_id}/workflow/readiness")
    def readiness(wp_id: WpId) -> dict[str, Any]:
        return work_views.jsonable(work_readiness.readiness(wp_id))

    @app.post(r + "/workpackages/{wp_id}/workflow/start")
    def start(wp_id: WpId, body: StartRun, who: Annotated[str, Depends(human_actor)]) -> JavJSONResponse:
        res = work_runs.start_run(wp_id, mode=body.mode, expected_assignment_revision=body.expected_revision,
                             input_hash=body.input_hash, actor=who, rerun_of=body.rerun_of,
                             scope=body.scope)
        run = work_runs.get_run(res["run_id"])
        return JavJSONResponse({**res, "status": run["status"]}, status_code=200 if res["deduped"] else 201)

    @app.get(r + "/workpackages/{wp_id}/runs")
    def wp_runs(wp_id: WpId) -> dict[str, Any]:
        return {"runs": work_views.run_list(wp_id)}

    # --- runs ---

    @app.get(r + "/runs")
    def all_runs(limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict[str, Any]:
        return {"runs": work_views.run_list(None, limit=limit)}

    @app.get(r + "/runs/{run_id}")
    def run(run_id: RunId, names: Literal["original", "unified"] = "original") -> dict[str, Any]:
        """082: `names=unified` adds the items' unified names (the review queue shows them instead of the originals)."""
        return work_views.run_view(run_id, names=names == "unified")

    @app.get(r + "/runs/{run_id}/journal")
    def journal(run_id: RunId) -> dict[str, Any]:
        return work_views.run_journal(run_id)

    @app.post(r + "/runs/{run_id}/cancel")
    def cancel(run_id: RunId, body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        work_runs.get_run(run_id)
        return {"run_id": run_id, "jobs": work_runs.cancel_run(run_id, actor=who), "status": work_runs.get_run(run_id)["status"]}

    @app.post(r + "/runs/{run_id}/supersede")
    def supersede(run_id: RunId, body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """151: a person supersedes an older live run that a later live run has repeated (`work_runs.supersede_run`)."""
        out = work_runs.supersede_run(run_id, actor=who)
        return {**out, "status": work_runs.get_run(run_id)["status"]}

    @app.post(r + "/runs/{run_id}/approve")
    def approve(run_id: RunId, body: Approve, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        work_runs.approve_run(run_id, actor=who, review_version=body.review_version, confirm_removed=body.confirm_removed)
        return work_views.run_view(run_id)
