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
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Mapping
from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from jav.app import (
    app_settings, human_tasks, logic_packs, package_release, package_scope, parties, scopes, work, work_readiness,
    work_recipes, work_runs, workflow_cases, workflow_steps,
)
from jav.core import activity_kinds, cfg, identity, store, trace
from jav.core.process import cases as process_cases
from jav.core.process import engine as process_engine
from jav.core.process import kinds as process_kinds
from jav.core.user_messages import explained
from jav.core.clock import utc_stamp as _now

# 175 (plan 170 E4): the actions a workflow's log records (`jav/core/activity_kinds.py`)
activity_kinds.register_events("workflow", ("create", "update", "budget", "link", "pull", "pull_interrupted", "package", "run",
                                            "needs_budget", "nothing_new", "left_out", "failed"), __name__)

log = logging.getLogger(__name__)

CONFIG = "workflows"
PROVIDERS = ("jev", "openai", "azure_di")  # the call log's providers (jav/core/calls.py)
# 181: the documents step's key in the templates and the work package kinds a package of it may have (the plain
# processing of a folder, files or uploads; not a mailbox's)
DOCUMENTS = "documents"
DOCUMENT_PACKAGES = ("folder", "manual", "watch", "upload")
TICK_EVERY_S = 10.0
# 153 (review D2): a start claimed this long ago and still not finished was interrupted (a service stopped while a
# large folder was fingerprinted): the step goes to `failed`, so a person can start it again. 214: the case's next turn
# finds such a start at once (`_case_step`); this stays the safety net for a start no turn reaches (an archived
# workflow's)
STALE_START_S = 3600

store.register_schema("workflows", """
CREATE TABLE IF NOT EXISTS workflows (
    id            TEXT PRIMARY KEY,
    template      TEXT NOT NULL,       -- configs/workflows.json template id
    definition    TEXT NOT NULL,       -- JSON: the template as it was when made (its steps stay, whatever the config)
    name          TEXT NOT NULL,
    party_id      TEXT,                -- the own party (jav.app.parties); 181: only when its steps need one or it was given
    period_start  TEXT,                -- ISO date (181: only with a period)
    period_end    TEXT,                -- ISO date, inclusive
    auto          INTEGER NOT NULL DEFAULT 1,   -- the chain starts the next step by itself
    status        TEXT NOT NULL DEFAULT 'open', -- open | archived
    actor         TEXT NOT NULL,       -- who made it: the owner of its packages
    actor_id      TEXT,                -- 229 (SZ2c): the stable ids beside the names (`jav.core.identity`)
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    previous_id   TEXT,                -- 147: the workflow this one repeats for the next period
    scope         TEXT NOT NULL DEFAULT '{}'  -- 181: JSON, the scope's parts beyond the party and the period
);
CREATE TABLE IF NOT EXISTS workflow_steps (
    workflow_id    TEXT NOT NULL,
    step           TEXT NOT NULL,
    source         TEXT NOT NULL,      -- JSON: {"kind": folder|files|mailbox|package|none, ...}
    budget         TEXT NOT NULL,      -- JSON {provider: usd}: the most an automatic start may reserve
    name           TEXT NOT NULL,      -- the work package's name (227: its phase is in its core row, the step's phase)
    workpackage_id TEXT,
    pull_id        TEXT,
    run_id         TEXT,
    note           TEXT,               -- why it failed, waits for a budget (JSON estimate) or found nothing
    updated_at     TEXT NOT NULL,
    engine         TEXT,               -- 160-D: jev | gpt, the step's own AI engine; NULL: the application's when it starts
    PRIMARY KEY (workflow_id, step)
);
CREATE INDEX IF NOT EXISTS ix_workflow_steps_wp ON workflow_steps(workpackage_id);
CREATE TABLE IF NOT EXISTS workflow_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    step        TEXT,
    action      TEXT NOT NULL,
    actor       TEXT NOT NULL,
    actor_id    TEXT,
    detail      TEXT,
    created_at  TEXT NOT NULL
);
""")


# 181: the workflows table as this version makes it, for the rebuild of an older one (`_general_scope`)
_TABLE = """CREATE TABLE workflows_181 (
    id TEXT PRIMARY KEY, template TEXT NOT NULL, definition TEXT NOT NULL, name TEXT NOT NULL, party_id TEXT,
    period_start TEXT, period_end TEXT, auto INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'open',
    actor TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, previous_id TEXT,
    scope TEXT NOT NULL DEFAULT '{}')"""
_COLUMNS = ("id, template, definition, name, party_id, period_start, period_end, auto, status, actor, created_at, "
            "updated_at, previous_id")


def _general_scope(conn) -> None:
    """181 (DECISIONS 181: a general scope, the table rebuilt): an older store's workflows table, whose party and period
    were required, is rebuilt with them optional and a `scope` column, its rows kept. In one write transaction, checked
    again inside it, so two processes starting at once rebuild it once."""
    def required() -> bool:
        return any(r[1] == "party_id" and r[3] for r in conn.execute("PRAGMA table_info(workflows)"))

    if not required():
        return
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        if required():
            conn.execute("DROP TABLE IF EXISTS workflows_181")
            conn.execute(_TABLE)
            conn.execute(f"INSERT INTO workflows_181({_COLUMNS}) SELECT {_COLUMNS} FROM workflows")
            conn.execute("DROP TABLE workflows")
            conn.execute("ALTER TABLE workflows_181 RENAME TO workflows")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _migrate(conn) -> None:
    store.add_columns(conn, "workflows", {"previous_id": "TEXT"})  # 147: a workflow repeated for the next period
    _general_scope(conn)  # a missing table has no required party, so nothing is rebuilt
    store.add_actor_ids(conn, "workflows", ("actor",))  # 229 (SZ2c): after the rebuild, which keeps the names
    store.add_actor_ids(conn, "workflow_events", ("actor",))
    store.add_columns(conn, "workflow_steps", {"engine": "TEXT"})  # 160-D: a step's own AI engine


store.register_migration("workflows", _migrate)
store.register_migration("workflow_cases", workflow_cases.adopt_missing)  # 214: the workflows made before get their case
store.register_migration("workflow_phases", workflow_cases.move_phases)  # 227: then the steps' phases move into the core

# 153 (review D1): a workflow names its own party and its steps' packages. A merge moves the party's workflows to the
# party it was merged into, and a party a workflow names cannot be deleted (before, the workflow kept a deleted party's
# id and every later step failed with "no own party"). Registered by `register` (173).
def _count_party(c, pid: str) -> int:
    return c.execute("SELECT COUNT(*) FROM workflows WHERE party_id=?", (pid,)).fetchone()[0]


def _repoint_party(c, old: str, new: str) -> None:
    c.execute("UPDATE workflows SET party_id=? WHERE party_id=?", (new, old))


PACKAGE_DELETED = "its package was deleted; start the step again"


