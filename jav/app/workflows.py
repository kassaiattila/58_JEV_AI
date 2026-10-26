"""146 (backlog F-package-kind-chooser; DECISIONS 146): workflows - the work packages of one job, chained.

The owner's decisions of 2026-10-11: the real work is a chain (emails and their attachments, or a folder's invoices;
bank statements; their reconciliation), so the kinds of work package are offered as templates (`configs/workflows.json`)
in a step-by-step wizard, and a template of several steps makes a **workflow**: the steps' work packages for one own
party and a period, with a control view of where the chain stands. The chain is automatic: a step starts by itself
once the steps it waits for (`after`) are approved, as a live run (a person still clears its to-dos and approves it);
a paid step only when the run's own estimate fits the budget a person approved for it in the wizard, otherwise it waits
for a person (`needs_budget`). The budget is never raised by itself.

A step's source is what the wizard gathered: a folder or files (documents, statements), a mailbox request (emails), an
existing work package (linked as it is; the chain starts no run on it) or nothing (the reconciliation, made for the
party's accounts and the period once its steps are done). A step is **satisfied** when its package's latest live run is
approved (a reconciliation: when a version is approved) or when it found nothing new (an empty folder, a download
without new emails, statements the store has already); an empty package is not kept.

Where a step's start stands is its phase: `waiting`, `starting` (claimed: one process at a time), `pulling` (a mailbox
download queued), `started`, `linked`, `needs_budget`, `nothing_new`, `failed`. What a person sees (`status`) adds the
package's own next step. `advance` moves the chain on; the worker calls `tick` in its loop (at most every
`TICK_EVERY_S`), the service on creation and when a person starts a step.

214 (plan G-process-core P1b-2): a workflow is a case of the process core under its own id (`jav.app.workflow_cases`):
the case starts in the transaction that makes the workflow, a workflow made before is adopted from the state its steps
reached, and archiving or restoring a workflow holds or resumes its case. P1b-3: the core moves the steps on. Its one
workflow step kind (`_case_step`) does under the case's claim what the step's phase asks for; `advance` is one woken
turn of the case, `tick` the worker's turns; a person's start, link and the chain switched on reach the case in the
transaction of the workflow's own change.

227 (plan R3 R3d; DECISIONS 227): a step's whole state is in its row in the case: the core's state and wait, and the
phase as the core step's own (`process_cases.set_phase`, a claim with `expect`), written with the step's own data and
its event in one transaction (`_update_step`); the interface reads the phase from there. The workflow's table keeps the
step's own data only (its source, budget, name, engine, package, download, run and note). Before, the phase was a
column of that table (`state`), kept beside the core's state.

215 (P2b): a step over its budget asks a person as a human task, opened with the wait (`workflow_cases.ask_budget`)
and decided by the person's start; the approval of a run of a step's package sends the case an event
(`jav.app.human_tasks`), which the worker takes at each of its rounds (229: the process core's own round,
`process_engine.turn_due`, which turns every case with something to do, not throttled like `tick`), so the chain moves
on at once. The check timer stays as the safety net.

218 (plan P3 P3l; DECISIONS 218): a step builds on the approved result of its earlier steps. A done step's result
names the approval its package was done with (`_approval`) and those its earlier steps were done with (`built_on`).
When an earlier step is reopened (a new live run of its package, its own version reopened:
`workflow_cases.package_reopened`), the steps built on it are out of date: the control view shows them so (`stale_of`)
and they do not count as done; once the earlier step is approved again, a step's old approval does not count either
(`_counts`): the chain reopens a logic pack's own version with a reason, so a person approves it again. Nothing runs
by itself.

147 (DECISIONS 147): a workflow is repeated for the next period from a draft the wizard shows filled in
(`repeat_draft`); a documents step may take only the documents no live run has processed yet (`only_new`), so the
folder of a year's invoices does not bring last month's back. The two workflows are linked (`previous_id`).

181 (plan 170 L5 = plan 160-E S6): the step kinds come from a registry (`jav/app/workflow_steps.py`): which packages a
step takes, how it starts, whether its source is fetched first, its engine, its repeat source, its estimate and what its
package's next step means. This module registers the documents step (the plain processing of a folder or files); the
email domain registers the emails step, the finance domain the statements and reconciliation steps. The workflow's
code names none of them.

Layer: UI/CLI → **this** (application operation) → `jav.app.work`, `jav.app.workflow_cases` (214: the process core),
`jav.app.workflow_steps` (and through it the registered
kinds' modules; 185: a domain's source kind, the mailbox's), `jav.app.parties` and `jav.app.work_views.next_step`. No AI call here: the runs it starts call
them, within their budgets.

231 (plan stage C, C3i): the workflows' records (their tables, templates, rows, steps, events and views, and the
checks of a new one) are `workflow_records.py`, how a workflow moves on (a step's start, the worker's tick, the process
core's turns, the wizard's estimate) `workflow_advance.py`; this module keeps making one and repeating one, and
re-exports the names its callers use.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from typing import Any

from jav.app import (
    scopes, work, workflow_cases, workflow_steps,
)
from jav.core import activity_kinds, identity, store
from jav.core.user_messages import explained
from jav.core.clock import utc_stamp as _now
from jav.app.workflow_records import (WorkflowError, _brief, _budget, _engine, _event, _period, _row, _source,
    _step_title, _steps, is_workflow, template, view)
from jav.app.workflow_advance import advance

# 231 (C3i): the shared names the callers use, re-exported (a fixed list: new code imports from the defining module)
from jav.app.workflow_records import (CONFIG as CONFIG, DOCUMENT_PACKAGES as DOCUMENT_PACKAGES, DOCUMENTS as DOCUMENTS,
    OLD_APPROVAL as OLD_APPROVAL, PACKAGE_DELETED as PACKAGE_DELETED, PROVIDERS as PROVIDERS,
    REAPPROVE_NOTE as REAPPROVE_NOTE, STALE_START_S as STALE_START_S, STATUS_BY_NEXT as STATUS_BY_NEXT,
    TICK_EVERY_S as TICK_EVERY_S, auto_actor as auto_actor, config as config, register as register,
    resolved as resolved, step_scope as step_scope, templates_view as templates_view, workflow_of as workflow_of,
    workflows as workflows)
from jav.app.workflow_advance import (BUDGET_GATE as BUDGET_GATE, INTERRUPTED as INTERRUPTED,
    budget_gate as budget_gate, documents_offer as documents_offer, estimate as estimate, link as link,
    release_stale_starts as release_stale_starts, start_step as start_step, tick as tick, update as update)


# 175 (plan 170 E4): the actions a workflow's log records (`jav/core/activity_kinds.py`)
activity_kinds.register_events("workflow", ("create", "update", "budget", "link", "pull", "pull_interrupted", "package", "run",
                                            "needs_budget", "nothing_new", "left_out", "failed"), __name__)


def template_needs(t: dict[str, Any]) -> list[str]:
    """181: the parts of the scope a template's steps need (their step kinds' `needs`), in the parts' order."""
    needed = {n for step in t["steps"] for n in workflow_steps.step_needs(step)}  # 231 (C3a-1): a process step's pack's
    return [p.name for p in scopes.parts() if p.name in needed]


