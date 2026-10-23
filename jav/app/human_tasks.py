"""215 (plan G-process-core P2): today's work as human tasks of the process core (`jav.core.process.tasks`).

Plain-language summary: what waits for a person in the application becomes a human task, written in the same
transaction as the change that raises or settles it, so a task and what it is about never part. Whom a task is for is
the owner's rule (decision of 2026-10-23): the package's responsible person; a package without one goes to its
creator (the person who started the run, or who made the workflow) when that person is on the Users list; otherwise
it is anyone's. No task gets a deadline (decision of 2026-10-23).

- `run_approval:<run>`: a finished live run waits for a person (opened when the run finishes unapproved, by
  `work_runs.refresh_run_status`; decided by its approval; withdrawn when it is superseded or stopped). The task
  belongs to the run, not to a workflow: a run that waits to be superseded outlives its workflow step. When the run's
  package is a workflow step's, its approval or withdrawal sends the workflow's case an event in the same transaction
  (`workflow_cases.package_settled`), so the chain moves on at once.
- The budget a workflow step waits for is `jav.app.workflow_cases`' task (`workflow_budget`), for the person this
  module names.

Layer: application operation; it imports the shared core and `jav.app.workflow_cases` (which imports only the core),
no domain module.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from jav.app import workflow_cases
from jav.core.process import actor as actors
from jav.core.process import tasks

RUN_APPROVAL = "run_approval"
FINISHED = ("needs_review", "done", "failed")  # a live run in these states, unapproved, waits for a person
MACHINE = actors.machine("work-runs")

tasks.register_kind(tasks.TaskKind(RUN_APPROVAL, __name__))


def assignee_for(c: sqlite3.Connection, wp_id: str | None, creator: str | None) -> str | None:
    """The owner's rule: the package's responsible person; without one, `creator` when on the Users list (as the list
    writes the name; any name while the list is empty); otherwise anyone (None)."""
    from jav.app import app_settings  # lazy: app_settings imports the work package module

    if wp_id is not None:
        row = c.execute("SELECT owner FROM workpackages WHERE id=?", (wp_id,)).fetchone()
        if row is not None and row["owner"] and row["owner"].strip():
            return actors.person(row["owner"]).id
    if not creator or not creator.strip():
        return None
    # on the caller's connection, inside its write transaction (another connection would wait for its lock); a store
    # that has no name list yet is one with an empty list
    listed = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_users'").fetchone() is not None
    name = app_settings.canonical_user(creator, c) if listed else " ".join(creator.split())
    return actors.person(name).id if name else None


def person(name: str | None) -> actors.Actor:
    """Who acts on a task: the named person, or the machine when no name came with the change."""
    return actors.person(name) if name and name.strip() else MACHINE


def open_run_approval(c: sqlite3.Connection, run_id: str) -> str | None:
    """The run's approval task when it is a finished, unapproved live run, in the caller's transaction ("opened" or
    "exists"); None for any other run."""
    run = c.execute("SELECT workpackage_id, mode, status, approval, actor FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if run is None or run["mode"] != "apply" or run["approval"] is not None or run["status"] not in FINISHED:
        return None
    return tasks.open_in(c, RUN_APPROVAL, run_id, MACHINE, assignee=assignee_for(c, run["workpackage_id"], run["actor"]),
                         detail={"workpackage_id": run["workpackage_id"]})


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
        workflow_cases.package_settled(c, row["workpackage_id"], f"{tid}#{task.round}",
                                       {"task": tid, "round": task.round,
                                        "status": tasks.DECIDED if approved is not None else tasks.WITHDRAWN}, actor)


def run_approved(c: sqlite3.Connection, run_id: str, actor: str, outcome: dict[str, Any]) -> None:
    """The run was approved, in the approval's transaction: its task is decided by the approver."""
    _settle(c, run_id, person(actor), approved=outcome)


def run_withdrawn(c: sqlite3.Connection, run_id: str, actor: str | None, note: str) -> None:
    """The run no longer waits for an approval (superseded, stopped), in that change's transaction."""
    _settle(c, run_id, person(actor), approved=None, note=note)
