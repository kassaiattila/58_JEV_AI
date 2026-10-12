"""148 (backlog F-outgoing-reconciliation; DECISIONS 148): sent messages from the mailbox.

The owner asked for the outgoing invoices to come from the sent messages too. The legacy Outlook bridge reads only the
Inbox and its direct subfolders, and a folder name it does not find gave an empty result without an error, so asking
for the Sent Items folder silently returned nothing. The bridge is now ported into this repository: it reads the Sent
Items folder as well (by its sent time), a folder name it cannot find is an error, and a sent message's payload says
`folder = 'sent'`, which the receiver keeps in `message.json`. An Inbox message's record is unchanged, so a message
pulled again is still recognised as the same.

Synthetic data only; no Outlook, no live call.
"""

from __future__ import annotations

import json

import pytest

from jav import config, ingest_server


def _payload(**over):
    base = {"message_id": "ENTRY-1", "account": "box@example.com", "from": "box@example.com", "subject": "Invoice INV-0001",
            "body_preview": "Synthetic body.", "received": "2026-09-27T10:00:00", "to": ["customer@example.com"], "cc": [],
            "attachments": []}
    base.update(over)
    return base


def test_the_service_calls_the_bridge_ported_into_this_repository():
    assert config.OUTLOOK_BRIDGE_SCRIPT == config.PROJECT_ROOT / "scripts" / "outlook_bridge.ps1"
    assert config.OUTLOOK_BRIDGE_SCRIPT.is_file()
    text = config.OUTLOOK_BRIDGE_SCRIPT.read_text(encoding="utf-8")
    assert "$OL_FOLDER_SENT = 5" in text and "function Get-MailFolders(" in text
    assert "was not found in mailbox" in text  # an unknown folder is an error, not an empty folder
    assert "function Get-InboxFolders(" not in text


def test_the_bridge_script_has_no_non_ascii_string_literal():
    # PowerShell 5.1 reads the file in the ANSI code page: a non-ASCII byte inside a string can end it early.
    for n, line in enumerate(config.OUTLOOK_BRIDGE_SCRIPT.read_text(encoding="utf-8").splitlines(), 1):
        code = line.split("#", 1)[0]
        assert code.isascii(), f"line {n}"


def test_a_sent_message_keeps_its_folder(tmp_path):
    res = ingest_server.ingest_message(_payload(folder="sent"), tmp_path / "inbox")
    assert json.loads((res["folder"] / "message.json").read_text(encoding="utf-8"))["folder"] == "sent"


def test_an_inbox_message_record_is_unchanged(tmp_path):
    root = tmp_path / "inbox"
    first = ingest_server.ingest_message(_payload(), root)
    assert "folder" not in json.loads((first["folder"] / "message.json").read_text(encoding="utf-8"))
    again = ingest_server.ingest_message(_payload(folder="inbox"), root)
    assert again["status"] == "duplicate"  # the same message pulled by the new bridge is recognised


@pytest.mark.parametrize("folder", ["outbox", "", 5, "../sent"])
def test_an_unknown_folder_value_is_refused(tmp_path, folder):
    with pytest.raises(ingest_server.BadPayload):
        ingest_server.ingest_message(_payload(folder=folder), tmp_path / "inbox")
