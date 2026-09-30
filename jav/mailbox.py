"""Mailbox reading from the local service (048 T2): count preview, download, a work package from the fresh messages.

The legacy Outlook script (`OUTLOOK_BRIDGE_SCRIPT`) is called unchanged via the `scripts/mail_bridge_call.ps1` wrapper:
- **preview** (`count`): the legacy `-CountOnly`; free of charge, writes no file, marks nothing as read;
- **download** (`fetch`): for the duration of the download we start our own email receiver on a free port with a
  one-off key (`jav.ingest_server.make_server`) and the script sends the messages there; the receiver writes them into
  the inbox folder with the existing repeat protection. The script's project root is our own `BRIDGE_ROOT`
  (attachments, "already read" list), not the legacy project.

The new or changed messages become a new work package (one message = one item, its `message.json`) with the
email-intent recipe assigned; no paid processing starts (decision of 2026-09-28: runs are started by hand). No new
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
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from jav import ingest_server, store, work
from jav.config import BRIDGE_ROOT, OUTLOOK_BRIDGE_SCRIPT, PROJECT_ROOT

log = logging.getLogger("jav.mailbox")

WRAPPER = PROJECT_ROOT / "scripts" / "mail_bridge_call.ps1"
EMAIL_RECIPE = "email-intent"
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
            raise ValueError(f"not e-mail addresses: {bad}")
        return [a.strip() for a in v]

    @field_validator("folders")
    @classmethod
    def _folders(cls, v: list[str]) -> list[str]:
        bad = [f for f in v if not _FOLDER.match(f.strip())]
        if bad:
            raise ValueError(f"invalid folder names: {bad}")
        return [f.strip() for f in v]

    @model_validator(mode="after")
    def _period(self) -> MailboxRequest:
        if (self.received_from is None) != (self.received_to is None):
            raise ValueError("received_from and received_to go together")
        if self.received_from and self.received_to and self.received_from > self.received_to:
            raise ValueError("received_from must not be after received_to")
        if self.received_from is None and self.since_days is None:
            self.since_days = 1
        return self

    def label(self) -> str:
        period = (f"{self.received_from}–{self.received_to}" if self.received_from else f"utolsó {self.since_days} nap")
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
    email-intent recipe."""
    token = secrets.token_urlsafe(24)
    stored: list[dict[str, Any]] = []
    lock = threading.Lock()

    def on_ingest(res: dict[str, Any], payload: dict[str, Any]) -> None:
        with lock:
            stored.append({"folder": Path(res["folder"]), "status": res["status"], "subject": str(payload.get("subject") or "")[:120]})

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
    origin). The email recipe runs the full document processing on the attachment (058 K5.2, automatic chain). No new
    attachment: the package is unchanged."""
    wp = work.get(wp_id)
    mails = [Path(i["source_path"]) for i in wp["items"] if i["kind"] == "email"]
    missing = set(missing_attachments(wp))
    if not missing:
        return wp
    item_of = {Path(i["source_path"]).resolve(): i["item_id"] for i in wp["items"] if i["kind"] == "email"}
    parents = {pdf: item_of[Path(msg).resolve()] for pdf, msg in pdf_attachments(mails).items() if pdf in missing}
    return work.add_items(wp_id, sorted(missing), kind="document", expected_revision=expected_revision, parents=parents)


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
    r = work.recipe(EMAIL_RECIPE)
    params = {k: spec["default"] for k, spec in r["params"].items()}
    work.assign_recipe(wp["id"], EMAIL_RECIPE, params=params, expected_revision=0, actor=actor,
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
    updated_at   TEXT NOT NULL
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
        raise ValueError("a schedule reads the last N days; a fixed date range is for one-off fetches")
    if not 15 <= interval_min <= 7 * 24 * 60:
        raise ValueError("interval_min must be between 15 minutes and 7 days")
    sid = f"mbx-{uuid.uuid4().hex[:10]}"
    now = _utc()
    with store.connect() as c:
        c.execute("INSERT INTO mailbox_schedules(id, request, interval_min, enabled, actor, next_at, created_at, updated_at)"
                  " VALUES (?,?,?,?,?,?,?,?)", (sid, req.model_dump_json(), interval_min, int(enabled), actor, now, now, now))
    return schedule(sid)


def update_schedule(schedule_id: str, *, enabled: bool | None = None, interval_min: int | None = None) -> dict[str, Any]:
    cur = schedule(schedule_id)
    if interval_min is not None and not 15 <= interval_min <= 7 * 24 * 60:
        raise ValueError("interval_min must be between 15 minutes and 7 days")
    en = cur["enabled"] if enabled is None else enabled
    iv = cur["interval_min"] if interval_min is None else interval_min
    # due at once when switched on; when the frequency changes, the next time follows the new frequency
    nxt = _utc() if (enabled and not cur["enabled"]) else cur["next_at"]
    if interval_min is not None and cur["last_at"]:
        nxt = _utc(datetime.fromisoformat(cur["last_at"]) + timedelta(minutes=iv))
    with store.connect() as c:
        c.execute("UPDATE mailbox_schedules SET enabled=?, interval_min=?, next_at=?, updated_at=? WHERE id=?",
                  (int(en), iv, nxt, _utc(), schedule_id))
    return schedule(schedule_id)


def delete_schedule(schedule_id: str) -> None:
    schedule(schedule_id)
    with store.connect() as c:
        c.execute("DELETE FROM mailbox_schedules WHERE id=?", (schedule_id,))


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


# --- email item on the review page (048 T2.3) --------------------------------------------------------------------


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


def effective_email_result(res: dict[str, Any], corrected_intent: str | None) -> dict[str, Any]:
    """The email result with the manual correction (058 K5.1): the corrected intent wins and the routing is recomputed
    from it in code (the machine signals - e.g. an injected instruction - still count). The machine intent is kept
    (`machine_intent`)."""
    from jav import policy
    from jav.emails import Attachment, is_bookkeeping_file

    signals = {k: v for k, v in (res.get("signals") or {}).items() if k != "scores"}
    # pre-048 runs also stored the message folder's bookkeeping file as an attachment: it is not one
    atts = [a for a in res.get("attachments") or [] if not is_bookkeeping_file(str(a.get("filename") or ""))]
    out = {"intent": res.get("intent"), "intent_label": intent_name(res.get("intent")), "confidence": res.get("intent_conf"),
           "next_flow": res.get("next_flow"), "attachments": atts, "signals": signals,
           "corrected": False, "machine_intent": res.get("intent")}
    if corrected_intent and corrected_intent != res.get("intent"):
        atts = [Attachment.model_validate(a) for a in out["attachments"]]
        out.update(intent=corrected_intent, intent_label=intent_name(corrected_intent), corrected=True,
                   next_flow=policy.email_next_flow(corrected_intent, 1.0, atts, {corrected_intent: 1.0}, signals))
    elif corrected_intent:
        out["corrected"] = True  # a person confirmed the machine intent
    return out


def task_view(flow_run_id: str, raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """058 K5.3: the task proposal with its decisions (None = the run did not ask for proposals)."""
    tasks = (raw or {}).get("tasks")
    if not tasks:
        return None
    decisions = store.email_task_decisions(flow_run_id)
    items = [{**t, "index": n, "decision": decisions.get(n)} for n, t in enumerate(tasks.get("tasks") or [])]
    return {"status": tasks.get("status"), "reason": tasks.get("reason"), "error": tasks.get("error"), "tasks": items,
            "rejected": tasks.get("rejected") or []}


def decide_task(run_id: str, item_id: str, index: int, *, decision: str, actor: str, note: str | None = None) -> dict[str, Any]:
    """A human decision on a task proposal (accept / reject). Once every proposal of the message is decided, the run's
    own "proposal awaits decision" to-do is resolved (the decisions go into the resolution). Frozen on an approved
    run."""
    run = work.get_run(run_id)
    if run["approval"]:
        raise work.RevisionConflict(f"run {run_id} is approved; task decisions are frozen")
    item = next((i for i in run["input"]["items"] if i["item_id"] == item_id and i.get("kind") == "email"), None)
    if item is None:
        raise KeyError(item_id)
    flow_id = work.flow_run_id(run_id, item_id)
    view = task_view(flow_id, store.email_result(flow_id))
    if view is None or not 0 <= index < len(view["tasks"]):
        raise KeyError(f"task {index}")
    store.email_task_decide(flow_id, index, decision=decision, actor=actor, note=note)
    view = task_view(flow_id, store.email_result(flow_id))
    if all(t["decision"] for t in view["tasks"]):
        summary = {"decisions": [{"index": t["index"], "decision": t["decision"]["decision"]} for t in view["tasks"]]}
        for r in work.item_reasons(run_id, item_id, item)["run"]:
            if r["reason"].startswith("tasks:proposed"):
                work.resolve_reason(r["id"], actor=actor, resolution=summary, note="minden feladatjavaslatról döntöttek")
    return view


def mark_task_done(run_id: str, item_id: str, index: int, *, done: bool, actor: str) -> dict[str, Any]:
    """062 (decision of 2026-09-29): an accepted task can be marked done by hand, and the mark can be withdrawn. The
    task happens in the real world, so it can be marked even on an approved run; a rejected or undecided task cannot."""
    run = work.get_run(run_id)
    item = next((i for i in run["input"]["items"] if i["item_id"] == item_id and i.get("kind") == "email"), None)
    if item is None:
        raise KeyError(item_id)
    flow_id = work.flow_run_id(run_id, item_id)
    view = task_view(flow_id, store.email_result(flow_id))
    if view is None or not 0 <= index < len(view["tasks"]):
        raise KeyError(f"task {index}")
    if not store.email_task_done(flow_id, index, actor=actor, done=done):
        raise work.RevisionConflict(f"task {index} is not accepted; only an accepted task can be marked done")
    return task_view(flow_id, store.email_result(flow_id))  # type: ignore[return-value]


def email_item_view(item: dict[str, Any], flow_run_id: str, corrected_intent: str | None = None) -> dict[str, Any]:
    """The email item: the message (from `message.json`), the intent detection result with the manual correction, and
    how much of the message text the detection saw (`body_coverage`, 058 K5.1)."""
    from jav.emails import EmailMessage, body_coverage

    path = Path(item["source_path"])
    msg = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    raw, from_this_run = email_result_for(flow_run_id, path.parent.name)
    res = {**effective_email_result(raw, corrected_intent), "from_this_run": from_this_run} if raw is not None else None
    body = msg.get("body") or ""
    coverage = (raw or {}).get("body") if from_this_run and (raw or {}).get("body") else body_coverage(
        EmailMessage(message_id=path.parent.name, body=body))
    return {"subject": msg.get("subject") or "", "sender": msg.get("sender"), "sender_name": msg.get("sender_name"),
            "to": msg.get("to") or [], "received_at": msg.get("received_at"), "mailbox": msg.get("mailbox"),
            "body": body[:20000], "attachments": [a.get("filename") for a in msg.get("attachments") or []],
            "body_coverage": coverage, "result": res, "tasks": task_view(flow_run_id, raw) if from_this_run else None}
