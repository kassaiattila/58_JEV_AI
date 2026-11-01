"""272 (K4, the rest of DOM-10): accepting every clear proposal builds the routing's view twice, and whether an
accepted attachment is still held is one query.

265 (DOM-10) read each email once for its attachments. Accepting every clear proposal still built the whole view three
times (to list the proposals, again under the package's lock, and for the answer), and the view asked the store once per
accepted attachment whether its package still holds it. The proposals are now listed under the lock, so the view is
built twice; and the holding is read for every accepted attachment in one query. The answer is the same. Invented
mails and documents; no AI.
"""

from __future__ import annotations

from jav.core import store
from jav.domains.email import email_routing
from tests.test_email_routing_181 import _invoice, _items, _mailbox, _party, _result, _routing, db  # noqa: F401


def _routed(db):  # noqa: F811
    _party()
    wp, ids = _mailbox(db, {"m1": ("invoice.pdf", "inbox"), "m2": ("other.pdf", "inbox")})
    _result(wp, ids["m1"], "invoice_hu", _invoice())
    _result(wp, ids["m2"], "invoice_hu", _invoice(invoice_number="INV-2", fulfillment_date="2026-06-25"))
    return _routing(wp)


def test_accepting_every_clear_proposal_builds_the_view_twice(db, monkeypatch) -> None:  # noqa: F811
    routing = _routed(db)
    built: list[str] = []
    real = email_routing.view
    monkeypatch.setattr(email_routing, "view", lambda wp_id: built.append(wp_id) or real(wp_id))
    answer = email_routing.accept_clear(routing, actor="Example Person")
    assert len(built) == 2
    assert all(i["decision"] and i["decision"]["decision"] == "accepted" for i in _items(answer).values())


def test_the_holding_of_the_accepted_attachments_is_one_query(db, monkeypatch) -> None:  # noqa: F811
    routing = _routed(db)
    email_routing.accept_clear(routing, actor="Example Person")
    seen: list[str] = []
    real = store.connect

    class _Counting:
        def __init__(self, c):
            self.c = c

        def execute(self, sql, *a):
            if sql.lstrip().startswith(("SELECT removed_revision FROM workpackage_items",
                                        "SELECT workpackage_id, item_id, removed_revision FROM workpackage_items")):
                seen.append(sql)
            return self.c.execute(sql, *a)

        def __getattr__(self, name):
            return getattr(self.c, name)

    def counting(*a, **k):
        cm = real(*a, **k)

        class _Ctx:
            def __enter__(self):
                return _Counting(cm.__enter__())

            def __exit__(self, *exc):
                return cm.__exit__(*exc)
        return _Ctx()

    monkeypatch.setattr(email_routing.store, "connect", counting)
    items = _items(email_routing.view(routing))
    assert len(seen) == 1 and all(i["held"] for i in items.values() if i["decision"])
