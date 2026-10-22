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

The automation state of a step is stored (`workflow_steps.state`): `waiting`, `starting` (claimed: one process at a
time), `pulling` (a mailbox download queued), `started`, `linked`, `needs_budget`, `nothing_new`, `failed`. What a person
sees (`status`) adds the package's own next step. `advance` moves the chain on; the worker calls `tick` in its loop
(at most every `TICK_EVERY_S`), the service on creation and when a person starts a step.

147 (DECISIONS 147): a workflow is repeated for the next period from a draft the wizard shows filled in
(`repeat_draft`); a documents step may take only the documents no live run has processed yet (`only_new`), so the
folder of a year's invoices does not bring last month's back. The two workflows are linked (`previous_id`).

181 (plan 170 L5 = plan 160-E S6): the step kinds come from a registry (`jav/workflow_steps.py`): which packages a
step takes, how it starts, whether its source is fetched first, its engine, its repeat source, its estimate and what its
package's next step means. This module registers the documents step (the plain processing of a folder or files); the
email domain registers the emails step, the finance domain the statements and reconciliation steps. The workflow's
code names none of them.

Layer: UI/CLI → **this** (application operation) → `jav.work`, `jav.workflow_steps` (and through it the registered
kinds' modules; 185: a domain's source kind, the mailbox's), `jav.parties` and `jav.work_views.next_step`. No AI call here: the runs it starts call
them, within their budgets.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from jav import (activity_kinds, app_settings, cfg, logic_packs, package_scope, parties, scopes, store, work,
                 work_readiness, work_recipes, work_runs, workflow_steps)
from jav.user_messages import explained
from jav.clock import utc_stamp as _now

# 175 (plan 170 E4): the actions a workflow's log records (`jav/activity_kinds.py`)
activity_kinds.register_events("workflow", ("create", "update", "budget", "link", "pull", "pull_interrupted", "package", "run",
                                            "needs_budget", "nothing_new", "left_out", "failed"), __name__)

log = logging.getLogger(__name__)

CONFIG = "workflows"
PROVIDERS = ("jev", "openai", "azure_di")  # the call log's providers (jav/runtime/calls.py)
# 181: the documents step's key in the templates and the work package kinds a package of it may have (the plain
# processing of a folder, files or uploads; not a mailbox's)
DOCUMENTS = "documents"
DOCUMENT_PACKAGES = ("folder", "manual", "watch", "upload")
OPEN_STATES = ("waiting", "pulling", "needs_budget", "failed")
TICK_EVERY_S = 10.0
# 153 (review D2): a start claimed this long ago and still not finished was interrupted (a service stopped while a
# large folder was fingerprinted): the step goes to `failed`, so a person can start it again
STALE_START_S = 3600

store.register_schema("workflows", """
CREATE TABLE IF NOT EXISTS workflows (
    id            TEXT PRIMARY KEY,
    template      TEXT NOT NULL,       -- configs/workflows.json template id
    definition    TEXT NOT NULL,       -- JSON: the template as it was when made (its steps stay, whatever the config)
    name          TEXT NOT NULL,
    party_id      TEXT,                -- the own party (jav.parties); 181: only when its steps need one or it was given
    period_start  TEXT,                -- ISO date (181: only with a period)
    period_end    TEXT,                -- ISO date, inclusive
    auto          INTEGER NOT NULL DEFAULT 1,   -- the chain starts the next step by itself
    status        TEXT NOT NULL DEFAULT 'open', -- open | archived
    actor         TEXT NOT NULL,       -- who made it: the owner of its packages
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
    name           TEXT NOT NULL,      -- the work package's name
    state          TEXT NOT NULL,      -- waiting | starting | pulling | started | linked | needs_budget | nothing_new | failed
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
    cols = {r[1] for r in conn.execute("PRAGMA table_info(workflows)")}
    if cols and "previous_id" not in cols:  # 147: a workflow repeated for the next period
        conn.execute("ALTER TABLE workflows ADD COLUMN previous_id TEXT")
    if cols:
        _general_scope(conn)
    step_cols = {r[1] for r in conn.execute("PRAGMA table_info(workflow_steps)")}
    if step_cols and "engine" not in step_cols:  # 160-D: a step's own AI engine
        conn.execute("ALTER TABLE workflow_steps ADD COLUMN engine TEXT")


store.register_migration("workflows", _migrate)

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
    workflow is restored a person can start it again; before, it kept its state without a package and stood still."""
    row = c.execute("SELECT w.name FROM workflow_steps s JOIN workflows w ON w.id=s.workflow_id"
                    " WHERE s.workpackage_id=? AND w.status='open' LIMIT 1", (wp_id,)).fetchone()
    if row is not None:
        raise explained(work.NotReady, "the package is a step of an open workflow; archive the workflow first or hide the package",
                        [{"code": "workflow_step", "message": f"The package is a step of the workflow {row["name"]}: it can only be hidden."}])
    steps = c.execute("SELECT s.workflow_id, s.step, w.actor FROM workflow_steps s JOIN workflows w ON w.id=s.workflow_id"
                      " WHERE s.workpackage_id=?", (wp_id,)).fetchall()
    c.execute("UPDATE workflow_steps SET workpackage_id=NULL, run_id=NULL, state='failed', note=?, updated_at=?"
              " WHERE workpackage_id=?", (PACKAGE_DELETED, _now(), wp_id))
    for s in steps:
        _event(c, s["workflow_id"], s["step"], "failed", auto_actor(s["actor"]), {"note": PACKAGE_DELETED, "workpackage_id": wp_id})


def register() -> None:
    """173 (plan 170 E2): the delete guard of a workflow's packages and its party reference (`registrations.load_all`).
    181: the documents step kind, and a step's package's scope (`step_scope`)."""
    work.register_delete_guard(_delete_guard)
    parties.register_reference("workflows", count=_count_party, repoint=_repoint_party)
    workflow_steps.register(DOCUMENTS_STEP)
    package_scope.register_source("workflow", step_scope)


class WorkflowError(ValueError):
    """A workflow request that cannot be met: an unknown template, step or source, or a step in the wrong state."""


def auto_actor(actor: str) -> str:
    """Who an automatic start is recorded for: the workflow's maker, marked."""
    return f"{actor} (auto)"


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
    needed = {n for step in t["steps"] for n in workflow_steps.of(step["kind"]).needs}
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
           steps: dict[str, dict[str, Any]], actor: str, name: str | None = None, names: dict[str, str] | None = None,
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
                  " created_at, updated_at, previous_id, scope) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (wf_id, t["id"], json.dumps(t, ensure_ascii=False), title[:200], scope.get(scopes.PARTY), start, end,
                   int(auto), actor, now, now, previous, json.dumps(other, ensure_ascii=False)))
        for sid, source, budget, step_name, engine in rows:
            linked = source["kind"] == "package"
            c.execute("INSERT INTO workflow_steps(workflow_id, step, source, budget, name, state, workpackage_id,"
                      " updated_at, engine) VALUES (?,?,?,?,?,?,?,?,?)",
                      (wf_id, sid, json.dumps(source, ensure_ascii=False), json.dumps(budget), step_name,
                       "linked" if linked else "waiting", source.get("workpackage_id"), now, engine))
        _event(c, wf_id, None, "create", actor, {"template": t["id"], "party": scope.get(scopes.PARTY),
                                                  "period": [start, end] if start else None, "auto": bool(auto)}
               | ({"previous": previous} if previous else {}))
    if advance_now:
        advance(wf_id, actor=actor)
    return view(wf_id)


