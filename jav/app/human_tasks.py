"""215 (plan G-process-core P2): today's work as human tasks of the process core (`jav.core.process.tasks`).

Plain-language summary: what waits for a person in the application becomes a human task, written in the same
transaction as the change that raises or settles it, so a task and what it is about never part. Whom a task is for is
the owner's rule (decision of 2026-10-23): the package's responsible person; a package without one goes to its
creator (the person who started the run, or who made the workflow) when that person is on the Users list; otherwise
it is anyone's. No task gets a deadline (decision of 2026-10-23). When a package's responsible person changes, its
open tasks go to whom the rule names now (`package_owner_changed`).

- `run_approval:<run>`: a finished live run waits for a person (opened when the run finishes unapproved, by
  `work_runs.refresh_run_status`; decided by its approval; withdrawn when it is superseded or stopped). The task
  belongs to the run, not to a workflow: a run that waits to be superseded outlives its workflow step. When the run's
  package is a workflow step's, its approval or withdrawal sends the workflow's case an event in the same transaction
  (`workflow_cases.package_settled`), so the chain moves on at once.
- `review:<to-do item>` (P2d): an open to-do item (a document's or an email's open reasons, one item per subject) is
  a task, its mirror: the store calls `review_item_changed` in the transaction that raises or closes the item
  (`store.set_review_item_hook`). The task is for the package of the run that raised the item last (a measurement's
  item has no package: anyone's), and goes to another person when another package's run raises it; it is decided when
  a person resolves the item's last reason, and withdrawn when a machine closes it (a re-run, a supersede, the step
  that no longer finds it). It keeps what it is about and the kind of run that opened it (live, trial, measurement).
- `own_approval:<package>` (P2d): a logic pack a person approves as its own version (`LogicPack.own_approval`: a
  reconciliation, a quote; not the email routing, which is done when every attachment is decided) waits for that
  approval from when it is made (`work.create_workpackage`) and again when its approved version is reopened
  (`package_release.reopen_own`); the approval decides it (`package_release.record_own`), on the fingerprint of what
  the person approved, and a deleted package withdraws it. An archived one keeps it open: restoring it needs the same
  approval. In a workflow the approval sends its step the same event as a run's approval.
- The budget a workflow step waits for is `jav.app.workflow_cases`' task (`workflow_budget`), for the person this
  module names.

The to-dos, runs and packages made before 215 get their tasks at the next start of a process (`adopt_missing`, the
store's schema change helper, registered after the tables it reads by `jav.app.package_release`); a task left open
while a version that keeps none settled what it is about (the code before 215 running against the same store) is
withdrawn then.

Layer: application operation; it imports the shared core, `jav.app.logic_packs` and `jav.app.workflow_cases` (which
import no other application module), no domain module.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from jav.app import logic_packs, workflow_cases
from jav.core import store
from jav.core import identity as actors
from jav.core.process import tasks

RUN_APPROVAL = "run_approval"
REVIEW = "review"
OWN_APPROVAL = "own_approval"
FINISHED = ("needs_review", "done", "failed")  # a live run in these states, unapproved, waits for a person
MACHINE = actors.machine("work-runs")
ADOPTION = actors.machine("human-task-adoption")  # who opens the tasks of the work made before

for _kind in (RUN_APPROVAL, REVIEW, OWN_APPROVAL):
    tasks.register_kind(tasks.TaskKind(_kind, __name__))


def assignee_for(c: sqlite3.Connection, wp_id: str | None, creator: str | None) -> str | None:
    """The owner's rule: the package's responsible person; without one, `creator` when on the Users list (as the list
    writes the name; any name while the list is empty); otherwise anyone (None)."""
    from jav.app import app_settings  # lazy: app_settings imports the work package module

    if wp_id is not None:
        row = c.execute("SELECT owner, owner_id FROM workpackages WHERE id=?", (wp_id,)).fetchone()
        if row is not None and row["owner"] and row["owner"].strip():
            return row["owner_id"] or actors.person(row["owner"]).id  # 229 (SZ2c): the owner's stable id
    if not creator or not creator.strip():
        return None
    # on the caller's connection, inside its write transaction (another connection would wait for its lock); a store
    # that has no name list yet is one with an empty list
    listed = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_users'").fetchone() is not None
    name = app_settings.canonical_user(creator, c) if listed else " ".join(creator.split())
    return actors.person(name).id if name else None


def person(actor: actors.Who | None) -> actors.Actor:
    """Who acts on a task: the actor the change came with (229: as the shared entrance knows it; a name is the local
    person of that name), or the machine when no name came with the change."""
    if isinstance(actor, actors.Actor):
        return actor
    return actors.person(actor) if actor and actor.strip() else MACHINE


# --- a live run's approval ----------------------------------------------------------------------------------------------


def open_run_approval(c: sqlite3.Connection, run_id: str, *, by: actors.Actor = MACHINE) -> str | None:
    """The run's approval task when it is a finished, unapproved live run, in the caller's transaction ("opened" or
    "exists"); None for any other run."""
    run = c.execute("SELECT workpackage_id, mode, status, approval, actor FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if run is None or run["mode"] != "apply" or run["approval"] is not None or run["status"] not in FINISHED:
        return None
    return tasks.open_in(c, RUN_APPROVAL, run_id, by, assignee=assignee_for(c, run["workpackage_id"], run["actor"]),
                         detail={"workpackage_id": run["workpackage_id"]})


def _settled(c: sqlite3.Connection, wp_id: str, tid: str, rnd: int, status: str, actor: actors.Actor) -> None:
    """The workflow step whose package it is hears of its approval or withdrawal (`workflow_cases.package_settled`)."""
    workflow_cases.package_settled(c, wp_id, f"{tid}#{rnd}", {"task": tid, "round": rnd, "status": status}, actor)


def _settle(c: sqlite3.Connection, run_id: str, actor: actors.Actor, *, approved: dict[str, Any] | None,
            note: str | None = None) -> None:
    tid = tasks.task_id(RUN_APPROVAL, run_id)
    task = tasks.task_in(c, tid)
    if task is None or task.status != tasks.OPEN:
        return
    if approved is not None:
        tasks.decide_in(c, tid, actor, outcome=approved)
    else:
        tasks.withdraw_in(c, tid, actor, note=note)
    row = c.execute("SELECT workpackage_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if row is not None:
        _settled(c, row["workpackage_id"], tid, task.round, tasks.DECIDED if approved is not None else tasks.WITHDRAWN,
                 actor)


def run_approved(c: sqlite3.Connection, run_id: str, actor: actors.Who, outcome: dict[str, Any]) -> None:
    """The run was approved, in the approval's transaction: its task is decided by the approver."""
    _settle(c, run_id, person(actor), approved=outcome)


