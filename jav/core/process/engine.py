"""The process core's engine (213, P1a; rules 6, 7 and 10 of plan 212 P0): claims, the worker's turn, the operations.

Plain-language summary: a worker takes one case that has something to do (a ready step, a step whose wait has an
event, a due timer) under a claim, moves it as far as it can and lets it go. A claim names the worker's holder, a lock
file the process keeps locked for its lifetime (the call log's pattern since 092): the claim of a process that died is
free at once, and a live worker's claim is never taken over, so any number of workers may run on one machine. In a
turn the case's due timers fire first, then the events its steps wait for are taken, then its steps run in the
definition's order; a step runs outside any transaction, and what it did is recorded with its history in one.

The durable workflow engine plug-in point (plan 212 P0 section 4) is the four operations `start`, `send_event`, `state`
and `cancel`; only ids and states go into the engine, never a document, an AI call or a cost.

The engine does not use the job queue: the queue's start-up reset (`queue.recover_orphans`) assumes one worker.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

from jav.core import calls, lock, store
from jav.core.clock import utc_stamp as _now
from jav.core.process import cases, hooks, kinds, outbox, timers
from jav.core.process.actor import Actor, machine
from jav.core.process.definition import ProcessDef, StepDef

log = logging.getLogger(__name__)

POLL_S = 0.5
RETRY_SAFETY_S = 30.0  # a retry timer is armed again this far ahead before its step runs, in case the run is cut off

store.register_schema("process.engine", """
CREATE TABLE IF NOT EXISTS process_claims (
    case_id    TEXT PRIMARY KEY,
    holder     TEXT NOT NULL,                 -- the claiming process's holder (jav.core.calls.holder)
    claimed_at TEXT NOT NULL
);
""")

_DUE = """SELECT c.case_id FROM process_cases c WHERE c.status='open' AND c.waiting_for IS NULL AND (
    EXISTS (SELECT 1 FROM process_steps s WHERE s.case_id=c.case_id
            AND (s.state='ready' OR (s.state='running' AND s.waiting_for IS NULL)))
    OR EXISTS (SELECT 1 FROM process_inbox e JOIN process_steps s ON s.case_id=e.case_id AND s.state='running'
               AND s.waiting_for=e.kind AND (e.step_id IS NULL OR e.step_id=s.step_id)
               WHERE e.case_id=c.case_id AND e.status='pending')
    OR EXISTS (SELECT 1 FROM process_timers t WHERE t.case_id=c.case_id AND t.status='armed' AND t.due_at<=?))
    ORDER BY c.updated_at, c.case_id"""

# --- the plug-in point's four operations -----------------------------------------------------------------------------

start = cases.start
send_event = cases.send_event
cancel = cases.cancel


def state(case_id: str) -> dict[str, Any]:
    """The case with its timers, its handovers and its claim."""
    out = cases.view(case_id)
    with store.connect() as c:
        held = c.execute("SELECT holder FROM process_claims WHERE case_id=?", (case_id,)).fetchone()
        out |= {"timers": timers.of_case(c, case_id), "handovers": outbox.of_case(c, case_id),
                "claimed_by": held["holder"] if held else None}
    return out


# --- what a step's kind gets ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class StepContext:
    """A step's view of its case while it runs: the case's data, its definition and the actor it runs as."""

    case_id: str
    step: StepDef
    definition: ProcessDef
    data: dict[str, Any]
    actor: Actor

    def transaction(self) -> AbstractContextManager[sqlite3.Connection]:
        """A write transaction for the step's own rows and the core's, written together."""
        return cases.transaction()

    def row(self) -> dict[str, Any]:
        """The step's state now."""
        with store.connect() as c:
            return cases.step_row(c, self.case_id, self.step.id)

    def result_of(self, step_id: str) -> tuple[int, Any]:
        """Another step's result version and result (rule 3: a step builds on a named result version)."""
        with store.connect() as c:
            st = cases.step_row(c, self.case_id, step_id)
        return int(st["result_version"]), st["result"]

    def wait(self, what: str, *, timer: tuple[str, float] | None = None,
             detail: dict[str, Any] | None = None) -> kinds.Wait:
        with cases.transaction() as c:
            cases.wait(c, self.case_id, self.step.id, what, self.actor, timer=timer, detail=detail)
        return kinds.WAIT

    def record(self, kind: str, detail: dict[str, Any] | None = None) -> None:
        with cases.transaction() as c:
            cases.record(c, self.case_id, self.step.id, kind, self.actor, detail)

    def record_handover(self, target: str, payload: dict[str, Any], *, handover_id: str | None = None) -> str:
        with cases.transaction() as c:
            return outbox.record(c, self.case_id, self.step.id, target, payload, self.actor, handover_id=handover_id)

    def send(self, handover_id: str, deliver: Callable[[str, dict[str, Any]], Any]) -> str:
        return outbox.send(handover_id, deliver, self.actor)


