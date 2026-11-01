"""272 (K3, the rest of UI-10): a list request may name the only columns it needs.

The period grid asks every 30 seconds for up to 1 000 cases with every column of the case list, though it shows a
case's party, period, state and steps. A list request now may name its `fields`: the page then carries only those
columns (and the rows' own keys), and the column counts of only those; the filters, the sort, the group and the
counts are the full list's. An unknown name is refused. Synthetic rows, offline.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jav.app.tablequery import Column, Query, Sort, run_query

COLS = [Column("name", "Name"), Column("party", "Party"), Column("note", "Note")]
ROWS = [{"_key": "1", "name": "b", "party": "Alfa", "note": "long text " * 50},
        {"_key": "2", "name": "a", "party": "Beta", "note": "more"}]


def test_a_page_carries_only_the_fields_asked_for() -> None:
    page = run_query(COLS, ROWS, Query(sort=[Sort(col="name")], fields=["party"]))
    assert page["rows"] == [{"_key": "2", "party": "Beta"}, {"_key": "1", "party": "Alfa"}]
    assert [c["key"] for c in page["columns"]] == ["party"] and set(page["facets"]) <= {"party"}
    assert (page["total"], page["matched"]) == (2, 2)


def test_without_fields_the_page_is_as_before() -> None:
    page = run_query(COLS, ROWS, Query())
    assert page["rows"] == ROWS and [c["key"] for c in page["columns"]] == ["name", "party", "note"]


def test_an_unknown_field_is_refused() -> None:
    with pytest.raises(ValueError, match="nothing"):
        run_query(COLS, ROWS, Query(fields=["nothing"]))
    with pytest.raises(ValidationError):
        Query(fields=["x" * 81])
