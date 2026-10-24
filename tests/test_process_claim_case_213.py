"""A second invented case of another shape on the process core (213; the 205 review's third example).

Plain-language summary: an invented damage claim, so that the core is not shaped by the quote case alone. After the
intake three checks run side by side (each waits only for the intake; one of them failing does not hold the others);
the assessment waits for all three by gate. A missing document is waited for with a reminder that fires again and
again while the wait goes on, and a deadline that closes the claim; the document arriving cancels both in one
transaction. 215 (P2a): the assessed claim is signed off by a human task with a deadline; when the clerk lets it
expire, it goes to the team lead with a new deadline (escalation), and a second expiry closes the claim. Synthetic
data, no AI call; one worker turn at a time in the test's process.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from jav.core import identity as actors
from jav.core.process import cases, engine, kinds, tasks, timers
from jav.core.process.definition import ProcessDef, StepDef

ME = actors.person("Claims Clerk")
LEAD = actors.person("Claims Team Lead")
OWNER = __name__
RAN: list[str] = []
REMIND_S = 0.05


def _intake(ctx: engine.StepContext) -> kinds.StepOutcome:
    RAN.append(ctx.step.id)
    return kinds.Done({"policy": ctx.data["policy"]})


DOWN: set[str] = set()  # the checks whose register does not answer now


def _check(ctx: engine.StepContext) -> kinds.StepOutcome:
    RAN.append(ctx.step.id)
    if ctx.step.id in DOWN:
        return kinds.Fail(f"{ctx.step.id}: the register did not answer")
    return kinds.Done({"ok": True})


def _documents(ctx: engine.StepContext) -> kinds.StepOutcome:
    if ctx.row()["result"] is not None or not ctx.data["document_missing"]:
        return kinds.DONE
    with ctx.transaction() as c:
        cases.wait(c, ctx.case_id, ctx.step.id, "document", ctx.actor,
                   timer=("deadline", time.time() + float(ctx.data["deadline_s"])))
        timers.arm(c, ctx.case_id, ctx.step.id, "reminder", time.time() + REMIND_S)
    return kinds.WAIT


def _document_arrived(ctx: engine.StepContext, c: sqlite3.Connection, event: cases.Event) -> str:
    cases.set_result(c, ctx.case_id, ctx.step.id, {"document": event.payload["name"]})
    return kinds.APPLIED


def _documents_timer(ctx: engine.StepContext, c: sqlite3.Connection, timer: timers.Timer) -> str:
    if timer.name == "reminder":  # the claimant is reminded; the wait goes on
        cases.record(c, ctx.case_id, ctx.step.id, "reminder_sent", ctx.actor)
        timers.arm(c, ctx.case_id, ctx.step.id, "reminder", time.time() + REMIND_S)
        return "reminded"
    cases.close(c, ctx.case_id, "expired", ctx.actor)
    return "expired"


def _assess(ctx: engine.StepContext) -> kinds.StepOutcome:
    RAN.append(ctx.step.id)
    return kinds.Done({"checks": [ctx.result_of(s)[1] for s in ("policy_valid", "coverage", "fraud_score")]})


def _sign_off(ctx: engine.StepContext) -> kinds.StepOutcome:
    """The clerk signs the assessed claim off by its deadline; an expired sign-off goes to the team lead once, with
    twice the clerk's time."""
    task = tasks.get(tasks.task_id("claim_sign_off", ctx.case_id))
    if task is not None and task.status == tasks.OPEN:
        return kinds.WAIT
    if task is not None and task.status == tasks.DECIDED:
        return kinds.Done(task.outcome)
    if task is not None and (task.status != tasks.EXPIRED or task.round > 1):
        return kinds.Close(task.status)  # withdrawn, or the team lead let it expire too
    escalated = task is not None
    with ctx.transaction() as c:
        tasks.open_in(c, "claim_sign_off", ctx.case_id, ctx.actor, assignee=(LEAD if escalated else ME).id,
                      case_id=ctx.case_id, step_id=ctx.step.id,
                      due_at=time.time() + float(ctx.data["sign_off_s"]) * (2 if escalated else 1),
                      result_ref="assessment-1", detail={"escalated": escalated})
    return kinds.WAIT


for _kind in (
    kinds.StepKind("claim_intake", OWNER, _intake),
    kinds.StepKind("claim_check", OWNER, _check),
    kinds.StepKind("claim_documents", OWNER, _documents, events=("document",), on_event=_document_arrived,
                   on_timer=_documents_timer),
    kinds.StepKind("claim_assess", OWNER, _assess),
    kinds.StepKind("claim_sign_off", OWNER, _sign_off, events=(tasks.EVENT,)),
):
    kinds.register(_kind)
tasks.register_kind(tasks.TaskKind("claim_sign_off", OWNER))