def _context(row: dict[str, Any], step: StepDef) -> StepContext:
    started_by = Actor.from_json(row["started_by"])
    return StepContext(row["case_id"], step, cases.definition_of(row), row["data"], machine(on_behalf_of=started_by))


# --- claims (rule 10) -------------------------------------------------------------------------------------------------


def _alive(holder: str) -> bool:
    return lock.is_held(calls.holder_path(holder))


def claim(now: float | None = None) -> str | None:
    """Claims the first case with something to do that no live process holds; None when there is none."""
    me, now = calls.holder(), time.time() if now is None else now
    with store.connect() as c:  # a look without the write lock first: an idle worker does not queue for it
        if c.execute(_DUE + " LIMIT 1", (now,)).fetchone() is None:
            return None
    with cases.transaction() as c:
        for row in c.execute(_DUE, (now,)).fetchall():
            held = c.execute("SELECT holder FROM process_claims WHERE case_id=?", (row["case_id"],)).fetchone()
            if held is not None and held["holder"] != me and _alive(held["holder"]):
                continue
            if held is not None and held["holder"] != me:
                log.info("case %s: the claim of stopped holder %s is taken over", row["case_id"], held["holder"])
            c.execute("INSERT INTO process_claims(case_id, holder, claimed_at) VALUES (?,?,?) ON CONFLICT(case_id)"
                      " DO UPDATE SET holder=excluded.holder, claimed_at=excluded.claimed_at",
                      (row["case_id"], me, _now()))
            return str(row["case_id"])
    return None


def release(case_id: str) -> None:
    with store.connect() as c:
        c.execute("DELETE FROM process_claims WHERE case_id=? AND holder=?", (case_id, calls.holder()))


# --- the turn ---------------------------------------------------------------------------------------------------------


def advance(case_id: str, now: float | None = None) -> None:
    """Everything the claimed case can do now: its due timers, the events its steps wait for, then its steps."""
    row = cases.get(case_id)
    if row["status"] != cases.OPEN or row["waiting_for"] is not None:
        return
    defn = cases.definition_of(row)
    missing = kinds.unknown(defn)
    if missing:
        with cases.transaction() as c:
            cases.need_migration(c, case_id, missing, machine(on_behalf_of=Actor.from_json(row["started_by"])))
        return
    with store.connect() as c:
        due = timers.due(c, case_id, time.time() if now is None else now)
    rerun = [t.step_id for t in due if _fire(t)]
    for event in cases.pending_events(case_id):
        _take(event)
    defn_steps = {s.id: s for s in defn.steps}
    for step_id in dict.fromkeys(rerun):
        _run_step(case_id, defn_steps[step_id], rerun=True)
    _run_steps(case_id)


def _fire(timer: timers.Timer) -> bool:
    """A due timer fires once: on a step still running, its kind's `on_timer` acts; on a step that has moved on or a
    closed case, it only leaves a history row. Without `on_timer` the timer is a retry: the step runs again keeping its
    wait (no history row per retry), and the timer is armed again `RETRY_SAFETY_S` ahead first, so a run cut off by a
    stopped process is retried later; the step's own wait arms it anew. A retry leaves no history row (a budget wait
    may be retried for days); the timer's row shows its latest effect. Returns True for a retry."""
    with cases.transaction() as c:
        if not timers.close(c, timer.timer_id, timers.FIRED, None):
            return False
        row = cases.case_row(c, timer.case_id)
        st = cases.step_row(c, timer.case_id, timer.step_id)
        ctx = _context(row, cases.definition_of(row).step(timer.step_id))
        retry = False
        if row["status"] != cases.OPEN or st["state"] != cases.RUNNING:
            effect = "late"
        else:
            kind = kinds.of(ctx.step.kind)
            if kind.on_timer is not None:
                with hooks.measured(f"timer:{ctx.step.kind}"):
                    effect = kind.on_timer(ctx, c, timer)
            else:
                effect, retry = "retry", True
        timers.set_effect(c, timer.timer_id, effect)
        if retry:
            timers.arm(c, timer.case_id, timer.step_id, timer.name, time.time() + RETRY_SAFETY_S)
        else:
            cases.record(c, timer.case_id, timer.step_id, "timer_fired", ctx.actor, {"timer": timer.name, "effect": effect})
        return retry