def _event(c, wf_id: str, step: str | None, action: str, actor: str, detail: dict[str, Any] | None = None) -> None:
    activity_kinds.check_event("workflow", action)
    c.execute("INSERT INTO workflow_events(workflow_id, step, action, actor, detail, created_at) VALUES (?,?,?,?,?,?)",
              (wf_id, step, action, actor, json.dumps(detail or {}, ensure_ascii=False, default=str), _now()))


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
    with store.connect() as c:
        rows = c.execute("SELECT * FROM workflow_steps WHERE workflow_id=?", (wf_id,)).fetchall()
    out = {}
    for r in rows:
        d = dict(r)
        d["source"], d["budget"] = json.loads(d["source"]), json.loads(d["budget"])
        out[d["step"]] = d
    return out


def _set(wf_id: str, step: str, *, expect: tuple[str, ...] | None = None, **fields: Any) -> bool:
    """Updates a step; with `expect` only from those states (the claim: False when another process got there first)."""
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k}=?" for k in fields)
    sql = f"UPDATE workflow_steps SET {cols} WHERE workflow_id=? AND step=?"
    args: list[Any] = [*fields.values(), wf_id, step]
    if expect:
        sql += f" AND state IN ({','.join('?' * len(expect))})"
        args += list(expect)
    with store.connect() as c:
        store.begin_immediate(c)
        changed = c.execute(sql, args).rowcount
        if changed:
            c.execute("UPDATE workflows SET updated_at=? WHERE id=?", (fields["updated_at"], wf_id))
    return bool(changed)


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
    from jav import work_views

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


