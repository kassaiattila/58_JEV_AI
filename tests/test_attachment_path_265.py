"""265 (code review SEC-08): an attachment whose path could not be resolved is a missing attachment.

When the receiver could not map the bridge's path of an attachment, the stored record kept `path: null`, and reading
the message fell back to the file name the sender gave, inside the message's folder: a file of that name there was
taken as the attachment. Now an entry without a path is missing (`path=None`); an old record listing bare names is read
as before. Synthetic message folders; no AI call.
"""

from __future__ import annotations

import json

from jav.domains.email.emails import load_message_dir


def _folder(tmp_path, attachments):
    folder = tmp_path / "msg"
    folder.mkdir()
    (folder / "message.json").write_text(json.dumps({"message_id": "m1", "attachments": attachments}), encoding="utf-8")
    (folder / "invoice.pdf").write_bytes(b"%PDF-1.4 another message's file")
    return folder


def test_an_entry_without_a_path_is_missing(tmp_path) -> None:
    folder = _folder(tmp_path, [{"filename": "invoice.pdf", "path": None}])
    [att] = load_message_dir(folder).attachments
    assert att.filename == "invoice.pdf" and att.path is None


def test_an_old_record_of_bare_names_reads_as_before(tmp_path) -> None:
    folder = _folder(tmp_path, ["invoice.pdf"])
    [att] = load_message_dir(folder).attachments
    assert att.path == str(folder / "invoice.pdf")