def run_withdrawn(c: sqlite3.Connection, run_id: str, actor: actors.Who | None, note: str) -> None:
    """The run no longer waits for an approval (superseded, stopped), in that change's transaction."""
    _settle(c, run_id, person(actor), approved=None, note=note)


# --- a to-do item -------------------------------------------------------------------------------------------------------


def _raised_by(c: sqlite3.Connection, flow_run_id: str | None) -> tuple[str | None, str]:
    """Whom the rule names for the run that raised an item, and the run's kind: live, trial or measurement (a
    measurement's item has no package: anyone's)."""
    run = c.execute("SELECT workpackage_id, mode, actor FROM runs WHERE run_id=?", (store.run_of(flow_run_id),)).fetchone()
    if run is None:
        return None, "measurement"
    return assignee_for(c, run["workpackage_id"], run["actor"]), "live" if run["mode"] == "apply" else "trial"


def _open_review(c: sqlite3.Connection, item: sqlite3.Row, by: actors.Actor) -> str:
    assignee, origin = _raised_by(c, item["run_id"])
    return tasks.open_in(c, REVIEW, str(item["id"]), by, assignee=assignee,
                         detail={"subject_kind": item["subject_kind"], "subject_id": item["subject_id"],
                                 "run": store.run_of(item["run_id"]), "origin": origin})


def review_item_changed(c: sqlite3.Connection, review_id: int, change: str, actor: actors.Who | None) -> None:
    """The store's hook, in the transaction of the change. An item raised and still open: its task opens, or (open)
    goes to whom the rule names for the run that raised it now. An item closed: its task is decided when a person
    resolved its last reason (the outcome lists the reasons people resolved), withdrawn otherwise."""
    item = c.execute("SELECT id, subject_kind, subject_id, run_id, status FROM review_queue WHERE id=?",
                     (review_id,)).fetchone()
    if item is None:
        return
    tid = tasks.task_id(REVIEW, str(review_id))
    task = tasks.task_in(c, tid)
    if item["status"] == "open":
        if change != store.REVIEW_RAISED:
            return
        if task is None or task.status != tasks.OPEN:
            _open_review(c, item, MACHINE)
        else:
            tasks.assign_in(c, tid, _raised_by(c, item["run_id"])[0], MACHINE)
        return
    if task is None or task.status != tasks.OPEN:
        return
    if item["status"] == "resolved" and person(actor) != MACHINE:
        resolved = [r["id"] for r in c.execute("SELECT id FROM review_reasons WHERE review_id=? AND status='resolved'"
                                               " ORDER BY id", (review_id,))]
        tasks.decide_in(c, tid, person(actor), outcome={"resolved": resolved})
    else:
        tasks.withdraw_in(c, tid, person(actor), note=f"the to-dos were closed: {item['status']}")


