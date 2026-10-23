"""The email routing after its first real trial (183; DECISIONS 183).

Guarantees tested:
- an attachment that was read but left no data points (a document of an unknown kind goes the facts way) is placed by
  its recognised type: a kind no role takes is only listed, with that type; an invoice or a statement without data, or a
  document whose kind was not recognised, is a blocker of its own (`no_data`); only an attachment no run has read yet is
  "not processed yet" (`no_result`);
- an incoming invoice in a sent email (a forwarded one) is proposed like any incoming invoice, with a note, and is
  among the clear proposals.
Synthetic files and results only; no AI call.
"""

from __future__ import annotations

from jav.domains.email import email_routing
from jav import store

from tests.test_email_routing_181 import _invoice, _items, _mailbox, _party, _result, db  # noqa: F401 (the fixture)


def _read(doc_id: str, doc_type: str | None, *, detail_type: str | None = None) -> None:
    """A document the type recognition has read (as the worker stores it), without data points."""
    store.upsert_document(doc_id=doc_id, source_path=f"{doc_id}.pdf", doc_type=doc_type, type_conf=0.9 if doc_type else 0.0,
                          run_id=f"run-{doc_id[:12]}:{doc_id[:16]}", detail_type=detail_type,
                          detail_method="jev" if detail_type else None)


def test_a_read_attachment_without_data_is_listed_by_its_kind_or_blocked_without_data(db) -> None:  # noqa: F811
    _party()
    wp, ids = _mailbox(db, {"m1": ("letter.pdf", "inbox"), "m2": ("return.pdf", "inbox"), "m3": ("scanned.pdf", "inbox"),
                            "m4": ("blank.pdf", "inbox"), "m5": ("late.pdf", "inbox"), "m6": ("passport.pdf", "inbox")})
    _read(ids["m1"], "other")
    _read(ids["m2"], "tax_return")
    _read(ids["m3"], "invoice_hu")
    _read(ids["m4"], None)
    _read(ids["m6"], "other", detail_type="id_document")
    # m5 has not been read by any run yet
    routing = email_routing.create(name="Routing", sources=[wp], actor="tester")["workpackage_id"]
    view = email_routing.view(routing)
    items = _items(view)
    for listed, kind in (("letter.pdf", "other"), ("return.pdf", "tax_return"), ("passport.pdf", "id_document")):
        assert items[listed]["placement"]["routable"] is False and items[listed]["placement"]["problem"] is None
        assert items[listed]["doc_type"] == kind and items[listed]["proposal"] is None
    assert {f: items[f]["placement"]["problem"] for f in ("scanned.pdf", "blank.pdf", "late.pdf")} == {
        "scanned.pdf": "no_data", "blank.pdf": "no_data", "late.pdf": "no_result"}
    assert items["scanned.pdf"]["doc_type"] == "invoice_hu" and items["late.pdf"]["doc_type"] is None
    assert view["counts"] == {"attachments": 6, "routable": 3, "decided": 0, "blocked": 3, "clear": 0, "accepted": 0}


def test_an_incoming_invoice_in_a_sent_email_is_proposed_with_a_note(db) -> None:  # noqa: F811
    party = _party()
    wp, ids = _mailbox(db, {"m1": ("forwarded.pdf", "sent"), "m2": ("received.pdf", "inbox")})
    _result(wp, ids["m1"], "invoice_hu", _invoice())
    _result(wp, ids["m2"], "invoice_hu", _invoice(invoice_number="INV-2"))
    routing = email_routing.create(name="Routing", sources=[wp], actor="tester")["workpackage_id"]
    items = _items(email_routing.view(routing))
    sent, received = items["forwarded.pdf"], items["received.pdf"]
    assert sent["placement"]["problem"] is None and sent["placement"]["note"] == "sent_incoming"
    assert received["placement"]["note"] is None
    assert sent["proposal"]["new"]["role"] == "incoming_invoices" and sent["proposal"]["new"]["party_id"] == party
    view = email_routing.accept_clear(routing, actor="Example Person")
    items = _items(view)
    assert items["forwarded.pdf"]["decision"]["target"] == items["received.pdf"]["decision"]["target"]
    assert view["counts"]["accepted"] == 2
