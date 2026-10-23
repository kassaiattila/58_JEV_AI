"""218: a wait that ends while its step is still running. A step names its wait and returns WAIT; before the engine
records the outcome, a person ends the wait directly (as when settling an uncertain handover, T01). The step then runs
again, as after any ended wait; it does not fail with "waited without naming what for". A step that returns WAIT
without ever naming a wait still fails. Seen once under load in the full test run (T01, 2026-10-23). Synthetic case,
one worker turn at a time in the test's process."""

from __future__ import annotations

from jav.core.process import actor as actors
from jav.core.process import cases, engine, kinds
from jav.core.process.definition import ProcessDef, StepDef

ME = actors.person("Tester")
RUNS: list[str] = []


def _waits_then_is_settled(ctx: engine.StepContext) -> kinds.StepOutcome:
    RUNS.append(ctx.case_id)
    if len(RUNS) > 1:
        return kinds.DONE
    outcome = ctx.wait("settlement")
    with cases.transaction() as c:  # the person settles before the engine records the WAIT
        cases.end_wait(c, ctx.case_id, ctx.step.id, ME, "settled by a person")
    return outcome


kinds.register(kinds.StepKind("waits_then_is_settled_218", __name__, _waits_then_is_settled))
kinds.register(kinds.StepKind("waits_for_nothing_218", __name__, lambda ctx: kinds.WAIT))


def _case(case_id: str, kind: str) -> None:
    cases.start(case_id, ProcessDef(id="race_218", version="1", title="A synthetic race",
                                    steps=(StepDef(id="s", kind=kind),)), {}, ME)
    list(engine.iterate_until_idle())


def test_a_wait_ended_while_its_step_ran_runs_the_step_again() -> None:
    RUNS.clear()
    _case("race-1", "waits_then_is_settled_218")
    step = cases.view("race-1")["steps"]["s"]
    assert step["state"] == "done" and step["note"] is None
    assert RUNS == ["race-1", "race-1"]


def test_a_step_that_waits_without_naming_a_wait_still_fails() -> None:
    _case("race-2", "waits_for_nothing_218")
    assert cases.view("race-2")["steps"]["s"]["note"] == "the step waited without naming what for"
