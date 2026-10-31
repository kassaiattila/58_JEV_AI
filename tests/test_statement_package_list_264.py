"""264 (plan E, F6; the owner's decision of 2026-10-31: the small lists the one list too): a bank statements batch's
statements are a list of the service - each with its file (leading to its review), account, period, how it was read
and its state - grouped by their state; a statement booking the same days as another says so, and its page lets a
person choose the valid one. Synthetic statements."""
from __future__ import annotations

from jav.app import datasets
from jav.app.tablequery import Query
from jav.domains.finance import statement_package


def test_a_statement_batch_s_statements_are_a_list_grouped_by_their_state(monkeypatch):
    rows = [{"item_id": "a" * 64, "kind": "document", "file": "export-2026-04.json", "state": "valid", "account": "…0000",
             "currency": "HUF", "period_start": "2026-04-01", "period_end": "2026-04-30", "rank": "code_checked"},
            {"item_id": "b" * 64, "kind": "document", "file": "export-2026-04-b.json", "state": "conflict", "account": "…0000",
             "currency": "HUF", "period_start": "2026-04-01", "period_end": "2026-04-30", "rank": "code_checked"},
            {"item_id": "c" * 64, "kind": "document", "file": "scan.pdf", "state": "pending"}]
    monkeypatch.setattr(statement_package, "package_view", lambda wp_id: {"scope": {}, "statements": rows})
    page = datasets.query("statement_package_statements", {"workpackage_id": "wp-000000000264"}, Query(limit=100))
    cols = {c["key"]: c for c in page["columns"]}
    assert cols["file"]["link"] == "item" and cols["state"].get("group") and cols["state"].get("badge")
    got = {r["file"]: r for r in page["rows"]}
    assert got["export-2026-04-b.json"]["state"] == "conflict" and got["export-2026-04-b.json"]["_wp"] == "wp-000000000264"
    assert got["export-2026-04.json"]["period"] == "2026-04-01 – 2026-04-30" and got["scan.pdf"]["period"] is None
    assert got["export-2026-04.json"]["account"] == "…0000 HUF"
