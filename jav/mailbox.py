"""Mailbox reading from the local service (048 T2): count preview, download, a work package from the fresh messages.

The Outlook script (`OUTLOOK_BRIDGE_SCRIPT`; 148: ported from the legacy project, it reads the Sent Items folder too and
an unknown folder is an error) is called via the `scripts/mail_bridge_call.ps1` wrapper:
- **preview** (`count`): the legacy `-CountOnly`; free of charge, writes no file, marks nothing as read;
- **download** (`fetch`): for the duration of the download we start our own email receiver on a free port with a
  one-off key (`jav.ingest_server.make_server`) and the script sends the messages there; the receiver writes them into
  the inbox folder with the existing repeat protection. The script's project root is our own `BRIDGE_ROOT`
  (attachments, "already read" list), not the legacy project.

The new or changed messages become a new work package (one message = one item, its `message.json`) with the
default processing assigned (080: email intent + attachments); no paid processing starts (decision of 2026-09-28: runs are started by hand). No new
message, no work package. Outlook must be running on the machine (`-ExistingOutlook`).
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import subprocess
import threading
import uuid
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from jav import decisions, ingest_server, item_kinds, store, work, workflow_steps
from jav.runtime import job_kinds
from jav.config import BRIDGE_ROOT, OUTLOOK_BRIDGE_SCRIPT, PROJECT_ROOT
from jav.user_messages import explained

log = logging.getLogger("jav.mailbox")

WRAPPER = PROJECT_ROOT / "scripts" / "mail_bridge_call.ps1"
COUNT_TIMEOUT_S = 180
FETCH_TIMEOUT_S = 1800
_ACCOUNT = re.compile(r"^[^@\s,;'\"`$]+@[^@\s,;'\"`$]+\.[^@\s,;'\"`$]+$")
_FOLDER = re.compile(r"^[^,;'\"`$\\]{1,80}$")

Runner = Callable[[list[str], int], tuple[int, str, str]]


class BridgeError(RuntimeError):
    """The legacy script failed (e.g. Outlook not running, unknown mailbox); the text is the script's message."""


class MailboxRequest(BaseModel):
    """What to read: mailbox(es), folder(s), period (the last N days or a date range), at most how many messages."""

    model_config = ConfigDict(extra="forbid")

    accounts: list[str] = Field(min_length=1, max_length=5)
    folders: list[str] = Field(default_factory=lambda: ["Inbox"], min_length=1, max_length=10)
    subfolders: bool = False
    since_days: int | None = Field(default=None, ge=1, le=3650)
    received_from: date | None = None
    received_to: date | None = None
    max_items: int = Field(default=0, ge=0, le=10000)

    @field_validator("accounts")
    @classmethod
    def _accounts(cls, v: list[str]) -> list[str]:
        bad = [a for a in v if not _ACCOUNT.match(a.strip())]
        if bad:
            raise explained(ValueError, "not e-mail addresses: {{bad}}", bad=bad)
        return [a.strip() for a in v]

    @field_validator("folders")
    @classmethod
    def _folders(cls, v: list[str]) -> list[str]:
        bad = [f for f in v if not _FOLDER.match(f.strip())]
        if bad:
            raise explained(ValueError, "invalid folder names: {{bad}}", bad=bad)
        return [f.strip() for f in v]

    @model_validator(mode="after")
    def _period(self) -> MailboxRequest:
        if (self.received_from is None) != (self.received_to is None):
            raise explained(ValueError, "received_from and received_to go together")
        if self.received_from and self.received_to and self.received_from > self.received_to:
            raise explained(ValueError, "received_from must not be after received_to")
        if self.received_from is None and self.since_days is None:
            self.since_days = 1
        return self

    def label(self) -> str:
        """The download in one line (the package's stored source, the logs). 183: English; the interface writes it in
        its own language from the request (`page_part`'s `mailbox_request`)."""
        period = (f"{self.received_from}–{self.received_to}" if self.received_from else f"last {self.since_days} days")
        return f"{', '.join(self.accounts)} · {', '.join(self.folders)} · {period}"


def _argv(req: MailboxRequest, mode: str, **extra: str) -> list[str]:
    argv = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER),
            "-Script", str(OUTLOOK_BRIDGE_SCRIPT), "-Mode", mode, "-Accounts", ",".join(req.accounts),
            "-Folders", ",".join(req.folders), "-MaxItems", str(req.max_items), "-RepoRoot", str(BRIDGE_ROOT)]
    if req.subfolders:
        argv.append("-Subfolders")
    if req.received_from and req.received_to:
        # the legacy script parses with `[datetime]::Parse`; the closing day must be included in full
        argv += ["-ReceivedFrom", f"{req.received_from}T00:00:00", "-ReceivedTo", f"{req.received_to}T23:59:59"]
    else:
        argv += ["-SinceDays", str(req.since_days)]
    for k, v in extra.items():
        argv += [f"-{k}", v]
    return argv


def _subprocess_runner(argv: list[str], timeout: int) -> tuple[int, str, str]:
    p = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
    dec = lambda b: b.decode("utf-8", errors="replace")  # noqa: E731
    return p.returncode, dec(p.stdout), dec(p.stderr)


def _tail(text: str, n: int = 12) -> list[str]:
    return [line for line in text.strip().splitlines() if line.strip()][-n:]


