"""Mailbox reading from the local service (048 T2): count preview, download, a work package from the fresh messages.

The Outlook script (`OUTLOOK_BRIDGE_SCRIPT`; 148: ported from the legacy project, it reads the Sent Items folder too and
an unknown folder is an error) is called via the `scripts/mail_bridge_call.ps1` wrapper:
- **preview** (`count`): the legacy `-CountOnly`; free of charge, writes no file, marks nothing as read;
- **download** (`fetch`): for the duration of the download we start our own email receiver on a free port with a
  one-off key (`jav.domains.email.ingest_server.make_server`) and the script sends the messages there; the receiver writes them into
  the inbox folder with the existing repeat protection. The script's project root is our own `BRIDGE_ROOT`
  (attachments, "already read" list), not the legacy project.

The new or changed messages become a new work package (one message = one item, its `message.json`) with the
default processing assigned (080: email intent + attachments); no paid processing starts (decision of 2026-09-28: runs are started by hand). No new
message, no work package. Outlook must be running on the machine (`-ExistingOutlook`).

231 (plan stage C, C3h): the call of the bridge, a download's package and the mark on a suspicious email's attachment
are `mailbox_bridge.py`, an email item on the review page `email_items.py`; this module keeps the downloads and their
schedules, the mailbox case's maker, the workflow's emails step and its source kind, and re-exports the names its
callers use.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jav.app import workflow_steps
from jav.core import identity, store
from jav.runtime import job_kinds
from jav.core.user_messages import explained
from jav.domains.email.mailbox_bridge import BridgeError, MailboxRequest, Runner, fetch, log, owner_of, scheduled_actor

# 231 (C3h): the shared names the callers use, re-exported (a fixed list: new code imports from the defining module)
from jav.domains.email.mailbox_bridge import (SUSPICIOUS_ATTACHMENT as SUSPICIOUS_ATTACHMENT,
    add_attachments as add_attachments, count as count, mark_suspicious_source as mark_suspicious_source,
    missing_attachments as missing_attachments, page_part as page_part, pdf_attachments as pdf_attachments,
    suspicious_email as suspicious_email)
from jav.domains.email.email_items import (EMAIL_FIELDS as EMAIL_FIELDS, TASK_KIND as TASK_KIND,
    correct_email as correct_email, decide_task as decide_task, effective_email_result as effective_email_result,
    email_item_result as email_item_result, email_item_view as email_item_view, email_result_for as email_result_for,
    intent_name as intent_name, item_titles as item_titles, mark_task_done as mark_task_done,
    next_flow_labels as next_flow_labels, parent_labels as parent_labels, processed_types as processed_types,
    reads_text as reads_text, table_attachments as table_attachments, task_view as task_view)


PULL_JOB_KIND = "mail_pull"


DEFAULT_INTERVAL_MIN = 60  # decision of 2026-09-28: hourly


DEFAULT_LOOKBACK_DAYS = 3  # window of a scheduled read; the script and the receiver both skip messages already read in


store.register_schema("mailbox", """
CREATE TABLE IF NOT EXISTS mailbox_schedules (
    id           TEXT PRIMARY KEY,
    request      TEXT NOT NULL,                -- JSON: MailboxRequest (visszatekintés napokban)
    interval_min INTEGER NOT NULL,
    enabled      INTEGER NOT NULL DEFAULT 1,
    actor        TEXT NOT NULL,
    actor_id     TEXT,                         -- 229 (SZ2c): the stable ids beside the names (`jav.core.identity`)
    next_at      TEXT NOT NULL,                -- UTC ISO
    last_at      TEXT,
    last_status  TEXT,                         -- ok | error
    last_result  TEXT,                         -- JSON: a letöltés összesítője vagy a hibaüzenet
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    changed_by   TEXT,                         -- 167 (review S-5): who last changed it (the creator first)
    changed_by_id TEXT,
    changed_at   TEXT                          -- and when; updated_at also moves with every download
);
CREATE TABLE IF NOT EXISTS mailbox_pulls (
    id           TEXT PRIMARY KEY,
    schedule_id  TEXT,                         -- NULL = kézi letöltés
    request      TEXT NOT NULL,
    actor        TEXT NOT NULL,
    actor_id     TEXT,
    status       TEXT NOT NULL,                -- queued | running | ok | error
    result       TEXT,                         -- JSON: új / változott / ismételt levelek, munkacsomag; vagy hiba
    created_at   TEXT NOT NULL,
    finished_at  TEXT,
    taker        TEXT                          -- 231 (C3d): the step it is for ("case:<case>:<step>", "workflow:<id>:<step>"); NULL: none
);
""")


def _add_change_columns(conn) -> None:
    """167 (review S-5): who last changed a schedule, on a table created before."""
    store.add_columns(conn, "mailbox_schedules", {"changed_by": "TEXT", "changed_at": "TEXT"})
    store.add_actor_ids(conn, "mailbox_schedules", ("actor", "changed_by"))  # 229 (SZ2c)
    store.add_actor_ids(conn, "mailbox_pulls", ("actor",))
    store.add_columns(conn, "mailbox_pulls", {"taker": "TEXT"})  # 231 (C3d): the step a download is for


store.register_migration("mailbox.schedule_changes", _add_change_columns)


def _utc(dt: datetime | None = None) -> str:
    return (dt or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


def _schedule_row(row) -> dict[str, Any]:
    out = dict(row)
    out["request"] = json.loads(out["request"])
    out["last_result"] = json.loads(out["last_result"]) if out["last_result"] else None
    out["enabled"] = bool(out["enabled"])
    out["label"] = MailboxRequest.model_validate(out["request"]).label()
    return out


def schedules() -> list[dict[str, Any]]:
    with store.connect() as c:
        return [_schedule_row(r) for r in c.execute("SELECT * FROM mailbox_schedules ORDER BY created_at")]


def schedule(schedule_id: str) -> dict[str, Any]:
    with store.connect() as c:
        row = c.execute("SELECT * FROM mailbox_schedules WHERE id=?", (schedule_id,)).fetchone()
    if row is None:
        raise KeyError(schedule_id)
    return _schedule_row(row)


def create_schedule(req: MailboxRequest, *, actor: identity.Who, interval_min: int = DEFAULT_INTERVAL_MIN,
                    enabled: bool = True) -> dict[str, Any]:
    """New schedule; the first download is due in the next worker cycle. A fixed date range makes no sense here."""
    if req.received_from is not None:
        raise explained(ValueError, "a schedule reads the last N days; a fixed date range is for one-off fetches")
    if not 15 <= interval_min <= 7 * 24 * 60:
        raise explained(ValueError, "interval_min must be between 15 minutes and 7 days")
    sid = f"mbx-{uuid.uuid4().hex[:10]}"
    now = _utc()
    with store.connect() as c:
        c.execute("INSERT INTO mailbox_schedules(id, request, interval_min, enabled, actor, actor_id, next_at, created_at,"
                  " updated_at, changed_by, changed_by_id, changed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (sid, req.model_dump_json(), interval_min, int(enabled), identity.name_of(actor), identity.id_of(actor), now, now, now, identity.name_of(actor), identity.id_of(actor), now))
    return schedule(sid)


def update_schedule(schedule_id: str, *, actor: identity.Who, enabled: bool | None = None,
                    interval_min: int | None = None) -> dict[str, Any]:
    """167 (review S-5): `actor` is recorded as the one who last changed it, and logged."""
    cur = schedule(schedule_id)
    if interval_min is not None and not 15 <= interval_min <= 7 * 24 * 60:
        raise explained(ValueError, "interval_min must be between 15 minutes and 7 days")
    en = cur["enabled"] if enabled is None else enabled
    iv = cur["interval_min"] if interval_min is None else interval_min
    # due at once when switched on; when the frequency changes, the next time follows the new frequency
    nxt = _utc() if (enabled and not cur["enabled"]) else cur["next_at"]
    if interval_min is not None and cur["last_at"]:
        nxt = _utc(datetime.fromisoformat(cur["last_at"]) + timedelta(minutes=iv))
    now = _utc()
    with store.connect() as c:
        c.execute("UPDATE mailbox_schedules SET enabled=?, interval_min=?, next_at=?, updated_at=?, changed_by=?,"
                  " changed_by_id=?, changed_at=? WHERE id=?", (int(en), iv, nxt, now, identity.name_of(actor), identity.id_of(actor), now, schedule_id))
    log.info("mailbox schedule %s changed by %s: enabled %s, every %d min", schedule_id, identity.name_of(actor), bool(en), iv)
    return schedule(schedule_id)


def delete_schedule(schedule_id: str, *, actor: identity.Who) -> None:
    """167 (review S-5): the row is gone afterwards, so who deleted it is in the service log."""
    schedule(schedule_id)
    with store.connect() as c:
        c.execute("DELETE FROM mailbox_schedules WHERE id=?", (schedule_id,))
    log.info("mailbox schedule %s deleted by %s", schedule_id, identity.name_of(actor))


def request_pull(req: MailboxRequest, *, actor: identity.Who, schedule_id: str | None = None,
                 dedup_key: str | None = None, taker: str | None = None) -> dict[str, Any]:
    """Queues a download (the worker runs it). A repeated `dedup_key` returns the existing download. 231 (C3d): `taker`,
    the step it is for (a case's, a workflow's); a download no step takes wraps its package by a mailbox case."""
    from jav.core import queue

    pid = f"pull-{uuid.uuid4().hex[:10]}"
    # 063: the download row is created before the job - the worker may claim the job the moment it is queued
    with store.connect() as c:
        c.execute("INSERT INTO mailbox_pulls(id, schedule_id, request, actor, actor_id, status, created_at, taker)"
                  " VALUES (?,?,?,?,?,?,?,?)", (pid, schedule_id, req.model_dump_json(), identity.name_of(actor), identity.id_of(actor),
                                               "queued", _utc(), taker))
    job = queue.enqueue(PULL_JOB_KIND, run_id=None, payload={"pull_id": pid}, dedup_key=dedup_key)
    if job.deduped:
        with store.connect() as c:
            c.execute("DELETE FROM mailbox_pulls WHERE id=?", (pid,))
        return pull(job.payload["pull_id"])
    return pull(pid)


def process_pull_job(job: Any) -> str:
    """The worker's mailbox download job (048 T2): the result or the error shows on the download and its schedule; the
    job is always completed. 185 (plan G-full-move T1c): until then the worker's `process_pull`."""
    from jav.core import queue

    run_pull_job(job.payload)
    return queue.complete(job.id)


