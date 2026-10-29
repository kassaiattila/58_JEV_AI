"""231 (plan stage C, C3i): the workflows' records, split out of `workflows.py`.

Plain-language summary: the workflows' tables and their migrations, the hooks an own party's merge and a package's
deletion need, the templates (`configs/workflows.json`), a workflow's stored row, steps and events, how a step's
status and a workflow's view are read, and the checks a new workflow's period, budget, engine, source and package go
through. The rules they follow are described in `workflows.py`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from jav.app import (
    logic_packs, package_release, package_scope, parties, scopes, work, work_recipes, work_runs, workflow_cases, workflow_steps,
)
from jav.core import activity_kinds, cfg, identity, store
from jav.core.process import cases as process_cases
from jav.core.user_messages import explained
from jav.core.clock import utc_stamp as _now


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
    store.begin_immediate(conn)  # 231 (E3): the shared write lock
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
    181: a step's package's scope (`step_scope`); 231 (C3b5b) the documents step kind is the documents pack's (made by
    the process runtime from the pack, `document_processing.register_workflow_steps`)."""
    work.register_delete_guard(_delete_guard)
    parties.register_reference("workflows", count=_count_party, repoint=_repoint_party)
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
    if wp["source_kind"] not in package_kinds(kind) or work.rule_name(wp_id) != workflow_steps.of(kind).rule:
        raise explained(WorkflowError, "work package {{name}} is not of a {{kind}} step's kind",
                        name=repr(wp["name"]), kind=kind)  # 231 (C3b5a): its rule too (a statement package's)
    with store.connect() as c:
        if c.execute("SELECT 1 FROM workflow_steps WHERE workpackage_id=?", (wp_id,)).fetchone():
            raise explained(WorkflowError, "work package {{name}} already belongs to a workflow", name=repr(wp["name"]))


def _event(c, wf_id: str, step: str | None, action: str, actor: identity.Who,
           detail: dict[str, Any] | None = None) -> None:
    activity_kinds.check_event("workflow", action)
    c.execute("INSERT INTO workflow_events(workflow_id, step, action, actor, actor_id, detail, created_at)"
              " VALUES (?,?,?,?,?,?,?)", (wf_id, step, action, identity.name_of(actor), identity.id_of(actor),
                                          json.dumps(detail or {}, ensure_ascii=False, default=str), _now()))


def _row(wf_id: str) -> dict[str, Any]:
    with store.connect() as c:
        row = c.execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
    if row is None:
        raise KeyError(wf_id)
    out = dict(row)
    out["definition"] = resolved(json.loads(out["definition"]))
    out["auto"] = bool(out["auto"])
    return out


def resolved(definition: dict[str, Any]) -> dict[str, Any]:
    """231 (C3a-2): a saved template as it runs now: a step of a retired kind reads as the kind that replaced it
    (`configs/workflows.json` `retired_kinds`: the reconciliation step as the reconciliation pack's process step),
    its id, title, order and role kept. The saved text stays as it was (its case's definition is its fingerprint)."""
    retired = config().get("retired_kinds") or {}
    steps = [{**s, **retired[s["kind"]]} if s.get("kind") in retired else s for s in definition.get("steps", [])]
    return {**definition, "steps": steps}


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
    sdef = next((x for x in resolved(json.loads(row["definition"]))["steps"] if x["id"] == row["step"]), {})
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
