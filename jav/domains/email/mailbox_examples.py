"""Invented mailboxes as example material (231, stage U, U1e; the owner's decision of 2026-10-28).

Plain-language summary: a mailbox download reads Outlook, so neither the download nor the email routing could be tried
on invented emails. The invented mailboxes (`configs/example_mailboxes.json`) each have an address on the reserved
`.example` domain and a few messages in their Inbox and Sent Items. A download of such an address is served by the
invented bridge instead of the Outlook script: it reads the same request (the folders, the period, at most how many
messages), and for a download it sends each message to the system's own temporary email receiver with the receiver's
key, as the Outlook bridge does: a batch is opened, each message sent with its attachments saved where the bridge saves
them, and the batch sealed. So the receiver, the package and the processing are the ones a real download goes through.
A message is written in the file, or taken from a golden set with its printed attachments; an attachment is a golden
set's printed document, written as a PDF. A request naming an invented and a real mailbox together is refused.

- `load(name)`: the invented mailboxes (`ExampleMailboxes`); `messages(mailbox)`: their messages as the bridge sends them.
- `Bridge`: the invented bridge, a runner of `mailbox_bridge`; `register()`: its addresses for `mailbox_bridge`.

Layer: the email domain; it uses the mailbox bridge's runner contract and the email receiver's paths.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jav.core import cfg
from jav.documents.synthetic_pdf import write_unicode_pdf_pages
from jav.domains.email import ingest_server, mailbox_bridge

__all__ = ["Bridge", "ExampleMailboxes", "load", "messages", "register"]

FOLDERS = {"inbox": "Inbox", "sent items": "Sent Items"}  # the folders the Outlook bridge reads by name (148)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Attachment(_Model):
    file: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.pdf$")
    golden: str
    case: str


class Message(_Model):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    folder: Literal["Inbox", "Sent Items"]
    golden: str | None = None  # the email taken from a golden set's case, with its printed PDF attachments
    case: str | None = None
    received: str | None = None
    sender: str | None = None
    to: tuple[str, ...] = ()
    subject: str | None = None
    body: str | None = None
    attachments: tuple[Attachment, ...] = ()
    from_: str | None = Field(default=None, alias="from")

    @model_validator(mode="after")
    def _whole(self) -> Message:
        if (self.golden is None) != (self.case is None):
            raise ValueError(f"{self.id}: a golden set and its case go together")
        if self.golden is None and not (self.received and self.from_ and self.subject is not None and self.body is not None):
            raise ValueError(f"{self.id}: a message of its own names when it came, who sent it, its subject and its text")
        return self


class Mailbox(_Model):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    address: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.example$")
    name: str
    messages: tuple[Message, ...] = Field(min_length=1)


class ExampleMailboxes(_Model):
    mailboxes: tuple[Mailbox, ...] = Field(min_length=1)


def load(name: str = "example_mailboxes") -> ExampleMailboxes:
    data = cfg.load(name)
    return ExampleMailboxes.model_validate({k: v for k, v in data.items() if k != "meta"})


def _golden_case(name: str, case_id: str) -> dict[str, Any]:
    case = next((c for c in cfg.load(name)["cases"] if c["id"] == case_id), None)
    if case is None:
        raise KeyError(f"{name}: no case {case_id!r}")
    return case


def _printed(name: str, case_id: str) -> list[str]:
    """A golden set's printed document: an invented invoice's rows (golden_synthetic.json)."""
    return list(_golden_case(name, case_id)["rows"])


def messages(mailbox: Mailbox) -> list[dict[str, Any]]:
    """The mailbox's messages as the bridge sends them: its own fields, and each attachment's file name and printed page."""
    out = []
    for m in mailbox.messages:
        entry = f"example-{mailbox.id}-{m.id}"
        if m.golden is not None:
            email = _golden_case(m.golden, m.case or "")["message"]
            pdfs = [(a["filename"], list(a["rows"])) for a in email.get("attachments", []) if a.get("format") == "pdf"]
            fields = {"from": email["sender"], "sender": email.get("sender_name"), "to": [mailbox.address],
                      "subject": email["subject"], "body": email["body"], "received": email["received_at"]}
        else:
            pdfs = [(a.file, _printed(a.golden, a.case)) for a in m.attachments]
            fields = {"from": m.from_, "sender": m.sender, "to": list(m.to), "subject": m.subject, "body": m.body,
                      "received": m.received}
        out.append({"entry_id": entry, "folder": m.folder, **fields, "attachments": pdfs})
    return out


# --- the invented bridge --------------------------------------------------------------------------------------------


def _args(argv: list[str]) -> dict[str, str | bool]:
    """The script's named arguments (`-Name value`; a switch without a value is True)."""
    out: dict[str, str | bool] = {}
    for i, a in enumerate(argv):
        if a.startswith("-") and len(a) > 1 and not a[1].isdigit():
            nxt = argv[i + 1] if i + 1 < len(argv) else None
            out[a[1:]] = nxt if nxt is not None and not nxt.startswith("-") else True
    return out


