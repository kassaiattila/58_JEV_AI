"""The process core's human task (215, plan G-process-core P2a; rules 3, 4, 5, 7, 8 and 9 of plan 212 P0).

Plain-language summary: a human task opens once under what it is about, and a closed one opens again in a new round; a
person decides it once, with a reason where its kind asks for one, and on the result version it was opened on; its
assignee and deadline change with their history; the authorisation check is asked before a person acts. In a case the
task is a running step's wait: its decision moves the step on at the case's next turn, its deadline expires it (a wake
never does so early), and closing the case withdraws it. A decision and its deadline never both win. Synthetic data,
no AI call; one worker turn at a time in the test's process.
"""

from __future__ import annotations

import time

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from jav.core.process import actor as actors
from jav.core.process import cases, engine, hooks, kinds, tasks
from jav.core.process.definition import ProcessDef, StepDef

CLERK = actors.person("Clerk")
LEAD = actors.person("Team Lead")
MACHINE = actors.machine("tests")
OWNER = __name__

for _task_kind in (tasks.TaskKind("check", OWNER), tasks.TaskKind("reopen_check", OWNER, reason_required=True),
                   tasks.TaskKind("sign_off", OWNER)):
    tasks.register_kind(_task_kind)


def _prepare(ctx: engine.StepContext) -> kinds.StepOutcome:
    return kinds.Done({"prepared": True})


def _sign_off(ctx: engine.StepContext) -> kinds.StepOutcome:
    """Asks the clerk to sign off once; done on an approval, closed with the task's end otherwise."""
    task = tasks.get(tasks.task_id("sign_off", ctx.case_id))
    if task is None:
        with ctx.transaction() as c:
            tasks.open_in(c, "sign_off", ctx.case_id, ctx.actor, assignee=CLERK.id, case_id=ctx.case_id,
                          step_id=ctx.step.id, due_at=ctx.data.get("due_at"), result_ref="draft-1")
        return kinds.WAIT
    if task.status == tasks.OPEN:
        return kinds.WAIT
    if task.status == tasks.DECIDED:
        return kinds.Done(task.outcome) if task.outcome.get("approve") else kinds.Close("rejected")
    return kinds.Close(task.status)


for _kind in (kinds.StepKind("preparing", OWNER, _prepare),
              kinds.StepKind("signing", OWNER, _sign_off, events=(tasks.EVENT,))):
    kinds.register(_kind)

SIGNED = ProcessDef(id="invented_sign_off", version="1", title="An invented sign-off", steps=(
    StepDef(id="prepare", kind="preparing"), StepDef(id="sign_off", kind="signing", gates=("prepare",))))


def turns(now: float | None = None) -> None:
    list(engine.iterate_until_idle(now=now))


# --- the task on its own ------------------------------------------------------------------------------------------------


def test_a_task_opens_once_under_its_subject_and_a_closed_one_opens_again_in_a_new_round() -> None:
    with cases.transaction() as c:
        assert tasks.open_in(c, "check", "doc-1", MACHINE, assignee=CLERK.id) == "opened"
        assert tasks.open_in(c, "check", "doc-1", MACHINE, assignee=LEAD.id) == "exists"
    tid = tasks.task_id("check", "doc-1")
    task = tasks.get(tid)
    assert (task.status, task.assignee, task.round, task.case_id) == ("open", CLERK.id, 1, None)
    assert tasks.decide(tid, CLERK, outcome={"ok": True}) == 1
    with cases.transaction() as c:
        assert tasks.open_in(c, "check", "doc-1", MACHINE, assignee=LEAD.id) == "reopened"
    task = tasks.get(tid)
    assert (task.status, task.assignee, task.round, task.outcome, task.closed_by) == ("open", LEAD.id, 2, None, None)
    assert [(h["round"], h["kind"], h["actor"]) for h in tasks.history(tid)] == [
        (1, "opened", MACHINE.id), (1, "decided", CLERK.id), (2, "reopened", MACHINE.id)]