def _delete_guard(c, wp_id: str) -> None:
    """153 (review D1): the package of an open workflow's step cannot be deleted (every later start of the step failed
    with the deleted package's id); it can be hidden, or the workflow archived first. An archived workflow's step lets
    its package go. 160 (review R-5): that step is failed with the reason (and its run forgotten), so after the
    workflow is restored a person can start it again; before, it kept its state without a package and stood still.
    227: it fails in its case too (a done one is reopened first), so its open budget task is withdrawn; before, the
    case still had it waiting or done."""
    row = c.execute("SELECT w.name FROM workflow_steps s JOIN workflows w ON w.id=s.workflow_id"
                    " WHERE s.workpackage_id=? AND w.status='open' LIMIT 1", (wp_id,)).fetchone()
    if row is not None:
        raise explained(work.NotReady, "the package is a step of an open workflow; archive the workflow first or hide the package",
                        [{"code": "workflow_step", "message": f"The package is a step of the workflow {row["name"]}: it can only be hidden."}])
    steps = c.execute("SELECT s.workflow_id, s.step, w.actor, w.actor_id FROM workflow_steps s"
                      " JOIN workflows w ON w.id=s.workflow_id"
                      " WHERE s.workpackage_id=?", (wp_id,)).fetchall()
    for s in steps:
        _update_step(c, s["workflow_id"], s["step"], phase="failed", workpackage_id=None, run_id=None, note=PACKAGE_DELETED)
        workflow_cases.fail_outside(c, s["workflow_id"], s["step"], PACKAGE_DELETED)
        _event(c, s["workflow_id"], s["step"], "failed", auto_actor(s), {"note": PACKAGE_DELETED, "workpackage_id": wp_id})


def register() -> None:
    """173 (plan 170 E2): the delete guard of a workflow's packages and its party reference (`registrations.load_all`).
    181: the documents step kind, and a step's package's scope (`step_scope`)."""
    work.register_delete_guard(_delete_guard)
    parties.register_reference("workflows", count=_count_party, repoint=_repoint_party)
    workflow_steps.register(DOCUMENTS_STEP)
    package_scope.register_source("workflow", step_scope)


class WorkflowError(ValueError):
    """A workflow request that cannot be met: an unknown template, step or source, or a step in the wrong state."""


def _maker(wf: dict[str, Any]) -> identity.Actor:
    """229 (SZ2c): who made the workflow, by the name and id it recorded (the owner of its steps' packages)."""
    return identity.recorded(wf["actor"], dict(wf).get("actor_id"))


def auto_actor(wf: Mapping[str, Any]) -> identity.Actor:
    """Who an automatic start is recorded for: the machine, acting for the workflow's maker; shown as the maker,
    marked (229, SZ2c-3: with the machine's id and the maker's stable one)."""
    return identity.acting_for("workflow-chain", f"{wf['actor']} (auto)", _maker(wf))


# --- templates ------------------------------------------------------------------------------------------------------


def config() -> dict[str, Any]:
    return cfg.load(CONFIG)


def templates_view() -> dict[str, Any]:
    """The templates as the wizard reads them (`configs/workflows.json` without its meta), each kind with what its
    registered step kind says (181: the packages it takes, whether it is paid, has its own engine, may leave out
    processed documents or take the subfolders, and the scope it needs)."""
    conf = {k: v for k, v in config().items() if k != "meta"}
    described = workflow_steps.described()
    return conf | {"kinds": {k: {**v, **described[k]} for k, v in conf["kinds"].items()}}


def template(template_id: str) -> dict[str, Any]:
    for t in config()["templates"]:
        if t["id"] == template_id:
            return t
    raise explained(WorkflowError, "unknown workflow template {{template_id}}", template_id=repr(template_id))


def is_workflow(t: dict[str, Any]) -> bool:
    """A template of several steps makes a workflow; a one-step template is a single work package."""
    return len(t["steps"]) > 1


def _step_title(step: dict[str, Any]) -> str:
    return step.get("title") or config()["kinds"][step["kind"]]["title"]


# --- making one -------------------------------------------------------------------------------------------------------


def template_needs(t: dict[str, Any]) -> list[str]:
    """181: the parts of the scope a template's steps need (their step kinds' `needs`), in the parts' order."""
    needed = {n for step in t["steps"] for n in workflow_steps.step_needs(step)}  # 231 (C3a-1): a process step's pack's
    return [p.name for p in scopes.parts() if p.name in needed]


def _period(start: Any, end: Any) -> tuple[str, str]:
    return scopes.period(start, end, WorkflowError)


