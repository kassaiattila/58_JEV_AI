"""231 (plan stage C, C3h): the call of the Outlook bridge and the package of a download, split out of `mailbox.py`.

Plain-language summary: what a download reads (`MailboxRequest`: the addresses, the folders, the period, at most how
many emails), the free count preview and the download itself through the Outlook script (a test never reaches the
script: it passes its own runner, and the tests' guard replaces `_subprocess_runner` here), the work package of the
fresh messages with its owner, the PDF attachments added later, and the mark on an attachment of a suspicious email.
231 (U1e): an invented mailbox's address is read by the runner its module registers (`register_invented`, the example
mailboxes' invented bridge) instead of the Outlook script; a request naming an invented and a real mailbox together is
refused. The rules it follows are described in `mailbox.py`.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import subprocess
import threading
from collections.abc import Callable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from jav.app import item_kinds, work, work_recipes, work_runs
from jav.core import display, identity, store, todo_kinds
from jav.domains.email import email_store, ingest_server
from jav.core.config import BRIDGE_ROOT, OUTLOOK_BRIDGE_SCRIPT, PROJECT_ROOT
from jav.core.user_messages import explained


log = logging.getLogger("jav.domains.email.mailbox")


WRAPPER = PROJECT_ROOT / "scripts" / "mail_bridge_call.ps1"


COUNT_TIMEOUT_S = 180


FETCH_TIMEOUT_S = 1800


_ACCOUNT = re.compile(r"^[^@\s,;'\"`$]+@[^@\s,;'\"`$]+\.[^@\s,;'\"`$]+$")


_FOLDER = re.compile(r"^[^,;'\"`$\\]{1,80}$")


Runner = Callable[[list[str], int], tuple[int, str, str]]


class BridgeError(RuntimeError):
    """The legacy script failed (e.g. Outlook not running, unknown mailbox); the text is the script's message."""


_INVENTED: dict[str, Runner] = {}  # 231 (U1e): an invented mailbox's address (lower case) -> the runner that reads it


def register_invented(addresses: list[str], runner: Runner) -> None:
    """Invented mailboxes, read by `runner` (the script's arguments in, its exit code and output out)."""
    _INVENTED.update({a.lower(): runner for a in addresses})


def _runner_for(req: MailboxRequest) -> Runner:
    """The Outlook script, or the runner of the invented mailboxes the request names (all of them one runner's)."""
    from jav.app import registrations

    registrations.load_all()
    invented = {_INVENTED[a.lower()] for a in req.accounts if a.lower() in _INVENTED}
    if not invented:
        return _subprocess_runner
    if len(invented) > 1 or any(a.lower() not in _INVENTED for a in req.accounts):
        raise explained(BridgeError, "an invented mailbox is read on its own, not together with a real one")
    return invented.pop()


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
    code, out, err = (runner or _runner_for(req))(_argv(req, "count"), COUNT_TIMEOUT_S)
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


def fetch(req: MailboxRequest, *, actor: identity.Who, runner: Runner | None = None, inbox_root: Path | None = None) -> dict[str, Any]:
    """Download through our own temporary email receiver; new / changed messages become a work package with the
    default processing (080)."""
    run = runner or _runner_for(req)
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
        code, out, err = run(_argv(req, "fetch", OrchUrl=url, ApiToken=token), FETCH_TIMEOUT_S)
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
        # 231 (D4): in the request's language (Hungarian in the worker, as before)
        result["error"] = display.text("The download was interrupted ({{error}}); a package was made from the emails that arrived.",
                                       error=type(interrupted).__name__)
    if code != 0 and not stored:
        raise BridgeError(_error_text(err, out, code))
    if fresh:
        result["workpackage"] = _workpackage(req, fresh, actor=actor)["id"]
    return result