def _window(args: dict[str, str | bool], now: datetime) -> tuple[datetime, datetime | None]:
    if isinstance(args.get("ReceivedFrom"), str) and isinstance(args.get("ReceivedTo"), str):
        return datetime.fromisoformat(str(args["ReceivedFrom"])), datetime.fromisoformat(str(args["ReceivedTo"]))
    return now - timedelta(days=int(str(args.get("SinceDays") or 1))), None


def _when(text: str) -> datetime:
    """A message's time as the period compares it: its local clock time (the script reads Outlook's local times)."""
    return datetime.fromisoformat(text).replace(tzinfo=None)


class Bridge:
    """The invented bridge: a runner of `mailbox_bridge` for the invented mailboxes' addresses."""

    def __init__(self, boxes: ExampleMailboxes | None = None, *, now: datetime | None = None) -> None:
        self.boxes, self.now = boxes, now

    def _boxes(self) -> dict[str, Mailbox]:
        return {b.address.lower(): b for b in (self.boxes or load()).mailboxes}

    def addresses(self) -> list[str]:
        return list(self._boxes())

    def _chosen(self, args: dict[str, str | bool]) -> tuple[list[tuple[str, dict[str, Any]]], str | None]:
        """The messages the request reads ((account, message), oldest first), or the script's error."""
        boxes = self._boxes()
        folders = [f.strip() for f in str(args.get("Folders") or "Inbox").split(",") if f.strip()]
        if unknown := [f for f in folders if f.lower() not in FOLDERS]:
            return [], f"Mail folder '{unknown[0]}' was not found (readable: Inbox, Sent Items)."
        wanted = {FOLDERS[f.lower()] for f in folders}
        start, end = _window(args, self.now or datetime.now())
        chosen = []
        for account in [a.strip() for a in str(args.get("Accounts") or "").split(",") if a.strip()]:
            box = boxes.get(account.lower())
            if box is None:
                return [], f"Mailbox '{account}' is not an invented one."
            chosen += [(box.address, m) for m in messages(box) if m["folder"] in wanted
                       and start <= _when(m["received"]) and (end is None or _when(m["received"]) <= end)]
        chosen.sort(key=lambda am: _when(am[1]["received"]))
        limit = int(str(args.get("MaxItems") or 0))
        return chosen[:limit] if limit else chosen, None

    def __call__(self, argv: list[str], timeout: int) -> tuple[int, str, str]:
        del timeout  # nothing here waits on Outlook
        args = _args(argv)
        chosen, error = self._chosen(args)
        if error:
            return 1, "", error
        if args.get("Mode") == "count":
            per: dict[str, int] = {}
            for account, _m in chosen:
                per[account] = per.get(account, 0) + 1
            line = {"count_only": True, "received_from": None, "received_to": None, "eligible": len(chosen),
                    "counts": {"scanned": len(chosen), "mail": len(chosen), "skippedSeen": 0},
                    "accounts": [{"account": a, "counts": {"mail": n}} for a, n in per.items()]}
            return 0, json.dumps(line) + "\n", ""
        url, token = str(args["OrchUrl"]), str(args["ApiToken"])
        base = url.rsplit("/ingest/email", 1)[0]
        batch = _post(f"{base}/api/intake-batches", {"name": "invented mailbox"}, token)
        for account, m in chosen:
            _post(url, {**self._payload(account, m), "batch_id": batch["id"]}, token)
        _post(f"{base}/api/intake-batches/{batch['id']}/seal", {}, token)
        return 0, f"=== TOTAL :: processed={len(chosen)} ===\n", ""

    @staticmethod
    def _payload(account: str, m: dict[str, Any]) -> dict[str, Any]:
        """The message as the Outlook bridge sends it; its attachments saved where the bridge saves them."""
        rel = f"inbox/email/{ingest_server.safe_mailbox_dir(account)}/{ingest_server.short_hash(m['entry_id'])}"
        folder = Path(ingest_server.BRIDGE_DATA_ROOT) / rel
        attachments = []
        for file_name, rows in m["attachments"]:
            folder.mkdir(parents=True, exist_ok=True)
            write_unicode_pdf_pages(folder / file_name, [rows])
            attachments.append({"path": f"/data/{rel}/{file_name}", "filename": file_name})
        return {"message_id": m["entry_id"], "account": account, "from": m["from"], "sender": m["sender"], "to": m["to"],
                "cc": [], "subject": m["subject"], "body_preview": m["body"], "received": m["received"],
                "attachments": attachments, **({"folder": "sent"} if m["folder"] == "Sent Items" else {})}


def _post(url: str, body: dict[str, Any], token: str) -> dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # the receiver is on 127.0.0.1
    with opener.open(request, timeout=30) as response:
        return json.loads(response.read() or b"{}")


def register() -> None:
    bridge = Bridge()
    mailbox_bridge.register_invented(bridge.addresses(), bridge)