def abandon_pull_job(job: Any, error: str) -> None:
    abandon_pull(job.payload["pull_id"], error)


def abandon_pull(pull_id: str, error: str) -> None:
    """063: the worker left the download without a proper close (shutdown, unexpected error): closed as an error."""
    body = json.dumps({"error": error[:500]}, ensure_ascii=False)
    with store.connect() as c:
        row = c.execute("SELECT schedule_id FROM mailbox_pulls WHERE id=?", (pull_id,)).fetchone()
        if row is None:
            return
        c.execute("UPDATE mailbox_pulls SET status='error', result=?, finished_at=? WHERE id=?", (body, _utc(), pull_id))
        if row["schedule_id"]:
            c.execute("UPDATE mailbox_schedules SET last_at=?, last_status='error', last_result=?, updated_at=? WHERE id=?",
                      (_utc(), body, _utc(), row["schedule_id"]))


def _pull_row(row) -> dict[str, Any]:
    out = dict(row)
    out["request"] = json.loads(out["request"])
    out["result"] = json.loads(out["result"]) if out["result"] else None
    out["label"] = MailboxRequest.model_validate(out["request"]).label()
    return out


def pull(pull_id: str) -> dict[str, Any]:
    with store.connect() as c:
        row = c.execute("SELECT * FROM mailbox_pulls WHERE id=?", (pull_id,)).fetchone()
    if row is None:
        raise KeyError(pull_id)
    return _pull_row(row)


