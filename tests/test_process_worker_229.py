"""The worker moves every case of the process core, not only the workflows' (229, plan structure stage 1, SZ1a).

Plain-language summary: a case of any process definition that has something to do now (a ready step, an event its
waiting step takes, a due timer) is moved on by the worker's round, as a workflow's case is; before, the worker looked
only at the workflows' cases, so a case of another kind (the quote from intake to sending, planned next) would never
have started. Invented processes, a temporary store, no AI call.
"""

from __future__ import annotations

import time

from jav.core import identity as actors
from jav.core.process import cases, engine, kinds
from jav.core.process.definition import ProcessDef, StepDef
from jav.runtime import worker

ME = actors.person("Tester")
OWNER = __name__
RUNS: list[str] = []


def _note(ctx: engine.StepContext) -> kinds.StepOutcome:
    RUNS.append(ctx.step.id)
    return kinds.DONE


def _answer(ctx: engine.StepContext) -> kinds.StepOutcome:
    if ctx.row()["result"] is not None:
        return kinds.Done(ctx.row()["result"])
    return ctx.wait("answer")


def _take_answer(ctx: engine.StepContext, c, event: cases.Event) -> str:
    cases.set_result(c, ctx.case_id, ctx.step.id, event.payload)
    return kinds.APPLIED


def _retry(ctx: engine.StepContext) -> kinds.StepOutcome:
    RUNS.append(ctx.step.id)
    if len(RUNS) > 1:
        return kinds.DONE
    return ctx.wait("outside", timer=("retry", time.time() - 1))  # due at once


kinds.register(kinds.StepKind("worker229_note", OWNER, _note))
kinds.register(kinds.StepKind("worker229_answer", OWNER, _answer, events=("answer",), on_event=_take_answer))
kinds.register(kinds.StepKind("worker229_retry", OWNER, _retry))


def define(*steps: StepDef) -> ProcessDef:
    return ProcessDef(id="invented_quote", version="1", title="An invented case that is not a workflow", steps=steps)


def setup_function() -> None:
    RUNS.clear()


def test_the_worker_moves_a_case_that_is_not_a_workflow() -> None:
    cases.start("q1", define(StepDef(id="intake", kind="worker229_note"),
                             StepDef(id="close", kind="worker229_note", after=("intake",))), {}, ME)
    worker.run_worker(once=True)
    assert RUNS == ["intake", "close"]
    assert cases.get("q1")["outcome"] == "done"


def test_the_worker_hands_an_event_to_a_waiting_step_of_any_case() -> None:
    cases.start("q2", define(StepDef(id="ask", kind="worker229_answer")), {}, ME)
    worker.run_worker(once=True)
    assert cases.get("q2")["status"] == "open"
    assert cases.send_event("q2", "ev-1", "answer", {"price": "12"}, ME) == "accepted"
    worker.run_worker(once=True)
    assert cases.get("q2")["outcome"] == "done"
    assert engine.state("q2")["steps"]["ask"]["result"] == {"price": "12"}


def test_the_worker_fires_a_due_timer_of_any_case() -> None:
    cases.start("q3", define(StepDef(id="fetch", kind="worker229_retry")), {}, ME)
    worker.run_worker(once=True)
    assert RUNS == ["fetch", "fetch"] and cases.get("q3")["outcome"] == "done"
