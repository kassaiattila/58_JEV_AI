"""138 (backlog Q-table-reader-isolation; DECISIONS 138): a tabular statement export is parsed in the isolated reader's
helper process, like a PDF (077).

The local service reads an export a person picks (the survey before a package is made) and the third-party parsers
(openpyxl, defusedxml, the CSV reader) take untrusted input; a hostile or broken workbook must not hang or exhaust the
service. The parsing runs in the helper within its time and memory limits, with every setting as a parameter; a
parser error comes back as the reader's own error with its message, a limit as a named refusal. Generated files only.
"""

from __future__ import annotations

import pytest

from jav import isolated_pdf, statement_table as st
from tests import test_statement_table_136 as t136


def test_the_parsing_runs_in_the_isolated_reader(tmp_path, monkeypatch):
    calls = []
    real = isolated_pdf.run

    def spy(fn, *, kind, **kwargs):
        calls.append((fn.__module__, fn.__name__, kind, sorted(kwargs)))
        return real(fn, kind=kind, **kwargs)

    monkeypatch.setattr(isolated_pdf, "run", spy)
    reading = st.read(t136._workbook(tmp_path))
    assert calls == [("jav.statement_table", "parse_rows", "read", ["data", "limits", "suffix"])]
    assert len(reading.accounts) == 4


def test_a_parser_error_keeps_its_message(tmp_path):
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"PK\x03\x04 not a workbook")
    with pytest.raises(st.StatementTableError, match="^the workbook cannot be read"):
        st.read(broken)


def test_a_reader_over_its_limit_is_a_named_refusal(tmp_path, monkeypatch):
    def over(fn, *, kind, **kwargs):
        raise isolated_pdf.PdfReaderLimit("the PDF reader gave no answer within 120 s", reason="timeout")

    monkeypatch.setattr(isolated_pdf, "run", over)
    with pytest.raises(st.StatementTableError, match="within the reader's limits.*timeout"):
        st.read(t136._workbook(tmp_path))


def test_the_limits_go_to_the_helper_as_parameters(tmp_path, monkeypatch):
    monkeypatch.setitem(st._conf()["limits"], "max_rows", 10)
    with pytest.raises(st.StatementTableError, match="row limit"):
        st.read(t136._workbook(tmp_path))