def pulls(limit: int = 20, *, schedule_id: str | None = None) -> list[dict[str, Any]]:
    """The newest downloads; 264 (F6): `schedule_id`, only that schedule's (its page lists them)."""
    where, args = ("WHERE schedule_id=? ", (schedule_id,)) if schedule_id else ("", ())
    with store.connect() as c:
        return [_pull_row(r) for r in c.execute(f"SELECT * FROM mailbox_pulls {where}ORDER BY created_at DESC, rowid DESC LIMIT ?",
                                                (*args, limit))]


def known_accounts() -> list[str]:
    """Mailbox addresses already used (058: selectable, no need to retype them): the addresses of the schedules and of
    the successful downloads, most recently used first, each once (case-insensitive)."""
    seen: dict[str, str] = {}
    with store.connect() as c:
        rows = [*c.execute("SELECT request FROM mailbox_pulls WHERE status='ok' ORDER BY created_at DESC, rowid DESC"),
                *c.execute("SELECT request FROM mailbox_schedules ORDER BY created_at DESC")]
    for r in rows:
        for a in json.loads(r["request"]).get("accounts") or []:
            seen.setdefault(str(a).strip().lower(), str(a).strip())
    return [v for v in seen.values() if v]


def tick(now: datetime | None = None) -> list[str]:
    """One download for each due, enabled schedule (once per time slot); returns the download identifiers."""
    now = now or datetime.now(timezone.utc)
    out = []
    with store.connect() as c:
        due = c.execute("SELECT * FROM mailbox_schedules WHERE enabled=1 AND next_at<=?", (_utc(now),)).fetchall()
    for row in due:
        p = request_pull(MailboxRequest.model_validate_json(row["request"]), actor=scheduled_actor(row),
                         schedule_id=row["id"], dedup_key=f"{PULL_JOB_KIND}:{row['id']}:{row['next_at']}")
        with store.connect() as c:
            c.execute("UPDATE mailbox_schedules SET next_at=?, updated_at=? WHERE id=?",
                      (_utc(now + timedelta(minutes=row["interval_min"])), _utc(now), row["id"]))
        out.append(p["id"])
    return out


