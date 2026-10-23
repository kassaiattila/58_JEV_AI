"""148 (backlog Q-direction-colonnade, Q-direction-unclear-38; DECISIONS 148): an invoice's direction when a side's
fields contradict each other, or the document type contradicts the parties.

The store showed wrong directions among the invoices an own company had received, all from misread sides: 14 had the
company's name on the supplier side but another company's tax number there, and were counted as the company's outgoing
invoices, so they were left out of the pairing of payments; others had the two tax numbers swapped, or the same number
on both sides. Two insurer's documents typed as outgoing invoices had an own party as the buyer and a supplier no own
party was tied to, and were counted as outgoing too.

Now each side is weighed for a party: its tax number counts two, its name one, for or against (another tax number
counts against a party only when it has one registered; the same number on both sides is a copy and counts for neither
side unless it is the party's). An invoice is outgoing only on consistent evidence: conflicting sides leave it unclear,
which keeps it a payment's candidate; when the same party is on both sides, the invoice is incoming if only the
supplier side has evidence against the party, otherwise unclear (seven received invoices had the company's name and tax
number on the supplier side and its name beside another number on the buyer side: a misread supplier block looks the
same as a misread buyer name, and an own name on the buyer side is evidence enough against outgoing).
The outgoing type decides only when the parties do not say the invoice is incoming.

Synthetic documents and made-up parties only; no AI call.
"""

from __future__ import annotations

import pytest

from jav import parties
from jav.core import store
from jav.domains.finance import reconcile
from tests import test_reconcile_k2_129 as k2

CLUB_TAX = "13570008-1-13"  # samples on the data guard's allow list
OTHER_TAX = "12121216-2-42"


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield


def _parties() -> tuple[str, str]:
    home = parties.create("Example Home", identities=[("name", "jane example", "Jane Example")], actor="t")["id"]
    club = parties.create("Sporting Club", identities=[("tax", parties.tax_key(CLUB_TAX), CLUB_TAX),
                                                       ("name", "sporting club", "Sporting Club")], actor="t")["id"]
    return home, club


def _direction(**values) -> tuple[str, str | None]:
    return parties.direction(parties.resolver(), values.pop("doc_type", "invoice_hu"), values)


def test_a_side_with_evidence_against_the_party_gives_way_to_a_clean_one(db):
    _home, club = _parties()
    # the club's name read as the supplier's, with another company's tax number, and the club as the buyer
    assert _direction(supplier_name="Sporting Club", supplier_tax_id=OTHER_TAX,
                      buyer_name="Sporting Club", buyer_tax_id=CLUB_TAX) == ("incoming", club)
    # the name alone, or with the club's own tax number, still ties the side
    assert _direction(supplier_name="Sporting Club", buyer_name="A Customer Bt.") == ("outgoing", club)
    assert _direction(supplier_name="Sporting Club", supplier_tax_id=CLUB_TAX, buyer_name="A Customer Bt.") == ("outgoing", club)


def test_conflicting_evidence_is_never_outgoing(db):
    _parties()
    # the club's name on the supplier side, another company's tax number there: not the club's outgoing invoice
    assert _direction(supplier_name="Sporting Club", supplier_tax_id=OTHER_TAX, buyer_name="A Customer Bt.") == ("unclear", None)
    # the two tax numbers swapped: each side has evidence for and against the club
    assert _direction(supplier_name="Example Supplier Kft.", supplier_tax_id=CLUB_TAX,
                      buyer_name="Sporting Club", buyer_tax_id=OTHER_TAX) == ("unclear", None)
    # the club on both sides, each side clean: the fields cannot tell which side was misread
    assert _direction(supplier_tax_id=CLUB_TAX, buyer_name="Sporting Club") == ("unclear", None)
    # the club wholly on the supplier side, its name beside another number on the buyer side: never outgoing
    assert _direction(supplier_name="Sporting Club", supplier_tax_id=CLUB_TAX,
                      buyer_name="Sporting Club", buyer_tax_id=OTHER_TAX) == ("unclear", None)


def test_the_same_tax_number_on_both_sides_is_a_copy(db):
    _home, club = _parties()
    # another company's number copied to the buyer side says nothing against the club's name there
    assert _direction(supplier_name="Example Supplier Kft.", supplier_tax_id=OTHER_TAX,
                      buyer_name="Sporting Club", buyer_tax_id=OTHER_TAX) == ("incoming", club)
    # the club's number on both sides: the names tell the sides apart
    assert _direction(supplier_name="Example Supplier Kft.", supplier_tax_id=CLUB_TAX,
                      buyer_name="Sporting Club", buyer_tax_id=CLUB_TAX) == ("incoming", club)
    assert _direction(supplier_tax_id=CLUB_TAX, buyer_tax_id=CLUB_TAX) == ("unclear", None)


def test_a_party_without_a_registered_tax_number_keeps_its_name_match(db):
    home, _club = _parties()
    assert _direction(buyer_name="Jane Example", buyer_tax_id=OTHER_TAX, supplier_name="Example Supplier Kft.") == ("incoming", home)


def test_the_outgoing_type_gives_way_when_the_parties_say_incoming(db):
    home, club = _parties()
    assert _direction(doc_type="invoice_out", supplier_name="Example Insurer Zrt.", buyer_name="Jane Example") == ("incoming", home)
    # the type still decides when the parties do not contradict it
    assert _direction(doc_type="invoice_out", buyer_name="A Customer Bt.") == ("outgoing", None)
    assert _direction(doc_type="invoice_out", supplier_tax_id=CLUB_TAX, buyer_name="Jane Example") == ("outgoing", club)
    assert _direction(doc_type="invoice_out", supplier_name="Example Insurer Zrt.", buyer_name="Jane Example",
                      buyer_tax_id=OTHER_TAX) == ("incoming", home)  # the home has no tax number registered


def test_such_incoming_invoices_are_a_payments_candidates_again(db):
    _parties()
    typed_out = k2._save("typed-out", k2._invoice(number="INS-1", supplier_name="Example Insurer Zrt.",
                                                   buyer_name="Jane Example"), doc_type="invoice_out")
    misread = k2._save("misread", k2._invoice(number="INV-7", amount="70.00", supplier_name="Sporting Club",
                                               supplier_tax_id=OTHER_TAX, buyer_name="Sporting Club", buyer_tax_id=CLUB_TAX))
    k2._save_statement("stmt", k2._line(memo="INS-1"), k2._line(memo="INV-7", amount="70.00"))
    snap = reconcile.snapshot()
    assert {i["id"]: i["direction"] for i in snap["invoices"]} == {typed_out: "incoming", misread: "incoming"}
    result = reconcile.propose(snap)
    assert not [e for e in result["excluded"] if e["kind"] == "invoice"]
    assert {c["invoice_id"] for c in result["candidates"] if c["proposed"]} == {typed_out, misread}


def test_the_engine_version_marks_the_change():
    assert reconcile.ENGINE_VERSION == "1.17.0"  # 154: no rule replacement drops a line; 151: combined fx payments
