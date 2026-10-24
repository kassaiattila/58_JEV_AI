"""A case adopted from a state reached outside the core, and a whole case put on hold (214, plan G-process-core P1b-2).

Plain-language summary: work that already ran before the process core existed (today's workflows) moves onto it
without starting again: the case is adopted with each step in the state the work had reached, a step that waits keeps
its wait and its timer, and from there the core moves it on as any other case. A case can also be put on hold as a
whole (a person put the work aside): nothing in it moves until it is resumed, and the events sent meanwhile wait for
it. Invented processes, a temporary store, no AI call.
"""

from __future__ import annotations

import time

import pytest

from jav.core import identity as actors
from jav.core.process import cases, engine, kinds
from jav.core.process.cases import Adopted
from jav.core.process.definition import ProcessDef, StepDef

ME = actors.person("Tester")
MOVER = actors.machine("adoption", on_behalf_of=ME)
OWNER = __name__
RAN: list[str] = []


def _note(ctx: engine.StepContext) -> kinds.StepOutcome:
    RAN.append(ctx.step.id)
    return kinds.Done({"step": ctx.step.id})


def _approval(ctx: engine.StepContext) -> kinds.StepOutcome:
    return kinds.DONE if ctx.row()["result"] else ctx.wait("approval")


def _approval_event(ctx: engine.StepContext, c, event: cases.Event) -> str:
    cases.set_result(c, ctx.case_id, ctx.step.id, {"approved_by": event.sent_by.id})
    return kinds.APPLIED


kinds.register(kinds.StepKind("adopt_note", OWNER, _note))
kinds.register(kinds.StepKind("adopt_approval", OWNER, _approval, events=("approval",), on_event=_approval_event))

FLOW = ProcessDef(id="invented_adoption", version="1", title="An invented process adopted midway", steps=(
    StepDef(id="intake", kind="adopt_note"), StepDef(id="approve", kind="adopt_approval"),
    StepDef(id="price", kind="adopt_note", after=("intake", "approve")),
    StepDef(id="send", kind="adopt_note", gates=("price",))))


@pytest.fixture(autouse=True)
def _fresh() -> None:
    RAN.clear()


def turns() -> list[str]:
    return list(engine.iterate_until_idle())


def states(case_id: str) -> dict[str, str]:
    return {sid: s["state"] for sid, s in cases.view(case_id)["steps"].items()}


def adopt(case_id: str, steps: dict[str, Adopted], *, definition: ProcessDef = FLOW, data: dict | None = None) -> str:
    with cases.transaction() as c:
        return cases.adopt(c, case_id, definition, data or {"n": 1}, ME, MOVER, steps)


# --- adoption ---------------------------------------------------------------------------------------------------------


def test_an_adopted_case_keeps_the_state_it_was_given_and_moves_on_from_there() -> None:
    later = time.time() + 3600
    assert adopt("c1", {"intake": Adopted(cases.DONE, result={"from": "before"}),
                        "approve": Adopted(cases.RUNNING, waiting_for="approval", timer=("check", later))}) == "adopted"
    view = engine.state("c1")
    assert states("c1") == {"intake": "done", "approve": "running", "price": "waiting", "send": "waiting"}
    assert view["steps"]["intake"]["result_version"] == 1 and view["steps"]["intake"]["result"] == {"from": "before"}
    assert view["steps"]["approve"]["waiting_for"] == "approval"
    assert [(t["step_id"], t["name"], t["status"]) for t in view["timers"]] == [("approve", "check", "armed")]
    [adopted] = view["history"]
    assert adopted["kind"] == "adopted" and adopted["actor"] == "machine:adoption"
    assert adopted["detail"]["steps"] == {"intake": "done", "approve": "running:approval", "price": "waiting",
                                          "send": "waiting"}
    assert cases.get("c1")["started_by"] == ME.as_json()  # the case is the maker's, the adoption the machine's
    turns()
    assert RAN == []  # nothing that was done runs again, and the approval still waits
    cases.send_event("c1", "ok", "approval", {}, ME)
    turns()
    assert RAN == ["price", "send"] and cases.get("c1")["outcome"] == "done"
    assert engine.state("c1")["timers"][0]["status"] == "cancelled"  # the event won; the check timer is gone


