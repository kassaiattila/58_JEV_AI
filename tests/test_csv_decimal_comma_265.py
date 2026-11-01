"""265 (code review APPW-14): a list's CSV for the Hungarian interface writes its number and amount columns with a
decimal comma.

The file is made for Hungarian Excel (`;` separator, BOM), which reads "1234.5" as text, so a sum could not be added
up. In the Hungarian interface a number or amount column's plain decimals now have a comma; a text column, a whole
number and the English interface's file are unchanged. Synthetic rows, offline.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal

import pytest

from jav.app import datasets, export
from jav.app.tablequery import Column, Query
from jav.core import display, store

COLS = [Column("name", "Name"), Column("amount", "Amount", "money"), Column("count", "Count", "number")]
ROWS = [{"name": "Invoice 1.5", "amount": "1234.50", "count": 3}, {"name": "x", "amount": Decimal("-7.25"), "count": 2.5},
        {"name": "y", "amount": None, "count": "12"}]


def test_only_the_numeric_columns_plain_decimals_get_a_comma() -> None:
    rows = [[r["name"], r["amount"], r["count"]] for r in ROWS]
    assert export.decimal_commas([False, True, True], rows) == [
        ["Invoice 1.5", "1234,50", 3], ["x", "-7,25", "2,5"], ["y", None, "12"]]
    assert export.decimal_commas([True], [[True], ["1e-05"], ["12.3.4"]]) == [[True], ["1e-05"], ["12.3.4"]]


@pytest.mark.parametrize(("language", "amounts"), [("hu", ["1234,50", "-7,25", ""]), ("en", ["1234.50", "-7.25", ""])])
def test_the_list_download_follows_the_interface_language(tmp_path, monkeypatch, language, amounts) -> None:
    monkeypatch.setattr(datasets, "export_rows", lambda *a, **k: (COLS, ROWS))
    with store.use_store(tmp_path / "c.sqlite"), display.use(language):
        data, _media, _name, count = datasets.export_file("workpackages", {}, Query(), "all", "csv")
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig")), delimiter=";"))
    assert count == 3 and [r[1] for r in rows[1:]] == amounts and rows[1][0] == "Invoice 1.5"