def _budget(raw: dict[str, Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for provider, value in (raw or {}).items():
        if provider not in PROVIDERS:
            raise explained(WorkflowError, "unknown budget provider {{provider}}", provider=repr(provider))
        try:
            amount = Decimal(str(value))
        except InvalidOperation as exc:
            raise explained(WorkflowError, "a budget is an amount in USD: {{value}}", value=repr(value)) from exc
        if amount < 0 or amount > 1000:
            raise explained(WorkflowError, "a budget is between 0 and 1000 USD: {{value}}", value=repr(value))
        out[provider] = str(amount)
    return out


def _engine(kind: str, source: dict[str, Any], raw: Any) -> str | None:
    """160-D: a step's own AI engine (None: the application's when the step starts). Only a step that makes and runs
    its own package has one; a reconciliation's AI and a package a person brought keep their own settings."""
    if raw is None:
        return None
    if raw not in work_recipes.ENGINE_JEV:
        raise explained(WorkflowError, "unknown engine {{raw}}; expected one of {{engine_jev}}",
                        raw=repr(raw), engine_jev=sorted(work_recipes.ENGINE_JEV))
    if not workflow_steps.of(kind).own_engine or source["kind"] not in workflow_steps.own_sources():
        raise explained(WorkflowError, "a {{kind}} step with a {{kind2}} source has no engine of its own",
                        kind=kind, kind2=repr(source["kind"]))
    return str(raw)


def _source(kind: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    """A step's source as the wizard gave it, checked against the kind's allowed sources. A documents step's folder or
    files may take only the documents no live run has processed yet (`only_new`, 147)."""
    raw = dict(raw or {})
    src = raw.get("kind")
    if src not in config()["kinds"][kind]["sources"]:
        raise explained(WorkflowError, "a {{kind}} step takes no {{src}} source", kind=kind, src=repr(src))
    only_new = {"only_new": bool(raw.get("only_new"))} if workflow_steps.of(kind).only_new else {}
    if raw.get("only_new") and not only_new:
        raise explained(WorkflowError, "only a documents step can leave out the documents a live run has processed")
    if src == "folder":
        folder = Path(str(raw.get("folder") or ""))
        if not folder.is_dir():
            raise explained(WorkflowError, "folder does not exist: {{folder}}", folder=folder)
        return {"kind": "folder", "folder": str(folder), "recursive": bool(raw.get("recursive"))} | only_new
    if src == "files":
        paths = [str(p) for p in raw.get("paths") or [] if str(p).strip()]
        if not paths:
            raise explained(WorkflowError, "give at least one file")
        if missing := [p for p in paths if not Path(p).is_file()]:
            raise explained(WorkflowError, "{{missing}} file(s) do not exist, the first: {{missing_0}}",
                            missing=len(missing), missing_0=missing[0])
        return {"kind": "files", "paths": paths} | only_new
    if (domain := workflow_steps.source_kind(src)) is not None:  # 185: a domain's (the email domain's mailbox)
        return domain.check(raw)
    if src == "package":
        wp_id = str(raw.get("workpackage_id") or "")
        _check_package(kind, wp_id)
        return {"kind": "package", "workpackage_id": wp_id}
    return {"kind": "none"}


def package_kinds(kind: str) -> tuple[str, ...]:
    """The work package kinds (source_kind) an existing package of a step of this kind may have (181: the registry's;
    until then `PACKAGE_KINDS`)."""
    return workflow_steps.of(kind).package_kinds


def _check_package(kind: str, wp_id: str) -> None:
    try:
        wp = work.get(wp_id)
    except KeyError as exc:
        raise explained(WorkflowError, "no work package {{wp_id}}", wp_id=repr(wp_id)) from exc
    if wp["source_kind"] not in package_kinds(kind):
        raise explained(WorkflowError, "work package {{name}} is not of a {{kind}} step's kind",
                        name=repr(wp["name"]), kind=kind)
    with store.connect() as c:
        if c.execute("SELECT 1 FROM workflow_steps WHERE workpackage_id=?", (wp_id,)).fetchone():
            raise explained(WorkflowError, "work package {{name}} already belongs to a workflow", name=repr(wp["name"]))


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


def _event(c, wf_id: str, step: str | None, action: str, actor: identity.Who,
           detail: dict[str, Any] | None = None) -> None:
    activity_kinds.check_event("workflow", action)
    c.execute("INSERT INTO workflow_events(workflow_id, step, action, actor, actor_id, detail, created_at)"
              " VALUES (?,?,?,?,?,?,?)", (wf_id, step, action, identity.name_of(actor), identity.id_of(actor),
                                          json.dumps(detail or {}, ensure_ascii=False, default=str), _now()))


# --- reading ------------------------------------------------------------------------------------------------------------


def _row(wf_id: str) -> dict[str, Any]:
    with store.connect() as c:
        row = c.execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
    if row is None:
        raise KeyError(wf_id)
    out = dict(row)
    out["definition"] = json.loads(out["definition"])
    out["auto"] = bool(out["auto"])
    return out


def _steps(wf_id: str) -> dict[str, dict[str, Any]]:
    """The steps' own data, each with its phase from its core row (227)."""
    with store.connect() as c:
        rows = c.execute("SELECT * FROM workflow_steps WHERE workflow_id=?", (wf_id,)).fetchall()
        core = process_cases.step_rows(c, wf_id)  # 229: the core's rows through its own read
    out = {}
    for r in rows:
        d = dict(r)
        d["source"], d["budget"] = json.loads(d["source"]), json.loads(d["budget"])
        d["phase"] = core[d["step"]]["phase"] if d["step"] in core else None
        out[d["step"]] = d
    return out


def _update_step(c, wf_id: str, step: str, *, expect: tuple[str, ...] | None = None, phase: str | None = None,
                 **fields: Any) -> bool:
    """Updates a step in the caller's write transaction: its own data, and (227) its `phase` in its core row; with
    `expect` only from those phases (the claim: False, and nothing written, when another process got there first)."""
    if expect is not None and phase is None:
        raise ValueError("a claim names the phase it moves the step to")
    if phase is not None and not process_cases.set_phase(c, wf_id, step, phase, expect=expect):
        return False
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k}=?" for k in fields)
    changed = c.execute(f"UPDATE workflow_steps SET {cols} WHERE workflow_id=? AND step=?",
                        [*fields.values(), wf_id, step]).rowcount
    if changed:
        c.execute("UPDATE workflows SET updated_at=? WHERE id=?", (fields["updated_at"], wf_id))
    return bool(changed)


def _set(wf_id: str, step: str, *, expect: tuple[str, ...] | None = None, **fields: Any) -> bool:
    """Updates a step in a write transaction of its own (`_update_step`)."""
    with store.connect() as c:
        store.begin_immediate(c)
        return _update_step(c, wf_id, step, expect=expect, **fields)


def _set_logged(wf_id: str, step: str, action: str, actor: identity.Who, detail: dict[str, Any] | None, *,
                expect: tuple[str, ...] | None = None, **fields: Any) -> bool:
    """213 (plan G-process-core P1b-1, rule 4 of plan 212 P0): a step's change and its event in one transaction; with
    `expect` neither is written when another process got there first. Before, the event was a second transaction, so a
    stop between the two left a change without its event."""
    with store.connect() as c:
        store.begin_immediate(c)
        if not _update_step(c, wf_id, step, expect=expect, **fields):
            return False
        _event(c, wf_id, step, action, actor, detail)
        return True


def step_scope(wp_id: str) -> dict[str, Any] | None:
    """181: the scope a workflow step's package takes: the workflow's party and period and the step's role (the template
    as the workflow was made; a workflow made before 181 takes the role its step has in the template now). None for a
    package of no workflow, or a step without party, period and role."""
    with store.connect() as c:
        row = c.execute("SELECT s.step, w.template, w.definition, w.party_id, w.period_start, w.period_end FROM workflow_steps s"
                        " JOIN workflows w ON w.id=s.workflow_id WHERE s.workpackage_id=?", (wp_id,)).fetchone()
    if row is None:
        return None
    sdef = next((x for x in json.loads(row["definition"])["steps"] if x["id"] == row["step"]), {})
    role = sdef.get("role")
    if role is None:
        now = next((t for t in config()["templates"] if t["id"] == row["template"]), {"steps": []})
        role = next((x.get("role") for x in now["steps"] if x["id"] == row["step"] and x["kind"] == sdef.get("kind")), None)
    scope = {"party_id": row["party_id"], "period_start": row["period_start"], "period_end": row["period_end"], "role": role}
    return scope if any(scope.values()) else None


def workflow_of(wp_id: str) -> dict[str, Any] | None:
    """The workflow a work package is a step of (for the package's header), or None."""
    with store.connect() as c:
        row = c.execute("SELECT s.workflow_id, s.step, w.name FROM workflow_steps s JOIN workflows w ON w.id=s.workflow_id"
                        " WHERE s.workpackage_id=?", (wp_id,)).fetchone()
    if row is None:
        return None
    sdef = next((s for s in _row(row["workflow_id"])["definition"]["steps"] if s["id"] == row["step"]), None)
    return {"id": row["workflow_id"], "name": row["name"], "step": row["step"],
            "step_title": _step_title(sdef) if sdef else row["step"]}


def _package_state(wp_id: str) -> tuple[bool, dict[str, Any] | None]:
    """Whether the package's step is done (its latest live run approved; a reconciliation's version approved), and
    its next step for the person (None when the package is gone)."""
    from jav.app import work_views

    try:
        wp = work.get(wp_id)
    except KeyError:
        return False, None
    pack = logic_packs.of(wp["source_kind"])
    if pack is not None and not pack.has_runs:  # 176: a logic pack without runs answers for itself
        return pack.approved(wp_id), pack.next_step(wp_id)
    nxt = work_views.next_step(wp, work_views.current_run(work_runs.run_rows(wp_id)))  # 153: a later stopped run hides nothing
    return _live_run_approved(wp_id), nxt


def _live_run_approved(wp_id: str) -> bool:
    """Whether the package has an approved live run and no other live run still going or open (160-C S3: a run over
    the pending items next to an earlier live run waiting for review; `work_runs.open_live_runs`)."""
    with store.connect() as c:  # 153: a live run a person stopped later does not undo an approved one
        rows = c.execute("SELECT approval, status FROM runs WHERE workpackage_id=? AND mode='apply' AND status != 'cancelled'",
                         (wp_id,)).fetchall()
    if not any(r["approval"] for r in rows) or any(not r["approval"] and r["status"] in ("queued", "running") for r in rows):
        return False
    return not work_runs.open_live_runs(wp_id)


def _approved_runs(wp_id: str) -> list[str]:
    with store.connect() as c:
        return [r["run_id"] for r in c.execute("SELECT run_id FROM runs WHERE workpackage_id=? AND mode='apply'"
                                               " AND status != 'cancelled' AND approval IS NOT NULL ORDER BY run_id",
                                               (wp_id,))]


def _pack(st: dict[str, Any]) -> tuple[bool, logic_packs.LogicPack | None]:
    """Whether the step's package still exists, and the logic pack it runs (None: a processing package)."""
    with store.connect() as c:
        kind = c.execute("SELECT source_kind FROM workpackages WHERE id=?", (st["workpackage_id"],)).fetchone()
    return (False, None) if kind is None else (True, logic_packs.of(kind["source_kind"]))


def _approval(st: dict[str, Any]) -> tuple[bool, Any]:
    """Whether the step is satisfied, and (218, P3l) by which approval of its package: a logic pack's own version
    ({version, fingerprint}), a processing package's approved live runs ({runs}); None for a step that found nothing
    new or a package done without an approval of its own (the email routing: every attachment decided)."""
    if st["phase"] == "nothing_new":
        return True, None
    if not st.get("workpackage_id") or st["phase"] not in ("started", "linked"):
        return False, None
    exists, pack = _pack(st)
    if not exists:
        return False, None
    wp_id = st["workpackage_id"]
    if pack is not None and not pack.has_runs:  # 176: a reconciliation step: a version of it is approved
        if not pack.approved(wp_id):
            return False, None
        active = package_release.own_approval(wp_id)["active"] if logic_packs.has_own_approval(pack, wp_id) else None
        return True, {"version": active["version"], "fingerprint": active["fingerprint"]} if active else None
    if not _live_run_approved(wp_id):
        return False, None
    return True, {"runs": _approved_runs(wp_id)}


def _satisfied(st: dict[str, Any]) -> bool:
    return _approval(st)[0]


# 218 (P3l): what a step done before keeps in its result once its earlier steps have another result: the approval its
# package had then, which no longer counts for the chain
OLD_APPROVAL = "old_approval"
REAPPROVE_NOTE = "a step it builds on has a new result: check it and approve it again"


def _ref_of(result: Any) -> Any:
    return result.get("ref") if isinstance(result, dict) else None


def _out_of_date(sdef: dict[str, Any], core: dict[str, dict[str, Any]]) -> list[str]:
    """218 (P3l): the earlier steps whose result changed since the step was built on them, while the step does not
    count for the chain (it went out of date when one of them was reopened, or the chain asks for its approval again);
    none for a step that is done or not out of date."""
    row = core.get(sdef["id"])
    if row is None or row["state"] == process_cases.DONE or not isinstance(row["result"], dict):
        return []
    result = row["result"]
    if row["state"] != process_cases.STALE and OLD_APPROVAL not in result:
        return []
    before = result.get("built_on")
    return [n for n in sdef.get("after", []) if not isinstance(before, dict) or n not in core
            or core[n]["state"] != process_cases.DONE or _ref_of(core[n]["result"]) != before.get(n)]


# a processing package's next step and what it means for its step; a step kind adds its own package's (181)
STATUS_BY_NEXT = {"running": "running", "review": "review", "release": "approve", "done": "approved",
                  "start": "attention", "blocked": "attention", "rerun": "attention", "go_live": "attention",
                  "empty": "attention"}


def _status(sdef: dict[str, Any], st: dict[str, Any], done: dict[str, bool]) -> tuple[str, Any]:
    """What a person sees of a step, and its package's next step."""
    if st["phase"] in ("started", "linked") and st.get("workpackage_id"):
        approved, nxt = _package_state(st["workpackage_id"])
        if nxt is None:
            return "missing", None
        statuses = {**STATUS_BY_NEXT, **workflow_steps.step_statuses(sdef)}  # 231 (C3a-1): a process step's capabilities'
        return ("approved" if approved else statuses.get(nxt["code"], "attention")), nxt
    if st["phase"] == "waiting":
        return ("ready" if all(done.get(a) for a in sdef.get("after", [])) else "waiting"), None
    return st["phase"], None  # starting, pulling, needs_budget, nothing_new, failed


@store.one_connection
def view(wf_id: str) -> dict[str, Any]:
    """The control view: the workflow, its steps in order with their state, package and next step, what needs a person
    first, and the latest events."""
    wf = _row(wf_id)
    steps = _steps(wf_id)
    kinds = config()["kinds"]
    party_names = {p["id"]: p["name"] for p in parties.parties()}
    with store.connect() as c:
        core = process_cases.step_rows(c, wf_id)  # 218: none for a workflow an older process made, until its first turn
    # 218 (P3l): a step out of date does not count as done; it names the earlier steps it was built on
    stale_of = {s["id"]: _out_of_date(s, core) for s in wf["definition"]["steps"]}
    done = {sid: _satisfied(st) and not stale_of.get(sid) for sid, st in steps.items()}
    out_steps = []
    for sdef in wf["definition"]["steps"]:
        st = steps[sdef["id"]]
        status, nxt = _status(sdef, st, done)
        stale = stale_of[sdef["id"]]
        if stale and (core[sdef["id"]]["state"] == process_cases.STALE or status == "approved"):
            status = "stale"
        package = None
        if st.get("workpackage_id"):
            try:
                package = {"id": st["workpackage_id"], "name": work.get(st["workpackage_id"])["name"], "next": nxt}
            except KeyError:
                package = {"id": st["workpackage_id"], "name": None, "next": None}
        note = st.get("note")
        if st["phase"] == "needs_budget" and note:
            note = json.loads(note)
        out_steps.append({"id": sdef["id"], "kind": sdef["kind"], "title": _step_title(sdef),
                          "kind_title": kinds[sdef["kind"]]["title"], "after": sdef.get("after", []),
                          "source": _shown_source(st["source"]), "budget": st["budget"], "engine": st.get("engine"),
                          "name": st["name"],
                          "state": st["phase"], "status": status, "done": done[sdef["id"]], "note": note,
                          "package": package, "run_id": st.get("run_id"), "pull_id": st.get("pull_id"),
                          "updated_at": st["updated_at"]} | ({"stale_of": stale} if stale else {}))
    attention = ("failed", "needs_budget", "review", "approve", "attention", "pairing", "missing", "ready")
    first = next((s for s in out_steps if s["status"] in attention
                  and (s["status"] != "ready" or not wf["auto"])), None)
    with store.connect() as c:
        events = [dict(r) for r in c.execute("SELECT step, action, actor, detail, created_at FROM workflow_events"
                                             " WHERE workflow_id=? ORDER BY id DESC LIMIT 50", (wf_id,))]
        repeated = [dict(r) for r in c.execute("SELECT id, name, period_start, period_end FROM workflows WHERE previous_id=?"
                                               " ORDER BY period_start, created_at", (wf_id,))]
    for e in events:
        e["detail"] = json.loads(e["detail"] or "{}")
    return {"workflow": {k: wf[k] for k in ("id", "template", "name", "party_id", "period_start", "period_end", "auto",
                                            "status", "actor", "created_at", "updated_at")}
            | {"party": party_names.get(wf["party_id"], wf["party_id"]), "template_title": wf["definition"]["title"]},
            "steps": out_steps, "done": sum(1 for s in out_steps if s["done"]), "total": len(out_steps),
            "next": {"step": first["id"], "status": first["status"]} if first else None, "events": events,
            "repeat_of": _brief(wf["previous_id"]) if wf.get("previous_id") else None, "repeated_as": repeated}


def _brief(wf_id: str) -> dict[str, Any] | None:
    """A workflow's id, name and period (the other end of a repeat), or None."""
    with store.connect() as c:
        row = c.execute("SELECT id, name, period_start, period_end FROM workflows WHERE id=?", (wf_id,)).fetchone()
    return dict(row) if row else None


def _shown_source(source: dict[str, Any]) -> dict[str, Any]:
    if source["kind"] == "files":
        return {"kind": "files", "count": len(source["paths"]), "first": Path(source["paths"][0]).name,
                "only_new": bool(source.get("only_new"))}
    if (domain := workflow_steps.source_kind(source["kind"])) is not None:  # 185: a domain's source shows its own
        return domain.shown(source)
    return source


def workflows(*, include_archived: bool = False) -> list[dict[str, Any]]:
    """The list: each workflow with its party, period, steps done of all, and what needs a person first."""
    with store.connect() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM workflows" + ("" if include_archived else " WHERE status='open'")
                                         + " ORDER BY updated_at DESC")]
    out = []
    for wf_id in ids:
        v = view(wf_id)
        out.append({**v["workflow"], "done": v["done"], "total": v["total"], "next": v["next"],
                    "steps": [{"id": s["id"], "title": s["title"], "status": s["status"]} for s in v["steps"]]})
    return out