def pdf_attachments(messages: list[Path]) -> dict[Path, Path]:
    """058 K5.2: the messages' PDF attachments that exist as files (attachment → the message's `message.json`). An
    attachment is read only from the permitted location (checked by `emails.load_message_dir`); image attachments are
    not included for now. U1: a message gone from the disk (its mailbox folder removed) has none to add."""
    from jav.domains.email import emails

    out: dict[Path, Path] = {}
    for m in messages:
        if not Path(m).is_file():
            continue
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
    later to a pre-058 email package). 180: registered by the email domain (`jav/domains/email/__init__.py`). 183: the request
    of the download that made it (None if no recorded download did), so that the interface names its source in its own
    language instead of the stored label."""
    return {"attachments_missing": len(missing_attachments(dict(wp))), "mailbox_request": _request_of(wp["id"])}


def _request_of(wp_id: str) -> dict[str, Any] | None:
    with store.connect() as c:
        row = c.execute("SELECT request FROM mailbox_pulls WHERE status='ok' AND json_extract(result, '$.workpackage')=?"
                        " ORDER BY created_at DESC LIMIT 1", (wp_id,)).fetchone()
    return json.loads(row["request"]) if row else None


SUSPICIOUS_ATTACHMENT = todo_kinds.SUSPICIOUS_ATTACHMENT  # 154 (DECISIONS 154); 204: the shared code


def suspicious_email(run_id: str, email_item_id: str) -> bool:
    """154: whether the run's email item was routed by a signal (an injected instruction -> `human:suspicious`,
    `email.json` `signal_routes`)."""
    from jav.domains.email import email_rules

    result = email_store.email_result(work_runs.flow_run_id(run_id, email_item_id))
    return bool(result) and result.get("next_flow") in set(email_rules.EMAIL_SIGNAL_ROUTES.values())


def mark_suspicious_source(run: dict[str, Any], item: dict[str, Any]) -> bool:
    """154 (DECISIONS 154): the attachments of an email routed as suspicious are processed but marked: each gets an
    `attachment:suspicious_email` to-do in the run, so the run cannot be approved before a person has looked at it,
    and a statement from it never replaces another by rule (`reconcile_store.statements`). Called after every item, so it
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


# 231 (D4): stored data (the schedule's word in the name every scheduled download recorded), so it stays as stored
_SCHEDULED_ACTOR = re.compile(r"^ütemezés \((.+)\)$")


def scheduled_actor(schedule: Mapping[str, Any]) -> identity.Actor:
    """229 (SZ2c-3): who a scheduled download acts as: the machine, for the person who saved the schedule (shown as
    before: the schedule's word with the saver's name, `_SCHEDULED_ACTOR`)."""
    saver = identity.recorded(schedule["actor"], dict(schedule).get("actor_id"))
    return identity.acting_for("mailbox-schedule", f"ütemezés ({saver.name})", saver)


def owner_of(actor: identity.Who) -> identity.Who:
    """065: owner of a downloaded package: whoever started it; if scheduled, the user who saved the schedule (229: with
    the stable id of the person the machine acts for)."""
    m = _SCHEDULED_ACTOR.match(identity.name_of(actor) or "")
    if m is None:
        return actor
    return identity.recorded(m.group(1), actor.on_behalf_of) if isinstance(actor, identity.Actor) else m.group(1)


def _workpackage(req: MailboxRequest, messages: list[Path], *, actor: identity.Who) -> dict[str, Any]:
    # 231 (D4): the package's name in the request's language (Hungarian for a schedule, as before)
    name = display.text("Mailbox: {{accounts}} · {{at}}", accounts=", ".join(req.accounts), at=f"{datetime.now():%Y-%m-%d %H:%M}")
    wp = work.create_workpackage(name=name, source_kind="mailbox", source_ref=req.label(), owner=owner_of(actor))
    wp = work.add_items(wp["id"], messages, kind="email", expected_revision=0)
    wp = add_attachments(wp["id"], expected_revision=wp["revision"])  # 058 K5.2: plus the PDF attachments
    r = work_recipes.default_recipe()  # 080: one processing; on an email, intent + attachments
    # the recipe's defaults; 160-D: the application's engine (`assign_recipe` fills what is not named)
    work_recipes.assign_recipe(wp["id"], r["id"], params={}, expected_revision=0, actor=actor,
                       note=display.text("automatically after a mailbox download (the run is started by hand)"))
    return work.get(wp["id"])
