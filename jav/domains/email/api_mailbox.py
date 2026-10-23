"""The email domain's addresses of the local service beyond its logic pack's (185, plan G-full-move T1a).

Plain-language summary: the addresses for the mailboxes and an email's task proposals:
- the mailbox page: its schedules, downloads, known accounts and defaults; a free count before a download; a download
  (run by the worker) and its state; a schedule made, changed or deleted (048 T2);
- an email package's PDF attachments taken in as documents (058 K5.2);
- a person's decision on a task proposal, and marking an accepted task done by hand (058 K5.3, 062).
They moved here from `jav/api.py` as they were: the same paths, request models, answers and error answer (a mailbox
bridge that cannot run is a 503). The email domain names this module (`jav/domains/email/__init__.py` `SERVICE`), and
`jav.api.create_app` adds it. The email routing's own addresses are its logic pack's (`jav/domains/email/api_email_routing.py`).

Layer: UI/CLI (the local service) → `jav.domains.email.mailbox`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Request
from fastapi import Path as PathParam
from pydantic import Field

from jav.app import corrections, work_views
from jav.core import store
from jav.domains.email import mailbox
from jav.service_shared import DecisionState, Empty, In, ItemId, Revision, RunId, Text, WpId, error, human_actor
from jav.core.user_messages import message_fields

ScheduleId = Annotated[str, PathParam(pattern=r"^mbx-[0-9a-f]{10}$")]
PullId = Annotated[str, PathParam(pattern=r"^pull-[0-9a-f]{10}$")]


class TaskDecision(In):
    decision: Literal[store.TASK_DECISIONS]  # type: ignore[valid-type]
    note: Text | None = None
    expected_state: DecisionState | None = None  # 187: the task's `decision_state` as the page read it


class TaskDone(In):
    done: bool
    expected_state: DecisionState | None = None


class CreateSchedule(In):
    request: mailbox.MailboxRequest
    interval_min: Annotated[int, Field(ge=15, le=7 * 24 * 60)] = mailbox.DEFAULT_INTERVAL_MIN


class UpdateSchedule(In):
    enabled: bool | None = None
    interval_min: Annotated[int, Field(ge=15, le=7 * 24 * 60)] | None = None


def routes(app: FastAPI, r: str) -> None:
    """The email domain's addresses under the service's prefix `r`, and the answer to a bridge that cannot run."""

    @app.exception_handler(mailbox.BridgeError)
    async def bridge_failed(_request: Request, exc: mailbox.BridgeError):
        return error(503, "mailbox_unavailable", str(exc), **message_fields(exc))

    @app.post(r + "/workpackages/{wp_id}/attachments")
    def add_attachments(wp_id: WpId, body: Revision, _who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """058 K5.2: the emails' PDF attachments go into the package as documents, pointing back to the email."""
        mailbox.add_attachments(wp_id, expected_revision=body.expected_revision)
        return work_views.workpackage_view(wp_id)

    @app.post(r + "/runs/{run_id}/items/{item_id}/tasks/{index}/decision")
    def task_decision(run_id: RunId, item_id: ItemId, index: Annotated[int, PathParam(ge=0, le=100)], body: TaskDecision,
                      who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """058 K5.3: only a human accepts or rejects a task proposal."""
        mailbox.decide_task(run_id, item_id, index, decision=body.decision, actor=who, note=body.note,
                            expected_state=body.expected_state)
        return work_views.jsonable(corrections.item_result(run_id, item_id))

    @app.post(r + "/runs/{run_id}/items/{item_id}/tasks/{index}/done")
    def task_done(run_id: RunId, item_id: ItemId, index: Annotated[int, PathParam(ge=0, le=100)], body: TaskDone,
                  who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """062: mark an accepted task as done by hand (or undo that)."""
        mailbox.mark_task_done(run_id, item_id, index, done=body.done, actor=who, expected_state=body.expected_state)
        return work_views.jsonable(corrections.item_result(run_id, item_id))

    # --- mailbox (048 T2): preview, download (run by the worker), schedule ---

    @app.get(r + "/mailbox")
    def mailbox_overview() -> dict[str, Any]:
        from jav.core.config import OUTLOOK_BRIDGE_SCRIPT

        return work_views.jsonable({"schedules": mailbox.schedules(), "pulls": mailbox.pulls(), "accounts": mailbox.known_accounts(),
                                    "bridge_available": OUTLOOK_BRIDGE_SCRIPT.is_file(),
                                    "defaults": {"interval_min": mailbox.DEFAULT_INTERVAL_MIN,
                                                 "lookback_days": mailbox.DEFAULT_LOOKBACK_DAYS}})

    @app.post(r + "/mailbox/count")
    def mailbox_count(body: mailbox.MailboxRequest) -> dict[str, Any]:
        """Free count preview (the legacy script's `-CountOnly` branch); Outlook must be running."""
        return work_views.jsonable(mailbox.count(body))

    @app.post(r + "/mailbox/pulls", status_code=202)
    def mailbox_pull(body: mailbox.MailboxRequest, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(mailbox.request_pull(body, actor=who))

    @app.get(r + "/mailbox/pulls/{pull_id}")
    def mailbox_pull_status(pull_id: PullId) -> dict[str, Any]:
        return work_views.jsonable(mailbox.pull(pull_id))

    @app.post(r + "/mailbox/schedules", status_code=201)
    def mailbox_schedule_create(body: CreateSchedule, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(mailbox.create_schedule(body.request, actor=who, interval_min=body.interval_min))

    @app.patch(r + "/mailbox/schedules/{schedule_id}")
    def mailbox_schedule_update(schedule_id: ScheduleId, body: UpdateSchedule,
                                who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(mailbox.update_schedule(schedule_id, actor=who, enabled=body.enabled,
                                                           interval_min=body.interval_min))

    @app.post(r + "/mailbox/schedules/{schedule_id}/delete")  # a POST with a JSON body, like the other deletions
    def mailbox_schedule_delete(schedule_id: ScheduleId, body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        mailbox.delete_schedule(schedule_id, actor=who)
        return {"deleted": schedule_id}


__all__ = ["routes"]