# --- repeating (147) ----------------------------------------------------------------------------------------------------


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


def _repeat_from_folder(wp_id: str) -> dict[str, Any] | None:
    """The documents step's repeat source: the folder its linked package was made from (a folder or watched one)."""
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


# --- moving on ----------------------------------------------------------------------------------------------------------


@store.one_connection
def advance(wf_id: str, *, actor: identity.Who) -> dict[str, Any]:
    """Moves the chain on: one turn of the workflow's case on the process core (214), woken, so a finished mailbox
    download or an approved package is seen at once. A finished download gets its package and run; a step whose steps it
    waits for are done starts (only while the workflow's chain is automatic; otherwise it waits for a person). A case
    another process is moving on is left to it. Idempotent."""
    wf = _row(wf_id)
    if wf["status"] != "open":
        return view(wf_id)
    workflow_cases.ensure(wf_id)
    _turn(wf_id, actor)
    return view(wf_id)


def start_step(wf_id: str, step: str, *, actor: identity.Who, budget: dict[str, Any] | None = None) -> dict[str, Any]:
    """A person starts a step now (whatever the steps it waits for), retries a failed one, or starts one that waits for
    a budget; a `budget` given here replaces the step's budget (the person's own decision, recorded). 214: the person's
    start reaches the case in the same transaction (`workflow_cases.person_starts`: the order overridden and recorded,
    a failed step retried, a wait ended), and the case's turn starts the step."""
    wf = _row(wf_id)
    if wf["status"] != "open":
        raise explained(WorkflowError, "the workflow is archived")
    sdef = next((s for s in wf["definition"]["steps"] if s["id"] == step), None)
    if sdef is None:
        raise explained(WorkflowError, "unknown step {{step}}", step=repr(step))
    st = _steps(wf_id)[step]
    if st["phase"] not in ("waiting", "failed", "needs_budget"):
        raise explained(WorkflowError, "step {{step}} is {{state}}: it cannot be started",
                        step=repr(step), state=st["phase"])
    new = _budget(budget) if budget is not None else None
    with store.connect() as c:
        store.begin_immediate(c)
        if new is not None:
            _update_step(c, wf_id, step, budget=json.dumps(new))
            _event(c, wf_id, step, "budget", actor, {"from": st["budget"], "to": new})
        workflow_cases.person_starts(c, wf_id, step, actor, decision={"budget": new if new is not None else st["budget"]})
    _turn(wf_id, actor)
    return view(wf_id)


