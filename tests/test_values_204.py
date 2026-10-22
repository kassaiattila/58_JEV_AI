"""204 (R1d): one reader each for the values the store keeps as text: a day, an amount, JSON lines.

Plain-language summary: dates are stored as ISO text and amounts as plain decimal text. Eight modules had their own
copy of the day reader, and three amount readers outside the reconciliation still took "NaN", "Infinity" or an
exponent (the error the 153 review closed in the reconciliation): the utility cost report, the output templates and
the Excel cells. Now they share `jav/values.py`. Synthetic values only.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from jav import report_utility, values
from jav.outputs import fill, xlsx


def test_a_stored_day_is_read_from_a_date_or_a_date_time():
    assert values.stored_day("2026-04-01") == date(2026, 4, 1)
    assert values.stored_day("2026-04-01T10:15:00") == date(2026, 4, 1)
    assert [values.stored_day(v) for v in ("", None, "2026-13-01", "01.04.2026")] == [None] * 4


def test_a_required_day_raises_when_it_is_missing_or_malformed():
    assert values.iso_day("2026-04-01 10:15") == date(2026, 4, 1)
    for bad in (None, "", "2026-02-30"):
        with pytest.raises(ValueError):
            values.iso_day(bad)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-inf", "1E+3", "12,5", "", None, "abc", True, float("nan"),
                                 Decimal("NaN")])
def test_an_amount_that_is_no_plain_decimal_is_none(bad):
    assert values.stored_decimal(bad) is None


def test_a_plain_amount_or_a_finite_number_is_read_exactly():
    assert [values.stored_decimal(v) for v in ("1234.50", "-12.5", "0.00", 7, Decimal("1.50"), 0.25)] == [
        Decimal("1234.50"), Decimal("-12.5"), Decimal("0.00"), Decimal(7), Decimal("1.50"), Decimal("0.25")]


def test_json_lines_skip_blank_lines(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text('{"a": 1}\n\n  \n{"b": "é"}\n', encoding="utf-8")
    assert values.json_lines(path) == [{"a": 1}, {"b": "é"}]


def test_the_utility_report_takes_no_nan_as_an_amount():
    conf = report_utility._conf()
    doc_type = next(iter(conf["utilities"]))
    start_f, end_f = conf["period_fields"]
    amount_f = conf["amount_fields"][0]
    record = {"item_id": "i1", "file": "x.pdf", "doc_type": doc_type,
              "fields": {start_f: "2026-01-01", end_f: "2026-01-31", amount_f: "NaN"}}
    grid = report_utility.build([record])
    assert [u["reason"] for u in grid["unplaced"]] == ["no_amount"]


def test_an_output_cell_shows_no_nan_as_a_number():
    assert fill.as_decimal("NaN") is None and fill._shown("NaN", "money") == "NaN"
    assert xlsx.cell_value("NaN", "money") == "NaN"
    assert xlsx.cell_value("1234.50", "money") == Decimal("1234.50")