def test_an_adoption_counts_as_the_start_and_a_case_already_there_keeps_its_own_state() -> None:
    adopt("c1", {"intake": Adopted(cases.DONE)})
    assert cases.start("c1", FLOW, {"n": 1}, ME) == "exists"  # the same start: the adopted case
    assert adopt("c1", {"intake": Adopted(cases.FAILED, note="ignored")}) == "exists"
    assert states("c1")["intake"] == "done"  # once adopted, the core's state counts
    with pytest.raises(cases.CaseConflict):
        adopt("c1", {}, data={"n": 2})
    cases.start("c2", FLOW, {"n": 1}, ME)
    assert adopt("c2", {}) == "exists"


def test_the_ready_steps_are_promoted_and_a_case_whose_steps_are_all_done_is_closed() -> None:
    adopt("c1", {"intake": Adopted(cases.DONE), "approve": Adopted(cases.DONE)})
    assert states("c1")["price"] == "ready"  # its order is done: it runs at the next turn
    adopt("c2", {sid: Adopted(cases.DONE) for sid in ("intake", "approve", "price", "send")})
    assert cases.get("c2")["status"] == "closed" and cases.get("c2")["outcome"] == "done"
    assert [h["kind"] for h in cases.view("c2")["history"]] == ["adopted", "closed"]


@pytest.mark.parametrize(("steps", "message"), [
    ({"nope": Adopted(cases.DONE)}, "no step"),
    ({"intake": Adopted("paused")}, "not a step state"),
    ({"intake": Adopted(cases.WAITING, waiting_for="approval")}, "only a running step waits"),
    ({"intake": Adopted(cases.DONE, timer=("check", 0.0))}, "only a running step waits"),
])
def test_an_outside_state_the_core_cannot_take_is_refused_and_nothing_is_written(steps, message) -> None:
    with pytest.raises(cases.AdoptionError, match=message):
        adopt("c1", steps)
    with pytest.raises(cases.UnknownCase):
        cases.get("c1")


# --- holding a whole case ----------------------------------------------------------------------------------------------


def test_a_held_case_does_not_move_until_it_is_resumed_and_its_events_wait_for_it() -> None:
    cases.start("c1", FLOW, {}, ME)
    with cases.transaction() as c:
        assert cases.hold(c, "c1", "archived", ME)
        assert not cases.hold(c, "c1", "archived", ME)  # it waits already
    assert engine.claim() is None and turns() == [] and RAN == []
    assert cases.send_event("c1", "ok", "approval", {}, ME) == "accepted"
    assert cases.view("c1")["events"]["ok"]["status"] == "pending"
    with cases.transaction() as c:
        assert not cases.resume(c, "c1", "something else", ME)
        assert cases.resume(c, "c1", "archived", ME)
    turns()
    view = cases.view("c1")
    assert view["outcome"] == "done" and view["events"]["ok"]["status"] == "applied"
    held = [h for h in view["history"] if h["kind"] in ("held", "resumed")]
    assert [(h["kind"], h["detail"], h["actor"]) for h in held] == [("held", {"for": "archived"}, "local:Tester"),
                                                                    ("resumed", {"for": "archived"}, "local:Tester")]
    with cases.transaction() as c:
        assert not cases.hold(c, "c1", "archived", ME)  # a closed case is not held


def test_a_hold_never_stands_in_for_the_migration_wait() -> None:
    gone = ProcessDef(id="invented_gone", version="1", title="A step kind the code lacks",
                      steps=(StepDef(id="a", kind="removed_in_v2"),))
    cases.start("c1", gone, {}, ME)
    turns()
    with cases.transaction() as c:
        assert not cases.hold(c, "c1", "archived", ME)
        assert not cases.resume(c, "c1", "archived", ME)
        with pytest.raises(ValueError, match="migration"):
            cases.resume(c, "c1", cases.MIGRATION, ME)
        with pytest.raises(ValueError, match="migration"):
            cases.hold(c, "c2", cases.MIGRATION, ME)
    assert cases.get("c1")["waiting_for"] == cases.MIGRATION