def _pull_actor(p: Mapping[str, Any]) -> identity.Actor:
    """229 (SZ2c-3): who a queued download acts as, from its row: a scheduled one for its schedule's saver while the
    schedule is there, otherwise as its row recorded it."""
    if p["schedule_id"]:
        with store.connect() as c:
            row = c.execute("SELECT actor, actor_id FROM mailbox_schedules WHERE id=?", (p["schedule_id"],)).fetchone()
        if row is not None:
            return scheduled_actor(row)
    return identity.recorded(p["actor"], dict(p).get("actor_id"))


def run_pull_job(payload: dict[str, Any], *, runner: Runner | None = None, inbox_root: Path | None = None) -> dict[str, Any]:
    """One download in the worker. Errors are recorded on the download (and schedule), never raised: no queue retry."""
    p = pull(payload["pull_id"])
    with store.connect() as c:
        c.execute("UPDATE mailbox_pulls SET status='running' WHERE id=?", (p["id"],))
    try:
        res = fetch(MailboxRequest.model_validate(p["request"]), actor=_pull_actor(p), runner=runner, inbox_root=inbox_root)
        status, result = "ok", {k: res[k] for k in ("new", "changed", "duplicate", "workpackage", "log")}
        if res.get("error"):  # 063: interrupted download - the messages that arrived were packaged, but the error shows
            status, result["error"] = "error", res["error"]
    except (BridgeError, subprocess.TimeoutExpired, OSError) as exc:
        status, result = "error", {"error": str(exc)[:500]}
    except Exception as exc:  # noqa: BLE001 - 063: every error shows on the download; the worker does not stop
        log.exception("mailbox pull %s failed", p["id"])
        status, result = "error", {"error": f"{type(exc).__name__}: {exc}"[:500]}
    if result.get("workpackage") and not p.get("taker"):
        _own_case(result["workpackage"], _pull_actor(p))
    body = json.dumps(result, ensure_ascii=False)
    with store.connect() as c:
        c.execute("UPDATE mailbox_pulls SET status=?, result=?, finished_at=? WHERE id=?", (status, body, _utc(), p["id"]))
        if p["schedule_id"]:
            c.execute("UPDATE mailbox_schedules SET last_at=?, last_status=?, last_result=?, updated_at=? WHERE id=?",
                      (_utc(), status, body, _utc(), p["schedule_id"]))
    return {"status": status, **result}


PACK = "mailbox"  # 231 (C3d): the process pack whose cases hold the downloaded emails


def _own_case(wp_id: str, actor: identity.Who) -> None:
    """231 (C3d; the owner's decision of 2026-10-26): the package of a download no step takes (a scheduled one, one from
    the settings) gets a case of the mailbox pack, its owner the package's; its live run stays a person's action. A
    failure is logged and never loses the package or the download's outcome."""
    from jav.app import process_runtime  # lazy: the process packs build on the domains

    try:
        process_runtime.wrap_into(PACK, wp_id, scope={}, actor=owner_of(actor))
    except Exception:  # noqa: BLE001 - the package stays, as an ordinary one
        log.exception("the downloaded package %s got no case", wp_id)


def case_fetch(scope: dict[str, Any], _name: str, owner: identity.Who | None, taker: str) -> str:
    """231 (C3d): the mailbox maker's fetch: the case's download is queued (the worker runs it) for its step."""
    req = MailboxRequest.model_validate(scope["source"]["request"])
    return str(request_pull(req, actor=owner or identity.machine("mailbox"), taker=taker)["id"])


def case_collect(pull_id: str) -> Any:
    """231 (C3d): where the case's download stands, as the workflow's emails step reads it (`workflow_poll`)."""
    from jav.app.document_processing import Collected  # lazy: the capability builds on the domains' makers

    p = pull(pull_id)
    result = p.get("result") or {}
    if p["status"] in ("queued", "running"):
        return Collected("running")
    if p["status"] != "ok" and result.get("workpackage"):
        return Collected("done", result["workpackage"], note=str(result.get("error") or p["status"]))
    if p["status"] != "ok":
        return Collected("failed", note=str(result.get("error") or p["status"]))
    return Collected("done", result.get("workpackage") or None)


