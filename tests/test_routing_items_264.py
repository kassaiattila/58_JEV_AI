"""264 (plan E, F6; the owner's decision of 2026-10-31: the small lists the one list too): an email routing's documents to
route are a list of the service - each attachment with its email, what it is (role, party, day), the proposal or what
holds it, and the decision - searchable and grouped by its role, party, problem or decision; the interface draws a row's
proposal and decision from the attachment it carries. Synthetic attachments."""
from __future__ import annotations

from jav.app import datasets
from jav.app.tablequery import Query
from jav.core import display
from jav.domains.email import email_routing


def _item(item_id: str, **over):
    base = {"item_id": item_id, "file": f"{item_id}.pdf", "package": "wp-000000000001", "doc_type": "invoice_hu", "tier": "done",
            "email": {"subject": "About June", "sender": "billing@example.com", "received_at": "2026-06-20T10:00:00", "folder": "inbox"},
            "placement": {"routable": True, "problem": None, "note": None, "role": "incoming_invoices", "role_title": "Incoming invoices",
                          "party": "Example Kft.", "party_id": "p1", "day": "2026-06-08"},
            "proposal": {"target": {"id": "wp-000000000002", "name": "Example Kft. · 2026-06 · Incoming invoices"}, "others": [], "new": None},
            "decision": None, "held": None, "decision_state": 0}
    return base | over


def test_the_documents_to_route_are_a_list_grouped_by_their_decision(monkeypatch):
    items = [_item("doc-1"),
             _item("doc-2", proposal=None, placement=_item("x")["placement"] | {"problem": "unknown_party", "party": None}),
             _item("doc-3", proposal=None, decision={"decision": "accepted", "target": "wp-000000000002", "made": False,
                                                    "target_name": "Example Kft. · 2026-06 · Incoming invoices"}),
             _item("other", placement={"routable": False, "problem": None, "note": None, "role": None, "role_title": None,
                                       "party": None, "party_id": None, "day": None})]
    monkeypatch.setattr(email_routing, "view", lambda wp_id: {"sources": [], "items": items, "counts": {}})
    page = datasets.query("routing_items", {"workpackage_id": "wp-000000000231"}, Query(limit=100))
    cols = {c["key"]: c for c in page["columns"]}
    assert cols["file"]["link"] == "item" and cols["decision"].get("group") and cols["problem"].get("group")
    assert cols["role"]["labels"] == {"incoming_invoices": display.text("Incoming invoices")}  # in the request's language
    rows = {r["_key"]: r for r in page["rows"]}
    assert set(rows) == {"doc-1", "doc-2", "doc-3"}  # an attachment of another kind is not routed
    assert (rows["doc-1"]["decision"], rows["doc-1"]["proposal"]) == ("open", "Example Kft. · 2026-06 · Incoming invoices")
    assert (rows["doc-2"]["problem"], rows["doc-3"]["decision"]) == ("unknown_party", "accepted")
    assert rows["doc-1"]["_wp"] == "wp-000000000001" and rows["doc-1"]["_item"]["item_id"] == "doc-1"