def link(wf_id: str, step: str, wp_id: str, *, actor: identity.Who) -> dict[str, Any]:
    """A person makes an existing work package the step's package (the chain starts no run on it). 214: the step then
    waits for the package's approval in the case, whatever its order (`workflow_cases.person_links`)."""
    wf = _row(wf_id)
    sdef = next((s for s in wf["definition"]["steps"] if s["id"] == step), None)
    if sdef is None:
        raise explained(WorkflowError, "unknown step {{step}}", step=repr(step))
    _check_package(sdef["kind"], wp_id)
    with store.connect() as c:
        store.begin_immediate(c)
        if not _update_step(c, wf_id, step, expect=("waiting", "failed", "nothing_new"), phase="linked",
                            workpackage_id=wp_id, source=json.dumps({"kind": "package", "workpackage_id": wp_id}),
                            note=None):
            raise explained(WorkflowError, "step {{step}} has started already", step=repr(step))
        _event(c, wf_id, step, "link", actor, {"workpackage": wp_id})
        workflow_cases.person_links(c, wf_id, step, actor)
    _turn(wf_id, actor)
    return view(wf_id)


def update(wf_id: str, *, actor: identity.Who, auto: bool | None = None, name: str | None = None,
           archived: bool | None = None) -> dict[str, Any]:
    """Switches the automatic chain, renames, archives or restores a workflow (its packages stay as they are). 214: its
    case is held while it is archived, and the steps waiting for a person go on when the chain is switched on."""
    _row(wf_id)
    changes: dict[str, Any] = {}
    if auto is not None:
        changes["auto"] = int(auto)
    if name is not None and name.strip():
        changes["name"] = name.strip()[:200]
    if archived is not None:
        changes["status"] = "archived" if archived else "open"
    if changes:
        with store.connect() as c:
            store.begin_immediate(c)
            if archived is not None:
                workflow_cases.set_archived(c, wf_id, archived, actor)
            if auto:
                workflow_cases.chain_on(c, wf_id, actor)
            c.execute(f"UPDATE workflows SET {', '.join(f'{k}=?' for k in changes)}, updated_at=? WHERE id=?",
                      (*changes.values(), _now(), wf_id))
            _event(c, wf_id, None, "update", actor, changes)
    if changes.get("auto"):
        advance(wf_id, actor=actor)
    return view(wf_id)


def _done(wf: dict[str, Any], step: str, actor: identity.Who, action: str, **fields: Any) -> None:
    """A step's outcome and its event, in one transaction (213, `_set_logged`)."""
    _set_logged(wf["id"], step, action, actor,
                {k: v for k, v in fields.items() if k in ("workpackage_id", "run_id", "pull_id", "note")}, **fields)


def _start(wf: dict[str, Any], sdef: dict[str, Any], *, actor: identity.Who, states: tuple[str, ...] = ("waiting",)) -> None:
    """Makes the step's package (or queues its mailbox download) and starts its run; a failure stays on the step. 160
    (review R-2): the package is noted on the step as soon as it exists, so a start interrupted later (before or after
    the run was made) is started again with that package (`start_step`), never with a second one."""
    step = sdef["id"]
    if not _set(wf["id"], step, expect=states, phase="starting", note=None):
        return  # another process has it, or it is past waiting
    st = _steps(wf["id"])[step]
    try:
        workflow_steps.of(sdef["kind"]).start(_context(wf, sdef, st, actor))  # 181: the kind's own start
    except Exception as exc:  # the step shows why; a person retries it
        log.warning("workflow %s step %s did not start: %s", wf["id"], step, exc)
        _done(wf, step, actor, "failed", phase="failed", note=str(exc)[:1000])
    except BaseException:  # 153 (review D2): interrupted (the process stops): the claim is released, then it stops
        _done(wf, step, actor, "failed", phase="failed", note=INTERRUPTED)
        raise


def _exclude(source: dict[str, Any]) -> list[Path]:
    """With the subfolders, the output folder of the named copies is left out (they are not new documents)."""
    out = app_settings.output_folder() if source.get("recursive") else None
    return [Path(out)] if out else []


def _documents(source: dict[str, Any]) -> tuple[list[Path], list[Path]]:
    """A documents step's documents, and those left out because a live run has processed them (`only_new`, 147)."""
    if source["kind"] == "folder":
        files = work.folder_documents(Path(source["folder"]), recursive=source["recursive"], exclude=_exclude(source))
    else:
        files = [Path(p) for p in source["paths"]]
    return work.unprocessed(files) if source.get("only_new") else (files, [])