def workflow_offer(ctx: workflow_steps.StepStart) -> None:
    """A workflow's emails step: its mailbox download is queued (one per start), and the step waits for it. 231 (C3d):
    the mailbox maker's workflow offer (its package comes with the poll, `workflow_poll_offer`)."""
    wf = ctx.workflow
    req = MailboxRequest.model_validate(ctx.source["request"])
    p = request_pull(req, actor=wf["actor"], dedup_key=f"workflow:{wf['id']}:{ctx.step['id']}:{uuid.uuid4().hex[:8]}",
                     taker=f"workflow:{wf['id']}:{ctx.step['id']}")  # C3d: its package is the step's
    ctx.fetching(str(p["id"]))
    return None


def workflow_poll_offer(ctx: workflow_steps.StepStart) -> str | None:
    """Once the step's download has finished: its package (the mailbox pack's step kind wraps it by a case and starts
    its live run), or the step found nothing new, or failed; None while it runs. 160 (review R-1): an interrupted
    download packaged the emails that arrived; the step runs that package, and the error stays in its events (before,
    the step failed without the package and a restart found nothing new). 231 (C3d): the mailbox maker's workflow poll
    (until then this step kind's own poll, which started the run itself)."""
    p = pull(ctx.state["pull_id"])
    if p["status"] in ("queued", "running") or not ctx.claim():
        return None
    result = p.get("result") or {}
    if p["status"] != "ok" and result.get("workpackage"):
        ctx.event("pull_interrupted", {"pull_id": ctx.state["pull_id"], "workpackage_id": result["workpackage"],
                                       "note": str(result.get("error") or p["status"])[:1000]})
        return str(result["workpackage"])
    if p["status"] != "ok":
        ctx.failed(str(result.get("error") or p["status"]))
        return None
    if not result.get("workpackage"):
        ctx.nothing_new("no new emails")
        return None
    return str(result["workpackage"])


def _checked_source(raw: Mapping[str, Any]) -> dict[str, Any]:
    request = MailboxRequest.model_validate(raw.get("request") or {})
    return {"kind": "mailbox", "request": request.model_dump(mode="json")}


def _shown_source(source: Mapping[str, Any]) -> dict[str, Any]:
    req = source["request"]
    return {"kind": "mailbox", "accounts": req.get("accounts"), "folders": req.get("folders")}


def _repeated_source(source: Mapping[str, Any], period: tuple[str, str] | None, wf: Mapping[str, Any]) -> dict[str, Any]:
    """The download's received range moves on with the workflow's period, or by its own length; a number of days stays
    as it is."""
    from jav.app.scopes import next_period

    req = dict(source["request"])
    if req.get("received_from") or req.get("received_to"):
        own = (req.get("received_from"), req.get("received_to"))
        if period is not None and own == (wf["period_start"], wf["period_end"]):
            moved = period
        else:  # its own range moves on (181: a workflow without a period gives no missing end)
            first, last = own[0] or wf["period_start"], own[1] or wf["period_end"]
            moved = next_period(first, last) if first and last else own
        req["received_from"], req["received_to"] = moved
    return {"kind": "mailbox", "request": req}  # a number of days stays as it is


def _counted_source(source: Mapping[str, Any]) -> tuple[int | None, str, str | None]:
    """A mailbox's emails are counted only when a most is given."""
    return source["request"].get("max_items") or 0, "email", "each email's PDF attachments add a document's budget"


def _source_words(source: Mapping[str, Any]) -> str:
    """231 (C3d): a mailbox download in a few words (a case's scope)."""
    return MailboxRequest.model_validate(source["request"]).label()


SOURCE = workflow_steps.SourceKind("mailbox", __name__, check=_checked_source, shown=_shown_source,
                                   repeated=_repeated_source, count=_counted_source, words=_source_words)


# 185 (plan G-full-move T1c): the worker's kind of job for a download and its tick for the due schedules, registered by
# the email domain (`jav/runtime/job_kinds.py`); each looks its function up when called, so a replaced one counts
JOB = job_kinds.JobKind(PULL_JOB_KIND, __name__, process=lambda job: process_pull_job(job),
                        abandon=lambda job, error: abandon_pull_job(job, error))


TICK = job_kinds.Tick("mailbox.tick", __name__, lambda: tick())
