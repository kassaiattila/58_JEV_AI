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

Layer: UI/CLI → **this** (application operation) → `jav.work`, `jav.statement_package`, `jav.reconcile_package`,
`jav.mailbox`, `jav.parties` and `jav.work_views.next_step`. No AI call here: the runs it starts call them, within their
budgets.
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

from jav import app_settings, cfg, mailbox, parties, reconcile_package, statement_package, store, work

log = logging.getLogger(__name__)

CONFIG = "workflows"
PROVIDERS = ("jev", "openai", "azure_di")  # the call log's providers (jav/runtime/calls.py)
# the work package kinds (source_kind) an existing package of a step's kind may have
PACKAGE_KINDS = {"documents": ("folder", "manual", "watch", "upload"), "emails": ("mailbox",),
                 "statements": ("statements",), "reconcile": ("reconcile",)}
OPEN_STATES = ("waiting", "pulling", "needs_budget", "failed")
TICK_EVERY_S = 10.0

store.register_schema("workflows", """
CREATE TABLE IF NOT EXISTS workflows (
    id            TEXT PRIMARY KEY,
    template      TEXT NOT NULL,       -- configs/workflows.json template id
    definition    TEXT NOT NULL,       -- JSON: the template as it was when made (its steps stay, whatever the config)
    name          TEXT NOT NULL,
    party_id      TEXT NOT NULL,       -- the own party (jav.parties)
    period_start  TEXT NOT NULL,       -- ISO date
    period_end    TEXT NOT NULL,       -- ISO date, inclusive
    auto          INTEGER NOT NULL DEFAULT 1,   -- the chain starts the next step by itself
    status        TEXT NOT NULL DEFAULT 'open', -- open | archived
    actor         TEXT NOT NULL,       -- who made it: the owner of its packages
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    previous_id   TEXT                 -- 147: the workflow this one repeats for the next period
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


def _migrate(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(workflows)")}
    if cols and "previous_id" not in cols:  # 147: a workflow repeated for the next period
        conn.execute("ALTER TABLE workflows ADD COLUMN previous_id TEXT")


store.register_migration("workflows", _migrate)


class WorkflowError(ValueError):
    """A workflow request that cannot be met: an unknown template, step or source, or a step in the wrong state."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def auto_actor(actor: str) -> str:
    """Who an automatic start is recorded for: the workflow's maker, marked."""
    return f"{actor} (auto)"


# --- templates ------------------------------------------------------------------------------------------------------


def config() -> dict[str, Any]:
    return cfg.load(CONFIG)


def template(template_id: str) -> dict[str, Any]:
    for t in config()["templates"]:
        if t["id"] == template_id:
            return t
    raise WorkflowError(f"unknown workflow template {template_id!r}")


def is_workflow(t: dict[str, Any]) -> bool:
    """A template of several steps makes a workflow; a one-step template is a single work package."""
    return len(t["steps"]) > 1


def _step_title(step: dict[str, Any]) -> str:
    return step.get("title") or config()["kinds"][step["kind"]]["title"]


# --- making one -------------------------------------------------------------------------------------------------------


def _party(party_id: str) -> dict[str, Any]:
    for p in parties.parties():
        if p["id"] == party_id:
            return p
    raise WorkflowError(f"unknown own party {party_id!r}")


def _period(start: Any, end: Any) -> tuple[str, str]:
    try:
        a, b = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    except ValueError as exc:
        raise WorkflowError(f"a period is two dates (YYYY-MM-DD): {exc}") from exc
    if a > b:
        raise WorkflowError("the period ends before it starts")
    return a.isoformat(), b.isoformat()


def _budget(raw: dict[str, Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for provider, value in (raw or {}).items():
        if provider not in PROVIDERS:
            raise WorkflowError(f"unknown budget provider {provider!r}")
        try:
            amount = Decimal(str(value))
        except InvalidOperation as exc:
            raise WorkflowError(f"a budget is an amount in USD: {value!r}") from exc
        if amount < 0 or amount > 1000:
            raise WorkflowError(f"a budget is between 0 and 1000 USD: {value!r}")
        out[provider] = str(amount)
    return out


def _source(kind: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    """A step's source as the wizard gave it, checked against the kind's allowed sources. A documents step's folder or
    files may take only the documents no live run has processed yet (`only_new`, 147)."""
    raw = dict(raw or {})
    src = raw.get("kind")
    if src not in config()["kinds"][kind]["sources"]:
        raise WorkflowError(f"a {kind} step takes no {src!r} source")
    only_new = {"only_new": bool(raw.get("only_new"))} if kind == "documents" else {}
    if raw.get("only_new") and not only_new:
        raise WorkflowError("only a documents step can leave out the documents a live run has processed")
    if src == "folder":
        folder = Path(str(raw.get("folder") or ""))
        if not folder.is_dir():
            raise WorkflowError(f"folder does not exist: {folder}")
        return {"kind": "folder", "folder": str(folder), "recursive": bool(raw.get("recursive"))} | only_new
    if src == "files":
        paths = [str(p) for p in raw.get("paths") or [] if str(p).strip()]
        if not paths:
            raise WorkflowError("give at least one file")
        if missing := [p for p in paths if not Path(p).is_file()]:
            raise WorkflowError(f"{len(missing)} file(s) do not exist, the first: {missing[0]}")
        return {"kind": "files", "paths": paths} | only_new
    if src == "mailbox":
        request = mailbox.MailboxRequest.model_validate(raw.get("request") or {})
        return {"kind": "mailbox", "request": request.model_dump(mode="json")}
    if src == "package":
        wp_id = str(raw.get("workpackage_id") or "")
        _check_package(kind, wp_id)
        return {"kind": "package", "workpackage_id": wp_id}
    return {"kind": "none"}


def _check_package(kind: str, wp_id: str) -> None:
    try:
        wp = work.get(wp_id)
    except KeyError as exc:
        raise WorkflowError(f"no work package {wp_id!r}") from exc
    if wp["source_kind"] not in PACKAGE_KINDS[kind]:
        raise WorkflowError(f"work package {wp['name']!r} is not of a {kind} step's kind")
    with store.connect() as c:
        if c.execute("SELECT 1 FROM workflow_steps WHERE workpackage_id=?", (wp_id,)).fetchone():
            raise WorkflowError(f"work package {wp['name']!r} already belongs to a workflow")


def create(*, template_id: str, party_id: str, period_start: Any, period_end: Any, steps: dict[str, dict[str, Any]],
           actor: str, name: str | None = None, names: dict[str, str] | None = None, auto: bool = True,
           advance_now: bool = True, previous: str | None = None) -> dict[str, Any]:
    """A new workflow of a template of several steps: every step needs its source (`steps[step]["source"]`) and may
    have a budget (`steps[step]["budget"]`, {provider: usd}); `names` are the steps' package names (the interface
    passes them in its language). With `advance_now` the steps that wait for nothing start at once. `previous` (147):
    the workflow this one repeats for the next period (`repeat_draft`)."""
    t = template(template_id)
    if not is_workflow(t):
        raise WorkflowError("a one-step template makes a work package, not a workflow")
    if previous is not None and _brief(previous) is None:
        raise WorkflowError(f"no workflow {previous!r} to repeat")
    party = _party(party_id)
    start, end = _period(period_start, period_end)
    defs = {s["id"]: s for s in t["steps"]}
    if unknown := set(steps) - set(defs):
        raise WorkflowError(f"unknown step(s) of {template_id}: {sorted(unknown)}")
    title = name.strip() if name and name.strip() else f"{party['name']} {start} – {end}"
    rows = []
    for sid, sdef in defs.items():
        given = steps.get(sid) or {}
        if "source" not in given:
            raise WorkflowError(f"step {sid!r} needs its source")
        source = _source(sdef["kind"], given["source"])
        step_name = ((names or {}).get(sid) or f"{title} · {_step_title(sdef)}").strip()[:200]
        rows.append((sid, source, _budget(given.get("budget")), step_name))
    wf_id = f"wf-{uuid.uuid4().hex[:12]}"
    now = _now()
    with store.connect() as c:
        store.begin_immediate(c)
        c.execute("INSERT INTO workflows(id, template, definition, name, party_id, period_start, period_end, auto, actor,"
                  " created_at, updated_at, previous_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (wf_id, t["id"], json.dumps(t, ensure_ascii=False), title[:200], party["id"], start, end, int(auto),
                   actor, now, now, previous))
        for sid, source, budget, step_name in rows:
            linked = source["kind"] == "package"
            c.execute("INSERT INTO workflow_steps(workflow_id, step, source, budget, name, state, workpackage_id,"
                      " updated_at) VALUES (?,?,?,?,?,?,?,?)",
                      (wf_id, sid, json.dumps(source, ensure_ascii=False), json.dumps(budget), step_name,
                       "linked" if linked else "waiting", source.get("workpackage_id"), now))
        _event(c, wf_id, None, "create", actor, {"template": t["id"], "party": party["id"], "period": [start, end],
                                                  "auto": bool(auto)} | ({"previous": previous} if previous else {}))
    if advance_now:
        advance(wf_id, actor=actor)
    return view(wf_id)


def _event(c, wf_id: str, step: str | None, action: str, actor: str, detail: dict[str, Any] | None = None) -> None:
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
    if wp["source_kind"] == "reconcile":
        approved = reconcile_package.approval(wp_id)["active"] is not None
        return approved, reconcile_package.package_view(wp_id)["next"]
    runs = work.run_rows(wp_id)
    nxt = work_views.next_step(wp, runs[0] if runs else None)
    return _live_run_approved(wp_id), nxt


def _live_run_approved(wp_id: str) -> bool:
    with store.connect() as c:
        row = c.execute("SELECT approval FROM runs WHERE workpackage_id=? AND mode='apply' ORDER BY created_at DESC, rowid DESC"
                        " LIMIT 1", (wp_id,)).fetchone()
    return bool(row and row["approval"])


def _satisfied(st: dict[str, Any]) -> bool:
    if st["state"] == "nothing_new":
        return True
    if not st.get("workpackage_id") or st["state"] not in ("started", "linked"):
        return False
    with store.connect() as c:
        kind = c.execute("SELECT source_kind FROM workpackages WHERE id=?", (st["workpackage_id"],)).fetchone()
    if kind is None:
        return False
    if kind["source_kind"] == "reconcile":
        return reconcile_package.approval(st["workpackage_id"])["active"] is not None
    return _live_run_approved(st["workpackage_id"])


STATUS_BY_NEXT = {"running": "running", "review": "review", "approve": "approve", "done": "approved",
                  "reconcile_approved": "approved", "reconcile_pair": "pairing", "reconcile_result": "pairing",
                  "reconcile_empty": "pairing", "start": "attention", "blocked": "attention", "rerun": "attention",
                  "go_live": "attention", "empty": "attention"}


def _status(sdef: dict[str, Any], st: dict[str, Any], done: dict[str, bool]) -> tuple[str, Any]:
    """What a person sees of a step, and its package's next step."""
    if st["state"] in ("started", "linked") and st.get("workpackage_id"):
        approved, nxt = _package_state(st["workpackage_id"])
        if nxt is None:
            return "missing", None
        return ("approved" if approved else STATUS_BY_NEXT.get(nxt["code"], "attention")), nxt
    if st["state"] == "waiting":
        return ("ready" if all(done.get(a) for a in sdef.get("after", [])) else "waiting"), None
    return st["state"], None  # starting, pulling, needs_budget, nothing_new, failed


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
                          "source": _shown_source(st["source"]), "budget": st["budget"], "name": st["name"],
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
    if source["kind"] == "mailbox":
        req = source["request"]
        return {"kind": "mailbox", "accounts": req.get("accounts"), "folders": req.get("folders")}
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
    """The source a linked package's step repeats from: the package's folder (a documents or statements package made
    from one), nothing for a reconciliation; None when it cannot be told (the wizard asks for it)."""
    if kind == "reconcile":
        return {"kind": "none"}
    try:
        wp = work.get(wp_id)
    except KeyError:
        return None
    ref = wp.get("source_ref")
    if kind in ("documents", "statements") and wp["source_kind"] in ("folder", "watch", "statements") and ref \
            and Path(ref).is_dir():
        return {"kind": "folder", "folder": ref, "recursive": False} | ({"only_new": True} if kind == "documents" else {})
    return None


def _repeated_source(kind: str, source: dict[str, Any], period: tuple[str, str], wf: dict[str, Any]) -> dict[str, Any] | None:
    if source["kind"] == "package":
        return _package_source(kind, source["workpackage_id"])
    if kind == "documents" and source["kind"] in ("folder", "files"):
        return source | {"only_new": True}  # last period's documents are not brought back
    if source["kind"] == "mailbox":
        req = dict(source["request"])
        if req.get("received_from") or req.get("received_to"):
            own = (req.get("received_from"), req.get("received_to"))
            moved = period if own == (wf["period_start"], wf["period_end"]) else next_period(
                own[0] or wf["period_start"], own[1] or wf["period_end"])
            req["received_from"], req["received_to"] = moved
        return {"kind": "mailbox", "request": req}  # a number of days stays as it is
    return source


def repeat_draft(wf_id: str) -> dict[str, Any]:
    """The workflow for the next period as the wizard shows it filled in: the template, the party, the steps' sources and
    budgets, the name with the new period (None when the name does not hold the period: the wizard proposes one). A
    documents step takes only the documents no live run has processed; a mailbox's dates move on. Nothing is written: a
    person checks it and makes the new workflow (`create` with `previous`), approving its budgets again."""
    wf = _row(wf_id)
    period = next_period(wf["period_start"], wf["period_end"])
    name = wf["name"]
    named = wf["period_start"] in name and wf["period_end"] in name
    steps = _steps(wf_id)
    return {"template": wf["template"], "party_id": wf["party_id"], "period_start": period[0], "period_end": period[1],
            "name": name.replace(wf["period_start"], period[0]).replace(wf["period_end"], period[1]) if named else None,
            "auto": wf["auto"], "previous": wf_id,
            "steps": {s["id"]: {"source": _repeated_source(s["kind"], steps[s["id"]]["source"], period, wf),
                                "budget": steps[s["id"]]["budget"]} for s in wf["definition"]["steps"]}}


# --- moving on ----------------------------------------------------------------------------------------------------------


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
            _poll_pull(wf, sdef, st, actor)
        elif st["state"] == "waiting" and wf["auto"] and all(_satisfied(steps[a]) for a in sdef.get("after", [])):
            _start(wf, sdef, actor=actor)
    return view(wf_id)


def start_step(wf_id: str, step: str, *, actor: str, budget: dict[str, Any] | None = None) -> dict[str, Any]:
    """A person starts a step now (whatever the steps it waits for), retries a failed one, or starts one that waits for
    a budget; a `budget` given here replaces the step's budget (the person's own decision, recorded)."""
    wf = _row(wf_id)
    if wf["status"] != "open":
        raise WorkflowError("the workflow is archived")
    sdef = next((s for s in wf["definition"]["steps"] if s["id"] == step), None)
    if sdef is None:
        raise WorkflowError(f"unknown step {step!r}")
    st = _steps(wf_id)[step]
    if st["state"] not in ("waiting", "failed", "needs_budget"):
        raise WorkflowError(f"step {step!r} is {st['state']}: it cannot be started")
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
        raise WorkflowError(f"unknown step {step!r}")
    _check_package(sdef["kind"], wp_id)
    if not _set(wf_id, step, expect=("waiting", "failed", "nothing_new"), state="linked", workpackage_id=wp_id,
                source=json.dumps({"kind": "package", "workpackage_id": wp_id}), note=None):
        raise WorkflowError(f"step {step!r} has started already")
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
    """Makes the step's package (or queues its mailbox download) and starts its run; a failure stays on the step."""
    step = sdef["id"]
    if not _set(wf["id"], step, expect=states, state="starting", note=None):
        return  # another process has it, or it is past waiting
    st = _steps(wf["id"])[step]
    source = st["source"]
    try:
        if sdef["kind"] == "emails":
            req = mailbox.MailboxRequest.model_validate(source["request"])
            pull = mailbox.request_pull(req, actor=wf["actor"], dedup_key=f"workflow:{wf['id']}:{step}:{uuid.uuid4().hex[:8]}")
            _done(wf, step, actor, "pull", state="pulling", pull_id=str(pull["id"]))
        elif sdef["kind"] == "documents":
            _start_documents(wf, sdef, st, actor=actor)
        elif sdef["kind"] == "statements":
            _start_statements(wf, sdef, st, actor=actor)
        elif sdef["kind"] == "reconcile":
            keys = [a["key"] for a in reconcile_package.accounts() if (a.get("party") or {}).get("id") == wf["party_id"]]
            if not keys:
                raise WorkflowError("the party has no account or card with a statement yet")
            scope = reconcile_package.create(name=st["name"], accounts=keys, period_start=wf["period_start"],
                                             period_end=wf["period_end"], actor=wf["actor"], party_id=wf["party_id"])
            _done(wf, step, actor, "package", state="started", workpackage_id=scope["workpackage_id"])
        else:
            raise WorkflowError(f"unknown step kind {sdef['kind']!r}")
    except Exception as exc:  # the step shows why; a person retries it
        log.warning("workflow %s step %s did not start: %s", wf["id"], step, exc)
        _done(wf, step, actor, "failed", state="failed", note=str(exc)[:1000])


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


def _start_documents(wf: dict[str, Any], sdef: dict[str, Any], st: dict[str, Any], *, actor: str) -> None:
    source, step = st["source"], sdef["id"]
    files, left_out = _documents(source)
    wp = None
    if files and source["kind"] == "folder":
        wp = work.create_from_folder(Path(source["folder"]), name=st["name"], owner=wf["actor"],
                                     recursive=source["recursive"], exclude=_exclude(source),
                                     only=files if left_out else None)
    elif files:
        wp = work.create_from_files(files, name=st["name"], owner=wf["actor"])
    if wp is None or not work.get(wp["id"])["items"]:
        if wp is not None:
            work.delete_workpackage(wp["id"], actor=actor)
        note = f"no new documents: {len(left_out)} already processed" if left_out else "no documents in the folder"
        _done(wf, step, actor, "nothing_new", state="nothing_new", note=note)
        return
    if left_out:
        with store.connect() as c:
            store.begin_immediate(c)
            _event(c, wf["id"], step, "left_out", actor, {"new": len(files), "left_out": len(left_out)})
    _start_run(wf, sdef, st, wp["id"], actor=actor)


def _start_statements(wf: dict[str, Any], sdef: dict[str, Any], st: dict[str, Any], *, actor: str) -> None:
    source = st["source"]
    paths = [Path(source["folder"])] if source["kind"] == "folder" else [Path(p) for p in source["paths"]]
    survey = statement_package.survey(paths, party_id=wf["party_id"], period_start=wf["period_start"],
                                      period_end=wf["period_end"])
    chosen = [s["id"] for s in survey["statements"] if s["chosen"]]
    pdfs = [p["path"] for p in survey["pdfs"] if p["chosen"]]
    if not chosen and not pdfs:
        _done(wf, sdef["id"], actor, "nothing_new", state="nothing_new",
              note=f"no new statement: {len(survey['statements'])} statement(s) and {len(survey['pdfs'])} PDF(s) "
                   "are in the store or outside the period")
        return
    scope = statement_package.create(name=st["name"], party_id=wf["party_id"], period_start=wf["period_start"],
                                     period_end=wf["period_end"], paths=paths, statements=chosen, pdfs=pdfs,
                                     actor=wf["actor"])
    _start_run(wf, sdef, st, scope["workpackage_id"], actor=actor)


def _poll_pull(wf: dict[str, Any], sdef: dict[str, Any], st: dict[str, Any], actor: str) -> None:
    pull = mailbox.pull(st["pull_id"])
    if pull["status"] in ("queued", "running"):
        return
    if not _set(wf["id"], sdef["id"], expect=("pulling",), state="starting"):
        return
    result = pull.get("result") or {}
    if pull["status"] != "ok":
        _done(wf, sdef["id"], actor, "failed", state="failed", note=str(result.get("error") or pull["status"])[:1000])
    elif not result.get("workpackage"):
        _done(wf, sdef["id"], actor, "nothing_new", state="nothing_new", note="no new emails")
    else:
        _start_run(wf, sdef, st, result["workpackage"], actor=actor)


def _start_run(wf: dict[str, Any], sdef: dict[str, Any], st: dict[str, Any], wp_id: str, *, actor: str) -> None:
    """The package's live run, when its own estimate fits the step's budget; otherwise the step waits for a person."""
    step = sdef["id"]
    try:
        ready = work.readiness(wp_id)
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
        res = work.start_run(wp_id, mode="apply", expected_assignment_revision=ready["assignment_revision"],
                             input_hash=ready["input_hash"], actor=actor)
        _done(wf, step, actor, "run", state="started", workpackage_id=wp_id, run_id=res["run_id"])
    except Exception as exc:
        log.warning("workflow %s step %s: run not started: %s", wf["id"], step, exc)
        _done(wf, step, actor, "failed", state="failed", workpackage_id=wp_id, note=str(exc)[:1000])


_last_tick = 0.0


def tick(now: float | None = None) -> int:
    """The worker's turn (at most every `TICK_EVERY_S`): advances every open, automatic workflow with a step still to
    move. Returns how many it looked at."""
    global _last_tick
    now = time.monotonic() if now is None else now
    if now - _last_tick < TICK_EVERY_S:
        return 0
    _last_tick = now
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


def _per_item(kind: str) -> dict[str, Decimal]:
    r = work.default_recipe()
    return work.item_budget(r, work.carried_params(r, {}), kind)


def _times(per: dict[str, Decimal], n: int) -> dict[str, str]:
    return {p: str((v * n).quantize(Decimal("0.0001"))) for p, v in per.items() if v and n}


def estimate(*, kind: str, source: dict[str, Any], party_id: str | None = None, period_start: Any = None,
             period_end: Any = None) -> dict[str, Any]:
    """What a step would cost at most with the default processing: the items it would hold and the budget per provider
    (the recipe's item budget times the items). A mailbox's emails are counted only when a most is given; a step of an
    existing package or a reconciliation costs nothing here. With `only_new` the documents a live run has processed are
    not counted (`left_out`)."""
    src = _source(kind, source)
    if src["kind"] in ("package", "none"):
        return {"items": None, "usd": {}, "note": None}
    if src["kind"] == "mailbox":
        n = src["request"].get("max_items") or 0
        per = _per_item("email")
        return {"items": n or None, "usd": _times(per, n) if n else {}, "per_item": {p: str(v) for p, v in per.items()},
                "note": "each email's PDF attachments add a document's budget"}
    if kind == "documents":
        files, left_out = _documents(src)
        return {"items": len(files), "usd": _times(_per_item("document"), len(files)), "left_out": len(left_out),
                "note": None}
    # statements: the code reads the exports for free; a PDF no reader knows is extracted by AI
    start, end = _period(period_start, period_end)
    paths = [Path(src["folder"])] if src["kind"] == "folder" else [Path(p) for p in src["paths"]]
    survey = statement_package.survey(paths, party_id=str(party_id), period_start=start, period_end=end)
    statements = sum(1 for s in survey["statements"] if s["chosen"])
    pdfs = sum(1 for p in survey["pdfs"] if p["chosen"])
    return {"items": statements + pdfs, "usd": _times(_per_item("document"), pdfs), "statements": statements, "pdfs": pdfs,
            "note": None}
