"""The process core's own rules (213, plan G-process-core P1a): definitions, cases, events, timers, handovers, claims.

Plain-language summary: small invented processes run in the test's process, one worker turn at a time, so each rule of
plan 212 P0 is checked on its own: a case keeps the definition it started with; a person may override the order but
not a gate; a repeated start or event changes the case once and other content under the same id is a conflict; every
change has its history row; an event and its deadline never both win; a lost reply is never sent again; a step whose
code is missing makes the case wait for a migration. The failure tests with separate worker processes are in
`test_process_trial_213.py`. Synthetic data, no AI call.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from jav.core import identity as actors
from jav.core import access, observability
from jav.core.process import cases, engine, kinds, outbox, timers
from jav.core.process.definition import ProcessDef, StepDef

ME = actors.person("Tester")
OWNER = __name__
SEEN: list[str] = []  # the steps the `note` kind ran, in order


def _note(ctx: engine.StepContext) -> kinds.StepOutcome:
    SEEN.append(ctx.step.id)
    return kinds.Done({"step": ctx.step.id})


def _approval(ctx: engine.StepContext) -> kinds.StepOutcome:
    decision = ctx.row()["result"]
    if decision is None:
        return ctx.wait("approval")
    return kinds.DONE if decision["decision"] == "approve" else kinds.Close("rejected")


def _approval_event(ctx: engine.StepContext, c, event: cases.Event) -> str:
    version, _ = ctx.result_of("price")
    if event.payload.get("result_version") != version:
        return kinds.REFUSED
    cases.set_result(c, ctx.case_id, ctx.step.id, {"decision": event.payload["decision"]})
    return kinds.APPLIED


def _document(ctx: engine.StepContext) -> kinds.StepOutcome:
    if ctx.row()["result"] is not None:
        return kinds.DONE
    return ctx.wait("document", timer=("deadline", time.time() + float(ctx.data.get("deadline_s", 60))))


def _document_event(ctx: engine.StepContext, c, event: cases.Event) -> str:
    cases.set_result(c, ctx.case_id, ctx.step.id, {"name": event.payload["name"]})
    return kinds.APPLIED


def _deadline(ctx: engine.StepContext, c, timer: timers.Timer) -> str:
    cases.close(c, ctx.case_id, "expired", ctx.actor)
    return "expired"


RETRIES: dict[str, int] = {}


def _retrying(ctx: engine.StepContext) -> kinds.StepOutcome:
    """Waits for a retry timer twice, then is done."""
    RETRIES[ctx.case_id] = RETRIES.get(ctx.case_id, 0) + 1
    if RETRIES[ctx.case_id] < 3:
        return ctx.wait("budget", timer=("retry", time.time() - 1))
    return kinds.DONE


def _broken(ctx: engine.StepContext) -> kinds.StepOutcome:
    if ctx.data.get("broken", True):
        raise RuntimeError("the step's code broke")
    return kinds.DONE


def _waits_for_nothing(ctx: engine.StepContext) -> kinds.StepOutcome:
    return kinds.WAIT


RECEIVED: list[str] = []


def _handover(ctx: engine.StepContext) -> kinds.StepOutcome:
    hid = ctx.record_handover("ledger", {"case": ctx.case_id})
    mode = ctx.data.get("receiver", "ok")

    def deliver(handover_id: str, payload: dict[str, Any]) -> dict[str, str]:
        RECEIVED.append(handover_id)
        if mode == "lose":
            raise TimeoutError("the reply was lost")
        if mode == "refuse":
            raise outbox.Refused("no such account")
        return {"receipt": handover_id}

    status = ctx.send(hid, deliver)
    if status == outbox.ACKNOWLEDGED:
        return kinds.DONE
    if status == outbox.FAILED:
        return kinds.Close("failed")
    return kinds.WAIT


for _kind in (
    kinds.StepKind("note", OWNER, _note),
    kinds.StepKind("approval", OWNER, _approval, events=("approval",), on_event=_approval_event),
    kinds.StepKind("document", OWNER, _document, events=("document",), on_event=_document_event, on_timer=_deadline),
    kinds.StepKind("retrying", OWNER, _retrying),
    kinds.StepKind("broken", OWNER, _broken),
    kinds.StepKind("waits_for_nothing", OWNER, _waits_for_nothing),
    kinds.StepKind("handover", OWNER, _handover),
):
    kinds.register(_kind)


def define(*steps: StepDef, version: str = "1") -> ProcessDef:
    return ProcessDef(id="invented", version=version, title="An invented process", steps=steps)


QUOTE = define(StepDef(id="intake", kind="note"), StepDef(id="price", kind="note", gates=("intake",)),
               StepDef(id="approve", kind="approval", gates=("price",)),
               StepDef(id="document", kind="document", after=("approve",)),
               StepDef(id="hand_over", kind="handover", gates=("approve",), after=("document",)))


def turns() -> list[str]:
    return list(engine.iterate_until_idle())


def history(case_id: str) -> list[str]:
    return [h["kind"] for h in cases.view(case_id)["history"]]


def steps(case_id: str) -> dict[str, str]:
    return {sid: s["state"] for sid, s in cases.view(case_id)["steps"].items()}


@pytest.fixture(autouse=True)
def _fresh() -> None:
    SEEN.clear()
    RETRIES.clear()
    RECEIVED.clear()


# --- definitions (rules 1, 2) -------------------------------------------------------------------------------------------


def test_a_definition_names_only_earlier_steps_once() -> None:
    with pytest.raises(ValidationError, match="not listed before"):
        define(StepDef(id="a", kind="note", after=("b",)), StepDef(id="b", kind="note"))
    with pytest.raises(ValidationError, match="listed twice"):
        define(StepDef(id="a", kind="note"), StepDef(id="a", kind="note"))
    with pytest.raises(ValidationError, match="twice in its order and gates"):
        define(StepDef(id="a", kind="note"), StepDef(id="b", kind="note", after=("a",), gates=("a",)))
    with pytest.raises(ValidationError):
        StepDef(id="Bad Id", kind="note")


def test_the_fingerprint_follows_the_content_not_the_object() -> None:
    again = ProcessDef.model_validate_json(QUOTE.canonical())
    assert again.fingerprint() == QUOTE.fingerprint() and again == QUOTE
    assert define(*QUOTE.steps, version="2").fingerprint() != QUOTE.fingerprint()
    assert QUOTE.dependants("approve") == ("document", "hand_over")


# --- starting and events (rules 4, 5) -------------------------------------------------------------------------------------


def test_a_repeated_start_is_one_case_and_other_data_is_a_conflict() -> None:
    assert [cases.start("c1", QUOTE, {"n": 1}, ME) for _ in range(2)] == ["started", "exists"]
    with pytest.raises(cases.CaseConflict):
        cases.start("c1", QUOTE, {"n": 2}, ME)
    with pytest.raises(cases.CaseConflict):
        cases.start("c1", define(*QUOTE.steps, version="2"), {"n": 1}, ME)
    view = cases.view("c1")
    assert steps("c1") == {"intake": "ready", "price": "waiting", "approve": "waiting", "document": "waiting",
                           "hand_over": "waiting"}
    assert history("c1") == ["started"] and view["history"][0]["actor"] == "local:Tester"
    assert view["definition"] == {"id": "invented", "version": "1", "sha": QUOTE.fingerprint()}


def test_events_are_taken_once_and_other_content_is_a_conflict() -> None:
    cases.start("c1", QUOTE, {}, ME)
    turns()
    assert cases.view("c1")["steps"]["approve"]["waiting_for"] == "approval"
    stale = {"decision": "approve", "result_version": 7}
    assert cases.send_event("c1", "e-stale", "approval", stale, ME) == "accepted"
    ok = {"decision": "approve", "result_version": 1}
    assert [cases.send_event("c1", "e1", "approval", ok, ME) for _ in range(3)] == ["accepted", "duplicate", "duplicate"]
    turns()
    assert cases.send_event("c1", "e1", "approval", {**ok, "decision": "reject"}, ME) == "conflict"
    view = cases.view("c1")
    assert view["events"]["e-stale"]["status"] == "refused"
    assert view["events"]["e1"] == {"kind": "approval", "status": "applied", "conflicts": 1}
    assert view["steps"]["approve"]["state"] == "done" and view["steps"]["document"]["waiting_for"] == "document"
    assert history("c1").count("event_applied") == 1 and history("c1").count("event_refused") == 1
    with pytest.raises(cases.UnknownEvent):
        cases.send_event("c1", "e2", "payment", {}, ME)
    with pytest.raises(cases.UnknownCase):
        cases.send_event("nope", "e3", "approval", ok, ME)


def test_an_event_waits_for_its_step_and_a_closed_case_ignores_it() -> None:
    cases.start("c1", QUOTE, {}, ME)
    assert cases.send_event("c1", "doc", "document", {"name": "early.pdf"}, ME) == "accepted"  # before its step waits
    turns()
    assert cases.view("c1")["events"]["doc"]["status"] == "pending"
    cases.send_event("c1", "ok", "approval", {"decision": "approve", "result_version": 1}, ME)
    turns()
    view = cases.view("c1")
    assert view["events"]["doc"]["status"] == "applied" and view["status"] == "closed" and view["outcome"] == "done"
    assert cases.send_event("c1", "late", "approval", {"decision": "approve", "result_version": 1}, ME) == "accepted"
    assert cases.view("c1")["events"]["late"]["status"] == "ignored"


def test_a_rejection_closes_the_case_and_cancel_ignores_what_waits() -> None:
    cases.start("c1", QUOTE, {}, ME)
    turns()
    cases.send_event("c1", "no", "approval", {"decision": "reject", "result_version": 1}, ME)
    turns()
    assert cases.get("c1")["outcome"] == "rejected" and RECEIVED == []
    cases.start("c2", QUOTE, {}, ME)
    turns()
    cases.send_event("c2", "doc", "document", {"name": "x.pdf"}, ME)
    assert cases.cancel("c2", ME) == "cancelled"
    assert cases.cancel("c2", ME) == "cancelled"  # a repeat changes nothing
    assert cases.view("c2")["events"]["doc"]["status"] == "ignored" and history("c2").count("closed") == 1


# --- order and gates (rule 2), stale results (rule 3) --------------------------------------------------------------------


def test_a_person_overrides_the_order_but_never_a_gate() -> None:
    cases.start("c1", QUOTE, {}, ME)
    with pytest.raises(cases.StepStateError, match="gate"):
        cases.override_order("c1", "hand_over", ME, reason="urgent")  # its gate (approve) is not done
    turns()
    cases.send_event("c1", "ok", "approval", {"decision": "approve", "result_version": 1}, ME)
    turns()
    assert steps("c1")["document"] == "running" and steps("c1")["hand_over"] == "waiting"
    cases.override_order("c1", "hand_over", ME, reason="the drawing comes later")  # only its order (document) is open
    turns()
    view = cases.view("c1")
    overridden = next(h for h in view["history"] if h["kind"] == "order_overridden")
    assert overridden["detail"] == {"skipped": ["document"], "reason": "the drawing comes later"}
    assert overridden["actor"] == "local:Tester" and view["steps"]["hand_over"]["state"] == "done"
    with pytest.raises(cases.StepStateError):
        cases.override_order("c1", "hand_over", ME)


def test_reopening_a_step_makes_the_steps_built_on_it_stale_until_it_is_done_again() -> None:
    flow = define(StepDef(id="a", kind="note"), StepDef(id="b", kind="note", gates=("a",)),
                  StepDef(id="c", kind="approval", after=("b",)), StepDef(id="price", kind="note"))
    cases.start("c1", flow, {}, ME)
    turns()
    assert steps("c1") == {"a": "done", "b": "done", "c": "running", "price": "done"}
    assert cases.reopen("c1", "a", ME, reason="the request changed") == ["b", "c"]
    assert steps("c1") == {"a": "running", "b": "stale", "c": "stale", "price": "done"}
    turns()
    view = cases.view("c1")
    assert view["steps"]["a"]["result_version"] == 2 and view["steps"]["b"]["result_version"] == 2
    assert view["steps"]["c"]["state"] == "running" and SEEN.count("b") == 2


# --- timers (rule 7) ------------------------------------------------------------------------------------------------------


def test_the_deadline_closes_a_waiting_case_and_an_early_event_cancels_it() -> None:
    for case_id in ("late", "early"):
        cases.start(case_id, define(StepDef(id="document", kind="document")), {"deadline_s": 3600}, ME)
    turns()
    cases.send_event("early", "doc", "document", {"name": "a.pdf"}, ME)
    turns()
    with cases.transaction() as c:  # both deadlines are due now (the test does not wait for the clock)
        c.execute("UPDATE process_timers SET due_at=0 WHERE name='deadline'")
    turns()
    late, early = engine.state("late"), engine.state("early")
    assert late["outcome"] == "expired" and late["timers"][0]["status"] == "fired"
    assert early["outcome"] == "done" and early["timers"][0]["status"] == "cancelled"
    assert early["timers"][0]["effect"] == "wait ended: event doc"


def test_a_timer_on_a_step_that_moved_on_changes_nothing() -> None:
    flow = define(StepDef(id="price", kind="note"), StepDef(id="document", kind="document"),
                  StepDef(id="approve", kind="approval"))
    cases.start("c1", flow, {"deadline_s": 60}, ME)
    turns()
    cases.send_event("c1", "doc", "document", {"name": "a.pdf"}, ME)
    turns()
    assert steps("c1")["document"] == "done"
    with cases.transaction() as c:  # a timer left armed on a step that has moved on
        timers.arm(c, "c1", "document", "stray", time.time() - 1)
    turns()
    view = engine.state("c1")
    stray = next(t for t in view["timers"] if t["name"] == "stray")
    assert stray["status"] == "fired" and stray["effect"] == "late" and history("c1")[-1] == "timer_fired"
    assert view["status"] == "open" and view["steps"]["document"]["result_version"] == 1


def test_a_retry_timer_runs_the_step_again_keeping_its_wait() -> None:
    cases.start("c1", define(StepDef(id="price", kind="retrying")), {}, ME)
    turns()
    assert RETRIES["c1"] == 3 and cases.get("c1")["outcome"] == "done"
    assert history("c1") == ["started", "step_started", "waiting", "step_done", "closed"]  # no row per retry
    assert [(t["status"], t["effect"]) for t in engine.state("c1")["timers"]] == [("cancelled", "step done")]


def test_a_retry_cut_off_by_a_stopped_process_is_retried_later(monkeypatch: pytest.MonkeyPatch) -> None:
    cases.start("c1", define(StepDef(id="price", kind="retrying")), {}, ME)
    assert engine.run_once()  # the first run waits; its retry timer is due
    with monkeypatch.context() as m:
        m.setattr(engine, "_run_step", lambda *a, **k: False)  # the process stops before the step runs again
        assert engine.run_once()
    assert RETRIES["c1"] == 1
    timer = engine.state("c1")["timers"][0]
    assert timer["status"] == "armed" and timer["due_at"] > time.time() + engine.RETRY_SAFETY_S - 5
    with cases.transaction() as c:
        c.execute("UPDATE process_timers SET due_at=0")
    turns()
    assert cases.get("c1")["outcome"] == "done"


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.permutations(["event", "deadline", "turn", "repeat"]))
def test_an_event_and_its_deadline_never_both_win(order: list[str]) -> None:
    case_id = f"race-{'-'.join(order)}"
    cases.start(case_id, define(StepDef(id="document", kind="document")), {"deadline_s": 3600}, ME)
    turns()
    for action in order:
        if action in ("event", "repeat"):
            cases.send_event(case_id, f"{case_id}-doc", "document", {"name": "a.pdf"}, ME)
        elif action == "deadline":
            with cases.transaction() as c:
                c.execute("UPDATE process_timers SET due_at=0 WHERE case_id=? AND status='armed'", (case_id,))
        else:
            turns()
    turns()
    view = engine.state(case_id)
    winners = [h["kind"] for h in view["history"] if h["kind"] in ("event_applied", "closed")
               and (h["kind"] == "event_applied" or h["detail"]["outcome"] == "expired")]
    assert len(winners) == 1, view["history"]
    assert view["outcome"] == ("done" if winners == ["event_applied"] else "expired")


# --- handovers (rule 4) ---------------------------------------------------------------------------------------------------


def test_a_handover_is_recorded_with_the_case_and_sent_once() -> None:
    cases.start("c1", define(StepDef(id="hand_over", kind="handover")), {}, ME)
    turns()
    view = engine.state("c1")
    assert view["outcome"] == "done" and view["handovers"][0]["status"] == "acknowledged" and RECEIVED == ["c1:hand_over:ledger"]
    assert history("c1").index("handover_recorded") < history("c1").index("handover_sent") < history("c1").index("handover_acknowledged")


def test_a_lost_reply_waits_for_a_person_and_is_never_sent_again() -> None:
    cases.start("c1", define(StepDef(id="hand_over", kind="handover")), {"receiver": "lose"}, ME)
    turns()
    turns()
    view = engine.state("c1")
    assert view["steps"]["hand_over"]["waiting_for"] == outbox.SETTLEMENT and view["handovers"][0]["status"] == "uncertain"
    assert len(RECEIVED) == 1
    with pytest.raises(outbox.NotUncertain):
        outbox.settle("c1:hand_over:ledger", "sent", ME)
    assert outbox.settle("c1:hand_over:ledger", "acknowledged", ME) == "acknowledged"
    turns()
    assert cases.get("c1")["outcome"] == "done" and len(RECEIVED) == 1


def test_a_handover_found_sent_lost_its_sender_and_becomes_uncertain() -> None:
    cases.start("c1", define(StepDef(id="hand_over", kind="handover")), {}, ME)
    with cases.transaction() as c:  # as if a worker recorded and began the send, then died before the answer
        cases.begin(c, "c1", "hand_over", ME)
        hid = outbox.record(c, "c1", "hand_over", "ledger", {"case": "c1"}, ME)
        c.execute("UPDATE process_outbox SET status='sent' WHERE handover_id=?", (hid,))
    turns()
    assert engine.state("c1")["handovers"][0]["status"] == "uncertain" and RECEIVED == []


def test_a_refused_handover_closes_the_case_as_failed() -> None:
    cases.start("c1", define(StepDef(id="hand_over", kind="handover")), {"receiver": "refuse"}, ME)
    turns()
    view = engine.state("c1")
    assert view["outcome"] == "failed" and view["handovers"][0] == {
        "handover_id": "c1:hand_over:ledger", "step_id": "hand_over", "target": "ledger", "status": "failed",
        "attempts": 1, "error": "no such account"}


# --- failures, migration, claims (rules 1, 10) ---------------------------------------------------------------------------


def test_a_broken_step_fails_with_its_reason_and_a_person_retries_it() -> None:
    cases.start("c1", define(StepDef(id="a", kind="broken"), StepDef(id="b", kind="waits_for_nothing")), {}, ME)
    turns()
    view = cases.view("c1")
    assert view["steps"]["a"] == {"state": "failed", "waiting_for": None, "result_version": 0, "result": None,
                                  "note": "RuntimeError: the step's code broke", "phase": None}  # 227: a kind's own
    assert view["steps"]["b"]["note"] == "the step waited without naming what for"
    cases.retry("c1", "a", ME)
    assert steps("c1")["a"] == "ready" and history("c1")[-1] == "step_retried"
    with pytest.raises(cases.StepStateError):
        cases.retry("c1", "a", ME)  # only a failed step is retried


def test_a_step_kind_the_code_lacks_makes_the_case_wait_for_a_migration() -> None:
    gone = define(StepDef(id="a", kind="note"), StepDef(id="b", kind="removed_in_v2", gates=("a",)))
    cases.start("c1", gone, {}, ME)
    turns()
    view = cases.view("c1")
    assert view["waiting_for"] == cases.MIGRATION and SEEN == []
    assert next(h for h in view["history"] if h["kind"] == "migration_needed")["detail"] == {"missing_kinds": ["removed_in_v2"]}
    assert engine.claim() is None


def test_a_case_keeps_the_definition_it_started_with() -> None:
    v1 = define(StepDef(id="a", kind="note"), StepDef(id="b", kind="note", gates=("a",)))
    v2 = define(StepDef(id="a", kind="note"), StepDef(id="notify", kind="note", gates=("a",)),
                StepDef(id="b", kind="note", gates=("notify",)), version="2")
    cases.start("old", v1, {}, ME)
    cases.start("new", v2, {}, ME)
    turns()
    assert set(cases.view("old")["steps"]) == {"a", "b"} and SEEN.count("notify") == 1
    assert cases.view("old")["definition"]["version"] == "1" and cases.view("new")["definition"]["version"] == "2"


def test_a_live_claim_is_not_taken_and_a_stopped_holders_claim_is() -> None:
    cases.start("c1", define(StepDef(id="a", kind="note")), {}, ME)
    with cases.transaction() as c:
        c.execute("INSERT INTO process_claims(case_id, holder, claimed_at) VALUES ('c1', 'stopped-holder', 'x')")
    assert engine.claim() == "c1"  # nobody holds the stopped holder's lock file
    engine.release("c1")
    assert engine.claim() == "c1"
    engine.release("c1")


# --- plug-in points (rules 8, 9) -----------------------------------------------------------------------------------------


def test_the_authorisation_check_is_asked_and_the_observer_gets_only_allowed_fields() -> None:
    seen: list[observability.Measurement] = []
    observability.set_observer(seen.append)
    access.set_authorizer(lambda who, action, case_id: not (who.name == "Visitor" and action == "cancel"))
    try:
        cases.start("c1", define(StepDef(id="a", kind="note")), {}, ME)
        with pytest.raises(access.NotAuthorised):
            cases.cancel("c1", actors.person("Visitor"))
        turns()
    finally:
        observability.set_observer(None)
        access.set_authorizer(None)
    assert [(m.operation, m.outcome) for m in seen] == [("step:note", "ok")]
    # 231 (E4): the cleaned attributes (none here) and the start beside them, nothing else
    assert set(vars(seen[0])) == {"operation", "seconds", "outcome", "attempts", "attributes", "started_at"}
    assert seen[0].attributes == {}


def test_an_actor_has_a_stable_id_and_the_machine_names_whom_it_acts_for() -> None:
    bot = actors.machine(on_behalf_of=ME)
    assert (bot.id, bot.kind, bot.on_behalf_of) == ("machine:process-core", "machine", "local:Tester")
    assert actors.Actor.from_json(bot.as_json()) == bot
    with pytest.raises(ValueError):
        actors.Actor(id="no-namespace", name="x", kind="human")
    with pytest.raises(ValueError):
        actors.person("  ")