store.set_review_item_hook(review_item_changed)


# --- a logic pack's own approval -----------------------------------------------------------------------------------------


def own_approval_waits(c: sqlite3.Connection, wp_id: str, *, by: actors.Actor = MACHINE,
                       reopened: int | None = None) -> str:
    """The package waits for its own approval, in the caller's transaction ("opened", "reopened" or "exists"): made, or
    its approved version `reopened`."""
    return tasks.open_in(c, OWN_APPROVAL, wp_id, by, assignee=assignee_for(c, wp_id, None),
                         detail={"workpackage_id": wp_id, **({"reopened": reopened} if reopened is not None else {})})


def package_made(c: sqlite3.Connection, wp_id: str, kind: str) -> None:
    """A new package, in the transaction that writes it: one of a logic pack a person approves as its own version
    waits for that approval."""
    if kind in logic_packs.kinds_with_own_approval():
        own_approval_waits(c, wp_id)


def own_approved(c: sqlite3.Connection, wp_id: str, actor: actors.Who, *, version: int, fingerprint: str) -> None:
    """The package's own version `version` was approved, in that transaction: its task is decided by the approver on
    what they approved, and its workflow step hears of it."""
    tid = tasks.task_id(OWN_APPROVAL, wp_id)
    task = tasks.task_in(c, tid)
    if task is None or task.status != tasks.OPEN:
        return
    tasks.decide_in(c, tid, person(actor), outcome={"version": version}, result_ref=fingerprint)
    _settled(c, wp_id, tid, task.round, tasks.DECIDED, person(actor))


def package_deleted(c: sqlite3.Connection, wp_id: str, actor: actors.Who) -> None:
    """The package was deleted, in that transaction: nothing waits for its own approval any more."""
    tid = tasks.task_id(OWN_APPROVAL, wp_id)
    if (task := tasks.task_in(c, tid)) is not None and task.status == tasks.OPEN:
        tasks.withdraw_in(c, tid, person(actor), note="the package was deleted")


# --- a package's new responsible person ---------------------------------------------------------------------------------

# the package's runs and the to-dos they raised, each with the creator the rule falls back on: the run's starter
_PACKAGE_RUNS = "SELECT run_id, actor FROM runs WHERE workpackage_id=?"
_PACKAGE_REVIEWS = ("SELECT q.id, r.actor FROM review_queue q"
                    " JOIN runs r ON r.run_id = substr(q.run_id, 1, instr(q.run_id || ':', ':') - 1)"
                    " WHERE r.workpackage_id=?")


def _package_tasks(c: sqlite3.Connection, wp_id: str) -> list[tuple[str, str | None]]:
    """The open tasks about a package with the creator the rule falls back on: its runs' approvals and the to-dos its
    runs raised (the run's starter), its own approval (none). 229: the core's tasks through its own reads."""
    runs = {r["run_id"]: r["actor"] for r in c.execute(_PACKAGE_RUNS, (wp_id,))}
    reviews = {str(r["id"]): r["actor"] for r in c.execute(_PACKAGE_REVIEWS, (wp_id,))}
    found: list[tuple[str, str | None]] = [
        (t.task_id, runs[t.subject]) for t in tasks.of_kind_in(c, RUN_APPROVAL, status=tasks.OPEN) if t.subject in runs]
    found += [(t.task_id, reviews[t.subject]) for t in tasks.of_kind_in(c, REVIEW, status=tasks.OPEN)
              if t.subject in reviews]
    own = tasks.task_in(c, tasks.task_id(OWN_APPROVAL, wp_id))
    if own is not None and own.status == tasks.OPEN:
        found.append((own.task_id, None))
    return found


def package_owner_changed(c: sqlite3.Connection, wp_id: str) -> int:
    """The package's responsible person changed, in that change's transaction: its open tasks (its runs' approvals,
    the to-dos its runs raised last, its own approval, its workflow step's budget) go to whom the rule names now.
    Returns how many moved."""
    moved = 0
    for tid, creator in [*_package_tasks(c, wp_id), *workflow_cases.budget_tasks_of(c, wp_id)]:
        moved += tasks.assign_in(c, tid, assignee_for(c, wp_id, creator), MACHINE)
    return moved