def _context(wf: dict[str, Any], sdef: dict[str, Any], st: dict[str, Any], actor: identity.Who) -> workflow_steps.StepStart:
    """181: the workflow's shared operations for a step kind's start or fetch check, each recording its event."""
    wf_id, step = wf["id"], sdef["id"]

    def event(action: str, detail: dict[str, Any]) -> None:
        with store.connect() as c:
            store.begin_immediate(c)
            _event(c, wf_id, step, action, actor, detail)

    def package(wp_id: str) -> None:  # 160 (review R-2): an interrupted start goes on with this package
        _set(wf_id, step, workpackage_id=wp_id)

    packages = {sid: x.get("workpackage_id") for sid, x in _steps(wf_id).items()}
    return workflow_steps.StepStart(
        workflow=wf, step=sdef, state=st, actor=actor, packages=packages, package=package,
        run=lambda wp_id: _start_run(wf, sdef, st, wp_id, actor=actor),
        made=lambda wp_id: _done(wf, step, actor, "package", phase="started", workpackage_id=wp_id),
        nothing_new=lambda note: _done(wf, step, actor, "nothing_new", phase="nothing_new", note=note),
        fetching=lambda fetch_id: _done(wf, step, actor, "pull", phase="pulling", pull_id=fetch_id),
        claim=lambda: _set(wf_id, step, expect=("pulling",), phase="starting"),
        failed=lambda note: _done(wf, step, actor, "failed", phase="failed", note=note[:1000]),
        event=event)


def _poll(wf: dict[str, Any], sdef: dict[str, Any], st: dict[str, Any], actor: identity.Who) -> None:
    """A step whose source is being fetched (a mailbox download) goes on once the fetch has finished (181: the kind's
    own check)."""
    kind = workflow_steps.of(sdef["kind"])
    if kind.poll is not None:
        kind.poll(_context(wf, sdef, st, actor))


def _start_documents(ctx: workflow_steps.StepStart) -> None:
    """The documents step: the folder's or the files' documents (only those no live run has processed, when asked)
    become the step's package and its live run starts; none: the step found nothing new and keeps no empty package."""
    source, wf = ctx.source, ctx.workflow
    files, left_out = _documents(source)
    wp = None
    if files and source["kind"] == "folder":
        wp = work.create_from_folder(Path(source["folder"]), name=ctx.state["name"], owner=_maker(wf),
                                     recursive=source["recursive"], exclude=_exclude(source),
                                     only=files if left_out else None)
    elif files:
        wp = work.create_from_files(files, name=ctx.state["name"], owner=_maker(wf))
    if wp is None or not work.get(wp["id"])["items"]:
        if wp is not None:
            work.delete_workpackage(wp["id"], actor=ctx.actor)
        ctx.nothing_new(f"no new documents: {len(left_out)} already processed" if left_out else "no documents in the folder")
        return
    ctx.package(wp["id"])
    if left_out:
        ctx.event("left_out", {"new": len(files), "left_out": len(left_out)})
    ctx.run(wp["id"])


# 181: the documents step, registered by `register`
DOCUMENTS_STEP = workflow_steps.StepKind(DOCUMENTS, __name__, DOCUMENT_PACKAGES, start=_start_documents, only_new=True,
                                         subfolders=True, repeat_from=_repeat_from_folder)


def _give_engine(wp_id: str, engine: str | None, *, actor: identity.Who) -> None:
    """160-D: the step's own engine on its package (keeping the package's other settings), before the readiness check
    sizes the run's budget. Without one the package keeps the engine it got: the application's when it was made, or
    when the run starts for a package without saved settings."""
    if engine is None:
        return
    a = work_recipes.current_assignment(wp_id)
    r = work_recipes.recipe(a["recipe_id"]) if a else work_recipes.default_recipe()
    want = work_recipes.engine_params(r, engine)
    if not want or (a is not None and a["params"].get("jev") == want["jev"]):
        return
    kept = a["params"] if a else work_recipes.default_params(r, engine)
    work_recipes.assign_recipe(wp_id, r["id"], params={**kept, **want}, expected_revision=a["revision"] if a else 0, actor=actor,
                       note=f"workflow step: engine {engine}")


BUDGET_GATE = "workflow.budget_gate"  # 218 (P3b): the decision point of a step's budget gate