def test_a_decision_is_made_once_with_its_reason_where_the_kind_asks_for_one() -> None:
    with cases.transaction() as c:
        tasks.open_in(c, "reopen_check", "v-1", MACHINE)
    tid = tasks.task_id("reopen_check", "v-1")
    with pytest.raises(tasks.ReasonRequired):
        tasks.decide(tid, CLERK, note="  ")
    assert tasks.get(tid).status == "open"
    tasks.decide(tid, CLERK, note="the bank sent a corrected statement")
    with pytest.raises(tasks.TaskClosed):
        tasks.decide(tid, LEAD, note="again")
    with cases.transaction() as c:
        assert tasks.withdraw_in(c, tid, MACHINE) is False
    task = tasks.get(tid)
    assert (task.status, task.closed_by.id, task.note) == ("decided", CLERK.id, "the bank sent a corrected statement")
    with pytest.raises(tasks.UnknownTask):
        tasks.decide("check:nothing", CLERK)
    with cases.transaction() as c, pytest.raises(tasks.UnknownTaskKind):
        tasks.open_in(c, "no_such_kind", "x", MACHINE)


def test_the_assignee_and_the_deadline_change_with_their_history() -> None:
    with cases.transaction() as c:
        tasks.open_in(c, "check", "a", MACHINE, assignee=CLERK.id)
        tasks.open_in(c, "check", "b", MACHINE)  # anyone's
        assert tasks.assign_in(c, "check:b", LEAD.id, CLERK) is True
        assert tasks.assign_in(c, "check:b", LEAD.id, CLERK) is False
        tasks.set_due_in(c, "check:a", 1_900_000_000.0, LEAD)
        with pytest.raises(ValueError, match="namespace"):
            tasks.open_in(c, "check", "c", MACHINE, assignee="Clerk")
    assert [t.subject for t in tasks.open_tasks(LEAD.id)] == ["b"]
    assert [t.subject for t in tasks.open_tasks()] == ["a", "b"]
    assert tasks.get("check:a").due_at == 1_900_000_000.0
    assert [h["kind"] for h in tasks.history("check:b")] == ["opened", "assigned"]
    assert tasks.history("check:b")[1]["detail"] == {"from": None, "to": LEAD.id}
    assert tasks.history("check:a")[1]["detail"] == {"from": None, "to": 1_900_000_000.0}


def test_a_decision_on_another_result_version_is_refused() -> None:
    with cases.transaction() as c:
        tasks.open_in(c, "check", "run-1", MACHINE, result_ref="review-7")
    with pytest.raises(tasks.StaleResult):
        tasks.decide("check:run-1", CLERK, result_ref="review-8")
    assert tasks.get("check:run-1").status == "open"
    tasks.decide("check:run-1", CLERK, result_ref="review-7")
    assert tasks.history("check:run-1")[-1]["detail"]["result_ref"] == "review-7"


def test_the_authorisation_check_is_asked_before_a_person_acts() -> None:
    asked: list[tuple[str, str]] = []

    def rule(actor: actors.Actor, action: str, case_id: str | None) -> bool:
        asked.append((actor.id, action))
        return action != "decide_task"

    hooks.set_authorizer(rule)
    try:
        with cases.transaction() as c:
            tasks.open_in(c, "check", "doc-2", MACHINE)
        with pytest.raises(hooks.NotAuthorised):
            tasks.decide("check:doc-2", CLERK)
    finally:
        hooks.set_authorizer(None)
    assert tasks.get("check:doc-2").status == "open"
    assert (MACHINE.id, "open_task") in asked and (CLERK.id, "decide_task") in asked


# --- the task in a case ---------------------------------------------------------------------------------------------------


def test_a_task_in_a_case_is_its_steps_wait_and_its_decision_moves_the_step_on() -> None:
    cases.start("s1", SIGNED, {}, CLERK)
    turns()
    view = engine.state("s1")
    assert view["steps"]["sign_off"]["state"] == "running" and view["steps"]["sign_off"]["waiting_for"] == tasks.EVENT
    assert [(t["task_id"], t["status"], t["assignee"]) for t in view["tasks"]] == [("sign_off:s1", "open", CLERK.id)]
    tasks.decide("sign_off:s1", CLERK, outcome={"approve": True}, result_ref="draft-1")
    assert engine.state("s1")["events"] == {"sign_off:s1#1": {"kind": tasks.EVENT, "status": "pending", "conflicts": 0}}
    turns()
    view = engine.state("s1")
    assert view["outcome"] == "done" and view["steps"]["sign_off"]["result"] == {"approve": True}
    kinds_seen = [h["kind"] for h in view["history"]]
    assert kinds_seen.index("task_opened") < kinds_seen.index("task_decided") < kinds_seen.index("event_applied")


