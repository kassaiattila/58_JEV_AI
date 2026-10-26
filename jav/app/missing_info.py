"""Waiting for missing facts with a task that expires (231, stage D, D-d6).

Plain-language summary: when the rules could not decide because facts are missing (the evaluation names them), a
person has to get them - usually by asking the client - within the days the process pack sets. This step opens that
person's task with the missing facts and its deadline, and waits. The person enters the facts in the field check (it
is reopened and frozen again), the rules are evaluated again, and once nothing is missing the task is withdrawn and the
case goes on. If the deadline passes, or the person says the facts will not come, the case closes with the outcome the
pack names. Nothing is missing at all: the step is done at once, with no task. (A deadline here is this step's own: the
owner's decision of 2026-10-26 on the D plan; the follow-up of a reply keeps none.)

- `CAPABILITY` (`missing_info@1`): params `from_step` (a rule evaluation), `days` (the deadline), `closes` (the case's
  outcome when the facts do not come); result: whether they were asked for and what is missing (nothing, once done).
- `will_not_come(case_id, step, actor, note)`: the person says the facts will not come (the step's action).

Layer: application; it uses the process core's human tasks, timers and events.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from jav.app import capabilities, human_tasks
from jav.core import identity, store
from jav.core.process import kinds, tasks
from jav.core.user_messages import explained

__all__ = ["CAPABILITY", "TASK", "MissingInfo", "MissingInfoError", "MissingResult", "register", "will_not_come"]

TASK = "missing_info"
WILL_NOT_COME = "will_not_come"
POLL_S = 5.0
DAY_S = 86400.0


class MissingInfoError(ValueError):
    """The step does not wait for missing facts."""


class _Evaluated(capabilities.Result):
    """What the step expects of the evaluation it reads: its version and the facts it missed."""

    version: int
    missing: list[dict[str, str]]


class MissingInfo(BaseModel):
    """The evaluation whose missing facts are asked for, the days they may take, and the case's outcome without them."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    from_step: str = capabilities.step_ref(min_length=1, of="rule_evaluation", expects=_Evaluated)
    days: float = Field(gt=0, le=365, title="Days to supply the missing facts")
    closes: str = Field(pattern=r"^[a-z][a-z0-9_]*$", title="The case's outcome when they do not come")


class MissingResult(capabilities.Result):
    """Whether the facts were asked for, and what is missing (nothing, once the step is done)."""

    requested: bool
    missing: list[dict[str, Any]]


def _task_id(case_id: str, step: str) -> str:
    return tasks.task_id(TASK, f"{case_id}:{step}")


def _run(ctx: Any, params: MissingInfo) -> kinds.StepOutcome:
    evaluated = capabilities.read_result(ctx, params, "from_step")
    missing = list(evaluated["missing"])
    tid = _task_id(ctx.case_id, ctx.step.id)
    task = tasks.get(tid)
    if task is not None and (task.status == tasks.EXPIRED
                             or task.status == tasks.DECIDED and (task.outcome or {}).get("answer") == WILL_NOT_COME):
        return kinds.Close(params.closes)
    if not missing:
        if task is not None and task.status == tasks.OPEN:
            with ctx.transaction() as c:
                tasks.withdraw_in(c, tid, ctx.actor, note="the missing facts arrived", notify=False)
        return kinds.Done({"requested": task is not None, "missing": [], "evaluation_version": int(evaluated["version"])})
    if task is None or task.status != tasks.OPEN:
        with ctx.transaction() as c:
            tasks.open_in(c, TASK, f"{ctx.case_id}:{ctx.step.id}", ctx.actor, case_id=ctx.case_id, step_id=ctx.step.id,
                          assignee=human_tasks.assignee_for(c, ctx.case_id, None),
                          due_at=time.time() + params.days * DAY_S,
                          detail={"missing": missing, "evaluation_version": int(evaluated["version"])})
    return ctx.wait(tasks.EVENT, timer=("check", time.time() + POLL_S))  # the task's closing, or the facts arriving


def _waits(case_id: str, step_id: str) -> bool:
    task = tasks.get(_task_id(case_id, step_id))
    return task is not None and task.status == tasks.OPEN


def will_not_come(case_id: str, step_id: str, actor: identity.Who, note: str | None = None) -> None:
    """The person says the missing facts will not come: the task is decided so, and the case closes with the pack's
    outcome at its next turn. A reason is required."""
    if not _waits(case_id, step_id):
        raise explained(MissingInfoError, "the step {{step}} does not wait for missing facts", step=step_id)
    if not (note or "").strip():
        raise explained(MissingInfoError, "saying the facts will not come needs a reason")
    with store.connect() as c:
        store.begin_immediate(c)
        tasks.decide_in(c, _task_id(case_id, step_id), identity.who(actor), outcome={"answer": WILL_NOT_COME}, note=note)


CAPABILITY = capabilities.Capability(
    name="missing_info", version=1, module=__name__, run=_run, kind="human", params=MissingInfo, state="step",
    output=MissingResult, events=(tasks.EVENT,),
    summary="Waits for the facts the rules miss with a person's task that expires; without them the case closes.",
    actions=(capabilities.Action(WILL_NOT_COME, "The facts will not come", _waits,
                                 lambda case_id, step_id, actor, note: will_not_come(case_id, step_id, actor, note)),))


def register() -> None:
    capabilities.register(CAPABILITY)


tasks.register_kind(tasks.TaskKind(TASK, __name__))