def budget_gate(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """218 (P3b): a workflow step's budget gate, a pure rule: each provider whose estimate (`estimate`, USD as text) is
    over the step's approved budget (`budget`; a provider without one has none); the step's package starts its live
    run only when none is, otherwise the step waits for a person's budget."""
    budget = inputs["budget"]
    over = {p: str(Decimal(v)) for p, v in sorted(inputs["estimate"].items()) if Decimal(v) > Decimal(budget.get(p, "0"))}
    return {"over": over, "decision": "needs_budget" if over else "start"}


def _gate_keys(wp_id: str) -> dict[str, tuple[str, ...]]:
    """The rule keys the estimate of the gate was made with: the item budgets of the package's recipe."""
    a = work_recipes.current_assignment(wp_id)
    rid = a["recipe_id"] if a else work_recipes.default_recipe()["id"]
    return {"recipes.json": (f"recipes[{rid}].max_item_usd", f"recipes[{rid}].max_item_usd_by_kind")}


def _start_run(wf: dict[str, Any], sdef: dict[str, Any], st: dict[str, Any], wp_id: str, *, actor: identity.Who) -> None:
    """The package's live run, when its own estimate fits the step's budget; otherwise the step waits for a person.
    218 (P3b): the gate's decision is traced in the transaction that records it on the step."""
    step = sdef["id"]
    try:
        _give_engine(wp_id, st.get("engine"), actor=actor)
        ready = work_readiness.readiness(wp_id)
        if not ready["ready"]:
            raise WorkflowError("; ".join(b["message"] for b in ready["blockers"]) or "the package cannot start")
        budget = _steps(wf["id"])[step]["budget"]
        estimate = {p: Decimal(str(v)) for p, v in (ready.get("budget") or {}).items()}
        inputs = {"estimate": {p: str(v) for p, v in estimate.items()}, "budget": budget}
        gate = budget_gate(inputs)

        def traced(c: Any, run_id: str | None = None) -> None:
            trace.record_in(c, BUDGET_GATE, subject=("workflow_step", f"{wf['id']}:{step}"), inputs=inputs,
                            outcome=gate, keys=_gate_keys(wp_id), run_id=run_id, case_id=wf["id"])

        if gate["over"]:
            note = {**inputs, "over": gate["over"]}
            with store.connect() as c:  # 215: the wait, its event and the person's task in one transaction
                store.begin_immediate(c)
                if _update_step(c, wf["id"], step, phase="needs_budget", workpackage_id=wp_id, note=json.dumps(note)):
                    _event(c, wf["id"], step, "needs_budget", actor, {"workpackage_id": wp_id, "note": json.dumps(note)})
                    workflow_cases.ask_budget(c, wf["id"], step, human_tasks.assignee_for(c, wp_id, wf["actor"]), note)
                    traced(c)
            return
        res = work_runs.start_run(wp_id, mode="apply", expected_assignment_revision=ready["assignment_revision"],
                             input_hash=ready["input_hash"], actor=actor)
        with store.connect() as c:  # the step's start, its event and the gate's trace in one transaction
            store.begin_immediate(c)
            _update_step(c, wf["id"], step, phase="started", workpackage_id=wp_id, run_id=res["run_id"])
            _event(c, wf["id"], step, "run", actor, {"workpackage_id": wp_id, "run_id": res["run_id"]})
            traced(c, res["run_id"])
    except Exception as exc:
        log.warning("workflow %s step %s: run not started: %s", wf["id"], step, exc)
        _done(wf, step, actor, "failed", phase="failed", workpackage_id=wp_id, note=str(exc)[:1000])


_last_tick = 0.0


INTERRUPTED = "the start was interrupted; start the step again"


def release_stale_starts(max_age_s: float = STALE_START_S) -> int:
    """153 (review D2): steps claimed for a start more than `max_age_s` ago and never finished (the process that held
    the claim stopped) go to `failed` with a note, so a person can start them again; before, they stayed "starting" for
    good. Returns how many it released. 227: under the case's claim, so a start a live process is still making is
    left to it, and the step fails in its case too (before, only its phase did, and the case still had it running)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max_age_s)).isoformat(timespec="seconds")
    with store.connect() as c:
        starting = set(process_cases.steps_in_phase_in(c, ("starting",)))  # 229: the core's rows through its own read
        stale = [r for r in c.execute("SELECT s.workflow_id, s.step, w.actor, w.actor_id FROM workflow_steps s"
                                      " JOIN workflows w ON w.id=s.workflow_id WHERE s.updated_at < ?", (cutoff,))
                 if (r["workflow_id"], r["step"]) in starting]
    released = 0
    for r in stale:
        if not process_engine.claim_case(r["workflow_id"]):
            continue  # a live process holds the case: its own turn settles the start
        try:
            with store.connect() as c:
                store.begin_immediate(c)
                if _update_step(c, r["workflow_id"], r["step"], expect=("starting",), phase="failed", note=INTERRUPTED):
                    _event(c, r["workflow_id"], r["step"], "failed", auto_actor(r), {"note": INTERRUPTED})
                    workflow_cases.fail_outside(c, r["workflow_id"], r["step"], INTERRUPTED)
                    released += 1
        finally:
            process_engine.release(r["workflow_id"])
    return released


def tick(now: float | None = None) -> int:
    """The worker's turn (at most every `TICK_EVERY_S`): releases interrupted starts (153), then advances every open,
    automatic workflow with a step still to move (214: a woken turn of its case, so each looks at its waiting steps
    every turn, as before). 229: the other workflow cases the process core has something for (a check timer that came
    due, an event, a step a person started while another process held the case) are turned by the core's own round
    (`process_engine.turn_due`), with every other case. Returns how many automatic workflows it advanced."""
    global _last_tick
    now = time.monotonic() if now is None else now
    if now - _last_tick < TICK_EVERY_S:
        return 0
    _last_tick = now
    release_stale_starts()
    with store.connect() as c:
        moving = {case_id for case_id, _ in process_cases.steps_in_phase_in(c, ("waiting", "pulling"))}  # 229
        rows = [r for r in c.execute("SELECT w.id, w.actor, w.actor_id FROM workflows w WHERE w.status='open' AND w.auto=1")
                if r["id"] in moving]
    for r in rows:
        try:
            advance(r["id"], actor=auto_actor(r))
        except Exception:  # one workflow's trouble does not stop the others
            log.exception("workflow %s could not advance", r["id"])
    return len(rows)


# --- the process core moves the steps on (214, plan G-process-core P1b-3) -------------------------------------------------

# who a turn acts for in the workflow's log and its runs: the caller of the turn (a person's start, the worker's turn as
# the maker's automatic one); a turn of the core's own due cases acts as the maker, marked automatic
_turn_actor: ContextVar[identity.Who | None] = ContextVar("workflow_turn_actor", default=None)
_ROUNDS = 6  # a start moves a step to its next state in a round or two; a step still moving after these does not settle


def _turn(wf_id: str, actor: identity.Who | None, *, wake: bool = True) -> bool:
    """One turn of the workflow's case under its claim (`process_engine.turn`); False when another process or thread
    holds it (that one moves it on)."""
    token = _turn_actor.set(actor)
    try:
        return process_engine.turn(wf_id, wake=wake)
    finally:
        _turn_actor.reset(token)


def _check() -> tuple[str, float]:
    """The check timer of a step that waits for its fetch or its package's approval: the next look, as often as the
    worker's turn."""
    return workflow_cases.CHECK, time.time() + TICK_EVERY_S


def _person_start(wf: dict[str, Any], sdef: dict[str, Any], st: dict[str, Any], actor: identity.Who) -> None:
    """A person's start: a step with a package that waits for a budget or failed starts its package's run (within the
    budget, which the person may have raised); any other is started from its source again."""
    if st.get("workpackage_id") and st["phase"] in ("needs_budget", "failed"):
        if _set(wf["id"], sdef["id"], expect=("needs_budget", "failed"), phase="starting"):
            _start_run(wf, sdef, _steps(wf["id"])[sdef["id"]], st["workpackage_id"], actor=actor)
    else:
        _start(wf, sdef, actor=actor, states=("waiting", "failed"))


def _case_step(ctx: process_engine.StepContext) -> process_kinds.StepOutcome:
    """The process core's workflow step (`workflow_cases.STEP_KIND`, 214): it runs under its case's claim and does what
    the step's phase asks for, until the step is done, waits or failed:
    - nothing new: done; started or linked: done once its package's latest live run is approved (a reconciliation's
      version), otherwise it waits for that with a check timer;
    - pulling: its fetch is checked (a finished one gets its package and run), otherwise it waits with a check timer;
    - starting: a start a stopped process left (the claim says nobody else is starting it): failed, to start again;
    - a person's start (`workflow_cases.take_go`): started now, in the person's name;
    - waiting for a budget: waits for a person; failed: failed with its note;
    - waiting: started when the chain is automatic, otherwise it waits for a person.
    An error while a step checks its download or its package's approval is logged and the step looks again at its next
    check, as before 214 (the worker's next turn); a start's own error fails the step with it (`_start`)."""
    wf = _row(ctx.case_id)
    sdef = next(s for s in wf["definition"]["steps"] if s["id"] == ctx.step.id)
    with ctx.transaction() as c:
        go = workflow_cases.take_go(c, ctx.case_id, ctx.step.id)
    actor = go or _turn_actor.get() or auto_actor(wf)
    try:
        return _drive(ctx, wf, sdef, go, actor)
    except Exception:
        waits = {"pulling": workflow_cases.FETCH, "started": workflow_cases.APPROVAL, "linked": workflow_cases.APPROVAL}
        phase = _steps(wf["id"])[sdef["id"]]["phase"]
        if phase not in waits:
            raise  # the case fails the step with the error; a person starts it again
        log.exception("workflow %s step %s: its check failed; it looks again at its next check", wf["id"], sdef["id"])
        return ctx.wait(waits[phase], timer=_check())


def _drive(ctx: process_engine.StepContext, wf: dict[str, Any], sdef: dict[str, Any], go: identity.Actor | None,
           actor: identity.Who) -> process_kinds.StepOutcome:
    """`_case_step`'s rounds: until the step is done, waits or failed."""
    polled = False
    for _ in range(_ROUNDS):
        st = _steps(wf["id"])[sdef["id"]]
        phase = st["phase"]
        if phase == "nothing_new":
            return process_kinds.Done({"state": phase, "ref": None, "built_on": _built_on(ctx)})
        if phase in ("started", "linked"):
            approved, ref = _approval(st)
            if _counts(ctx, wf, st, approved, ref):
                return process_kinds.Done({"state": phase, "workpackage_id": st["workpackage_id"], "run_id": st.get("run_id"),
                                           "ref": ref, "built_on": _built_on(ctx)})
            return ctx.wait(workflow_cases.APPROVAL, timer=_check())
        if phase == "pulling":
            if polled:
                return ctx.wait(workflow_cases.FETCH, timer=_check())
            _poll(wf, sdef, st, actor)
            polled = True
        elif phase == "starting":
            _set_logged(wf["id"], sdef["id"], "failed", auto_actor(wf), {"note": INTERRUPTED},
                        expect=("starting",), phase="failed", note=INTERRUPTED)
        elif go is not None:
            go = None
            _person_start(wf, sdef, st, actor)
        elif phase == "needs_budget":
            return ctx.wait(workflow_cases.BUDGET)
        elif phase == "failed":
            return process_kinds.Fail(st.get("note") or "the step failed")
        elif not wf["auto"]:
            return ctx.wait(workflow_cases.PERSON)
        else:
            _start(wf, sdef, actor=actor)
    return process_kinds.Fail(f"the step did not settle: it is still {st['phase']}")


def _built_on(ctx: process_engine.StepContext) -> dict[str, Any]:
    """218 (P3l, rule 3): the approval each of the step's earlier steps was done with, as their results name it now."""
    return {n: _ref_of(ctx.result_of(n)[1]) for n in ctx.step.needs()}


def _old_approvals(last: dict[str, Any], found: Any) -> list[Any]:
    """The approvals that no longer count for a step out of date: the one it was done with and the one its package had
    at its first look after its earlier steps were done again."""
    old: list[Any] = []
    for r in (last.get("ref"), found):
        if r is not None and r not in old:
            old.append(r)
    return old


def _counts(ctx: process_engine.StepContext, wf: dict[str, Any], st: dict[str, Any], approved: bool, ref: Any) -> bool:
    """218 (P3l; DECISIONS 218): whether the step's package's approval counts for the chain now. A step whose earlier
    steps have another result than it was built on (`built_on`: kept when it was done, or when it went out of date
    before it was ever done) keeps, at its first look after them, the approvals that no longer count (`OLD_APPROVAL`):
    the one it was done with and the one its package has then. Only another approval counts, so one given before the
    earlier step's new approval does not either, nor the old one coming back (a later run stopped). A logic pack's own
    version still holding is reopened with a reason (its approval waits for a person again); a processing package needs
    a new live run a person starts. A package done without an approval of its own (the email routing: a person decides
    each attachment) counts as it stands. Nothing runs by itself."""
    row = ctx.row()
    last = row["result"] if isinstance(row["result"], dict) else {}
    before = last.get("built_on")
    if before is None or before == _built_on(ctx):  # never out of date, or built on what its earlier steps have now
        return approved
    _, pack = _pack(st)
    own = logic_packs.has_own_approval(pack, st["workpackage_id"])  # 231 (C3a-1): a case's too
    if pack is not None and not pack.has_runs and not own:
        return approved
    if OLD_APPROVAL not in last:
        old = _old_approvals(last, ref if approved else None)
        with ctx.transaction() as c:
            process_cases.set_result(c, ctx.case_id, ctx.step.id, {**last, OLD_APPROVAL: old})
    else:
        old = last[OLD_APPROVAL]
    if not approved or ref not in old:
        return approved
    if pack is not None and own and pack.reopen is not None:
        pack.reopen(st["workpackage_id"], note=REAPPROVE_NOTE, actor=auto_actor(wf))
    return False


def _went_stale(c: Any, case_id: str, step_id: str | None, actor: Any) -> None:
    """218 (P3l): a workflow step that goes out of date before it was ever done keeps what its earlier steps' results
    were then (`built_on`), in the transaction that marks it, so its first look after them knows they changed. A done
    step keeps the one it was done with. Registered with the core's `on_leave`; nothing for another case."""
    if step_id is None:
        return
    case = process_cases.find_case_in(c, case_id)  # 229: the core's rows through its own reads
    if case is None or not case["definition_id"].startswith(workflow_cases.DEFINITION_PREFIX):
        return
    row = process_cases.find_step_in(c, case_id, step_id)
    if row is None or row["state"] != process_cases.STALE:
        return
    result = row["result"]
    if isinstance(result, dict) and "built_on" in result:
        return
    needs = process_cases.definition_of(process_cases.case_row(c, case_id)).step(step_id).needs()
    rows = process_cases.step_rows(c, case_id)
    process_cases.set_result(c, case_id, step_id, {**(result if isinstance(result, dict) else {}),
                                                   "built_on": {n: _ref_of(rows[n]["result"]) for n in needs}})


process_cases.on_leave(_went_stale)


# 214: registered on import, not by `register`: a case whose step kind the running code lacks waits for a migration for
# good, so any process that turns a workflow's case must know it. 215: it takes a task's closing for the budget and the
# package's approval it waits for (an earlier round's is refused); a case of before goes the same way
process_kinds.register(process_kinds.StepKind(workflow_cases.STEP_KIND, __name__, _case_step,
                                              events=(workflow_cases.BUDGET, workflow_cases.APPROVAL),
                                              on_event=workflow_cases.task_event))
# 218 (P3b): the budget gate's decision point
trace.register(trace.Point(
    BUDGET_GATE, owner=__name__, files=("recipes.json",), rule=budget_gate,
    what="whether a workflow step's package starts its live run or the step waits for a person's budget: the run's "
         "estimate per provider against the budget a person approved for the step",
    not_for="the run's reservations while it runs (the call log keeps those)"))


# --- the wizard's estimate -----------------------------------------------------------------------------------------------


def _per_item(kind: str, engine: str | None = None) -> dict[str, Decimal]:
    r = work_recipes.default_recipe()
    return work_readiness.item_budget(r, work_recipes.default_params(r, engine), kind)  # 160-D: the step's engine or the application's


def _times(per: dict[str, Decimal], n: int) -> dict[str, str]:
    return {p: str((v * n).quantize(Decimal("0.0001"))) for p, v in per.items() if v and n}


def estimate(*, kind: str, source: dict[str, Any], party_id: str | None = None, period_start: Any = None,
             period_end: Any = None, engine: str | None = None) -> dict[str, Any]:
    """What a step would cost at most with the default processing: the items it would hold and the budget per provider
    (the recipe's item budget times the items). A mailbox's emails are counted only when a most is given; a step of an
    existing package or a reconciliation costs nothing here. With `only_new` the documents a live run has processed are
    not counted (`left_out`)."""
    if kind not in config()["kinds"]:  # 181: any registered kind of the templates
        raise explained(WorkflowError, "unknown step kind {{kind}}", kind=repr(kind))
    src = _source(kind, source)
    if src["kind"] in ("package", "none"):
        return {"items": None, "usd": {}, "note": None}
    engine = _engine(kind, src, engine)
    if (domain := workflow_steps.source_kind(src["kind"])) is not None:  # 185: a domain's source counts its items
        n, item_kind, note = domain.count(src)
        per = _per_item(item_kind, engine)
        return {"items": n or None, "usd": _times(per, n) if n else {}, "per_item": {p: str(v) for p, v in per.items()},
                "note": note}
    own = workflow_steps.of(kind).estimate
    if own is None:  # the documents are counted
        files, left_out = _documents(src)
        return {"items": len(files), "usd": _times(_per_item("document", engine), len(files)), "left_out": len(left_out),
                "note": None}
    # 181: the kind's own count (the statements': the code reads the exports for free; a PDF no reader knows is
    # extracted by AI), checked against the workflow's period first
    start, end = _period(period_start, period_end)
    counted = own(workflow_steps.paths_of(src), party_id=party_id, period_start=start, period_end=end)
    paid = counted.pop("paid")
    return {"items": counted.pop("items"), "usd": _times(_per_item("document", engine), paid), **counted, "note": None}