# --- the work made before -----------------------------------------------------------------------------------------------

# the subjects that wait for a person: an open to-do item, a finished live run not yet approved, a logic pack's package
# without an approved own version of its kind (229: compared with the core's tasks through its own reads)
_OPEN_REVIEWS = "SELECT q.id, q.subject_kind, q.subject_id, q.run_id FROM review_queue q WHERE q.status='open' ORDER BY q.id"
_WAITING_RUNS = ("SELECT r.run_id FROM runs r WHERE r.mode='apply' AND r.approval IS NULL"
                 f" AND r.status IN ({', '.join(repr(s) for s in FINISHED)}) ORDER BY r.created_at, r.run_id")
_APPROVED_OWN = ("SELECT DISTINCT workpackage_id FROM package_versions WHERE content IS NOT NULL"
                 " AND reopened_at IS NULL")
_WAITING_OWN = ("SELECT w.id FROM workpackages w WHERE w.source_kind IN ({kinds}) AND NOT EXISTS (SELECT 1 FROM"
                " package_versions v WHERE v.workpackage_id = w.id AND v.content IS NOT NULL AND v.reopened_at IS NULL)"
                " ORDER BY w.created_at, w.id")
SETTLED_UNSEEN = "settled while no task was kept"


def _stale(conn: sqlite3.Connection, reviews: list[sqlite3.Row], runs: list[str]) -> list[str]:
    """The open tasks whose subject no longer waits for a person: an item closed, a run approved, superseded or
    stopped, a logic pack approved or deleted (by a version that keeps no task)."""
    open_items, waiting_runs = {str(r["id"]) for r in reviews}, set(runs)
    packages = {r["id"] for r in conn.execute("SELECT id FROM workpackages")}
    approved = {r["workpackage_id"] for r in conn.execute(_APPROVED_OWN)}
    stale = [t.task_id for t in tasks.of_kind_in(conn, REVIEW, status=tasks.OPEN) if t.subject not in open_items]
    stale += [t.task_id for t in tasks.of_kind_in(conn, RUN_APPROVAL, status=tasks.OPEN) if t.subject not in waiting_runs]
    stale += [t.task_id for t in tasks.of_kind_in(conn, OWN_APPROVAL, status=tasks.OPEN)
              if t.subject not in packages or t.subject in approved]
    return sorted(stale)


def _missing(conn: sqlite3.Connection) -> tuple[list[sqlite3.Row], list[str], list[str], list[str]]:
    kinds = logic_packs.kinds_with_own_approval()  # complete once the registrations are loaded; else at a later start
    open_reviews = conn.execute(_OPEN_REVIEWS).fetchall()
    waiting_runs = [r["run_id"] for r in conn.execute(_WAITING_RUNS)]
    own = [r["id"] for r in conn.execute(_WAITING_OWN.format(kinds=", ".join("?" * len(kinds))), kinds)] if kinds else []
    have = {kind: tasks.ids_of_kind_in(conn, kind) for kind in (REVIEW, RUN_APPROVAL, OWN_APPROVAL)}
    return ([r for r in open_reviews if tasks.task_id(REVIEW, str(r["id"])) not in have[REVIEW]],
            [r for r in waiting_runs if tasks.task_id(RUN_APPROVAL, r) not in have[RUN_APPROVAL]],
            [w for w in own if tasks.task_id(OWN_APPROVAL, w) not in have[OWN_APPROVAL]],
            _stale(conn, open_reviews, waiting_runs))


def adopt_missing(conn: sqlite3.Connection) -> int:
    """The store's schema change helper (`store.register_migration`): every open to-do item, every finished live run
    waiting for its approval and every logic pack waiting for its own approval without a task gets one, by the owner's
    rule, opened by the adoption; an open task whose subject no longer waits (settled by a version that keeps no task)
    is withdrawn by it. In one write transaction checked again inside it, so two processes starting at once do each
    once. Returns how many tasks it opened or withdrew."""
    if not any(_missing(conn)):
        return 0
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        reviews, runs, own, stale = _missing(conn)
        for item in reviews:
            _open_review(conn, item, ADOPTION)
        for run_id in runs:
            open_run_approval(conn, run_id, by=ADOPTION)
        for wp_id in own:
            own_approval_waits(conn, wp_id, by=ADOPTION)
        for tid in stale:
            tasks.withdraw_in(conn, tid, ADOPTION, note=SETTLED_UNSEEN)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return len(reviews) + len(runs) + len(own) + len(stale)
