"""216 (plan G-process-core P2e): the "Waiting for me" list - the open human tasks for the person working now.

Plain-language summary: the list shows what waits for a person: their own tasks and anyone's (a task the owner's rule
gave to nobody), each with its kind, what it is about, its package, since when it waits, where it comes from (a live
run, a trial run, an earlier measurement) and where it is done. By default only live work shows: a live run's to-dos
and every approval and budget; on request the to-dos of trial runs and measurements too (the owner's decisions of
2026-10-23). The rows are read from the process core's tasks (`jav.core.process.tasks`) and what they are about; the
list changes nothing.

Each row's `_wp` and `_stage` say where the work is done (the dataset's `next` link): a to-do opens its item's review
page, a run's approval the package's result, a logic pack's approval and a step's budget the package's page. 231
(A7d): a task of a process pack's case (a step's start, a message whose arrival is unknown, a follow-up) opens the case's
page, named by its step.

Layer: application view, read only; it imports the shared core and the application's views, no domain module.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jav.app import human_tasks, item_kinds, logic_packs, work_views, workflow_cases
from jav.core import store
from jav.core import identity as actors
from jav.core.process import cases, tasks

LIVE, TRIAL, MEASUREMENT = "live", "trial", "measurement"  # where a task comes from
MINE, ANYONE = "mine", "anyone"  # whom it is for, seen from the person

Row = dict[str, Any]


class _Packages:
    """What the rows of one list read about the packages: their names and, per package, its items by the subject of
    their to-dos with their titles (each package read once)."""

    def __init__(self, c: sqlite3.Connection) -> None:
        self.c = c
        self.rows = {r["id"]: dict(r) for r in c.execute("SELECT id, name, source_kind, source_ref FROM workpackages")}
        self._items: dict[str, dict[tuple[str, str], tuple[str, str]]] = {}

    def item(self, wp_id: str, subject: tuple[str, str]) -> tuple[str, str] | None:
        """The package's item whose to-dos have this subject: (its id, its title); None when it has none."""
        if wp_id not in self._items:
            items = [dict(r) for r in self.c.execute("SELECT * FROM workpackage_items WHERE workpackage_id=?", (wp_id,))]
            titles = work_views.item_titles(items, work_views.package_root(self.rows.get(wp_id, {})))
            self._items[wp_id] = {item_kinds.of(i).subject(i): (i["item_id"], titles.get(i["item_id"])
                                                                or Path(i["source_path"]).name) for i in items}
        return self._items[wp_id].get(subject)


def _review(packages: _Packages, task: tasks.Task) -> Row:
    """A to-do item: the item's title in the package of the run that raised it last, its first open reason and how many
    are open; the review page of that item. An item a measurement raised has no package (its document's file name)."""
    c = packages.c
    q = c.execute("SELECT subject_kind, subject_id, run_id, reasons FROM review_queue WHERE id=?",
                  (int(task.subject),)).fetchone()
    reasons = json.loads(q["reasons"] or "[]") if q else []
    row: Row = {"what": task.detail.get("subject_id"), "reason": reasons[0] if reasons else None, "reasons": len(reasons),
                "origin": MEASUREMENT, "_wp": None, "_stage": None}
    if q is None:
        return row
    run = c.execute("SELECT workpackage_id, mode FROM runs WHERE run_id=?", (store.run_of(q["run_id"]),)).fetchone()
    if run is None:
        doc = c.execute("SELECT source_path FROM documents WHERE doc_id=?", (q["subject_id"],)).fetchone()
        return {**row, "what": Path(doc["source_path"]).name if doc else q["subject_id"]}
    row.update(origin=LIVE if run["mode"] == "apply" else TRIAL, _wp=run["workpackage_id"], _stage="review")
    found = packages.item(run["workpackage_id"], (q["subject_kind"], q["subject_id"]))
    if found is not None:
        row.update(what=found[1], _stage=f"review/{found[0]}")
    return row


def _run_approval(packages: _Packages, task: tasks.Task) -> Row:
    """A finished live run waiting for its approval: the package's result, where it is approved and released."""
    run = packages.c.execute("SELECT workpackage_id FROM runs WHERE run_id=?", (task.subject,)).fetchone()
    return {"what": "Live run", "origin": LIVE, "_wp": run["workpackage_id"] if run else None, "_run": task.subject,
            "_stage": "result"}


def _own_approval(packages: _Packages, task: tasks.Task) -> Row:
    """A logic pack waiting for a person's approval of its own version: the package's page."""
    wp = packages.rows.get(task.subject)
    pack = logic_packs.of(wp["source_kind"]) if wp else None  # 229 (MD2): what its approval is about, the pack's own
    return {"what": pack.approval_what if pack else "Approval", "origin": LIVE, "_wp": task.subject, "_stage": None}


def _budget(packages: _Packages, task: tasks.Task) -> Row:
    """A workflow step over its budget: the step's package's page, which names its workflow."""
    wf_id, _, step = task.subject.rpartition(":")
    row = packages.c.execute("SELECT workpackage_id FROM workflow_steps WHERE workflow_id=? AND step=?",
                             (wf_id, step)).fetchone()
    return {"what": step, "origin": LIVE, "_wp": row["workpackage_id"] if row else None, "_stage": None}


_ROWS: dict[str, Callable[[_Packages, tasks.Task], Row]] = {
    human_tasks.REVIEW: _review, human_tasks.RUN_APPROVAL: _run_approval, human_tasks.OWN_APPROVAL: _own_approval,
    workflow_cases.BUDGET_TASK: _budget,
}


def _case_task(packages: _Packages, task: tasks.Task) -> Row | None:
    """231 (A7d): a task of a case whose container is a work package (a process pack's case): the case's page, named by
    the step's title; None for another task."""
    if task.case_id is None or task.case_id not in packages.rows:
        return None
    row = cases.case_row(packages.c, task.case_id)
    step = cases.definition_of(row).step(str(task.step_id))
    return {"what": step.title or step.id, "origin": LIVE, "_wp": task.case_id, "_stage": None}


def rows(actor: str, *, every_origin: bool = False) -> list[Row]:
    """The open tasks for `actor` and anyone's, oldest first; only live work unless `every_origin`. A task of a kind
    this list does not know shows with its subject, as live work."""
    me = actors.person(actor).id
    out: list[Row] = []
    with store.connect() as c:
        packages = _Packages(c)
        for task in tasks.open_for_in(c, me):
            row = _ROWS[task.kind](packages, task) if task.kind in _ROWS else _case_task(packages, task) or {
                "what": task.subject, "origin": LIVE, "_wp": None, "_stage": None}
            if not every_origin and row["origin"] != LIVE:
                continue
            out.append({"kind": task.kind, "workpackage_name": packages.rows.get(row["_wp"], {}).get("name"),
                        "opened_at": task.opened_at, "assignee": MINE if task.assignee == me else ANYONE,
                        "reason": None, "reasons": None, **row, "_key": task.task_id})
    return out


__all__ = ["ANYONE", "LIVE", "MEASUREMENT", "MINE", "TRIAL", "rows"]
