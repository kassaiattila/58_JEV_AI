"""Waiting for a reply (231, plan stage A, A7d; DECISIONS 231): the general `wait_reply` capability of every process pack.

Plain-language summary: after a case sent something, it waits for the other side's answer. A person records that the
reply arrived, or that none is needed; later (stage C) an incoming email will say so by itself. If nothing happens for
the days the process pack sets (the owner's decision of 2026-10-24: 5 days for the IT quote), a follow-up task opens in
the "Waiting for me" list, without a deadline and at most once per step: the person records the reply, that none is
needed, or that they reminded the other side and the case keeps waiting (with no further reminder).

- `WaitReply`: what a process pack sets: after how many days the follow-up task opens.
- `reply(case_id, step_id, answer, actor, note)`: the reply recorded (`replied` or `not_needed`), whether or not the
  follow-up task is open; `keep_waiting(...)`: the person reminded the other side.

Layer: application; it uses the process core's events, timers and human tasks.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from jav.app import capabilities
from jav.core import identity, store
from jav.core.clock import utc_stamp
from jav.core.process import cases, kinds, tasks, timers
from jav.core.process.engine import StepContext
from jav.core.user_messages import explained

__all__ = ["FOLLOW_UP_TASK", "KEEP_WAITING", "NOT_NEEDED", "REPLIED", "REPLY", "ReplyError", "WaitReply", "keep_waiting",
           "register", "reply"]

REPLY = "reply"  # the event a reply sends the step
REPLIED, NOT_NEEDED, KEEP_WAITING = "replied", "not_needed", "keep_waiting"
FOLLOW_UP_TASK = "follow_up"
REMIND = "remind"  # the step's timer: when the follow-up task opens
DAY_S = 86400.0
_OWNER = __name__


class ReplyError(ValueError):
    """A reply that cannot be recorded: the step does not wait for one, or the answer is unknown."""


class WaitReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    remind_after_days: float = Field(gt=0, le=365)


def _task_id(case_id: str, step_id: str) -> str:
    return tasks.task_id(FOLLOW_UP_TASK, f"{case_id}:{step_id}")


def _gathered(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row.get("result") or {})


def _run(ctx: StepContext, params: WaitReply) -> kinds.StepOutcome:
    """Done once a reply is recorded; otherwise it waits for one, with the follow-up's timer the first time."""
    gathered = _gathered(ctx.row())
    if REPLY in gathered:
        return kinds.Done(gathered)
    task = tasks.get(_task_id(ctx.case_id, ctx.step.id))
    if task is not None and task.status == tasks.OPEN:
        return kinds.WAIT
    if task is not None and task.status == tasks.DECIDED:
        answer = (task.outcome or {}).get(REPLY)
        if answer in (REPLIED, NOT_NEEDED):
            return kinds.Done({**gathered, REPLY: answer, "by": task.closed_by.name if task.closed_by else None,
                               "at": task.closed_at, "note": task.note, "reminded": True})
        return ctx.wait(REPLY)  # reminded: no further follow-up
    if "since" not in gathered:
        gathered["since"] = time.time()
        with ctx.transaction() as c:
            cases.set_result(c, ctx.case_id, ctx.step.id, gathered)
    return ctx.wait(REPLY, timer=(REMIND, gathered["since"] + params.remind_after_days * DAY_S))


def _on_event(ctx: StepContext, c: Any, event: cases.Event) -> str:
    """A reply: kept with the step (the step is then done); an unknown answer is refused. The follow-up task's closing
    only ends the wait (the step reads the task)."""
    if event.kind != REPLY:
        return kinds.APPLIED
    answer = event.payload.get(REPLY)
    if answer not in (REPLIED, NOT_NEEDED):
        return kinds.REFUSED
    gathered = _gathered(cases.step_row(c, ctx.case_id, ctx.step.id))
    cases.set_result(c, ctx.case_id, ctx.step.id, {**gathered, REPLY: answer, "by": event.sent_by.name,
                                                   "at": utc_stamp(), "note": event.payload.get("note"),
                                                   "reminded": "reminded_at" in gathered})
    return kinds.APPLIED


def _on_timer(ctx: StepContext, c: Any, timer: Any) -> str:
    """The days passed without a reply: the follow-up task opens once, without a deadline; the step waits for it."""
    if timer.name != REMIND:
        return "ignored"
    tid = _task_id(ctx.case_id, ctx.step.id)
    if tasks.task_in(c, tid) is not None:
        return "late"
    gathered = _gathered(cases.step_row(c, ctx.case_id, ctx.step.id))
    cases.set_result(c, ctx.case_id, ctx.step.id, {**gathered, "reminded_at": utc_stamp()})
    tasks.open_in(c, FOLLOW_UP_TASK, f"{ctx.case_id}:{ctx.step.id}", ctx.actor, case_id=ctx.case_id,
                  step_id=ctx.step.id, detail={"since": gathered.get("since")})
    return "follow_up"