def test_a_task_in_a_case_needs_its_running_step_to_take_the_closing_event() -> None:
    cases.start("s2", SIGNED, {}, CLERK)
    with cases.transaction() as c, pytest.raises(cases.StepStateError, match="running step"):
        tasks.open_in(c, "check", "x", MACHINE, case_id="s2", step_id="sign_off")
    turns()
    with cases.transaction() as c, pytest.raises(cases.UnknownEvent):
        tasks.open_in(c, "check", "y", MACHINE, case_id="s2", step_id="sign_off", waits="document")
    with cases.transaction() as c, pytest.raises(ValueError, match="names its step"):
        tasks.open_in(c, "check", "z", MACHINE, case_id="s2")
    assert tasks.get("check:x") is None and tasks.get("check:y") is None


def test_the_deadline_expires_the_task_and_a_wake_does_not_expire_it_early() -> None:
    due = time.time() + 3600
    cases.start("s3", SIGNED, {"due_at": due}, CLERK)
    turns()
    assert engine.turn("s3", wake=True)
    assert tasks.get("sign_off:s3").status == "open"
    turns(now=due + 1)
    task, view = tasks.get("sign_off:s3"), engine.state("s3")
    assert task.status == "expired" and task.closed_by.kind == "machine"
    assert view["outcome"] == "expired"
    timer = next(t for t in view["timers"] if t["name"] == "task:sign_off:s3")
    assert (timer["status"], timer["effect"]) == ("fired", "expired")
    with pytest.raises(tasks.TaskClosed):
        tasks.decide("sign_off:s3", CLERK, outcome={"approve": True})


def test_closing_the_case_withdraws_its_open_task_without_an_event() -> None:
    cases.start("s4", SIGNED, {"due_at": time.time() + 3600}, CLERK)
    turns()
    cases.cancel("s4", LEAD)
    task, view = tasks.get("sign_off:s4"), engine.state("s4")
    assert (task.status, task.closed_by.id) == ("withdrawn", LEAD.id)
    assert all(t["status"] != "armed" for t in view["timers"]) and view["events"] == {}


def test_a_task_withdrawn_while_its_step_waits_wakes_the_step() -> None:
    cases.start("s5", SIGNED, {}, CLERK)
    turns()
    with cases.transaction() as c:
        assert tasks.withdraw_in(c, "sign_off:s5", MACHINE, note="the draft was deleted") is True
    turns()
    assert cases.get("s5")["outcome"] == "withdrawn"
    assert tasks.history("sign_off:s5")[-1]["detail"] == {"note": "the draft was deleted"}


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.permutations(["decide", "deadline", "turn", "repeat"]))
def test_a_decision_and_its_deadline_never_both_win(order: list[str]) -> None:
    case_id = f"race-{'-'.join(order)}"
    due = time.time() + 3600
    cases.start(case_id, SIGNED, {"due_at": due}, CLERK)
    turns()
    tid = tasks.task_id("sign_off", case_id)
    for action in order:
        if action in ("decide", "repeat"):
            try:
                tasks.decide(tid, CLERK, outcome={"approve": True})
            except tasks.TaskClosed:
                pass
        elif action == "deadline":
            turns(now=due + 1)
        else:
            turns()
    turns(now=due + 1)
    ends = [h["kind"] for h in tasks.history(tid) if h["kind"] in ("decided", "expired")]
    assert len(ends) == 1, tasks.history(tid)
    assert cases.get(case_id)["outcome"] == ("done" if ends == ["decided"] else "expired")
    deadline = next(t for t in engine.state(case_id)["timers"] if t["name"] == f"task:{tid}")
    assert (deadline["status"], deadline["effect"]) == (("cancelled", "task decided") if ends == ["decided"]
                                                        else ("fired", "expired"))
