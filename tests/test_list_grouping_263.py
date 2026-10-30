"""263 (plan E, E1; the owner's decision of 2026-10-30: one list everywhere, searchable, sortable and grouped by more
than one thing): a list's rows grouped by a column. The rows of a group stand together in the order the person chose,
the groups in their captions' order with the empty one last, and each group carries how many rows match, not only the
ones on the page."""
import pytest

from jav.app.tablequery import Column, Query, run_query

COLS = [Column("name", "Name"), Column("kind", "Kind", "enum", labels={"a": "Beta", "b": "Alpha"}), Column("n", "N", "number")]
ROWS = [
    {"_key": "1", "name": "x", "kind": "a", "n": 3},
    {"_key": "2", "name": "y", "kind": "b", "n": 4},
    {"_key": "3", "name": "z", "kind": "a", "n": 2},
    {"_key": "4", "name": "w", "kind": None, "n": 1},
    {"_key": "5", "name": "v", "kind": "b", "n": 1},
]


def test_a_groups_rows_stand_together_in_the_chosen_order_and_the_groups_by_their_captions():
    page = run_query(COLS, ROWS, Query(group="kind", sort=[{"col": "n"}]))
    # "Alpha" (b) before "Beta" (a), the empty group last; inside a group by n
    assert [r["_key"] for r in page["rows"]] == ["5", "2", "3", "1", "4"]
    assert page["group"] == "kind"
    assert page["groups"] == [{"value": "b", "count": 2}, {"value": "a", "count": 2}, {"value": None, "count": 1}]


def test_the_groups_count_every_matching_row_not_only_the_page():
    page = run_query(COLS, ROWS, Query(group="kind", limit=2, q="x"))
    assert [r["_key"] for r in page["rows"]] == ["1"]
    assert page["groups"] == [{"value": "a", "count": 1}]
    page = run_query(COLS, ROWS, Query(group="kind", limit=2))
    assert len(page["rows"]) == 2
    assert sum(g["count"] for g in page["groups"]) == 5


def test_without_a_group_the_rows_keep_their_order_and_the_page_is_as_it_was():
    page = run_query(COLS, ROWS, Query(sort=[{"col": "name"}]))
    assert [r["_key"] for r in page["rows"]] == ["5", "4", "1", "2", "3"]
    assert "group" not in page and "groups" not in page


def test_a_group_by_a_column_the_list_does_not_have_is_refused():
    with pytest.raises(ValueError, match="unknown column"):
        run_query(COLS, ROWS, Query(group="colour"))


def test_a_yes_no_column_groups_by_no_then_yes_as_the_interface_reads_them():
    cols = [Column("name", "Name"), Column("manual", "By hand", "bool")]
    rows = [{"_key": "1", "name": "a", "manual": True}, {"_key": "2", "name": "b", "manual": False}]
    page = run_query(cols, rows, Query(group="manual"))
    assert [r["_key"] for r in page["rows"]] == ["2", "1"]
    assert page["groups"] == [{"value": "false", "count": 1}, {"value": "true", "count": 1}]
