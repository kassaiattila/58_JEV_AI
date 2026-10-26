"""231 (plan stage A, A8; DECISIONS 231): the send capability's Outlook ways.

A case's message goes into the person's desktop Outlook as a draft through one small script; with the real send it is
sent, only to the allowlist's recipients. When Outlook is not running nothing is written and the handover is refused;
a script that stopped midway or did not answer in time leaves the outcome unknown, for a person to check. The mailbox
download stays read-only. A stand-in runs the script here; no Outlook, no AI call.
"""

from __future__ import annotations

import json
import re
import subprocess
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path

import pytest

from jav.app import capabilities, sending
from jav.core import identity
from jav.core.config import PROJECT_ROOT
from jav.core.process import cases, engine, outbox, tasks
from jav.core.process.definition import ProcessDef, StepDef
from jav.domains.email import outlook_drafts

MACHINE = identity.machine("tests")
WRITES = re.compile(r"CreateItem|\.(Save|Send|Delete|Move|Copy)\s*\(", re.IGNORECASE)


def _letter(_case_id: str, _source_step, _source) -> sending.Message:  # D0-b: the step too
    msg = EmailMessage(policy=SMTP)
    msg["To"], msg["Subject"], msg["X-Unsent"] = "buyer@example.com", "Our offer", "1"
    msg.set_content("Dear Buyer,\n\nplease find our offer attached.\n")
    msg.add_attachment(b"PK invented document", maintype="application", subtype="octet-stream", filename="offer-v1.docx")
    return sending.Message(msg.as_bytes(), "offer-v1.eml", "buyer@example.com", "Our offer")


@pytest.fixture()
def builders(monkeypatch):
    capabilities.of("send@1")  # the application's registrations
    monkeypatch.setattr(sending, "_BUILDERS", {**sending._BUILDERS})
    sending.register_builder(sending.MessageBuilder("invented_letter", __name__, _letter, "An invented letter."))


class Script:
    """The script's stand-in: what it was asked (the request file is read while it runs) and what it answers."""

    def __init__(self, code: int = 0, out: str = '{"ok": true, "state": "draft", "entry_id": "E-1"}', err: str = "",
                 raises: Exception | None = None) -> None:
        self.code, self.out, self.err, self.raises = code, out, err, raises
        self.calls: list[dict] = []

    def __call__(self, argv: list[str], timeout: int) -> tuple[int, str, str]:
        request = json.loads(Path(argv[argv.index("-Request") + 1]).read_text(encoding="utf-8"))
        files = {Path(p).name: Path(p).read_bytes() for p in request["attachments"]}
        self.calls.append({"argv": argv, "request": request, "files": files, "timeout": timeout})
        if self.raises is not None:
            raise self.raises
        return self.code, self.out, self.err


def _case(case_id: str, script: Script, mode: str = "outlook_draft") -> dict:
    step = StepDef(id="send", kind="cap.send.v1", params={"message": "invented_letter", "mode": mode})
    cases.start(case_id, ProcessDef(id="invented_outlook", version="1", title="An invented send", steps=(step,)), {},
                MACHINE)
    with outlook_drafts.use_runner(script):
        engine.turn(case_id, wake=True)
    return engine.state(case_id)


def test_the_mailbox_download_stays_read_only_and_only_the_draft_script_writes() -> None:
    for name in ("outlook_bridge.ps1", "mail_bridge_call.ps1"):
        assert not WRITES.search((PROJECT_ROOT / "scripts" / name).read_text(encoding="utf-8")), name
    script = outlook_drafts.SCRIPT.read_text(encoding="utf-8")
    assert script.isascii()  # PowerShell 5.1 reads a script without a byte order mark in the system code page
    assert [m.group(0) for m in WRITES.finditer(script)] == ["CreateItem", ".Send(", ".Save("]
    assert re.search(r"if \(\$Send\) \{\s*\$mail\.Send\(\)", script)  # the send only behind its switch


def test_a_case_puts_its_message_into_outlook_as_a_draft(builders) -> None:
    script = Script()
    state = _case("case-outlook-1", script)
    assert state["steps"]["send"]["state"] == "done"
    assert state["steps"]["send"]["result"]["receipt"] == {"outlook": "draft", "entry_id": "E-1"}
    [call] = script.calls
    assert "-Send" not in call["argv"] and call["argv"][call["argv"].index("-File") + 1] == str(outlook_drafts.SCRIPT)
    assert call["request"]["to"] == "buyer@example.com" and call["request"]["subject"] == "Our offer"
    assert call["request"]["body"].replace("\r\n", "\n") == "Dear Buyer,\n\nplease find our offer attached.\n"
    assert call["files"] == {"offer-v1.docx": b"PK invented document"}  # Outlook shows the file's own name


def test_without_a_running_outlook_nothing_is_written_and_the_handover_is_refused(builders) -> None:
    state = _case("case-outlook-2", Script(code=3, out='{"ok": false, "refused": true, '
                                                       '"error": "Outlook is not running in this session"}'))
    assert state["steps"]["send"]["state"] == "failed"
    assert state["steps"]["send"]["note"] == "Outlook is not running in this session"
    assert [h["status"] for h in state["handovers"]] == [outbox.FAILED]


@pytest.mark.parametrize("script", [Script(code=1, out="", err="Exception calling \"Save\": the store is busy"),
                                    Script(raises=subprocess.TimeoutExpired("powershell.exe", 90))],
                         ids=["stopped midway", "no answer in time"])
def test_a_script_that_stopped_or_did_not_answer_leaves_the_outcome_to_a_person(builders, script) -> None:
    state = _case(f"case-outlook-3-{id(script)}", script)
    assert [h["status"] for h in state["handovers"]] == [outbox.UNCERTAIN]
    assert state["steps"]["send"]["waiting_for"] == tasks.EVENT  # the person checks the Drafts folder


def test_the_real_send_goes_out_only_to_the_allowlist(builders, monkeypatch) -> None:
    script = Script(out='{"ok": true, "state": "sent"}')
    assert _case("case-outlook-4", script, mode="outlook_send")["steps"]["send"]["state"] == "failed"
    assert script.calls == []  # the shipped allowlist is empty: nothing was handed over
    payload = {"to": "buyer@example.com", "subject": "x", "data": ""}
    with outlook_drafts.use_runner(script), pytest.raises(outbox.Refused):
        outlook_drafts.deliver_send("h-1", payload)  # checked again by the sender itself
    monkeypatch.setattr(sending.cfg, "load", lambda name: {"meta": {"version": "x"}, "outlook_send": {"allow": ["@example.com"]}})
    state = _case("case-outlook-5", script, mode="outlook_send")
    assert state["steps"]["send"]["state"] == "done" and state["steps"]["send"]["result"]["receipt"] == {"outlook": "sent"}
    assert "-Send" in script.calls[-1]["argv"]
