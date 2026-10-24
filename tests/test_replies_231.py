"""231 (plan stage A, A7d; DECISIONS 231): the general wait_reply capability.

After a case sent something it waits for the other side's reply: a person records that it arrived or that none is
needed. When the days the process pack sets pass without one, a follow-up task opens once, without a deadline (the
owner's decision of 2026-10-24: after 5 days for the IT quote); the person records the reply, or that they reminded the
other side, and then the case waits on with no further reminder. A person's actions are the capability's, each
available only while the step waits for it. Synthetic cases; no AI call.
"""

from __future__ import annotations

import time

import pytest

from jav.app import capabilities, replies
from jav.core import identity
from jav.core.process import cases, engine, tasks
from jav.core.process.definition import ProcessDef, StepDef

CLERK = identity.person("Clerk")
MACHINE = identity.machine("tests")
DAYS = 5


@pytest.fixture(autouse=True)
def registered() -> None:
    capabilities.of("wait_reply@1")  # the application's registrations


def _case(case_id: str) -> str:
    step = StepDef(id="follow", kind="cap.wait_reply.v1", params={"remind_after_days": DAYS})
    cases.start(case_id, ProcessDef(id="invented_reply", version="1", title="An invented reply", steps=(step,)), {},
                MACHINE)
    engine.turn(case_id)
    return case_id


def _step(case_id: str) -> dict:
    return engine.state(case_id)["steps"]["follow"]


def _follow_ups(case_id: str) -> list[dict]:
    return [t for t in engine.state(case_id)["tasks"] if t["task_id"].startswith(f"{replies.FOLLOW_UP_TASK}:")]


def _later(case_id: str, days: float) -> None:
    engine.turn(case_id, now=time.time() + days * replies.DAY_S)


def test_a_reply_before_the_reminder_finishes_the_step_without_a_follow_up() -> None:
    case_id = _case("case-reply-1")
    step = _step(case_id)
    assert step["state"] == "running" and step["waiting_for"] == replies.REPLY
    [timer] = engine.state(case_id)["timers"]
    assert timer["name"] == "remind" and timer["status"] == "armed"
    assert abs(timer["due_at"] - (step["result"]["since"] + DAYS * replies.DAY_S)) < 1
    replies.reply(case_id, "follow", replies.REPLIED, CLERK, "  they accept  ")
    engine.turn(case_id)
    result = _step(case_id)["result"]
    assert engine.state(case_id)["status"] == "closed"
    assert (result["reply"], result["by"], result["note"], result["reminded"]) == ("replied", "Clerk", "  they accept  ",
                                                                                   False)
    assert [t["status"] for t in engine.state(case_id)["timers"]] == ["cancelled"] and _follow_ups(case_id) == []


def test_after_the_days_a_follow_up_opens_once_without_a_deadline_and_records_the_reply() -> None:
    case_id = _case("case-reply-2")
    _later(case_id, DAYS - 1)
    assert _follow_ups(case_id) == []
    _later(case_id, DAYS + 0.01)
    [task] = _follow_ups(case_id)
    assert task["status"] == tasks.OPEN and task["due_at"] is None and task["assignee"] is None
    assert _step(case_id)["waiting_for"] == tasks.EVENT
    assert {a.name for a in capabilities.of("wait_reply@1").actions if a.available(case_id, "follow")} == {
        "replied", "not_needed", "keep_waiting"}
    replies.reply(case_id, "follow", replies.NOT_NEEDED, CLERK)
    engine.turn(case_id)
    result = _step(case_id)["result"]
    assert _step(case_id)["state"] == "done" and (result["reply"], result["by"], result["reminded"]) == (
        "not_needed", "Clerk", True)


def test_a_reminded_case_waits_on_without_another_follow_up() -> None:
    case_id = _case("case-reply-3")
    _later(case_id, DAYS + 0.01)
    replies.keep_waiting(case_id, "follow", CLERK, "phoned them")
    engine.turn(case_id)
    assert _step(case_id)["waiting_for"] == replies.REPLY and _step(case_id)["state"] == "running"
    _later(case_id, 3 * DAYS)
    assert [t["status"] for t in _follow_ups(case_id)] == [tasks.DECIDED]  # at most one per step
    assert {a.name for a in capabilities.of("wait_reply@1").actions if a.available(case_id, "follow")} == {
        "replied", "not_needed"}
    with pytest.raises(replies.ReplyError):
        replies.keep_waiting(case_id, "follow", CLERK)
    replies.reply(case_id, "follow", replies.REPLIED, CLERK)
    engine.turn(case_id)
    assert _step(case_id)["state"] == "done" and _step(case_id)["result"]["reminded"] is True


def test_a_reply_is_refused_where_the_step_does_not_wait_for_one() -> None:
    case_id = _case("case-reply-4")
    with pytest.raises(replies.ReplyError):
        replies.reply(case_id, "follow", "maybe", CLERK)
    cases.send_event(case_id, "odd", replies.REPLY, {"reply": "maybe"}, CLERK, step_id="follow")
    engine.turn(case_id)
    assert _step(case_id)["state"] == "running"  # the unknown answer was refused
    replies.reply(case_id, "follow", replies.REPLIED, CLERK)
    engine.turn(case_id)
    with pytest.raises(replies.ReplyError):
        replies.reply(case_id, "follow", replies.REPLIED, CLERK)
    assert {a.name for a in capabilities.of("wait_reply@1").actions if a.available(case_id, "follow")} == set()
