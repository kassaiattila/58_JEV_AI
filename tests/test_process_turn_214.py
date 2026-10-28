"""One case's turn, a wake, and a person's actions inside the caller's transaction (214, plan G-process-core P1b-3).

Plain-language summary: a caller can move one named case on now (its turn), under the same claim as a worker's; a
case a live process or another thread of this one holds is left alone. A wake asks the case to look again now: the
retry timers of its waiting steps fire at once, a deadline only when it is due. A person's overrides (the order, a
retry, a reopened step) can be written in the caller's own transaction; reopening a step of a case that was closed as
done opens the case again. Invented processes, a temporary store, no AI call.
"""

from __future__ import annotations

import threading
import time

import pytest

from jav.core import identity as actors
from jav.core.process import cases, engine, kinds
from jav.core.process.definition import ProcessDef, StepDef

ME = actors.person("Tester")
OWNER = __name__
CHECKS: list[str] = []


def _polled(ctx: engine.StepContext) -> kinds.StepOutcome:
    """Waits for a check until its case's data says the outside work is done."""
    CHECKS.append(ctx.case_id)
    if ctx.data.get("done") or len(CHECKS) > 2:
        return kinds.DONE
    return ctx.wait("check", timer=("check", time.time() + 3600))


def _deadline(ctx: engine.StepContext) -> kinds.StepOutcome:
    return ctx.wait("document", timer=("deadline", time.time() + 3600))


def _expire(ctx: engine.StepContext, c, timer) -> str:
    cases.close(c, ctx.case_id, "expired", ctx.actor)
    return "expired"


def _note(ctx: engine.StepContext) -> kinds.StepOutcome:
    return kinds.DONE


kinds.register(kinds.StepKind("turn_polled", OWNER, _polled))
kinds.register(kinds.StepKind("turn_deadline", OWNER, _deadline, events=("document",), on_timer=_expire))
kinds.register(kinds.StepKind("turn_note", OWNER, _note))


def define(*steps: StepDef, name: str = "invented_turn") -> ProcessDef:
    return ProcessDef(id=name, version="1", title="An invented process", steps=steps)


@pytest.fixture(autouse=True)
def _fresh() -> None:
    CHECKS.clear()


def test_a_turn_moves_the_named_case_only() -> None:
    flow = define(StepDef(id="a", kind="turn_note"), StepDef(id="b", kind="turn_note", after=("a",)))
    cases.start("c1", flow, {}, ME)
    cases.start("c2", flow, {}, ME)
    assert engine.turn("c1")
    assert cases.get("c1")["outcome"] == "done" and cases.get("c2")["status"] == "open"
    assert engine.turn("c1")  # a closed case's turn does nothing, and says it had the claim
    assert engine.state("c1")["claimed_by"] is None


def test_a_case_another_thread_holds_is_left_alone() -> None:
    cases.start("c1", define(StepDef(id="a", kind="turn_note")), {}, ME)
    holding, release = threading.Event(), threading.Event()

    def hold() -> None:
        assert engine.claim_case("c1")
        holding.set()
        release.wait(10)
        engine.release("c1")

    other = threading.Thread(target=hold)
    other.start()
    try:
        assert holding.wait(10)
        assert not engine.claim_case("c1") and not engine.turn("c1") and engine.claim() is None
        assert cases.get("c1")["status"] == "open"
    finally:
        release.set()
        other.join(10)
    assert engine.turn("c1") and cases.get("c1")["outcome"] == "done"


def test_a_wake_fires_a_retry_timer_at_once_but_a_deadline_only_when_due() -> None:
    cases.start("polled", define(StepDef(id="a", kind="turn_polled")), {}, ME)
    cases.start("deadline", define(StepDef(id="a", kind="turn_deadline")), {}, ME)
    list(engine.iterate_until_idle())
    assert CHECKS == ["polled"] and engine.claim() is None  # both wait an hour
    assert engine.turn("polled", wake=True)
    assert CHECKS == ["polled", "polled"]
    assert cases.view("polled")["steps"]["a"]["waiting_for"] == "check"  # it waits again, its timer moved on
    assert [h["kind"] for h in cases.view("polled")["history"]].count("timer_fired") == 0  # a retry leaves no row
    assert engine.turn("deadline", wake=True)
    assert cases.get("deadline")["status"] == "open" and engine.state("deadline")["timers"][0]["status"] == "armed"


def test_the_due_cases_are_those_of_every_definition() -> None:
    cases.start("w1", define(StepDef(id="a", kind="turn_note"), name="family_one"), {}, ME)
    cases.start("w2", define(StepDef(id="a", kind="turn_note"), name="family_two"), {}, ME)
    assert engine.due_cases() == ["w1", "w2"]
    assert engine.turn_due() == 2  # 229: the round turns them all
    assert engine.due_cases() == [] and cases.get("w1")["outcome"] == cases.get("w2")["outcome"] == "done"


def test_whether_one_case_has_something_to_do_now() -> None:
    """U-A8 (the walkthrough of 2026-10-28): whether the worker has something to do for one case now - a ready step, an
    event a waiting step takes, a due timer - so its page asks again until the worker's next round moved it."""
    cases.start("w1", define(StepDef(id="a", kind="turn_note")), {}, ME)
    cases.start("deadline", define(StepDef(id="a", kind="turn_deadline")), {}, ME)
    assert engine.is_due("w1") and engine.is_due("deadline")  # ready steps
    list(engine.iterate_until_idle())
    assert not engine.is_due("w1")  # done and closed
    assert not engine.is_due("deadline")  # it waits an hour for a document
    assert engine.is_due("deadline", now=time.time() + 7200)  # its timer is due then
    cases.send_event("deadline", "doc-1", "document", {}, ME)
    assert engine.is_due("deadline")  # the event its step takes
    assert not engine.is_due("nowhere")


def test_a_persons_overrides_can_share_the_callers_transaction() -> None:
    flow = define(StepDef(id="a", kind="turn_polled"), StepDef(id="b", kind="turn_note", after=("a",)))
    cases.start("c1", flow, {}, ME)
    engine.turn("c1")
    with pytest.raises(RuntimeError), cases.transaction() as c:
        cases.override_order_in(c, "c1", "b", ME, reason="urgent")
        raise RuntimeError("the caller's own write failed")
    assert cases.view("c1")["steps"]["b"]["state"] == "waiting"  # undone with the caller's write
    with cases.transaction() as c:
        cases.override_order_in(c, "c1", "b", ME, reason="urgent")
    assert cases.view("c1")["steps"]["b"]["state"] == "ready"


def test_reopening_a_step_of_a_case_closed_as_done_opens_the_case_again() -> None:
    flow = define(StepDef(id="a", kind="turn_note"), StepDef(id="b", kind="turn_note", after=("a",)))
    cases.start("c1", flow, {}, ME)
    engine.turn("c1")
    assert cases.get("c1")["outcome"] == "done"
    with cases.transaction() as c:
        assert cases.reopen_in(c, "c1", "a", ME, reason="its package was deleted") == ["b"]
    view = cases.view("c1")
    assert (view["status"], view["outcome"]) == ("open", None)
    assert [h["kind"] for h in view["history"]][-3:] == ["case_reopened", "reopened", "stale"]
    engine.turn("c1")
    assert cases.get("c1")["outcome"] == "done"
    cases.start("c2", define(StepDef(id="a", kind="turn_note")), {}, ME)
    cases.cancel("c2", ME)
    with pytest.raises(cases.CaseClosed), cases.transaction() as c:
        cases.reopen_in(c, "c2", "a", ME, reason="a cancelled case stays closed")
