"""153 (review C1, C3): a crafted bank statement file does not keep the service busy, and an oversized one is refused
before it is read.

The review of 2026-10-13 sent a 20 KB camt.053 file with a 20,000-digit amount and a 40 KB CIB text file with long runs
of spaces to an isolated copy of the service: each kept it busy for 13-18 s (a health check waited as long), because
the statement patterns backtrack and the reading after the isolated helper's parse runs in the service. A 1 GB file was
read whole before its size was checked. Synthetic inputs only; time bounds are generous (the unbounded patterns took
seconds on far smaller inputs).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from jav import statement_table as st

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {p["name"]: p for p in
            json.loads((ROOT / "configs" / "statement_tables.json").read_text(encoding="utf-8"))["profiles"]}


def _fast(fn, limit: float = 1.0):
    started = time.perf_counter()
    out = fn()
    assert time.perf_counter() - started < limit
    return out


def test_an_endless_xml_amount_is_refused_at_once():
    assert _fast(lambda: st._xml_amount("1" * 20_000 + "x")) is None
    assert _fast(lambda: st._xml_amount("1" * 20_000)) is None  # longer than any amount
    assert [st._xml_amount(v) for v in ("7291.00", ".00", "-12.5", "12.")] == [st.Decimal("7291.00"), st.Decimal("0.00"),
                                                                                st.Decimal("-12.50"), None]


def test_the_erste_rate_pattern_reads_a_rate_and_not_an_endless_number():
    rate = re.compile(PROFILES["camt053"]["banks"]["GIBAHUHB"]["details"]["rate"])
    assert _fast(lambda: rate.search("1" * 20_000 + "x")) is None
    assert rate.search("Tr.összeg - árfolyam: 20.00 USD 365.12 HUF/USD")["rate"] == "365.12 HUF/USD"


def test_long_lines_and_space_runs_are_bounded_before_the_patterns():
    lines, repairs = st._bounded(["2026.05.10. TRANSFER" + " " * 30_000 + "1.000,00   5.000,00", "x" * (st.LINE_MAX + 1), "ok"])
    assert lines == ["2026.05.10. TRANSFER  1.000,00  5.000,00", "ok"]
    assert repairs == [f"1 line(s) over {st.LINE_MAX} characters left out"]


def test_a_text_statement_full_of_space_runs_is_read_in_bounded_time():
    profile = PROFILES["cib_text_hu"]
    crafted = ["2026.05.10. " + "A " * 900 + " " * 40 + "x"] * 2_000  # each line a near miss of the line pattern
    lines, _ = st._bounded(crafted)
    line_re = re.compile(profile["line"])
    _fast(lambda: [line_re.match(ln) for ln in lines], limit=5.0)


def test_an_oversized_file_is_refused_before_it_is_read(tmp_path, monkeypatch):
    big = tmp_path / "statement.xlsx"
    with big.open("wb") as f:
        f.truncate(st._conf()["limits"]["max_bytes"] + 1)  # a sparse file: nothing to write
    monkeypatch.setattr(Path, "read_bytes", lambda self: pytest.fail("the file was read before its size was checked"))
    with pytest.raises(st.StatementTableError, match="size limit"):
        st._read_file(big)
    text = tmp_path / "statement.txt"
    with text.open("wb") as f:
        f.truncate(st._conf()["limits"]["max_bytes"] + 1)
    with pytest.raises(st.StatementTableError, match="size limit"):
        st._read_file(text)


def test_a_csv_of_empty_cells_stops_at_the_cell_limit():
    limits = {**st._conf()["limits"], "max_cells": 1_000}
    with pytest.raises(st.StatementTableError, match="cell limit"):
        st._csv_rows(b"," * 5_000, limits)
    assert st._csv_rows(b"a;b\n1;2\n", limits) == [["a", "b"], ["1", "2"]]