@store.one_connection
def create(*, template_id: str, party_id: str | None, period_start: Any, period_end: Any,
           steps: dict[str, dict[str, Any]], actor: identity.Who, name: str | None = None, names: dict[str, str] | None = None,
           auto: bool = True, advance_now: bool = True, previous: str | None = None) -> dict[str, Any]:
    """A new workflow of a template of several steps: every step needs its source (`steps[step]["source"]`) and may
    have a budget (`steps[step]["budget"]`, {provider: usd}); `names` are the steps' package names (the interface
    passes them in its language). With `advance_now` the steps that wait for nothing start at once. `previous` (147):
    the workflow this one repeats for the next period (`repeat_draft`). 181: the party and the period are needed only
    when the template's steps need them (`template_needs`); given without being needed, they are kept."""
    t = template(template_id)
    if not is_workflow(t):
        raise explained(WorkflowError, "a one-step template makes a work package, not a workflow")
    if previous is not None and _brief(previous) is None:
        raise explained(WorkflowError, "no workflow {{previous}} to repeat", previous=repr(previous))
    given = {scopes.PARTY: party_id or None,
             scopes.PERIOD: (period_start, period_end) if period_start or period_end else None}
    scope = scopes.check(template_needs(t), given, error=WorkflowError)
    start, end = scope.get(scopes.PERIOD) or (None, None)
    defs = {s["id"]: s for s in t["steps"]}
    if unknown := set(steps) - set(defs):
        raise explained(WorkflowError, "unknown step(s) of {{template_id}}: {{unknown}}",
                        template_id=template_id, unknown=sorted(unknown))
    title = name.strip() if name and name.strip() else scopes.label(scope) or t["title"]
    rows = []
    for sid, sdef in defs.items():
        given = steps.get(sid) or {}
        if "source" not in given:
            raise explained(WorkflowError, "step {{sid}} needs its source", sid=repr(sid))
        source = _source(sdef["kind"], given["source"])
        step_name = ((names or {}).get(sid) or f"{title} · {_step_title(sdef)}").strip()[:200]
        rows.append((sid, source, _budget(given.get("budget")), step_name, _engine(sdef["kind"], source, given.get("engine"))))
    wf_id = f"wf-{uuid.uuid4().hex[:12]}"
    now = _now()
    with store.connect() as c:
        store.begin_immediate(c)
        other = {k: v for k, v in scope.items() if k not in (scopes.PARTY, scopes.PERIOD)}  # 181: a further part
        c.execute("INSERT INTO workflows(id, template, definition, name, party_id, period_start, period_end, auto, actor,"
                  " actor_id, created_at, updated_at, previous_id, scope) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (wf_id, t["id"], json.dumps(t, ensure_ascii=False), title[:200], scope.get(scopes.PARTY), start, end,
                   int(auto), identity.name_of(actor), identity.id_of(actor), now, now, previous,
                   json.dumps(other, ensure_ascii=False)))
        for sid, source, budget, step_name, engine in rows:
            c.execute("INSERT INTO workflow_steps(workflow_id, step, source, budget, name, workpackage_id, updated_at,"
                      " engine) VALUES (?,?,?,?,?,?,?,?)",
                      (wf_id, sid, json.dumps(source, ensure_ascii=False), json.dumps(budget), step_name,
                       source.get("workpackage_id"), now, engine))
        workflow_cases.start(c, wf_id, t, actor,  # 214: its case, with its rows or neither; 227: its steps' phases
                             linked=tuple(sid for sid, source, *_ in rows if source["kind"] == "package"))
        _event(c, wf_id, None, "create", actor, {"template": t["id"], "party": scope.get(scopes.PARTY),
                                                  "period": [start, end] if start else None, "auto": bool(auto)}
               | ({"previous": previous} if previous else {}))
    if advance_now:
        advance(wf_id, actor=actor)
    return view(wf_id)