_PS_ERROR = re.compile(r"FullyQualifiedErrorId\s*:\s*(.+)$", re.MULTILINE)


def _error_text(err: str, out: str, code: int) -> str:
    """Human-readable part of a PowerShell error: the thrown message (`FullyQualifiedErrorId`), else the last lines."""
    m = _PS_ERROR.search(err or "")
    if m:
        return m.group(1).strip()
    return "; ".join(_tail(err or out, 4)) or f"bridge exit {code}"


def count(req: MailboxRequest, *, runner: Runner | None = None) -> dict[str, Any]:
    """Free count preview: how many messages fall into the period, how many of them were already read in, and how
    many it would download.

    The legacy script's `eligible` is the number of messages to download (not yet read in); all messages of the period
    are `counts.mail` (065: the UI used to show `eligible` as the total)."""
    code, out, err = (runner or _subprocess_runner)(_argv(req, "count"), COUNT_TIMEOUT_S)
    lines = [line for line in out.strip().splitlines() if line.strip().startswith("{")]
    if code != 0 or not lines:
        raise BridgeError(_error_text(err, out, code))
    raw = json.loads(lines[-1])
    counts = raw.get("counts") or {}
    return {"request": req.model_dump(mode="json"), "label": req.label(), "eligible": int(raw.get("eligible") or 0),
            "in_period": int(counts.get("mail") or 0),
            "already_read": int(counts.get("skippedSeen") or 0), "scanned": int(counts.get("scanned") or 0),
            "window": {"from": raw.get("received_from"), "to": raw.get("received_to")},
            "accounts": [{"account": a.get("account"), "eligible": (a.get("counts") or {}).get("mail")} for a in raw.get("accounts") or []]}


def fetch(req: MailboxRequest, *, actor: str, runner: Runner | None = None, inbox_root: Path | None = None) -> dict[str, Any]:
    """Download through our own temporary email receiver; new / changed messages become a work package with the
    default processing (080)."""
    token = secrets.token_urlsafe(24)
    stored: list[dict[str, Any]] = []
    lock = threading.Lock()

    def on_ingest(res: dict[str, Any], payload: dict[str, Any]) -> None:
        with lock:
            stored.append({"folder": Path(res["folder"]), "status": res["status"]})  # 167 (S-6): no subject kept

    httpd = ingest_server.make_server(0, inbox_root=inbox_root or ingest_server.INBOX_ROOT, token=token, on_ingest=on_ingest)
    thread = threading.Thread(target=httpd.serve_forever, name="mail-ingest", daemon=True)
    thread.start()
    interrupted: Exception | None = None
    try:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/ingest/email"
        code, out, err = (runner or _subprocess_runner)(_argv(req, "fetch", OrchUrl=url, ApiToken=token), FETCH_TIMEOUT_S)
    except (subprocess.TimeoutExpired, OSError) as exc:
        # 063: messages that already arrived in an interrupted download (timeout, stopped script) must not be lost
        interrupted, code, out, err = exc, -1, "", f"{type(exc).__name__}: {exc}"
    finally:
        httpd.shutdown()
        httpd.server_close()
    if interrupted is not None and not stored:
        raise interrupted
    messages = [s["folder"] / "message.json" for s in stored]
    # 063: a message downloaded earlier but never packaged is fresh too (e.g. from an earlier interrupted download)
    packaged = work.packaged_sources([m for m, s in zip(messages, stored) if s["status"] == "duplicate"])
    fresh = list(dict.fromkeys(m for m, s in zip(messages, stored) if s["status"] in ("new", "changed") or m not in packaged))
    result: dict[str, Any] = {"label": req.label(), "exit_code": code, "log": _tail(out + "\n" + err),
                              "stored": len(stored), "new": sum(s["status"] == "new" for s in stored),
                              "changed": sum(s["status"] == "changed" for s in stored),
                              "duplicate": sum(s["status"] == "duplicate" for s in stored), "workpackage": None}
    if interrupted is not None:
        result["error"] = f"A letöltés megszakadt ({type(interrupted).__name__}); a megérkezett levelekből csomag készült."
    if code != 0 and not stored:
        raise BridgeError(_error_text(err, out, code))
    if fresh:
        result["workpackage"] = _workpackage(req, fresh, actor=actor)["id"]
    return result


def pdf_attachments(messages: list[Path]) -> dict[Path, Path]:
    """058 K5.2: the messages' PDF attachments that exist as files (attachment → the message's `message.json`). An
    attachment is read only from the permitted location (checked by `emails.load_message_dir`); image attachments are
    not included for now."""
    from jav import emails

    out: dict[Path, Path] = {}
    for m in messages:
        for a in emails.load_message_dir(Path(m).parent).attachments:
            if a.path and a.ext == ".pdf":
                out.setdefault(Path(a.path).resolve(), Path(m))
    return out


def missing_attachments(wp: dict[str, Any]) -> list[Path]:
    """PDF attachments of the package's messages that are not yet items of the package (a pre-058 email package)."""
    mails = [Path(i["source_path"]) for i in wp["items"] if i["kind"] == "email"]
    have = {Path(i["source_path"]).resolve() for i in wp["items"] if i["kind"] == "document"}
    return [p for p in pdf_attachments(mails) if p not in have]


