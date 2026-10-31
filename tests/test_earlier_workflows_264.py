"""264 (plan E, F6; the owner's decision of 2026-10-31: the small lists the one list too): the earlier workflows are a list
of the service - each with its template, party, period, how many of its steps are done, its next step and its state -
each opening its own page; the archived ones are among them (grouped or filtered by their state instead of a checkbox).
Synthetic data, temporary store, no paid calls."""
from __future__ import annotations

from jav.app import datasets, parties, workflows as wf
from jav.app.tablequery import Query
from tests.test_workflow_references_153 import _make, db  # noqa: F401 - the fixture is used by name


def test_the_earlier_workflows_are_a_list_each_opening_its_page(db):  # noqa: F811
    party = parties.create("Example C Kft.", identities=[], actor="t")["id"]
    made = _make(db, party, advance_now=False)["workflow"]
    wf.update(made["id"], archived=True, actor="t")
    page = datasets.query("earlier_workflows", {}, Query(limit=100))
    cols = {c["key"]: c for c in page["columns"]}
    assert cols["name"]["link"] == "workflow"
    assert cols["status"].get("group") and cols["template"].get("group") and cols["next_status"].get("group")
    [row] = page["rows"]
    assert row["_key"] == made["id"] and row["status"] == "archived" and row["party"] == "Example C Kft."
    assert row["total"] == len(row["_steps"]) and all({"title", "status"} <= set(s) for s in row["_steps"])
