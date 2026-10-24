"""The Outlook ways of the send capability (231, plan stage A, A8; DECISIONS 231).

Plain-language summary: a process pack may choose that its case's message goes into the person's own Outlook as a
draft, which they open, check and send themselves; or (only to the addresses an owner allowed) straight out through
Outlook. The message the case recorded (an email file with its attachments) is unpacked into a temporary folder and
handed to a small script (`scripts/outlook_draft.ps1`) that talks to the desktop Outlook already running; the mailbox
download stays read-only. When Outlook is not running, nothing is written and the handover is refused (a person tries
again); a script that stopped midway or did not answer in time leaves the outcome unknown, and a person checks the
Drafts folder and says whether the message is there.

- `deliver_draft(handover_id, payload)` / `deliver_send(...)`: the senders of the `outlook_draft` and `outlook_send`
  modes (`jav/app/sending.py`).
- `use_runner(runner)`: the call that runs the script (a test's stand-in).

Layer: domain (email), an adapter to the desktop Outlook; it registers into the application's send capability.
"""

from __future__ import annotations

import base64
import json
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from email import message_from_bytes
from email.policy import default
from pathlib import Path
from typing import Any

from jav.core.config import PROJECT_ROOT
from jav.core.process import outbox

__all__ = ["SCRIPT", "TIMEOUT_S", "deliver_draft", "deliver_send", "register", "use_runner"]

SCRIPT = PROJECT_ROOT / "scripts" / "outlook_draft.ps1"
TIMEOUT_S = 90  # Outlook may take a while to attach a large document
REFUSED_EXIT = 3  # the script's exit code when nothing was written (Outlook is not running here)

Runner = Callable[[list[str], int], tuple[int, str, str]]


def _subprocess_runner(argv: list[str], timeout: int) -> tuple[int, str, str]:
    done = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
    return done.returncode, done.stdout.decode("utf-8", errors="replace"), done.stderr.decode("utf-8", errors="replace")


_runner: Runner = _subprocess_runner


@contextmanager
def use_runner(runner: Runner) -> Iterator[None]:
    """Runs the script through `runner` (a test's stand-in) inside the block."""
    global _runner
    prior, _runner = _runner, runner
    try:
        yield
    finally:
        _runner = prior


def _answer(out: str) -> dict[str, Any]:
    """The script's JSON line (its last one), or nothing when it printed none."""
    for line in reversed(out.strip().splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def _deliver(payload: dict[str, Any], *, send: bool) -> dict[str, Any]:
    message = message_from_bytes(base64.b64decode(payload["data"]), policy=default)
    body = message.get_body(("plain",))
    with tempfile.TemporaryDirectory(prefix="jav-outlook-") as tmp:
        attachments = []
        for n, part in enumerate(message.iter_attachments(), 1):
            name = Path(part.get_filename() or f"attachment-{n}").name  # a name only: never a path out of the folder
            target = Path(tmp) / str(n) / name  # its own folder: Outlook shows the file's own name, two may share it
            target.parent.mkdir()
            target.write_bytes(part.get_payload(decode=True) or b"")
            attachments.append(str(target))
        request = Path(tmp) / "request.json"
        request.write_text(json.dumps({"to": payload.get("to"), "subject": payload.get("subject") or "",
                                       "body": body.get_content() if body is not None else "",
                                       "attachments": attachments}, ensure_ascii=False), encoding="utf-8")
        argv = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
                "-Request", str(request), *(["-Send"] if send else [])]
        code, out, err = _runner(argv, TIMEOUT_S)  # a timeout leaves the outcome unknown (the send capability's rule)
    answer = _answer(out)
    if code == REFUSED_EXIT or answer.get("refused"):
        raise outbox.Refused(str(answer.get("error") or "Outlook is not running"))
    if code != 0 or not answer.get("ok"):
        tail = "; ".join(line for line in (err or out).strip().splitlines()[-3:] if line.strip())
        raise RuntimeError(f"the Outlook script ended with {code}: {tail or 'no answer'}")
    return {"outlook": answer.get("state"), **({"entry_id": answer["entry_id"]} if answer.get("entry_id") else {})}


def deliver_draft(_handover_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The recorded message as a draft in the person's Outlook."""
    return _deliver(payload, send=False)


def deliver_send(_handover_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The recorded message sent through Outlook, only to the allowlist's recipients (checked again here)."""
    from jav.app import sending

    if not sending.allowed(payload.get("to")):
        raise outbox.Refused("the real send is switched off for these recipients: not on the allowlist (send.json)")
    return _deliver(payload, send=True)


def register() -> None:
    from jav.app import sending

    sending.register_sender(sending.Sender(sending.OUTLOOK_DRAFT, __name__, deliver_draft))
    sending.register_sender(sending.Sender(sending.OUTLOOK_SEND, __name__, deliver_send))