def add_attachments(wp_id: str, *, expected_revision: int) -> dict[str, Any]:
    """Adds the messages' PDF attachments to the package as documents, pointing to their message (the attachment's
    origin). The processing runs the full document processing on the attachment (058 K5.2, automatic chain). No new
    attachment: the package is unchanged."""
    wp = work.get(wp_id)
    mails = [Path(i["source_path"]) for i in wp["items"] if i["kind"] == "email"]
    missing = set(missing_attachments(wp))
    if not missing:
        return wp
    item_of = {Path(i["source_path"]).resolve(): i["item_id"] for i in wp["items"] if i["kind"] == "email"}
    parents = {pdf: item_of[Path(msg).resolve()] for pdf, msg in pdf_attachments(mails).items() if pdf in missing}
    return work.add_items(wp_id, sorted(missing), kind="document", expected_revision=expected_revision, parents=parents)


def page_part(wp: Mapping[str, Any]) -> dict[str, Any]:
    """058 K5.2: a mailbox package's part of its page: how many PDF attachments are not yet items (they can be added
    later to a pre-058 email package). 180: registered by the email domain (`jav/domains/email.py`). 183: the request
    of the download that made it (None if no recorded download did), so that the interface names its source in its own
    language instead of the stored label."""
    return {"attachments_missing": len(missing_attachments(dict(wp))), "mailbox_request": _request_of(wp["id"])}


def _request_of(wp_id: str) -> dict[str, Any] | None:
    with store.connect() as c:
        row = c.execute("SELECT request FROM mailbox_pulls WHERE status='ok' AND json_extract(result, '$.workpackage')=?"
                        " ORDER BY created_at DESC LIMIT 1", (wp_id,)).fetchone()
    return json.loads(row["request"]) if row else None


# --- an attachment of a suspicious email (154; 177: the email domain's rule, `jav/item_kinds.py`; 180: registered by
# `jav/domains/email.py`) --------------------------------------------------------------------------------------------

SUSPICIOUS_ATTACHMENT = "attachment:suspicious_email"  # 154 (DECISIONS 154)


def suspicious_email(run_id: str, email_item_id: str) -> bool:
    """154: whether the run's email item was routed by a signal (an injected instruction -> `human:suspicious`,
    policy `email.signal_routes`)."""
    from jav import policy

    result = store.email_result(work.flow_run_id(run_id, email_item_id))
    return bool(result) and result.get("next_flow") in set(policy.EMAIL_SIGNAL_ROUTES.values())


def mark_suspicious_source(run: dict[str, Any], item: dict[str, Any]) -> bool:
    """154 (DECISIONS 154): the attachments of an email routed as suspicious are processed but marked: each gets an
    `attachment:suspicious_email` to-do in the run, so the run cannot be approved before a person has looked at it,
    and a statement from it never replaces another by rule (`reconcile.statements`). Called after every item, so it
    does not matter whether the email or its attachment is processed first. Returns whether this item got the to-do."""
    run_id = run["run_id"]
    if item.get("kind") == item_kinds.EMAIL:
        if suspicious_email(run_id, item["item_id"]):
            for attachment in run["input"]["items"]:
                if attachment.get("parent_item_id") == item["item_id"]:
                    work.raise_item_reasons(run_id, attachment, [SUSPICIOUS_ATTACHMENT], producer="email_source")
        return False
    parent = item.get("parent_item_id")
    if parent and suspicious_email(run_id, parent):
        work.raise_item_reasons(run_id, item, [SUSPICIOUS_ATTACHMENT], producer="email_source")
        return True
    return False



_SCHEDULED_ACTOR = re.compile(r"^ütemezés \((.+)\)$")


def owner_of(actor: str) -> str:
    """065: owner of a downloaded package: whoever started it; if scheduled, the user who saved the schedule."""
    m = _SCHEDULED_ACTOR.match(actor)
    return m.group(1) if m else actor


def _workpackage(req: MailboxRequest, messages: list[Path], *, actor: str) -> dict[str, Any]:
    name = f"Postafiók: {', '.join(req.accounts)} · {datetime.now():%Y-%m-%d %H:%M}"
    wp = work.create_workpackage(name=name, source_kind="mailbox", source_ref=req.label(), owner=owner_of(actor))
    wp = work.add_items(wp["id"], messages, kind="email", expected_revision=0)
    wp = add_attachments(wp["id"], expected_revision=wp["revision"])  # 058 K5.2: plus the PDF attachments
    r = work.default_recipe()  # 080: one processing; on an email, intent + attachments
    # the recipe's defaults; 160-D: the application's engine (`assign_recipe` fills what is not named)
    work.assign_recipe(wp["id"], r["id"], params={}, expected_revision=0, actor=actor,
                       note="postafiók-letöltés után automatikusan (a futtatás kézi)")
    return work.get(wp["id"])


