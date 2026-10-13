"""153 (review C6): an email's attachment named as a network path is refused before anything resolves it.

The attachment's name from `message.json` was joined to the email's folder and resolved before the check that it stays
inside: a network path made the resolution contact the host (an outgoing SMB connection, which can leak the Windows
sign-in hash). Such a name, and one relative to another drive, is now refused by its text. Synthetic data only.
"""

from pathlib import Path

import pytest

from jav import emails

UNC = "\\\\attacker.example\\share\\invoice.pdf"  # two leading backslashes


@pytest.mark.parametrize("name", [UNC, "//attacker.example/share/invoice.pdf", "Q:invoice.pdf"])
def test_a_network_or_other_drive_relative_attachment_is_refused_unresolved(tmp_path, monkeypatch, name):
    assert name != "Q:invoice.pdf" or not str(tmp_path).upper().startswith("Q:")
    monkeypatch.setattr(Path, "resolve", lambda self, strict=False: pytest.fail(f"{self} was resolved"))
    assert emails._allowed_attachment(tmp_path / name, tmp_path) is False


def test_an_attachment_in_the_emails_folder_is_still_read(tmp_path):
    (tmp_path / "invoice.pdf").write_bytes(b"%PDF-1.4 synthetic")
    assert emails._allowed_attachment(tmp_path / "invoice.pdf", tmp_path) is True