def _take(event: cases.Event) -> None:
    """A pending event goes to the first running step waiting for its kind; it stays pending until one does."""
    with cases.transaction() as c:
        ev = c.execute("SELECT status FROM process_inbox WHERE event_id=?", (event.event_id,)).fetchone()
        if ev is None or ev["status"] != cases.PENDING:
            return
        row = cases.case_row(c, event.case_id)
        if row["status"] != cases.OPEN:
            cases.take_event(c, event.event_id, cases.IGNORED)
            return
        defn = cases.definition_of(row)
        steps = cases.step_rows(c, event.case_id)
        target = next((s for s in defn.steps if steps[s.id]["state"] == cases.RUNNING
                       and steps[s.id]["waiting_for"] == event.kind and event.step_id in (None, s.id)), None)
        if target is None:
            return
        ctx = _context(row, target)
        kind = kinds.of(target.kind)
        with hooks.measured(f"event:{target.kind}"):
            outcome = kind.on_event(ctx, c, event) if kind.on_event is not None else kinds.APPLIED
        if outcome not in (kinds.APPLIED, kinds.REFUSED):
            raise ValueError(f"step kind {target.kind!r} answered an event with {outcome!r}")
        cases.take_event(c, event.event_id, outcome)
        cases.record(c, event.case_id, target.id, f"event_{outcome}", event.sent_by,
                     {"event_id": event.event_id, "kind": event.kind})
        if outcome == kinds.APPLIED:
            cases.end_wait(c, event.case_id, target.id, event.sent_by, f"event {event.event_id}")


def _runnable(case_id: str) -> list[StepDef]:
    with store.connect() as c:
        row = cases.case_row(c, case_id)
        if row["status"] != cases.OPEN:
            return []
        steps = cases.step_rows(c, case_id)
    return [s for s in cases.definition_of(row).steps if steps[s.id]["state"] == cases.READY
            or (steps[s.id]["state"] == cases.RUNNING and steps[s.id]["waiting_for"] is None)]


def _run_steps(case_id: str) -> None:
    """Runs the case's runnable steps in the definition's order until none is left."""
    tried: set[str] = set()
    while True:
        step = next((s for s in _runnable(case_id) if s.id not in tried), None)
        if step is None:
            return
        tried.add(step.id)
        if _run_step(case_id, step):
            tried.clear()  # a step that moved may have made others runnable, or itself again (it is done or waits)


def _run_step(case_id: str, step: StepDef, *, rerun: bool = False) -> bool:
    """Runs one step and records what it did; True when the step or the case moved. With `rerun` (a retry timer) a
    running step runs again while it keeps its wait."""
    with cases.transaction() as c:
        row = cases.case_row(c, case_id)
        ctx = _context(row, step)
        if rerun:
            if row["status"] != cases.OPEN or cases.step_row(c, case_id, step.id)["state"] != cases.RUNNING:
                return False
        elif not cases.begin(c, case_id, step.id, ctx.actor):
            return False
    try:
        with hooks.measured(f"step:{step.kind}"):
            outcome = kinds.of(step.kind).run(ctx)
    except Exception as exc:  # noqa: BLE001 - the step fails with the reason; a person retries it
        log.exception("case %s step %s failed", case_id, step.id)
        with cases.transaction() as c:
            cases.fail(c, case_id, step.id, ctx.actor, f"{type(exc).__name__}: {exc}")
        return True
    with cases.transaction() as c:
        if cases.case_row(c, case_id)["status"] != cases.OPEN:
            return True
        st = cases.step_row(c, case_id, step.id)
        if st["state"] != cases.RUNNING:
            return True
        if isinstance(outcome, kinds.Done):
            cases.complete(c, case_id, step.id, ctx.actor, outcome.result)
        elif isinstance(outcome, kinds.Close):
            cases.close(c, case_id, outcome.outcome, ctx.actor)
        elif isinstance(outcome, kinds.Fail):
            cases.fail(c, case_id, step.id, ctx.actor, outcome.note)
        elif st["waiting_for"] is None:  # a wait for nothing named would never be woken
            cases.fail(c, case_id, step.id, ctx.actor, "the step waited without naming what for")
        else:
            return False
    return True


def run_once(now: float | None = None) -> bool:
    """One case's turn; False when no case had anything to do."""
    case_id = claim(now)
    if case_id is None:
        return False
    try:
        advance(case_id, now)
    finally:
        release(case_id)
    return True


def run(*, stop: Callable[[], bool], poll_s: float = POLL_S) -> dict[str, int]:
    """The worker loop until `stop()`. At start, calls left reserved by stopped processes become uncertain
    (`calls.recover_uncertain` leaves a live process's calls alone); claims need no start-up reset."""
    info = {"uncertain_marked": calls.recover_uncertain(), "turns": 0, "errors": 0}
    log.info("process worker started: %s", info)
    while not stop():
        try:
            moved = run_once()
        except Exception:  # noqa: BLE001 - operational safety net: logged, the case is claimed again later
            log.exception("a process turn failed")
            info["errors"] += 1
            moved = False
        if moved:
            info["turns"] += 1
        else:
            time.sleep(poll_s)
    return info


def iterate_until_idle(limit: int = 1000, now: float | None = None) -> Iterator[str]:
    """Turns until no case has anything to do (tests and command-line runs); yields each case moved."""
    for _ in range(limit):
        case_id = claim(now)
        if case_id is None:
            return
        try:
            advance(case_id, now)
        finally:
            release(case_id)
        yield case_id
    raise RuntimeError(f"cases still had work after {limit} turns")