# --- downloads and scheduling (048 T2.2) -------------------------------------------------------------------
# Every download (manual or scheduled) is one `mailbox_pulls` row + one `mail_pull` work-queue job: the worker runs it
# (`run_pull_job`), because a download can take minutes; the status and the result show on the row. A schedule =
# mailbox(es) + folders + look-back (days) + frequency. The worker calls `tick()` on every cycle: it starts a download
# for each due schedule (once per time slot) and moves the next time forward. An error (e.g. Outlook not running) is
# not retried at once; it is tried again at the next scheduled time.

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
    next_at      TEXT NOT NULL,                -- UTC ISO
    last_at      TEXT,
    last_status  TEXT,                         -- ok | error
    last_result  TEXT,                         -- JSON: a letöltés összesítője vagy a hibaüzenet
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    changed_by   TEXT,                         -- 167 (review S-5): who last changed it (the creator first)
    changed_at   TEXT                          -- and when; updated_at also moves with every download
);
CREATE TABLE IF NOT EXISTS mailbox_pulls (
    id           TEXT PRIMARY KEY,
    schedule_id  TEXT,                         -- NULL = kézi letöltés
    request      TEXT NOT NULL,
    actor        TEXT NOT NULL,
    status       TEXT NOT NULL,                -- queued | running | ok | error
    result       TEXT,                         -- JSON: új / változott / ismételt levelek, munkacsomag; vagy hiba
    created_at   TEXT NOT NULL,
    finished_at  TEXT
);
""")


def _add_change_columns(conn) -> None:
    """167 (review S-5): who last changed a schedule, on a table created before."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(mailbox_schedules)")}
    for col in ("changed_by", "changed_at"):
        if cols and col not in cols:
            conn.execute(f"ALTER TABLE mailbox_schedules ADD COLUMN {col} TEXT")


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