def _satisfied(st: dict[str, Any]) -> bool:
    if st["state"] == "nothing_new":
        return True
    if not st.get("workpackage_id") or st["state"] not in ("started", "linked"):
        return False
    with store.connect() as c:
        kind = c.execute("SELECT source_kind FROM workpackages WHERE id=?", (st["workpackage_id"],)).fetchone()
    if kind is None:
        return False
    pack = logic_packs.of(kind["source_kind"])
    if pack is not None and not pack.has_runs:  # 176: a reconciliation step: a version of it is approved
        return pack.approved(st["workpackage_id"])
    return _live_run_approved(st["workpackage_id"])


# a processing package's next step and what it means for its step; a step kind adds its own package's (181)
STATUS_BY_NEXT = {"running": "running", "review": "review", "release": "approve", "done": "approved",
                  "start": "attention", "blocked": "attention", "rerun": "attention", "go_live": "attention",
                  "empty": "attention"}


def _status(sdef: dict[str, Any], st: dict[str, Any], done: dict[str, bool]) -> tuple[str, Any]:
    """What a person sees of a step, and its package's next step."""
    if st["state"] in ("started", "linked") and st.get("workpackage_id"):
        approved, nxt = _package_state(st["workpackage_id"])
        if nxt is None:
            return "missing", None
        statuses = {**STATUS_BY_NEXT, **workflow_steps.of(sdef["kind"]).statuses}
        return ("approved" if approved else statuses.get(nxt["code"], "attention")), nxt
    if st["state"] == "waiting":
        return ("ready" if all(done.get(a) for a in sdef.get("after", [])) else "waiting"), None
    return st["state"], None  # starting, pulling, needs_budget, nothing_new, failed


@store.one_connection
def view(wf_id: str) -> dict[str, Any]:
    """The control view: the workflow, its steps in order with their state, package and next step, what needs a person
    first, and the latest events."""
    wf = _row(wf_id)
    steps = _steps(wf_id)
    kinds = config()["kinds"]
    party_names = {p["id"]: p["name"] for p in parties.parties()}
    done = {sid: _satisfied(st) for sid, st in steps.items()}
    out_steps = []
    for sdef in wf["definition"]["steps"]:
        st = steps[sdef["id"]]
        status, nxt = _status(sdef, st, done)
        package = None
        if st.get("workpackage_id"):
            try:
                package = {"id": st["workpackage_id"], "name": work.get(st["workpackage_id"])["name"], "next": nxt}
            except KeyError:
                package = {"id": st["workpackage_id"], "name": None, "next": None}
        note = st.get("note")
        if st["state"] == "needs_budget" and note:
            note = json.loads(note)
        out_steps.append({"id": sdef["id"], "kind": sdef["kind"], "title": _step_title(sdef),
                          "kind_title": kinds[sdef["kind"]]["title"], "after": sdef.get("after", []),
                          "source": _shown_source(st["source"]), "budget": st["budget"], "engine": st.get("engine"),
                          "name": st["name"],
                          "state": st["state"], "status": status, "done": done[sdef["id"]], "note": note,
                          "package": package, "run_id": st.get("run_id"), "pull_id": st.get("pull_id"),
                          "updated_at": st["updated_at"]})
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
def advance(wf_id: str, *, actor: str) -> dict[str, Any]:
    """Moves the chain on: a finished mailbox download gets its package and run; a waiting step whose steps it waits for
    are done starts (only while the workflow's chain is automatic). Idempotent; each start is claimed first."""
    wf = _row(wf_id)
    if wf["status"] != "open":
        return view(wf_id)
    for sdef in wf["definition"]["steps"]:
        steps = _steps(wf_id)
        st = steps[sdef["id"]]
        if st["state"] == "pulling":
            _poll(wf, sdef, st, actor)
        elif st["state"] == "waiting" and wf["auto"] and all(_satisfied(steps[a]) for a in sdef.get("after", [])):
            _start(wf, sdef, actor=actor)
    return view(wf_id)


