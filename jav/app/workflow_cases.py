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

The workflow's own data (its party, period, steps' sources, budgets, packages, and the step state the interface
reads) stay in its own tables (`jav.app.workflows`).

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

from jav.core.process import actor as actors
from jav.core.process import cases
from jav.core.process.cases import Adopted
from jav.core.process.definition import ProcessDef, StepDef

log = logging.getLogger(__name__)

STEP_KIND = "workflow_step"  # the core's one step kind for a workflow's steps; the step's own kind is its parameter
ARCHIVED = "archived"  # the hold of an archived workflow's case
FETCH, APPROVAL, BUDGET = "fetch", "approval", "budget"  # what a running workflow step waits for
CHECK = "check"  # the timer of a step that waits for its fetch or its package's approval
ADOPTION = "workflow-adoption"  # the machine that adopts the workflows made before

# a workflow step's stored state -> the core's state and what a running step waits for (adoption)
_ADOPTED: dict[str, tuple[str, str | None]] = {
    "waiting": (cases.WAITING, None), "starting": (cases.RUNNING, None), "pulling": (cases.RUNNING, FETCH),
    "started": (cases.RUNNING, APPROVAL), "linked": (cases.RUNNING, APPROVAL), "needs_budget": (cases.RUNNING, BUDGET),
    "nothing_new": (cases.DONE, None), "failed": (cases.FAILED, None),
}

_MISSING = ("SELECT id FROM workflows w WHERE NOT EXISTS (SELECT 1 FROM process_cases c WHERE c.case_id=w.id)"
            " ORDER BY created_at, id")


def definition(template: Mapping[str, Any]) -> ProcessDef:
    """The process definition of a workflow's saved template; its version is the saved template's fingerprint."""
    saved = json.dumps(template, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return ProcessDef(
        id=f"workflow_{template['id']}", version=hashlib.sha256(saved.encode("utf-8")).hexdigest()[:12],
        title=template["title"],
        steps=tuple(StepDef(id=s["id"], kind=STEP_KIND, title=s.get("title"), after=tuple(s.get("after", ())),
                            params={"kind": s["kind"]}) for s in template["steps"]))


def maker(name: str) -> actors.Actor:
    """The person who made the workflow (its `actor`) or acts on it, as the core records them."""
    return actors.person(name)


def _data(wf_id: str) -> dict[str, Any]:
    return {"workflow": wf_id}


def start(c: sqlite3.Connection, wf_id: str, template: Mapping[str, Any], actor: str) -> str:
    """The new workflow's case, in the caller's transaction that writes the workflow."""
    return cases.start_in(c, wf_id, definition(template), _data(wf_id), maker(actor))


def _adopted(state: str, note: str | None, now: float) -> Adopted:
    if state not in _ADOPTED:
        raise cases.AdoptionError(f"a workflow step state {state!r} has no state in the process core")
    core, waits = _ADOPTED[state]
    return Adopted(core, waiting_for=waits, note=note if core == cases.FAILED else None,
                   timer=(CHECK, now) if waits in (FETCH, APPROVAL) else None)


def adopt(c: sqlite3.Connection, wf_id: str) -> str | None:
    """Adopts a workflow without a case from the state its steps reached, in the caller's write transaction ("adopted");
    None when it has its case. An archived workflow's case is held."""
    if c.execute("SELECT 1 FROM process_cases WHERE case_id=?", (wf_id,)).fetchone() is not None:
        return None
    row = c.execute("SELECT definition, actor, status FROM workflows WHERE id=?", (wf_id,)).fetchone()
    if row is None:
        raise KeyError(wf_id)
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
    if conn.execute(_MISSING).fetchone() is None:
        return 0
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    adopted = 0
    try:
        for (wf_id,) in conn.execute(_MISSING).fetchall():
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


def set_archived(c: sqlite3.Connection, wf_id: str, archived: bool, actor: str) -> None:
    """Holds the workflow's case when it is archived and resumes it when it is restored, in the caller's transaction
    that changes the workflow (a workflow without a case is adopted first)."""
    adopt(c, wf_id)
    if archived:
        cases.hold(c, wf_id, ARCHIVED, maker(actor))
    else:
        cases.resume(c, wf_id, ARCHIVED, maker(actor))
