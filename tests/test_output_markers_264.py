"""264 (plan E, F6; the owner's decision of 2026-10-31: the small lists the one list too): an output's markers to copy
into an own template are a list of the service - each marker with its label, its kind and the marker of its total -
grouped by the table it belongs to; a table's row count and its months are rows of their own kind in its group."""
from __future__ import annotations

from jav.app import datasets
from jav.app.outputs import samples
from jav.app.tablequery import Query


def test_an_output_s_markers_are_a_list_grouped_by_their_table():
    page = datasets.query("output_markers", {"output": "package_result"}, Query(limit=1000))
    cols = {c["key"]: c for c in page["columns"]}
    assert cols["table"].get("group") and cols["kind"]["labels"]
    rows = page["rows"]
    groups = samples.markers("package_result")
    expected = sum(len(g["rows"]) + (1 if g["count"] else 0) + (2 if g["months"] else 0) for g in groups)
    assert page["total"] == len(rows) == expected
    by_marker = {r["marker"]: r for r in rows}
    values = groups[0]["rows"][0]
    assert by_marker[values["marker"]]["table"] == "values"
    counted = next(g for g in groups if g["count"])
    assert by_marker[counted["count"]]["kind"] == "count"
    summed = next(r for g in groups for r in g["rows"] if r["sum"])
    assert by_marker[summed["marker"]]["sum"] == summed["sum"]