def start_step(wf_id: str, step: str, *, actor: str, budget: dict[str, Any] | None = None) -> dict[str, Any]:
    """A person starts a step now (whatever the steps it waits for), retries a failed one, or starts one that waits for
    a budget; a `budget` given here replaces the step's budget (the person's own decision, recorded)."""
    wf = _row(wf_id)
    if wf["status"] != "open":
        raise explained(WorkflowError, "the workflow is archived")
    sdef = next((s for s in wf["definition"]["steps"] if s["id"] == step), None)
    if sdef is None:
        raise explained(WorkflowError, "unknown step {{step}}", step=repr(step))
    st = _steps(wf_id)[step]
    if st["state"] not in ("waiting", "failed", "needs_budget"):
        raise explained(WorkflowError, "step {{step}} is {{state}}: it cannot be started",
                        step=repr(step), state=st["state"])
    if budget is not None:
        new = _budget(budget)
        _set(wf_id, step, budget=json.dumps(new))
        with store.connect() as c:
            store.begin_immediate(c)
            _event(c, wf_id, step, "budget", actor, {"from": st["budget"], "to": new})
    st = _steps(wf_id)[step]
    if st.get("workpackage_id") and st["state"] in ("needs_budget", "failed"):
        if _set(wf_id, step, expect=("needs_budget", "failed"), state="starting"):
            _start_run(wf, sdef, _steps(wf_id)[step], st["workpackage_id"], actor=actor)
    else:
        _start(wf, sdef, actor=actor, states=("waiting", "failed"))
    return view(wf_id)


def link(wf_id: str, step: str, wp_id: str, *, actor: str) -> dict[str, Any]:
    """A person makes an existing work package the step's package (the chain starts no run on it)."""
    wf = _row(wf_id)
    sdef = next((s for s in wf["definition"]["steps"] if s["id"] == step), None)
    if sdef is None:
        raise explained(WorkflowError, "unknown step {{step}}", step=repr(step))
    _check_package(sdef["kind"], wp_id)
    if not _set(wf_id, step, expect=("waiting", "failed", "nothing_new"), state="linked", workpackage_id=wp_id,
                source=json.dumps({"kind": "package", "workpackage_id": wp_id}), note=None):
        raise explained(WorkflowError, "step {{step}} has started already", step=repr(step))
    with store.connect() as c:
        store.begin_immediate(c)
        _event(c, wf_id, step, "link", actor, {"workpackage": wp_id})
    return view(wf_id)


def update(wf_id: str, *, actor: str, auto: bool | None = None, name: str | None = None,
           archived: bool | None = None) -> dict[str, Any]:
    """Switches the automatic chain, renames, archives or restores a workflow (its packages stay as they are)."""
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
            c.execute(f"UPDATE workflows SET {', '.join(f'{k}=?' for k in changes)}, updated_at=? WHERE id=?",
                      (*changes.values(), _now(), wf_id))
            _event(c, wf_id, None, "update", actor, changes)
    if changes.get("auto"):
        advance(wf_id, actor=actor)
    return view(wf_id)


def _done(wf: dict[str, Any], step: str, actor: str, action: str, **fields: Any) -> None:
    _set(wf["id"], step, **fields)
    with store.connect() as c:
        store.begin_immediate(c)
        _event(c, wf["id"], step, action, actor,
               {k: v for k, v in fields.items() if k in ("workpackage_id", "run_id", "pull_id", "note")})


def _start(wf: dict[str, Any], sdef: dict[str, Any], *, actor: str, states: tuple[str, ...] = ("waiting",)) -> None:
    """Makes the step's package (or queues its mailbox download) and starts its run; a failure stays on the step. 160
    (review R-2): the package is noted on the step as soon as it exists, so a start interrupted later (before or after
    the run was made) is started again with that package (`start_step`), never with a second one."""
    step = sdef["id"]
    if not _set(wf["id"], step, expect=states, state="starting", note=None):
        return  # another process has it, or it is past waiting
    st = _steps(wf["id"])[step]
    try:
        workflow_steps.of(sdef["kind"]).start(_context(wf, sdef, st, actor))  # 181: the kind's own start
    except Exception as exc:  # the step shows why; a person retries it
        log.warning("workflow %s step %s did not start: %s", wf["id"], step, exc)
        _done(wf, step, actor, "failed", state="failed", note=str(exc)[:1000])
    except BaseException:  # 153 (review D2): interrupted (the process stops): the claim is released, then it stops
        _done(wf, step, actor, "failed", state="failed", note=INTERRUPTED)
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


