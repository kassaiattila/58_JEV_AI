"""The process core's engine (213, P1a; rules 6, 7 and 10 of plan 212 P0): claims, the worker's turn, the operations.

Plain-language summary: a worker takes one case that has something to do (a ready step, a step whose wait has an
event, a due timer) under a claim, moves it as far as it can and lets it go. A claim names the worker's holder, a lock
file the process keeps locked for its lifetime (the call log's pattern since 092): the claim of a process that died is
free at once, and a live worker's claim is never taken over, so any number of workers may run on one machine. In a
turn the case's due timers fire first, then the events its steps wait for are taken, then its steps run in the
definition's order; a step runs outside any transaction, and what it did is recorded with its history in one.

The durable workflow engine plug-in point (plan 212 P0 section 4) is the four operations `start`, `send_event`, `state`
and `cancel`; only ids and states go into the engine, never a document, an AI call or a cost.

214 (P1b-3): a caller can also move one named case on now (`turn`, under the same claim), and wake it: the retry
timers of its waiting steps fire at once, a deadline (a timer its kind handles) only when due. A claim is exclusive
between the threads of one process too (the local service answers requests on several threads).

215 (P2a): a human task's deadline is a timer of its case too: when due, it expires the task (`tasks.expire_in`),
whose closing event the same turn then takes; a wake never fires it early.

229 (plan structure stage 1, SZ1a): the worker's round turns every case with something to do now, of any process
definition (`turn_due`); before, it looked only at the workflows' cases, so a case of another kind never started. A
case whose turn raises is logged and left to the next round, so it never holds the others up.

The engine does not use the job queue: the queue's start-up reset (`queue.recover_orphans`) assumes one worker.
"""

from __future__ import annotations

import logging
import math
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

from jav.core import calls, lock, store
from jav.core.clock import utc_stamp as _now
from jav.core import observability
from jav.core.identity import Actor, machine
from jav.core.process import cases, kinds, outbox, tasks, timers
from jav.core.process.definition import ProcessDef, StepDef

__all__ = [  # 229 (SZ1b): what code outside the process core may use; the rest is the core's own
    "POLL_S", "StepContext", "start", "send_event", "cancel", "state", "claim_case", "release", "turn", "due_cases",
    "turn_due", "run_once", "run", "iterate_until_idle",
]

log = logging.getLogger(__name__)

POLL_S = 0.5
RETRY_SAFETY_S = 30.0  # a retry timer is armed again this far ahead before its step runs, in case the run is cut off
DUE_PASSES = 3  # 229: a round looks again this often for cases a turn made due (a retry timer due at once)

store.register_schema("process.engine", """
CREATE TABLE IF NOT EXISTS process_claims (
    case_id    TEXT PRIMARY KEY,
    holder     TEXT NOT NULL,                 -- the claiming process's holder (jav.core.calls.holder)
    claimed_at TEXT NOT NULL
);
""")

_OPEN_WHERE = "c.status='open' AND c.waiting_for IS NULL"
_EVENT_TAKEN = """EXISTS (SELECT 1 FROM process_inbox e JOIN process_steps s ON s.case_id=e.case_id AND s.state='running'
               AND s.waiting_for=e.kind AND (e.step_id IS NULL OR e.step_id=s.step_id)
               WHERE e.case_id=c.case_id AND e.status='pending')"""
_DUE_WHERE = f"""{_OPEN_WHERE} AND (
    EXISTS (SELECT 1 FROM process_steps s WHERE s.case_id=c.case_id
            AND (s.state='ready' OR (s.state='running' AND s.waiting_for IS NULL)))
    OR {_EVENT_TAKEN}
    OR EXISTS (SELECT 1 FROM process_timers t WHERE t.case_id=c.case_id AND t.status='armed' AND t.due_at<=?))"""
_DUE = f"SELECT c.case_id FROM process_cases c WHERE {_DUE_WHERE} ORDER BY c.updated_at, c.case_id"

# 214: the cases a thread of this process holds, so another thread of it never takes them (the claims table names the
# process only)
_held_here: set[str] = set()
_here_lock = threading.Lock()