def create_schedule(req: MailboxRequest, *, actor: str, interval_min: int = DEFAULT_INTERVAL_MIN,
                    enabled: bool = True) -> dict[str, Any]:
    """New schedule; the first download is due in the next worker cycle. A fixed date range makes no sense here."""
    if req.received_from is not None:
        raise explained(ValueError, "a schedule reads the last N days; a fixed date range is for one-off fetches")
    if not 15 <= interval_min <= 7 * 24 * 60:
        raise explained(ValueError, "interval_min must be between 15 minutes and 7 days")
    sid = f"mbx-{uuid.uuid4().hex[:10]}"
    now = _utc()
    with store.connect() as c:
        c.execute("INSERT INTO mailbox_schedules(id, request, interval_min, enabled, actor, next_at, created_at, updated_at,"
                  " changed_by, changed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (sid, req.model_dump_json(), interval_min, int(enabled), actor, now, now, now, actor, now))
    return schedule(sid)


def update_schedule(schedule_id: str, *, actor: str, enabled: bool | None = None,
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
        c.execute("UPDATE mailbox_schedules SET enabled=?, interval_min=?, next_at=?, updated_at=?, changed_by=?, changed_at=?"
                  " WHERE id=?", (int(en), iv, nxt, now, actor, now, schedule_id))
    log.info("mailbox schedule %s changed by %s: enabled %s, every %d min", schedule_id, actor, bool(en), iv)
    return schedule(schedule_id)


def delete_schedule(schedule_id: str, *, actor: str) -> None:
    """167 (review S-5): the row is gone afterwards, so who deleted it is in the service log."""
    schedule(schedule_id)
    with store.connect() as c:
        c.execute("DELETE FROM mailbox_schedules WHERE id=?", (schedule_id,))
    log.info("mailbox schedule %s deleted by %s", schedule_id, actor)


def request_pull(req: MailboxRequest, *, actor: str, schedule_id: str | None = None,
                 dedup_key: str | None = None) -> dict[str, Any]:
    """Queues a download (the worker runs it). A repeated `dedup_key` returns the existing download."""
    from jav.runtime import queue

    pid = f"pull-{uuid.uuid4().hex[:10]}"
    # 063: the download row is created before the job - the worker may claim the job the moment it is queued
    with store.connect() as c:
        c.execute("INSERT INTO mailbox_pulls(id, schedule_id, request, actor, status, created_at) VALUES (?,?,?,?,?,?)",
                  (pid, schedule_id, req.model_dump_json(), actor, "queued", _utc()))
    job = queue.enqueue(PULL_JOB_KIND, run_id=None, payload={"pull_id": pid}, dedup_key=dedup_key)
    if job.deduped:
        with store.connect() as c:
            c.execute("DELETE FROM mailbox_pulls WHERE id=?", (pid,))
        return pull(job.payload["pull_id"])
    return pull(pid)


def process_pull_job(job: Any) -> str:
    """The worker's mailbox download job (048 T2): the result or the error shows on the download and its schedule; the
    job is always completed. 185 (plan G-full-move T1c): until then the worker's `process_pull`."""
    from jav.runtime import queue

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


def pulls(limit: int = 20) -> list[dict[str, Any]]:
    with store.connect() as c:
        return [_pull_row(r) for r in c.execute("SELECT * FROM mailbox_pulls ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,))]


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
        p = request_pull(MailboxRequest.model_validate_json(row["request"]), actor=f"ütemezés ({row['actor']})",
                         schedule_id=row["id"], dedup_key=f"{PULL_JOB_KIND}:{row['id']}:{row['next_at']}")
        with store.connect() as c:
            c.execute("UPDATE mailbox_schedules SET next_at=?, updated_at=? WHERE id=?",
                      (_utc(now + timedelta(minutes=row["interval_min"])), _utc(now), row["id"]))
        out.append(p["id"])
    return out


def run_pull_job(payload: dict[str, Any], *, runner: Runner | None = None, inbox_root: Path | None = None) -> dict[str, Any]:
    """One download in the worker. Errors are recorded on the download (and schedule), never raised: no queue retry."""
    p = pull(payload["pull_id"])
    with store.connect() as c:
        c.execute("UPDATE mailbox_pulls SET status='running' WHERE id=?", (p["id"],))
    try:
        res = fetch(MailboxRequest.model_validate(p["request"]), actor=p["actor"], runner=runner, inbox_root=inbox_root)
        status, result = "ok", {k: res[k] for k in ("new", "changed", "duplicate", "workpackage", "log")}
        if res.get("error"):  # 063: interrupted download - the messages that arrived were packaged, but the error shows
            status, result["error"] = "error", res["error"]
    except (BridgeError, subprocess.TimeoutExpired, OSError) as exc:
        status, result = "error", {"error": str(exc)[:500]}
    except Exception as exc:  # noqa: BLE001 - 063: every error shows on the download; the worker does not stop
        log.exception("mailbox pull %s failed", p["id"])
        status, result = "error", {"error": f"{type(exc).__name__}: {exc}"[:500]}
    body = json.dumps(result, ensure_ascii=False)
    with store.connect() as c:
        c.execute("UPDATE mailbox_pulls SET status=?, result=?, finished_at=? WHERE id=?", (status, body, _utc(), p["id"]))
        if p["schedule_id"]:
            c.execute("UPDATE mailbox_schedules SET last_at=?, last_status=?, last_result=?, updated_at=? WHERE id=?",
                      (_utc(), status, body, _utc(), p["schedule_id"]))
    return {"status": status, **result}


# --- a workflow's emails step (181, plan 170 L5; until then in `jav/workflows.py`) --------------------------------


def workflow_start(ctx: workflow_steps.StepStart) -> None:
    """A workflow's emails step: its mailbox download is queued (one per start), and the step waits for it."""
    wf = ctx.workflow
    req = MailboxRequest.model_validate(ctx.source["request"])
    p = request_pull(req, actor=wf["actor"], dedup_key=f"workflow:{wf['id']}:{ctx.step['id']}:{uuid.uuid4().hex[:8]}")
    ctx.fetching(str(p["id"]))


def workflow_poll(ctx: workflow_steps.StepStart) -> None:
    """Once the step's download has finished: its package's live run starts, or the step found nothing new, or failed.
    160 (review R-1): an interrupted download packaged the emails that arrived; the step runs that package, and the
    error stays in its events (before, the step failed without the package and a restart found nothing new)."""
    p = pull(ctx.state["pull_id"])
    if p["status"] in ("queued", "running") or not ctx.claim():
        return
    result = p.get("result") or {}
    if p["status"] != "ok" and result.get("workpackage"):
        ctx.event("pull_interrupted", {"pull_id": ctx.state["pull_id"], "workpackage_id": result["workpackage"],
                                       "note": str(result.get("error") or p["status"])[:1000]})
        ctx.run(result["workpackage"])
    elif p["status"] != "ok":
        ctx.failed(str(result.get("error") or p["status"]))
    elif not result.get("workpackage"):
        ctx.nothing_new("no new emails")
    else:
        ctx.run(result["workpackage"])


# 181: the emails step of a workflow (registered by the email domain, `jav/domains/email.py`)
STEP = workflow_steps.StepKind("emails", __name__, ("mailbox",), start=workflow_start, poll=workflow_poll)

# --- 185 (plan G-full-move T1c): a mailbox download as a workflow step's source (`workflow_steps.SourceKind`; until
# then in `jav/workflows.py`) ---------------------------------------------------------------------------------------


def _checked_source(raw: Mapping[str, Any]) -> dict[str, Any]:
    request = MailboxRequest.model_validate(raw.get("request") or {})
    return {"kind": "mailbox", "request": request.model_dump(mode="json")}


def _shown_source(source: Mapping[str, Any]) -> dict[str, Any]:
    req = source["request"]
    return {"kind": "mailbox", "accounts": req.get("accounts"), "folders": req.get("folders")}


def _repeated_source(source: Mapping[str, Any], period: tuple[str, str] | None, wf: Mapping[str, Any]) -> dict[str, Any]:
    """The download's received range moves on with the workflow's period, or by its own length; a number of days stays
    as it is."""
    from jav.workflows import next_period

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


SOURCE = workflow_steps.SourceKind("mailbox", __name__, check=_checked_source, shown=_shown_source,
                                   repeated=_repeated_source, count=_counted_source)

# 185 (plan G-full-move T1c): the worker's kind of job for a download and its tick for the due schedules, registered by
# the email domain (`jav/runtime/job_kinds.py`); each looks its function up when called, so a replaced one counts
JOB = job_kinds.JobKind(PULL_JOB_KIND, __name__, process=lambda job: process_pull_job(job),
                        abandon=lambda job, error: abandon_pull_job(job, error))
TICK = job_kinds.Tick("mailbox.tick", __name__, lambda: tick())


# --- email item on the review page (048 T2.3) --------------------------------------------------------------------

EMAIL_FIELDS = ("intent",)  # 058 K5.1: an email's intent is correctable (the email is the source, not extracted)


def item_titles(items: list[dict[str, Any]]) -> dict[str, str]:
    """048 T2: an email's title in the item list is its subject and sender (the file name is always `message.json`);
    058 K5.2: an attachment's title names the email it came from. 185 (plan G-full-move T1e): the email kind's handler
    (until then in `jav/work_views.py` `item_titles`)."""
    from jav.emails import message_version

    out, subjects = {}, {}
    for i in items:
        if i.get("kind") != item_kinds.EMAIL:
            continue
        m, status = message_version(i)  # 086 N04: the version the item was added with, not the latest
        if not m and status != "changed":
            continue  # unreadable: the file name stays the title
        subjects[i["item_id"]] = ("(a levél futáskori változata nem található)" if status == "changed"
                                  else m.get("subject") or "(tárgy nélkül)")[:100]
        out[i["item_id"]] = f"{subjects[i['item_id']]} — {m.get('sender_name') or m.get('sender') or '?'}"
    for i in items:  # 058 K5.2: the attachment's origin in its name (which email it came from)
        if i.get("parent_item_id") in subjects:
            out[i["item_id"]] = f"{Path(i['source_path']).name} (a levél csatolmánya: {subjects[i['parent_item_id']]})"
    return out


def parent_labels(items: list[dict[str, Any]]) -> dict[str, str]:
    """Subjects of the attachments' parent emails (only if the run has attachments), for the documents' source email
    column. 185 (plan G-full-move T1e): the email kind's handler (until then in `jav/export.py` `_email_subjects`)."""
    from jav.emails import message_version

    parents = {i.get("parent_item_id") for i in items if i.get("parent_item_id")}
    out = {}
    for i in items:
        if i["item_id"] in parents:
            msg, status = message_version(i)  # 086 N04: the version the run processed
            # data (a cell of the download), not a label
            out[i["item_id"]] = ("(a levél futáskori változata nem található)" if status == "changed"
                                 else msg.get("subject") or ("(tárgy nélkül)" if msg else "(a levél nem olvasható)"))
    return out


def email_item_result(run: dict[str, Any], item: dict[str, Any], engine: str | None) -> dict[str, Any]:
    """048 T2: an email item's result on the review page: no extraction or page image; the email, its intent and its
    tasks. 185 (plan G-full-move T1e): the email kind's handler (`item_kinds.ItemHandler`; until then in
    `jav/corrections.py` `item_result`)."""
    from jav import corrections

    run_id, item_id = run["run_id"], item["item_id"]
    reasons = work.item_reasons(run_id, item_id, item)
    corr = corrections.current(run_id, item_id)
    # 058 K5.2: the email's attachments that ran as documents in the run (the UI refers to them)
    attachment_items = [{"item_id": i["item_id"], "filename": Path(i["source_path"]).name}
                        for i in run["input"]["items"] if i.get("parent_item_id") == item_id]
    email = email_item_view(item, work.flow_run_id(run_id, item_id), corr["fields"].get("intent"))
    own = bool(email["result"] and email["result"]["from_this_run"])
    return {"run_id": run_id, "item_id": item_id, "kind": "email", "extraction": None, "correction": corr,
            "effective": {}, "lists": {}, "checks": [], "provenance": {}, "source": None,
            "attachment_items": attachment_items, "email": email,
            # an intent taken from another run was not produced with this run's settings
            "engine": engine if own else None,
            "open_reasons": reasons["run"], "earlier_open_reasons": reasons["earlier"]}


def correct_email(run_id: str, item: dict[str, Any], *, fields: dict[str, Any], expected_revision: int, actor: str,
                  note: str | None, sources: dict[str, list[int]], confirm: list[str]) -> dict[str, Any]:
    """Manual correction of an email's intent (versioned, like a document's fields). The corrected intent settles the
    run's own intent to-dos (uncertain / unrecognised intent): the decision closes them; a to-do with another reason
    (e.g. suspicious content) stays open. 185 (plan G-full-move T1e): the email kind's handler (until then
    `jav/corrections.py` `_save_email`)."""
    from jav import corrections, intents

    if confirm:
        raise explained(ValueError, "fields cannot be confirmed on an email; correct its intent instead")
    unknown = sorted(set(fields) - set(EMAIL_FIELDS))
    if unknown:
        raise explained(ValueError, "only {{email_fields}} can be corrected on an email: {{unknown}}",
                        email_fields=", ".join(EMAIL_FIELDS), unknown=unknown)
    if sources:
        raise explained(ValueError, "source selection is not supported for emails")
    key = fields.get("intent")
    if key is not None and key not in intents.BY_KEY:
        raise explained(ValueError, "unknown intent: {{key}}", key=key)
    item_id = item["item_id"]
    corrections.insert_revision(run_id, item_id, fields, expected_revision, actor, note, None)
    if key is not None:
        for r in work.item_reasons(run_id, item_id, item)["run"]:
            if r["reason"].startswith("intent:"):
                work.resolve_reason(r["id"], actor=actor, resolution={"intent": key}, note="a szándék kézzel javítva")
    return corrections.current(run_id, item_id)


def intent_name(key: str | None) -> str | None:
    """The intent's Hungarian name from the registry (the key itself for an unknown key)."""
    from jav import intents

    return (intents.BY_KEY[key].display_name if key in intents.BY_KEY else key) if key else None


def next_flow_labels() -> dict[str, str]:
    """Hungarian names of the proposed next steps (058 K5.1): the fixed codes from `configs/datasets.json`, and "data
    extraction from the attachment" per type, with the document type's name. The UI translates the same with its own
    dictionary."""
    from jav import cfg

    out = dict(cfg.load("datasets")["labels"]["next_flow"])
    for key, name in cfg.load("field_labels")["doc_types"].items():
        out[f"m2:{key}"] = f"Adatkinyerés a csatolmányból ({name})"
    return out


def email_result_for(flow_run_id: str, message_id: str) -> tuple[dict[str, Any] | None, bool]:
    """The run's email result and whether it comes from this run. First the run's own row (058); for a pre-058 run the
    `emails` row if it comes from this run; otherwise the message's latest result (`from_this_run=False`, flagged in the
    UI)."""
    own = store.email_result(flow_run_id)
    if own is not None:
        return own, True
    with store.connect() as c:
        row = c.execute("SELECT * FROM emails WHERE message_id=?", (message_id,)).fetchone()
    if row is None:
        return None, False
    out = dict(row)
    out["signals"] = json.loads(out["signals"]) if out["signals"] else None
    out["attachments"] = json.loads(out["attachments"] or "[]")
    out["body"] = None
    return out, row["run_id"] == flow_run_id


def processed_types(doc_ids: list[str | None]) -> dict[str, str]:
    """126: the type each document was last processed as (`documents.doc_type`: the type pack's category once the data
    extraction saved it, else the recognised category)."""
    ids = sorted({d for d in doc_ids if d})
    if not ids:
        return {}
    with store.connect() as c:
        rows = c.execute(f"SELECT doc_id, doc_type FROM documents WHERE doc_id IN ({','.join('?' * len(ids))})", ids).fetchall()
    return {r["doc_id"]: r["doc_type"] for r in rows if r["doc_type"]}


def effective_email_result(res: dict[str, Any], corrected_intent: str | None) -> dict[str, Any]:
    """The email result with the manual correction (058 K5.1): the corrected intent wins and the routing is recomputed
    from it in code (the machine signals - e.g. an injected instruction - still count). The machine intent is kept
    (`machine_intent`)."""
    from jav import policy
    from jav.emails import Attachment, is_bookkeeping_file

    signals = {k: v for k, v in (res.get("signals") or {}).items() if k != "scores"}
    # pre-048 runs also stored the message folder's bookkeeping file as an attachment: it is not one
    atts = [a for a in res.get("attachments") or [] if not is_bookkeeping_file(str(a.get("filename") or ""))]
    # 126 (Q-gpt-receipt-label): the type shown is the one the document was processed as (a foreign provider's receipt
    # recognised as a receipt goes to the foreign invoice pack); the recognised category stays in `doc_type`, and the
    # routing below still reads that
    processed = processed_types([a.get("doc_id") for a in atts])
    atts = [{**a, "shown_type": processed.get(a.get("doc_id") or "") or a.get("doc_type")} for a in atts]
    out = {"intent": res.get("intent"), "intent_label": intent_name(res.get("intent")), "confidence": res.get("intent_conf"),
           "next_flow": res.get("next_flow"), "attachments": atts, "signals": signals,
           "corrected": False, "machine_intent": res.get("intent"),
           "sent": res.get("folder") == "sent"}  # 149: a sent message is not asked about its intent
    if corrected_intent and corrected_intent != res.get("intent"):
        atts = [Attachment.model_validate(a) for a in out["attachments"]]
        out.update(intent=corrected_intent, intent_label=intent_name(corrected_intent), corrected=True,
                   next_flow=policy.email_next_flow(corrected_intent, 1.0, atts, {corrected_intent: 1.0}, signals))
    elif corrected_intent:
        out["corrected"] = True  # a person confirmed the machine intent
    return out


# 187 (plan G-full-move T2c): a person's decisions on an email's task proposals, in the shared decision journal
TASK_KIND = "email_task"
decisions.register(decisions.Kind(TASK_KIND, ("decide", "done", "undone"), __name__))


def _task_key(flow_run_id: str, index: int) -> str:
    return f"{flow_run_id}#{index}"


def task_view(flow_run_id: str, raw: dict[str, Any] | None, *, with_state: bool = True) -> dict[str, Any] | None:
    """058 K5.3: the task proposal with its decisions (None = the run did not ask for proposals). 187: each task's
    `decision_state`, which the page sends back with a change (`with_state=False`: a download, which has no page)."""
    tasks = (raw or {}).get("tasks")
    if not tasks:
        return None
    decided = store.email_task_decisions(flow_run_id)
    proposed = tasks.get("tasks") or []
    items = [{**t, "index": n, "decision": decided.get(n)} for n, t in enumerate(proposed)]
    if with_state:
        with store.connect() as c:
            state = decisions.states(c, TASK_KIND, [_task_key(flow_run_id, n) for n in range(len(proposed))])
        items = [{**t, "decision_state": state[_task_key(flow_run_id, t["index"])]} for t in items]
    return {"status": tasks.get("status"), "reason": tasks.get("reason"), "error": tasks.get("error"), "tasks": items,
            "rejected": tasks.get("rejected") or []}


def decide_task(run_id: str, item_id: str, index: int, *, decision: str, actor: str, note: str | None = None,
                expected_state: int | None = None) -> dict[str, Any]:
    """A human decision on a task proposal (accept / reject). Once every proposal of the message is decided, the run's
    own "proposal awaits decision" to-do is resolved (the decisions go into the resolution). Frozen on an approved
    run: 086 (audit of 2026-10-02, N02) the writing transaction checks the approval again, so a decision checked before
    a concurrent approval is refused instead of being written after it (the decisions are part of the approved result,
    `corrections.review_version`). 187: the change goes into the decision journal in the same transaction (before, a
    changed decision overwrote the earlier one with nothing kept), and a stale `expected_state` is refused."""
    run = work.get_run(run_id)
    if run["approval"]:
        raise explained(work.RevisionConflict, "run {{run_id}} is approved; task decisions are frozen", run_id=run_id)
    item = next((i for i in run["input"]["items"] if i["item_id"] == item_id and i.get("kind") == "email"), None)
    if item is None:
        raise KeyError(item_id)
    flow_id = work.flow_run_id(run_id, item_id)
    view = task_view(flow_id, store.email_result(flow_id))
    if view is None or not 0 <= index < len(view["tasks"]):
        raise KeyError(f"task {index}")
    key = _task_key(flow_id, index)
    with store.connect() as c:
        store.begin_immediate(c)
        if decisions.run_approved(c, run_id):
            raise explained(work.RevisionConflict, "run {{run_id}} is approved; task decisions are frozen",
                            run_id=run_id)
        decisions.check(c, TASK_KIND, key, expected_state)
        store.email_task_decide(flow_id, index, decision=decision, actor=actor, note=note, c=c)
        decisions.record(c, TASK_KIND, key, "decide", actor=actor, value={"decision": decision}, note=note,
                         workpackage_id=run["workpackage_id"], run_id=run_id)
    view = task_view(flow_id, store.email_result(flow_id))
    if all(t["decision"] for t in view["tasks"]):
        summary = {"decisions": [{"index": t["index"], "decision": t["decision"]["decision"]} for t in view["tasks"]]}
        for r in work.item_reasons(run_id, item_id, item)["run"]:
            if r["reason"].startswith("tasks:proposed"):
                work.resolve_reason(r["id"], actor=actor, resolution=summary, note="minden feladatjavaslatról döntöttek")
    return view


def mark_task_done(run_id: str, item_id: str, index: int, *, done: bool, actor: str,
                   expected_state: int | None = None) -> dict[str, Any]:
    """062 (decision of 2026-09-29): an accepted task can be marked done by hand, and the mark can be withdrawn. The
    task happens in the real world, so it can be marked even on an approved run; a rejected or undecided task cannot.
    187: in one transaction with its journal row, under the page's `expected_state`."""
    run = work.get_run(run_id)
    item = next((i for i in run["input"]["items"] if i["item_id"] == item_id and i.get("kind") == "email"), None)
    if item is None:
        raise KeyError(item_id)
    flow_id = work.flow_run_id(run_id, item_id)
    view = task_view(flow_id, store.email_result(flow_id))
    if view is None or not 0 <= index < len(view["tasks"]):
        raise KeyError(f"task {index}")
    key = _task_key(flow_id, index)
    with store.connect() as c:
        store.begin_immediate(c)
        decisions.check(c, TASK_KIND, key, expected_state)
        if not store.email_task_done(flow_id, index, actor=actor, done=done, c=c):
            raise explained(work.RevisionConflict, "task {{index}} is not accepted; only an accepted task can be marked done",
                            index=index)
        decisions.record(c, TASK_KIND, key, "done" if done else "undone", actor=actor,
                         workpackage_id=run["workpackage_id"], run_id=run_id)
    return task_view(flow_id, store.email_result(flow_id))  # type: ignore[return-value]


def email_item_view(item: dict[str, Any], flow_run_id: str, corrected_intent: str | None = None) -> dict[str, Any]:
    """The email item: the message (the version the item was added with, 086 N04: `emails.message_version`), the intent
    detection result with the manual correction, and how much of the message text the detection saw (`body_coverage`,
    058 K5.1). `source_status` says whether the email has changed since (`earlier`) or that version is gone
    (`changed`: no text is shown)."""
    from jav.emails import EmailMessage, body_coverage, message_version

    path = Path(item["source_path"])
    msg, source_status = message_version(item)
    raw, from_this_run = email_result_for(flow_run_id, path.parent.name)
    res = {**effective_email_result(raw, corrected_intent), "from_this_run": from_this_run} if raw is not None else None
    body = msg.get("body") or ""
    coverage = (raw or {}).get("body") if from_this_run and (raw or {}).get("body") else body_coverage(
        EmailMessage(message_id=path.parent.name, body=body))
    return {"subject": msg.get("subject") or "", "sender": msg.get("sender"), "sender_name": msg.get("sender_name"),
            "to": msg.get("to") or [], "received_at": msg.get("received_at"), "mailbox": msg.get("mailbox"),
            "body": body[:20000], "attachments": [a.get("filename") for a in msg.get("attachments") or []],
            "body_coverage": coverage, "result": res, "tasks": task_view(flow_run_id, raw) if from_this_run else None,
            "source_status": source_status}