def _step_state(case_id: str, step_id: str) -> tuple[dict[str, Any] | None, tasks.Task | None]:
    with store.connect() as c:
        return cases.find_step_in(c, case_id, step_id), tasks.task_in(c, _task_id(case_id, step_id))


def _waits(case_id: str, step_id: str) -> bool:
    step, task = _step_state(case_id, step_id)
    return bool(step and step["state"] == cases.RUNNING
                and (step["waiting_for"] == REPLY or task is not None and task.status == tasks.OPEN))


def _following_up(case_id: str, step_id: str) -> bool:
    _, task = _step_state(case_id, step_id)
    return task is not None and task.status == tasks.OPEN


def reply(case_id: str, step_id: str, answer: str, actor: identity.Who, note: str | None = None) -> None:
    """The reply recorded on the step (`replied` or `not_needed`): the open follow-up task decided with it, otherwise
    the reply event sent; the step is done at the case's next turn."""
    if answer not in (REPLIED, NOT_NEEDED):
        raise ReplyError(f"a reply is {REPLIED} or {NOT_NEEDED}, not {answer!r}")
    if not _waits(case_id, step_id):
        raise explained(ReplyError, "the step {{step}} does not wait for a reply", step=step_id)
    who = identity.who(actor)
    if _following_up(case_id, step_id):
        tasks.decide(_task_id(case_id, step_id), who, outcome={REPLY: answer}, note=note)
        return
    cases.send_event(case_id, f"{case_id}:{step_id}:{REPLY}", REPLY, {REPLY: answer, "note": note}, who,
                     step_id=step_id)


def keep_waiting(case_id: str, step_id: str, actor: identity.Who, note: str | None = None) -> None:
    """The person reminded the other side: the follow-up task closes and the step waits on, with no further reminder."""
    if not _following_up(case_id, step_id):
        raise explained(ReplyError, "the step {{step}} has no follow-up to close", step=step_id)
    tasks.decide(_task_id(case_id, step_id), identity.who(actor), outcome={REPLY: KEEP_WAITING}, note=note)


CAPABILITY = capabilities.Capability(
    name="wait_reply", version=1, module=_OWNER, run=_run, kind="wait", params=WaitReply, effects="store",
    events=(REPLY,), on_event=_on_event, on_timer=_on_timer,
    summary="Waits for the other side's reply; after the days set, a follow-up task opens once, without a deadline.",
    actions=(capabilities.Action("replied", "A reply arrived", _waits,
                                 lambda case_id, step_id, actor, note: reply(case_id, step_id, REPLIED, actor, note)),
             capabilities.Action("not_needed", "No reply is needed", _waits,
                                 lambda case_id, step_id, actor, note: reply(case_id, step_id, NOT_NEEDED, actor, note)),
             capabilities.Action("keep_waiting", "I reminded them, keep waiting", _following_up,
                                 lambda case_id, step_id, actor, note: keep_waiting(case_id, step_id, actor, note))))


def _stamp(epoch: float | None) -> str | None:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds") if epoch else None


def _reply_view(case_id: str, step_id: str | None, shared: dict[str, Any]) -> dict[str, Any]:
    """231 (A7e): what a reply step shows on its case's page: since when it waits, when the follow-up opens (or opened),
    the follow-up task's state, the reply recorded and, while it waits, the case's next step."""
    step = str(step_id)
    with store.connect() as c:
        row = cases.find_step_in(c, case_id, step) or {}
        task = tasks.task_in(c, _task_id(case_id, step))
        remind = next((t for t in timers.of_case(c, case_id) if t["step_id"] == step and t["name"] == REMIND), None)
    gathered = _gathered(row)
    nxt = None
    if row.get("state") == cases.RUNNING:
        following = task is not None and task.status == tasks.OPEN
        nxt = {"code": "case_follow_up" if following else "case_reply_wait",
               "label": "Follow up the reply" if following else "Waiting for the reply", "stage": "result",
               "element": "reply_wait"}
    return {"state": row.get("state"), "since": _stamp(gathered.get("since")),
            "remind_at": _stamp(remind["due_at"]) if remind else None, "reminded_at": gathered.get("reminded_at"),
            "follow_up": task.status if task else None,
            **{k: gathered.get(k) for k in (REPLY, "by", "at", "note")}, "next": nxt}


def register() -> None:
    from jav.app import case_views

    capabilities.register(CAPABILITY)
    case_views.register(case_views.ElementData("reply_wait", "wait_reply", _OWNER, _reply_view))


tasks.register_kind(tasks.TaskKind(FOLLOW_UP_TASK, __name__))