def _first_of_month_after(d: date, months: int) -> date:
    m = d.month - 1 + months
    return date(d.year + m // 12, m % 12 + 1, 1)


def next_period(start: Any, end: Any) -> tuple[str, str]:
    """The period after this one: whole calendar months are followed by as many months (a month by the next month, a
    quarter by the next quarter); any other period by one as long, right after it."""
    a, b = (date.fromisoformat(d) for d in _period(start, end))
    after = b + timedelta(days=1)
    if a.day == 1 and after.day == 1:
        months = (after.year - a.year) * 12 + after.month - a.month
        return after.isoformat(), (_first_of_month_after(after, months) - timedelta(days=1)).isoformat()
    return after.isoformat(), (after + (b - a)).isoformat()


def _package_source(kind: str, wp_id: str) -> dict[str, Any] | None:
    """The source a linked package's step repeats from, by its kind (181: `StepKind.repeat_from`): the package's folder
    (a documents or statements package made from one), nothing for a reconciliation; None when it cannot be told (the
    wizard asks for it). A step that leaves out processed documents does so in its folder too."""
    step = workflow_steps.of(kind)
    src = step.repeat_from(wp_id) if step.repeat_from else None
    if src is not None and src["kind"] == "folder" and step.only_new:
        src = src | {"only_new": True}
    return src


def repeat_from_folder(wp_id: str) -> dict[str, Any] | None:
    """The documents step's repeat source: the folder its linked package was made from (a folder or watched one); 231
    (C3b5b) the documents maker's (`jav/app/document_processing.py`)."""
    try:
        wp = work.get(wp_id)
    except KeyError:
        return None
    return workflow_steps.folder_source(wp, ("folder", "watch"))


def _repeated_source(kind: str, source: dict[str, Any], period: tuple[str, str] | None,
                     wf: dict[str, Any]) -> dict[str, Any] | None:
    if source["kind"] == "package":
        return _package_source(kind, source["workpackage_id"])
    if workflow_steps.of(kind).only_new and source["kind"] in ("folder", "files"):
        return source | {"only_new": True}  # last period's documents are not brought back
    if (domain := workflow_steps.source_kind(source["kind"])) is not None:  # 185: a mailbox's dates move on
        return domain.repeated(source, period, wf)
    return source


def repeat_draft(wf_id: str) -> dict[str, Any]:
    """The workflow for the next period as the wizard shows it filled in: the template, the party, the steps' sources and
    budgets, the name with the new period (None when the name does not hold the period: the wizard proposes one). A
    documents step takes only the documents no live run has processed; a mailbox's dates move on. Nothing is written: a
    person checks it and makes the new workflow (`create` with `previous`), approving its budgets again. 181: a workflow
    without a period is repeated as it is, under its own name."""
    wf = _row(wf_id)
    name = wf["name"]
    period = next_period(wf["period_start"], wf["period_end"]) if wf["period_start"] else None
    if period is None:
        new_name: str | None = name
    elif wf["period_start"] in name and wf["period_end"] in name:
        new_name = name.replace(wf["period_start"], period[0]).replace(wf["period_end"], period[1])
    else:
        new_name = None
    steps = _steps(wf_id)
    return {"template": wf["template"], "party_id": wf["party_id"], "period_start": period[0] if period else None,
            "period_end": period[1] if period else None, "name": new_name,
            "auto": wf["auto"], "previous": wf_id,
            "steps": {s["id"]: {"source": _repeated_source(s["kind"], steps[s["id"]]["source"], period, wf),
                                "budget": steps[s["id"]]["budget"], "engine": steps[s["id"]].get("engine")}
                      for s in wf["definition"]["steps"]}}