def _context(wf: dict[str, Any], sdef: dict[str, Any], st: dict[str, Any], actor: str) -> workflow_steps.StepStart:
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
        made=lambda wp_id: _done(wf, step, actor, "package", state="started", workpackage_id=wp_id),
        nothing_new=lambda note: _done(wf, step, actor, "nothing_new", state="nothing_new", note=note),
        fetching=lambda fetch_id: _done(wf, step, actor, "pull", state="pulling", pull_id=fetch_id),
        claim=lambda: _set(wf_id, step, expect=("pulling",), state="starting"),
        failed=lambda note: _done(wf, step, actor, "failed", state="failed", note=note[:1000]),
        event=event)


def _poll(wf: dict[str, Any], sdef: dict[str, Any], st: dict[str, Any], actor: str) -> None:
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
        wp = work.create_from_folder(Path(source["folder"]), name=ctx.state["name"], owner=wf["actor"],
                                     recursive=source["recursive"], exclude=_exclude(source),
                                     only=files if left_out else None)
    elif files:
        wp = work.create_from_files(files, name=ctx.state["name"], owner=wf["actor"])
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


def _give_engine(wp_id: str, engine: str | None, *, actor: str) -> None:
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


def _start_run(wf: dict[str, Any], sdef: dict[str, Any], st: dict[str, Any], wp_id: str, *, actor: str) -> None:
    """The package's live run, when its own estimate fits the step's budget; otherwise the step waits for a person."""
    step = sdef["id"]
    try:
        _give_engine(wp_id, st.get("engine"), actor=actor)
        ready = work_readiness.readiness(wp_id)
        if not ready["ready"]:
            raise WorkflowError("; ".join(b["message"] for b in ready["blockers"]) or "the package cannot start")
        budget = _steps(wf["id"])[step]["budget"]
        estimate = {p: Decimal(str(v)) for p, v in (ready.get("budget") or {}).items()}
        over = {p: str(v) for p, v in estimate.items() if v > Decimal(budget.get(p, "0"))}
        if over:
            note = {"estimate": {p: str(v) for p, v in estimate.items()}, "budget": budget, "over": over}
            _done(wf, step, actor, "needs_budget", state="needs_budget", workpackage_id=wp_id,
                  note=json.dumps(note))
            return
        res = work_runs.start_run(wp_id, mode="apply", expected_assignment_revision=ready["assignment_revision"],
                             input_hash=ready["input_hash"], actor=actor)
        _done(wf, step, actor, "run", state="started", workpackage_id=wp_id, run_id=res["run_id"])
    except Exception as exc:
        log.warning("workflow %s step %s: run not started: %s", wf["id"], step, exc)
        _done(wf, step, actor, "failed", state="failed", workpackage_id=wp_id, note=str(exc)[:1000])


_last_tick = 0.0


INTERRUPTED = "the start was interrupted; start the step again"


def release_stale_starts(max_age_s: float = STALE_START_S) -> int:
    """153 (review D2): steps claimed for a start more than `max_age_s` ago and never finished (the process that held
    the claim stopped) go to `failed` with a note, so a person can start them again; before, they stayed "starting" for
    good. Returns how many it released."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max_age_s)).isoformat(timespec="seconds")
    with store.connect() as c:
        stale = c.execute("SELECT s.workflow_id, s.step, w.actor FROM workflow_steps s JOIN workflows w ON w.id=s.workflow_id"
                          " WHERE s.state='starting' AND s.updated_at < ?", (cutoff,)).fetchall()
    released = 0
    for r in stale:
        if _set(r["workflow_id"], r["step"], expect=("starting",), state="failed", note=INTERRUPTED):
            with store.connect() as c:
                store.begin_immediate(c)
                _event(c, r["workflow_id"], r["step"], "failed", auto_actor(r["actor"]), {"note": INTERRUPTED})
            released += 1
    return released


def tick(now: float | None = None) -> int:
    """The worker's turn (at most every `TICK_EVERY_S`): releases interrupted starts (153), then advances every open,
    automatic workflow with a step still to move. Returns how many it looked at."""
    global _last_tick
    now = time.monotonic() if now is None else now
    if now - _last_tick < TICK_EVERY_S:
        return 0
    _last_tick = now
    release_stale_starts()
    with store.connect() as c:
        rows = c.execute("SELECT DISTINCT w.id, w.actor FROM workflows w JOIN workflow_steps s ON s.workflow_id=w.id"
                         " WHERE w.status='open' AND w.auto=1 AND s.state IN ('waiting', 'pulling')").fetchall()
    for r in rows:
        try:
            advance(r["id"], actor=auto_actor(r["actor"]))
        except Exception:  # one workflow's trouble does not stop the others
            log.exception("workflow %s could not advance", r["id"])
    return len(rows)


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
