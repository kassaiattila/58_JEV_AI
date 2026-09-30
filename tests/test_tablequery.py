"""Unified list query (056 U1): search, column filters, Hungarian sorting, paging. Synthetic data."""

import pytest

from jav.tablequery import Column, Query, run_query

COLS = [
    Column("name", "Név"),
    Column("amount", "Összeg", kind="money"),
    Column("status", "Állapot", kind="enum"),
    Column("day", "Nap", kind="date"),
]
ROWS = [
    {"_key": "1", "name": "Őz", "amount": "1200.00", "status": "done", "day": "2026-01-05"},
    {"_key": "2", "name": "alma", "amount": "-5", "status": "needs_review", "day": "2026-02-01"},
    {"_key": "3", "name": "Álom", "amount": None, "status": "done", "day": None},
    {"_key": "4", "name": "számla", "amount": "80", "status": "failed", "day": "2026-01-20"},
    {"_key": "5", "name": "Ózd", "amount": "1 153", "status": "done", "day": "2026-03-01"},
]


def _keys(q: Query) -> list[str]:
    return [r["_key"] for r in run_query(COLS, ROWS, q)["rows"]]


def test_default_query_returns_all_rows_with_counts_and_facets():
    res = run_query(COLS, ROWS, Query())
    assert res["total"] == 5 and res["matched"] == 5 and len(res["rows"]) == 5
    assert res["facets"]["status"] == ["done", "failed", "needs_review"]  # the enum column's values for the filter
    assert [c["key"] for c in res["columns"]] == ["name", "amount", "status", "day"]


def test_search_is_case_and_accent_insensitive():
    assert _keys(Query(q="SZAMLA")) == ["4"]
    assert _keys(Query(q="alom")) == ["3"]


def test_hungarian_sort_orders_accented_letters_after_base_and_nulls_last():
    assert _keys(Query(sort=[{"col": "name"}])) == ["2", "3", "5", "1", "4"]  # alma, Álom, Ózd, Őz, számla
    by_amount = _keys(Query(sort=[{"col": "amount", "desc": True}]))
    assert by_amount == ["1", "5", "4", "2", "3"]  # 1200 > 1153 > 80 > -5, empty last even when descending
    assert _keys(Query(sort=[{"col": "day"}]))[-1] == "3"


def test_multi_level_sort_is_stable():
    assert _keys(Query(sort=[{"col": "status"}, {"col": "amount", "desc": True}])) == ["1", "5", "3", "4", "2"]


def test_column_filters():
    assert _keys(Query(filters=[{"col": "status", "op": "in", "value": ["failed", "needs_review"]}])) == ["2", "4"]
    assert _keys(Query(filters=[{"col": "amount", "op": "gte", "value": "80"}])) == ["1", "4", "5"]
    assert _keys(Query(filters=[{"col": "amount", "op": "lte", "value": "0"}])) == ["2"]
    assert _keys(Query(filters=[{"col": "day", "op": "gte", "value": "2026-01-10"},
                                {"col": "day", "op": "lte", "value": "2026-02-28"}])) == ["2", "4"]
    assert _keys(Query(filters=[{"col": "amount", "op": "empty"}])) == ["3"]
    assert _keys(Query(filters=[{"col": "name", "op": "contains", "value": "oz"}])) == ["1", "5"]
    assert _keys(Query(filters=[{"col": "status", "op": "eq", "value": "done"}])) == ["1", "3", "5"]


def test_paging_reports_matched_count_before_the_page():
    res = run_query(COLS, ROWS, Query(sort=[{"col": "name"}], offset=2, limit=2))
    assert [r["_key"] for r in res["rows"]] == ["5", "1"] and res["matched"] == 5 and res["offset"] == 2


def test_unknown_column_is_a_named_error():
    with pytest.raises(ValueError, match="unknown column"):
        run_query(COLS, ROWS, Query(sort=[{"col": "nope"}]))
    with pytest.raises(ValueError, match="unknown column"):
        run_query(COLS, ROWS, Query(filters=[{"col": "nope", "op": "eq", "value": "x"}]))


def test_selected_keys_limit_the_rows():
    assert _keys(Query(keys=["4", "1"], sort=[{"col": "name"}])) == ["1", "4"]


def test_plain_numbers_in_a_text_column_sort_as_numbers():
    cols = [Column("v", "Érték")]
    rows = [{"_key": k, "v": v} for k, v in [("a", "12583"), ("b", "9908"), ("c", "HUF"), ("d", "2026-05-07"), ("e", "-5")]]
    assert [r["_key"] for r in run_query(cols, rows, Query(sort=[{"col": "v"}]))["rows"]] == ["e", "b", "a", "d", "c"]
