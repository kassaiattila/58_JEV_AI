"""The to-dos' and the system's addresses of the local service (195, plan G-tidy R4; until then in `jav/service/api.py`).

Plain-language summary: closing a to-do, and the addresses of the system page: the worker's state and stopping it, the
last dependency audit, the pinned JEV version against the provider's moving name (200), the store backup's state and a
backup now, and the paid calls with an uncertain outcome, listed and settled by hand. They moved here from `jav/service/api.py`
as they were: the same paths, request models and answers, in the same order. `jav.service.api.create_app` adds this module
after the workflows' one.

Layer: UI/CLI (the local service) → `jav.app.work`, `jav.runtime.backup`, `jav.runtime.deps_audit`, `jav.ai.jev_version`,
`jav.core.calls`, `jav.runtime.worker`.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi import Path as PathParam
from pydantic import Field

from jav.runtime import backup, deps_audit
from jav.app import work_runs, work_views
from jav.ai import jev_version
from jav.service.service_shared import Empty, In, Text, human_actor, settings
from jav.runtime import worker
from jav.core import calls

log = logging.getLogger("jav.service.api")


class ResolveReason(In):
    resolution: dict[Annotated[str, Field(max_length=64)], Any] | None = Field(default=None, max_length=50)
    note: Text | None = None


class ResolveCall(In):
    """076: settling a paid call with an uncertain outcome by hand, as `calls-resolve` does."""

    # None: unknown, the maximum stays committed; 167 (review R-9): the same cap as the settlement itself
    cost_usd: Decimal | None = Field(default=None, ge=0, le=calls.MAX_SETTLED_COST_USD, allow_inf_nan=False)
    note: str = Field(min_length=3, max_length=500)


def routes(app: FastAPI, r: str) -> None:
    """The to-dos' and the system's addresses under the service's prefix `r`."""

    # --- to-dos ---

    @app.post(r + "/review-reasons/{reason_id}/resolve")
    def resolve_reason(reason_id: Annotated[int, PathParam(ge=1)], body: ResolveReason,
                       who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work_runs.resolve_reason(reason_id, actor=who, resolution=body.resolution, note=body.note)

    # --- worker ---

    @app.get(r + "/worker")
    def worker_status() -> dict[str, Any]:
        return work_views.jsonable(worker.status())  # 227 (plan R3c): the service reads the worker

    @app.post(r + "/worker/stop")
    def worker_stop(body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        log.info("worker stop requested by %s", who)  # 066 Á35: who asked (operational log)
        worker.request_stop()
        return work_views.jsonable(worker.status())

    # --- dependency audit (075): the last result; the audit itself runs from the CLI or the daily backup ---

    @app.get(r + "/system/deps-audit")
    def deps_audit_status() -> dict[str, Any]:
        return work_views.jsonable({"status": deps_audit.status(), "max_age_days": deps_audit.MAX_AGE_DAYS})

    # --- the pinned JEV version (200): the moving name's last look; the look itself runs with the daily backup ---

    @app.get(r + "/system/jev-version")
    def jev_version_status() -> dict[str, Any]:
        return work_views.jsonable(jev_version.status())

    # --- store backup (064): status of the latest backup, and backup now ---

    @app.get(r + "/system/backup")
    def backup_status() -> dict[str, Any]:
        c = settings().get("backup", {})
        conf = {k: c.get(k) for k in ("schedule", "keep", "copy_to", "with_burr", "with_docs", "max_age_hours")}
        conf["copy_to"] = backup.configured_copy_to()  # 076: the config or the local environment
        return work_views.jsonable({"status": backup.status(backup.default_root()), "config": conf})

    @app.post(r + "/system/backup")
    def backup_now(body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """Back up now, with the daily backup's settings (locally and to the second location). A failure also shows in
        the status. 160 (review R-6): it counts with the manual backups, so it never pushes out a daily one."""
        log.info("backup requested by %s", who)
        return work_views.jsonable(backup.scheduled(kind="manual"))

    # --- paid calls with an uncertain outcome (076): listed and settled by hand, as `calls-uncertain` / `calls-resolve` ---

    @app.get(r + "/system/uncertain-calls")
    def uncertain_calls() -> dict[str, Any]:
        return work_views.jsonable({"calls": calls.uncertain_list()})

    @app.post(r + "/system/uncertain-calls/{invocation_id}/resolve")
    def resolve_uncertain_call(invocation_id: int, body: ResolveCall,
                               who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """The attempt becomes `failed` with the given cost (or with the maximum still committed when the cost is
        unknown); the step may then run again. The note records who settled it."""
        try:
            calls.resolve_uncertain(invocation_id, cost_usd=body.cost_usd, note=f"{who}: {body.note}")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        log.info("uncertain call %d settled by %s", invocation_id, who)
        return {"ok": True}
