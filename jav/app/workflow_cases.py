"""214 (plan G-process-core P1b-2): a workflow is a case of the process core.

Plain-language summary: each workflow is one case of the process core (`jav.core.process`) under the workflow's own id.
The case's process definition is the workflow's saved template (the template as it was when the workflow was made):
one step per template step, all of the core's one workflow step kind, with the template's order (`after`) as the
order a person may override. Its version is the saved template's fingerprint, so the workflows of one saved template
share it and a changed template is a new version. The case starts in the transaction that writes the workflow, so
there is never one without the other.

A workflow made before has no case: the store's schema change helper adopts it at the next start of a process, from
the state its steps reached (`adopt_missing`):
- waiting: waits (ready once its order is done);
- starting: running (its start was under way);
- pulling: running, waits for its fetch (a mailbox download), with a check timer;
- started, linked: running, waits for its package's approval, with a check timer;
- needs_budget: running, waits for a person's budget;
- nothing_new: done;
- failed: failed, with its note.
An archived workflow's case is on hold (`ARCHIVED`); archiving and restoring a workflow hold and resume its case in
the workflow's own transaction.

214 (P1b-3): the core moves the steps on (`jav.app.workflows` registers the step kind). A person's actions reach the
case in the transaction of the workflow's own change: a person's start (`person_starts`: the order overridden and
recorded, a failed step retried, a wait ended, a done step reopened; the start itself is marked for the step's next
run, which takes it once), a linked package (`person_links`, the same without the mark), the automatic chain switched
on (`chain_on`: the steps waiting for a person go on).

215 (P2b): a step over its budget asks a person as a human task in the case (`ask_budget`, `BUDGET_TASK`), and the
person's start decides it (`person_starts`): its closing event ends the step's wait. When a run of a step's package is
approved or withdrawn, the step waiting for its package's approval gets an event in that transaction
(`package_settled`), so the chain moves on at once. The step's kind takes both events and refuses one of an earlier
round of its task (`task_event`).

218 (plan P3 P3l): when the package of a done step is reopened (a new live run of it, its approved own version
reopened), the step is reopened in the case in that change's transaction (`package_reopened`), so the steps built on it
go out of date.

227 (plan R3 R3d; DECISIONS 227): a step's whole state is in its row in the case. Where its start stands (waiting,
starting, pulling, started, linked, needs_budget, nothing_new, failed) is the core step's phase (`cases.set_phase`),
which the core keeps through its own changes, so the step goes on from it after a restart or after it went out of date;
the case starts with each step's first phase. A store of before kept it in the workflow's table: it moves into the
core rows once every workflow has its case, and that column is dropped (`move_phases`). A step failed outside its
case's turn (its package deleted, a start a stopped process left) is failed in the case too (`fail_outside`).

The workflow's own data (its party, period, steps' sources, budgets, packages, downloads, runs and notes) stay in its
own tables (`jav.app.workflows`).

Layer: application operation beside `jav.app.workflows`; it imports only the shared core.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from collections.abc import Mapping
from typing import Any

from jav.core import store
from jav.core import identity as actors
from jav.core.process import cases, kinds, tasks
from jav.core.process.cases import Adopted
from jav.core.process.definition import ProcessDef, StepDef

log = logging.getLogger(__name__)

STEP_KIND = "workflow_step"  # the core's one step kind for a workflow's steps; the step's own kind is its parameter
DEFINITION_PREFIX = "workflow_"  # a workflow's process definition is `workflow_<template>`
ARCHIVED = "archived"  # the hold of an archived workflow's case
# what a running workflow step waits for: its fetch, its package's approval, a person's budget, a person's start (the
# automatic chain is off)
FETCH, APPROVAL, BUDGET, PERSON = "fetch", "approval", "budget", "person"
CHECK = "check"  # the timer of a step that waits for its fetch or its package's approval
ADOPTION = "workflow-adoption"  # the machine that adopts the workflows made before
GO = "go"  # a person's start, marked on the step's result until its next run takes it
GO_ID = "go_id"  # 229 (SZ2c-3): that person's stable id beside the name
BUDGET_TASK = "workflow_budget"  # 215: the human task of a step over its budget, `workflow_budget:<workflow>:<step>`
MACHINE = actors.machine("workflows")

tasks.register_kind(tasks.TaskKind(BUDGET_TASK, __name__))

WAITING, LINKED = "waiting", "linked"  # 227: a step's first phase (the others: `jav.app.workflows`)
OLD_STATE = "state"  # 227: the workflow table's column that held the step's phase before

# a workflow step's phase (before 227: its stored state) -> the core's state and what a running step waits for (adoption)
_ADOPTED: dict[str, tuple[str, str | None]] = {
    "waiting": (cases.WAITING, None), "starting": (cases.RUNNING, None), "pulling": (cases.RUNNING, FETCH),
    "started": (cases.RUNNING, APPROVAL), "linked": (cases.RUNNING, APPROVAL), "needs_budget": (cases.RUNNING, BUDGET),
    "nothing_new": (cases.DONE, None), "failed": (cases.FAILED, None),
}



def _missing(c: sqlite3.Connection) -> list[str]:
    """The workflows without a case, oldest first (229: through the core's own read)."""
    return cases.without_case_in(c, [r["id"] for r in c.execute("SELECT id FROM workflows ORDER BY created_at, id")])


def definition(template: Mapping[str, Any]) -> ProcessDef:
    """The process definition of a workflow's saved template; its version is the saved template's fingerprint."""
    saved = json.dumps(template, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return ProcessDef(
        id=f"workflow_{template['id']}", version=hashlib.sha256(saved.encode("utf-8")).hexdigest()[:12],
        title=template["title"],
        steps=tuple(StepDef(id=s["id"], kind=STEP_KIND, title=s.get("title"), after=tuple(s.get("after", ())),
                            params={"kind": s["kind"]}) for s in template["steps"]))


def maker(actor: actors.Who) -> actors.Actor:
    """The person who made the workflow (its `actor`) or acts on it, as the core records them (229: the actor itself
    when the caller has one; a name is the local person of that name)."""
    return actor if isinstance(actor, actors.Actor) else actors.person(actor)


def _data(wf_id: str) -> dict[str, Any]:
    return {"workflow": wf_id}


def start(c: sqlite3.Connection, wf_id: str, template: Mapping[str, Any], actor: actors.Who, *,
          linked: tuple[str, ...] = ()) -> str:
    """The new workflow's case, in the caller's transaction that writes the workflow. A `linked` step (a person brought
    its package) does not wait for its order: it waits for its package's approval at once, the override recorded.
    227: each step's first phase, `linked` or `waiting`."""
    out = cases.start_in(c, wf_id, definition(template), _data(wf_id), maker(actor))
    if out != "started":
        return out
    for s in template["steps"]:
        cases.set_phase(c, wf_id, s["id"], LINKED if s["id"] in linked else WAITING)
    for step in linked:
        if cases.step_row(c, wf_id, step)["state"] == cases.WAITING:
            cases.override_order_in(c, wf_id, step, maker(actor), reason="its package was brought with the workflow")
    return out


def ensure(wf_id: str) -> None:
    """The workflow's case, adopted now when a process started before the workflow was made had no case for it."""
    with store.connect() as c:
        if cases.find_case_in(c, wf_id) is not None:
            return
        store.begin_immediate(c)
        adopt(c, wf_id)


def _adopted(state: str, note: str | None, now: float) -> Adopted:
    if state not in _ADOPTED:
        raise cases.AdoptionError(f"a workflow step state {state!r} has no state in the process core")
    core, waits = _ADOPTED[state]
    return Adopted(core, waiting_for=waits, note=note if core == cases.FAILED else None,
                   timer=(CHECK, now) if waits in (FETCH, APPROVAL) else None, phase=state)


def _keeps_old_states(c: sqlite3.Connection) -> bool:
    return any(r[1] == OLD_STATE for r in c.execute("PRAGMA table_info(workflow_steps)"))


def adopt(c: sqlite3.Connection, wf_id: str) -> str | None:
    """Adopts a workflow without a case from the state its steps reached, in the caller's write transaction ("adopted");
    None when it has its case. An archived workflow's case is held. 227: each step's state, which the workflow's table
    kept before, becomes its phase; once the column is dropped every workflow has its case."""
    if cases.find_case_in(c, wf_id) is not None:
        return None
    row = c.execute("SELECT definition, actor, status FROM workflows WHERE id=?", (wf_id,)).fetchone()
    if row is None:
        raise KeyError(wf_id)
    if not _keeps_old_states(c):
        raise cases.AdoptionError(f"workflow {wf_id} has no case and the store keeps no step state to adopt it from")
    now = time.time()
    steps = {r["step"]: _adopted(r["state"], r["note"], now)
             for r in c.execute("SELECT step, state, note FROM workflow_steps WHERE workflow_id=?", (wf_id,))}
    owner = maker(row["actor"])
    by = actors.machine(ADOPTION, on_behalf_of=owner)
    out = cases.adopt(c, wf_id, definition(json.loads(row["definition"])), _data(wf_id), owner, by, steps)
    if row["status"] == "archived":
        cases.hold(c, wf_id, ARCHIVED, by)
    return out


def adopt_missing(conn: sqlite3.Connection) -> int:
    """The store's schema change helper (`store.register_migration`): every workflow without a case is adopted, in one
    write transaction checked again inside it, so two processes starting at once adopt each workflow once. A workflow
    the core cannot take (a saved template it cannot read) is logged and left without a case, each in a savepoint of
    its own, so it never stops the store from opening. Returns how many were adopted."""
    if not _missing(conn):
        return 0
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    adopted = 0
    try:
        for wf_id in _missing(conn):
            conn.execute("SAVEPOINT workflow_adoption")
            try:
                adopted += adopt(conn, wf_id) == "adopted"
            except (ValueError, KeyError):
                conn.execute("ROLLBACK TO workflow_adoption")
                log.exception("workflow %s could not be adopted onto the process core", wf_id)
            conn.execute("RELEASE workflow_adoption")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return adopted


def move_phases(conn: sqlite3.Connection) -> int:
    """227 (plan R3 R3d): the store's schema change helper after `adopt_missing`. A store of before kept each workflow
    step's state in the workflow's table (`workflow_steps.state`): it becomes the phase of the step's row in the core,
    and the column is dropped, in one write transaction checked again inside it, so two processes starting at once move
    it once. The column is dropped only once every workflow has its case: one the core could not take keeps its
    steps' states for a later start. Returns how many phases it moved."""
    if not _keeps_old_states(conn):
        return 0
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        moved = 0
        if _keeps_old_states(conn):
            moved = cases.adopt_phases_in(conn, {(r["workflow_id"], r["step"]): r[OLD_STATE] for r in conn.execute(
                f"SELECT workflow_id, step, {OLD_STATE} FROM workflow_steps WHERE {OLD_STATE} IS NOT NULL")})
            if not _missing(conn):
                conn.execute(f"ALTER TABLE workflow_steps DROP COLUMN {OLD_STATE}")
            else:
                log.warning("a workflow has no case yet: its steps' states stay in the workflow's table")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return moved


def fail_outside(c: sqlite3.Connection, wf_id: str, step: str, note: str) -> None:
    """227: a step failed outside its case's turn (its package was deleted, a start a stopped process left), in the
    caller's transaction that records it on the step: it fails in the case too, and a done one is reopened first (its
    work was not finished after all; the steps built on it go out of date). A step that has not begun, has failed or
    is out of date keeps its state, and its next run finds the phase; so does a case closed otherwise than done."""
    case = cases.case_row(c, wf_id)
    if case["status"] == cases.CLOSED and case["outcome"] != "done":
        return
    state = cases.step_row(c, wf_id, step)["state"]
    if state == cases.DONE:
        cases.reopen_in(c, wf_id, step, MACHINE, reason=note)
    if state in (cases.DONE, cases.READY, cases.RUNNING):
        cases.fail(c, wf_id, step, MACHINE, note)


def set_archived(c: sqlite3.Connection, wf_id: str, archived: bool, actor: actors.Who) -> None:
    """Holds the workflow's case when it is archived and resumes it when it is restored, in the caller's transaction
    that changes the workflow (a workflow without a case is adopted first)."""
    adopt(c, wf_id)
    if archived:
        cases.hold(c, wf_id, ARCHIVED, maker(actor))
    else:
        cases.resume(c, wf_id, ARCHIVED, maker(actor))


def _open_for(c: sqlite3.Connection, wf_id: str, step: str, who: actors.Actor, reason: str) -> None:
    """Whatever the step's state in the core, it runs at the case's next turn: its order overridden (recorded), a
    failed one retried, a wait ended, a done one reopened (with its case when it was closed as done)."""
    st = cases.step_row(c, wf_id, step)
    if st["state"] in (cases.WAITING, cases.STALE):
        cases.override_order_in(c, wf_id, step, who, reason=reason)
    elif st["state"] == cases.FAILED:
        cases.retry_in(c, wf_id, step, who)
    elif st["state"] == cases.RUNNING and st["waiting_for"] is not None:
        cases.end_wait(c, wf_id, step, who, reason)
    elif st["state"] == cases.DONE:
        cases.reopen_in(c, wf_id, step, who, reason=reason)


def budget_task(wf_id: str, step: str) -> str:
    return tasks.task_id(BUDGET_TASK, f"{wf_id}:{step}")


def ask_budget(c: sqlite3.Connection, wf_id: str, step: str, assignee: str | None, detail: dict[str, Any]) -> None:
    """215: the step's package's estimate is over its budget: a person decides, in the caller's transaction that
    records the wait. While the step runs in the case, the task is its wait (a person's start decides it); otherwise
    (a step no turn of the case runs) it stands on its own and the start ends the wait as before."""
    row = cases.find_step_in(c, wf_id, step)
    in_case = row is not None and row["state"] == cases.RUNNING
    tasks.open_in(c, BUDGET_TASK, f"{wf_id}:{step}", MACHINE, assignee=assignee, detail=detail,
                  **({"case_id": wf_id, "step_id": step, "waits": BUDGET} if in_case else {}))


def budget_tasks_of(c: sqlite3.Connection, wp_id: str) -> list[tuple[str, str]]:
    """215 (P2d): the open budget tasks of the steps whose package it is, each with the workflow's maker (the creator
    the owner's rule falls back on)."""
    makers = {f"{r['workflow_id']}:{r['step']}": r["actor"] for r in c.execute(
        "SELECT s.workflow_id, s.step, w.actor FROM workflow_steps s JOIN workflows w ON w.id = s.workflow_id"
        " WHERE s.workpackage_id=?", (wp_id,))}
    return [(t.task_id, makers[t.subject]) for t in tasks.of_kind_in(c, BUDGET_TASK, status=tasks.OPEN)
            if t.subject in makers]


def person_starts(c: sqlite3.Connection, wf_id: str, step: str, actor: actors.Who, *, decision: Any = None) -> None:
    """A person starts the step now, in the caller's transaction: it runs at the case's next turn, and that run takes
    the person's start once (`take_go`). 215: a step waiting for a budget has its task decided by the start
    (`decision`); the task's closing event ends the wait in the case."""
    adopt(c, wf_id)
    who = maker(actor)
    task = tasks.task_in(c, budget_task(wf_id, step))
    asked = task is not None and task.status == tasks.OPEN
    if asked:
        tasks.decide_in(c, budget_task(wf_id, step), who, outcome=decision)
    if not (asked and task is not None and task.case_id is not None):  # else the task's closing ends the wait
        _open_for(c, wf_id, step, who, "a person started the step")
    cases.set_result(c, wf_id, step, {GO: who.name, GO_ID: who.id})


def package_settled(c: sqlite3.Connection, wp_id: str, event_id: str, payload: dict[str, Any],
                    actor: actors.Actor) -> bool:
    """215: a run of the package was approved or withdrawn, in that change's transaction: the workflow step whose
    package it is, when it waits for its package's approval, gets the event (its next turn looks again). False when
    no step waits."""
    row = c.execute("SELECT workflow_id, step FROM workflow_steps WHERE workpackage_id=?", (wp_id,)).fetchone()
    if row is None:
        return False
    st = cases.find_step_in(c, row["workflow_id"], row["step"])
    if st is None or st["state"] != cases.RUNNING or st["waiting_for"] != APPROVAL:
        return False
    return cases.send_event_in(c, row["workflow_id"], event_id, APPROVAL, payload, actor,
                               step_id=row["step"]) == "accepted"


def package_reopened(c: sqlite3.Connection, wp_id: str, actor: actors.Actor, reason: str) -> list[str]:
    """218 (plan P3 P3l; DECISIONS 218): the package of a done workflow step was reopened (a new live run of it, its
    approved own version reopened), in that change's transaction: the step is reopened in its case (a case closed as
    done opens again) and the steps built on it go out of date (rule 3). Returns them. Nothing happens for a package
    of no workflow, a step that is not done (its own start's run, a step waiting for its approval) or a case closed
    otherwise."""
    row = c.execute("SELECT workflow_id, step FROM workflow_steps WHERE workpackage_id=?", (wp_id,)).fetchone()
    if row is None:
        return []
    case = cases.find_case_in(c, row["workflow_id"])
    if case is None or (case["status"] == cases.CLOSED and case["outcome"] != "done"):
        return []
    st = cases.find_step_in(c, row["workflow_id"], row["step"])
    if st is None or st["state"] != cases.DONE:
        return []
    return cases.reopen_in(c, row["workflow_id"], row["step"], actor, reason=reason)


def task_event(ctx: object, c: sqlite3.Connection, event: cases.Event) -> str:
    """215: the step's kind takes a task's closing (its budget decided, its package's run settled); one of an earlier
    round of the task (the task opened again since) is refused."""
    task = tasks.task_in(c, str(event.payload.get("task")))
    return kinds.APPLIED if task is not None and task.round == event.payload.get("round") else kinds.REFUSED


def person_links(c: sqlite3.Connection, wf_id: str, step: str, actor: actors.Who) -> None:
    """A person made an existing package the step's, in the caller's transaction: at the case's next turn the step
    waits for the package's approval, whatever its order."""
    adopt(c, wf_id)
    _open_for(c, wf_id, step, maker(actor), "a person linked a package")


def chain_on(c: sqlite3.Connection, wf_id: str, actor: actors.Who) -> None:
    """The automatic chain is switched on, in the caller's transaction: the steps waiting for a person's start go on."""
    adopt(c, wf_id)
    for sid, st in cases.step_rows(c, wf_id).items():
        if st["state"] == cases.RUNNING and st["waiting_for"] == PERSON:
            cases.end_wait(c, wf_id, sid, maker(actor), "the automatic chain was switched on")


def take_go(c: sqlite3.Connection, wf_id: str, step: str) -> actors.Actor | None:
    """Who started the step by hand since its last run (`person_starts`), taken once: the mark is cleared. 229: with
    the id the mark recorded (a mark made before has the name's local one)."""
    result = cases.step_row(c, wf_id, step)["result"]
    if not isinstance(result, dict) or GO not in result:
        return None
    cases.set_result(c, wf_id, step, None)
    return actors.recorded(str(result[GO]), result.get(GO_ID))
