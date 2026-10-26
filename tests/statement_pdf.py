"""231 (plan stage C, C3g): the synthetic 'PDF' statements of the tests hold their lines as plain text.

The text reader and the ledger reader each call the PDF line reader (`_pdf_lines`, `jav/domains/finance/
statement_common.py`) by the name they imported, so a test replaces it in both (until C3g one module held them all).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from jav.domains.finance import statement_ledger, statement_text


def _text_lines(path: Path) -> list[str]:
    return Path(path).read_text(encoding="utf-8").splitlines()


def pdf_lines_as_text(monkeypatch, read: Callable[[Path], list[str]] = _text_lines) -> None:
    """Every reader takes a 'PDF' file's lines from its plain text."""
    for reader in (statement_text, statement_ledger):
        monkeypatch.setattr(reader, "_pdf_lines", read)