# --- the plug-in point's four operations -----------------------------------------------------------------------------

start = cases.start
send_event = cases.send_event
cancel = cases.cancel


def state(case_id: str) -> dict[str, Any]:
    """The case with its timers, its handovers, its human tasks and its claim."""
    out = cases.view(case_id)
    with store.connect() as c:
        held = c.execute("SELECT holder FROM process_claims WHERE case_id=?", (case_id,)).fetchone()
        out |= {"timers": timers.of_case(c, case_id), "handovers": outbox.of_case(c, case_id),
                "tasks": tasks.of_case(c, case_id), "claimed_by": held["holder"] if held else None}
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


def _take_here(case_id: str) -> bool:
    with _here_lock:
        if case_id in _held_here:
            return False
        _held_here.add(case_id)
        return True


def _leave_here(case_id: str) -> None:
    with _here_lock:
        _held_here.discard(case_id)


def _claim_in(c: sqlite3.Connection, case_id: str, me: str) -> bool:
    """Claims the case in the caller's write transaction unless a live process or another thread of this one holds it."""
    if not _take_here(case_id):
        return False
    held = c.execute("SELECT holder FROM process_claims WHERE case_id=?", (case_id,)).fetchone()
    if held is not None and held["holder"] != me and _alive(held["holder"]):
        _leave_here(case_id)
        return False
    if held is not None and held["holder"] != me:
        log.info("case %s: the claim of stopped holder %s is taken over", case_id, held["holder"])
    c.execute("INSERT INTO process_claims(case_id, holder, claimed_at) VALUES (?,?,?) ON CONFLICT(case_id)"
              " DO UPDATE SET holder=excluded.holder, claimed_at=excluded.claimed_at", (case_id, me, _now()))
    return True


def claim(now: float | None = None) -> str | None:
    """Claims the first case with something to do that no live process holds; None when there is none."""
    me, now = calls.holder(), time.time() if now is None else now
    with store.connect() as c:  # a look without the write lock first: an idle worker does not queue for it
        if c.execute(_DUE + " LIMIT 1", (now,)).fetchone() is None:
            return None
    taken: str | None = None
    try:
        with cases.transaction() as c:
            for row in c.execute(_DUE, (now,)).fetchall():
                if _claim_in(c, row["case_id"], me):
                    taken = str(row["case_id"])
                    break
    except BaseException:  # the claim was not written: this thread does not hold the case either
        if taken is not None:
            _leave_here(taken)
        raise
    return taken


def claim_case(case_id: str) -> bool:
    """214: claims this case, whatever it has to do, unless a live process or another thread of this one holds it."""
    taken = False
    try:
        with cases.transaction() as c:
            cases.case_row(c, case_id)  # an unknown case is an error, not a claim
            taken = _claim_in(c, case_id, calls.holder())
    except BaseException:  # the claim was not written: this thread does not hold the case either
        if taken:
            _leave_here(case_id)
        raise
    return taken


def release(case_id: str) -> None:
    try:
        with store.connect() as c:
            c.execute("DELETE FROM process_claims WHERE case_id=? AND holder=?", (case_id, calls.holder()))
    finally:
        _leave_here(case_id)


def due_cases(now: float | None = None) -> list[str]:
    """214: the cases with something to do now (a ready step, an event a waiting step takes, a due timer), of any
    process definition, oldest change first."""
    with store.connect() as c:
        return [r["case_id"] for r in c.execute(_DUE, (time.time() if now is None else now,))]


def turn_due(now: float | None = None, *, passes: int = DUE_PASSES) -> int:
    """229 (SZ1a): the worker's round: a turn for every case with something to do now, of any process definition, and
    again for those a turn made due, at most `passes` looks. A case a live process or another thread holds is left to
    that one; a case whose turn raises is logged and left to the next round, so the others still move. Returns how many
    turns it made."""
    failed: set[str] = set()
    moved = 0
    for _ in range(passes):
        todo = [case_id for case_id in due_cases(now) if case_id not in failed]
        if not todo:
            break
        for case_id in todo:
            try:
                moved += turn(case_id, now=now)
            except Exception:  # noqa: BLE001 - operational safety net: logged, the case is turned again next round
                log.exception("case %s could not take its turn", case_id)
                failed.add(case_id)
    return moved