_STEPS = (
    StepDef(id="intake", kind="claim_intake"),
    StepDef(id="policy_valid", kind="claim_check", gates=("intake",)),
    StepDef(id="coverage", kind="claim_check", gates=("intake",)),
    StepDef(id="fraud_score", kind="claim_check", gates=("intake",)),
    StepDef(id="documents", kind="claim_documents", gates=("intake",)),
    StepDef(id="assess", kind="claim_assess", gates=("policy_valid", "coverage", "fraud_score", "documents")),
)
CLAIM = ProcessDef(id="invented_claim", version="1", title="Invented damage claim", steps=_STEPS)
SIGNED_CLAIM = ProcessDef(id="invented_claim_signed", version="1", title="Invented damage claim with a sign-off",
                          steps=(*_STEPS, StepDef(id="sign_off", kind="claim_sign_off", gates=("assess",))))


def turns(now: float | None = None) -> None:
    list(engine.iterate_until_idle(now=now))


def claim(**changes: object) -> dict[str, object]:
    return {"policy": "P-001", "document_missing": True, "deadline_s": 60, **changes}


@pytest.fixture(autouse=True)
def _fresh() -> None:
    RAN.clear()
    DOWN.clear()


def test_the_parallel_checks_run_once_each_and_a_failed_one_holds_only_the_assessment() -> None:
    DOWN.add("coverage")
    cases.start("k1", CLAIM, claim(document_missing=False), ME)
    turns()
    view = cases.view("k1")
    assert RAN == ["intake", "policy_valid", "coverage", "fraud_score"]
    assert {s: v["state"] for s, v in view["steps"].items()} == {
        "intake": "done", "policy_valid": "done", "coverage": "failed", "fraud_score": "done", "documents": "done",
        "assess": "waiting"}
    assert view["steps"]["coverage"]["note"] == "coverage: the register did not answer"
    DOWN.clear()  # the register answers again; a person retries the check
    cases.retry("k1", "coverage", ME)
    RAN.clear()
    turns()
    assert RAN == ["coverage", "assess"] and cases.get("k1")["outcome"] == "done"


def test_the_reminder_repeats_while_the_document_is_awaited_and_the_document_ends_both_timers() -> None:
    cases.start("k2", CLAIM, claim(), ME)
    turns()
    for _ in range(3):  # the reminder fires again and again; the wait goes on
        time.sleep(REMIND_S * 2)
        turns()
    view = engine.state("k2")
    reminders = [h for h in view["history"] if h["kind"] == "reminder_sent"]
    assert len(reminders) >= 3 and view["steps"]["documents"]["waiting_for"] == "document"
    assert len([h for h in view["history"] if h["kind"] == "waiting"]) == 1
    assert cases.send_event("k2", "doc-1", "document", {"name": "police-report.pdf"}, ME) == "accepted"
    turns()
    view = engine.state("k2")
    assert view["outcome"] == "done" and RAN[-1] == "assess"
    assert {t["name"]: t["status"] for t in view["timers"]} == {"deadline": "cancelled", "reminder": "cancelled"}
    assert view["steps"]["assess"]["result"] == {"checks": [{"ok": True}] * 3}


def test_without_the_document_the_deadline_closes_the_claim_and_the_reminders_stop() -> None:
    cases.start("k3", CLAIM, claim(deadline_s=0.3), ME)
    turns()
    time.sleep(0.4)
    turns()
    view = engine.state("k3")
    assert view["outcome"] == "expired" and "assess" not in RAN
    assert {t["name"]: t["status"] for t in view["timers"]} == {"deadline": "fired", "reminder": "cancelled"}
    assert cases.send_event("k3", "doc-late", "document", {"name": "late.pdf"}, ME) == "accepted"
    assert cases.view("k3")["events"]["doc-late"]["status"] == "ignored"


def test_an_unsigned_claim_goes_to_the_team_lead_when_the_clerks_deadline_passes() -> None:
    cases.start("k4", SIGNED_CLAIM, claim(document_missing=False, sign_off_s=3600), ME)
    turns()
    tid = tasks.task_id("claim_sign_off", "k4")
    assert [t.assignee for t in tasks.open_tasks(ME.id)] == [ME.id] and tasks.get(tid).round == 1
    turns(now=time.time() + 3601)  # the clerk's deadline passes
    task = tasks.get(tid)
    assert (task.status, task.round, task.assignee, task.detail) == ("open", 2, LEAD.id, {"escalated": True})
    assert tasks.open_tasks(ME.id) == []
    tasks.decide(tid, LEAD, outcome={"pay": "1200.00"}, result_ref="assessment-1")
    turns()
    view = engine.state("k4")
    assert view["outcome"] == "done" and view["steps"]["sign_off"]["result"] == {"pay": "1200.00"}
    assert [(h["round"], h["kind"]) for h in tasks.history(tid)] == [
        (1, "opened"), (1, "expired"), (2, "reopened"), (2, "decided")]


def test_a_sign_off_the_team_lead_lets_expire_too_closes_the_claim() -> None:
    cases.start("k5", SIGNED_CLAIM, claim(document_missing=False, sign_off_s=3600), ME)
    turns()
    turns(now=time.time() + 3601)
    assert tasks.get(tasks.task_id("claim_sign_off", "k5")).assignee == LEAD.id
    turns(now=time.time() + 7201)
    assert cases.get("k5")["outcome"] == "expired" and tasks.get(tasks.task_id("claim_sign_off", "k5")).round == 2
