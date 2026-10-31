"""265 (code review AI-03): a text or table file is checked against the input size limit before it is read, and a
text that is not UTF-8 is a named error.

A `.txt`, `.csv` or table file was read whole before any size check (only a PDF had one), and a Windows-1250 text
failed with a general decoding error. Now the shared limit (`configs/service.json`) applies first
(`DocumentTooLarge`) and a non-UTF-8 text says so (`TextDocumentError`). Synthetic files; no AI call.
"""

from __future__ import annotations

import pytest

from jav.documents import pdf, text_document


def test_a_text_file_over_the_limit_is_refused_before_it_is_read(tmp_path, monkeypatch) -> None:
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * 3_000_000)
    limits = pdf.input_limits()
    monkeypatch.setattr(pdf, "input_limits", lambda: pdf.InputLimits(1, limits.max_document_pages, limits.max_page_megapixels))
    with pytest.raises(pdf.DocumentTooLarge, match="over the 1 MB input limit"):
        text_document.read_file(big)


def test_a_text_that_is_not_utf8_is_a_named_error(tmp_path) -> None:
    latin = tmp_path / "level.txt"
    latin.write_bytes(b"Total: 1500 \xe9\xe1 \xf5")  # accented letters in Windows-1250, not UTF-8
    with pytest.raises(text_document.TextDocumentError, match="not UTF-8"):
        text_document.read_file(latin)
    utf8 = tmp_path / "ok.txt"
    utf8.write_text("Invoice", encoding="utf-8")
    assert text_document.read_file(utf8) == "Invoice"