def turn(case_id: str, *, wake: bool = False, now: float | None = None) -> bool:
    """214: the named case's turn now, under its claim (`advance`; with `wake` its retry timers fire at once). False
    when a live process or another thread of this one holds it: that one moves it on."""
    if not claim_case(case_id):
        return False
    try:
        advance(case_id, now, wake=wake)
    finally:
        release(case_id)
    return True


# --- the turn ---------------------------------------------------------------------------------------------------------


def advance(case_id: str, now: float | None = None, *, wake: bool = False) -> None:
    """Everything the claimed case can do now: its due timers, the events its steps wait for, then its steps. With
    `wake` (214) the retry timers of its waiting steps fire now too; a timer its step's kind handles (`on_timer`, e.g.
    a deadline) or a human task's deadline (215) still fires only when due."""
    row = cases.get(case_id)
    if row["status"] != cases.OPEN or row["waiting_for"] is not None:
        return
    defn = cases.definition_of(row)
    missing = kinds.unknown(defn)
    if missing:
        with cases.transaction() as c:
            cases.need_migration(c, case_id, missing, machine(on_behalf_of=Actor.from_json(row["started_by"])))
        return
    kind_of = {s.id: s.kind for s in defn.steps}
    with store.connect() as c:
        due = timers.due(c, case_id, math.inf if wake else time.time() if now is None else now)
    if wake:
        when = time.time() if now is None else now
        due = [t for t in due if t.due_at <= when
               or (kinds.of(kind_of[t.step_id]).on_timer is None and not tasks.is_timer(t))]
    rerun = [t.step_id for t in due if _fire(t)]
    for event in cases.pending_events(case_id):
        _take(event)
    defn_steps = {s.id: s for s in defn.steps}
    for step_id in dict.fromkeys(rerun):
        _run_step(case_id, defn_steps[step_id], rerun=True)
    _run_steps(case_id)


def _fire(timer: timers.Timer) -> bool:
    """A due timer fires once: on a step still running, a human task's deadline expires the task (215), otherwise its
    kind's `on_timer` acts; on a step that has moved on or a closed case, it only leaves a history row. Without
    `on_timer` the timer is a retry: the step runs again keeping its wait (no history row per retry), and the timer is
    armed again `RETRY_SAFETY_S` ahead first, so a run cut off by a stopped process is retried later; the step's own
    wait arms it anew. A retry leaves no history row (a budget wait may be retried for days); the timer's row shows its
    latest effect. Returns True for a retry."""
    with cases.transaction() as c:
        if not timers.close(c, timer.timer_id, timers.FIRED, None):
            return False
        row = cases.case_row(c, timer.case_id)
        st = cases.step_row(c, timer.case_id, timer.step_id)
        ctx = _context(row, cases.definition_of(row).step(timer.step_id))
        retry = False
        if row["status"] != cases.OPEN or st["state"] != cases.RUNNING:
            effect = "late"
        elif tasks.is_timer(timer):
            effect = "expired" if tasks.expire_in(c, tasks.of_timer(timer), ctx.actor) else "late"
        else:
            kind = kinds.of(ctx.step.kind)
            if kind.on_timer is not None:
                with observability.measured(f"timer:{ctx.step.kind}"):
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
        with observability.measured(f"event:{target.kind}"):
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
        # 218: where the case's history stood when the step began; a wait it names may end before its outcome is in
        began = c.execute("SELECT COALESCE(MAX(id), 0) FROM process_history WHERE case_id=?", (case_id,)).fetchone()[0]
    try:
        with observability.measured(f"step:{step.kind}"):
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
        elif st["waiting_for"] is None:
            # 218: the wait the step named ended while it ran (a person settled an uncertain handover): it runs again,
            # as after any ended wait; a wait for nothing named would never be woken
            if c.execute("SELECT 1 FROM process_history WHERE case_id=? AND step_id=? AND kind='wait_ended' AND id>?",
                         (case_id, step.id, began)).fetchone() is None:
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
