"""263 (plan E, F3; the owner's decision of 2026-10-30: every list the one list): a reconciliation statement's invoices
and lines are datasets of the shared data view - searchable, sortable, grouped by their result - read from the statement
as it stands now, an own party's outgoing invoice shown by its buyer. Invented club invoices and one statement line."""

from __future__ import annotations

from jav.app import datasets, registrations
from jav.app.tablequery import Query
from tests.test_guards_167 import _package, db  # noqa: F401 (the fixture)

registrations.load_all()
ALL = Query(limit=1000)


def test_the_statement_s_invoices_and_lines_are_lists_grouped_by_their_result(db) -> None:  # noqa: F811
    pkg = _package(invoices={"CLUB-1": "HUF", "CLUB-2": "HUF"})
    invoices = datasets.query("reconcile_statement_invoices", {"workpackage_id": pkg["wp"]}, ALL)
    assert sorted(r["number"] for r in invoices["rows"]) == ["CLUB-1", "CLUB-2"]
    assert all(r["result"] for r in invoices["rows"])
    # the club's outgoing invoices are shown by their buyer, as the pairing shows them (148)
    assert all(r["buyer"] and r["counterparty"] for r in invoices["rows"])
    cols = {c["key"]: c for c in invoices["columns"]}
    assert cols["result"].get("group") and cols["counterparty"].get("group")
    grouped = datasets.query("reconcile_statement_invoices", {"workpackage_id": pkg["wp"]}, Query(group="result", limit=1000))
    assert sum(g["count"] for g in grouped["groups"]) == 2
    lines = datasets.query("reconcile_statement_lines", {"workpackage_id": pkg["wp"]}, ALL)
    (line,) = lines["rows"]
    assert line["counterparty"] == "Northwind Trading" and line["direction"] == "credit" and line["result"] == "open"
    found = datasets.query("reconcile_statement_lines", {"workpackage_id": pkg["wp"]}, Query(q="Northwind"))
    assert found["matched"] == 1
