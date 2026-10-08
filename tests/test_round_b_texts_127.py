"""127 (5th group, round B): the JEV question texts of the buyer, the credit note, the receipt identifier and the pro
forma, and the invariant that keeps GPT's saved answers valid: the first clause of a type description (the only part
GPT is shown) does not change.

Offline: the texts are read from the JSON; no model is called.
"""

from jav import cfg, detect_gpt
from jav.doc_types import DOC_TYPES

BY_KEY = {t.key: t for t in DOC_TYPES}


def test_the_invoice_number_is_the_credit_notes_own_number():
    hu = cfg.load("callsite:select")
    for text in (hu["instructions"]["invoice_number"], hu["presence_what"]["invoice_number"],
                 cfg.load("callsite:verify")["field_specs"]["invoice_number"]):
        assert "credit note" in text and "original invoice" in text
    assert "jóváíró" in hu["glossary"]
    foreign = cfg.load("callsite:select_foreign")
    for text in (foreign["instructions"]["invoice_number"], foreign["presence_what"]["invoice_number"],
                 cfg.load("callsite:verify_foreign")["field_specs"]["invoice_number"]):
        assert "credit" in text.lower() and "original invoice" in text


def test_a_receipts_own_identifier_in_the_decided_order_and_never_the_order_number():
    """The owner's decision of 2026-10-07: receipt number > transaction id; the order number stays out."""
    foreign = cfg.load("callsite:select_foreign")
    for text in (foreign["instructions"]["invoice_number"], foreign["presence_what"]["invoice_number"],
                 cfg.load("callsite:verify_foreign")["field_specs"]["invoice_number"]):
        low = text.lower()
        assert low.index("receipt number") < low.index("transaction")
        assert "never" in low and "order number" in low


def test_the_buyer_can_be_a_private_person_and_its_name_stops_before_the_address():
    hu = cfg.load("callsite:select")["instructions"]["buyer_name"]
    assert "private individual" in hu and "address glued on" in hu
    foreign = cfg.load("callsite:select_foreign")["instructions"]["buyer_name"]
    assert "private person" in foreign and "not 'none'" in foreign
    assert "contains the company" in foreign and "without the city" in foreign


def test_the_gpt_visible_first_clauses_of_the_invoice_and_the_pro_forma_are_unchanged():
    assert detect_gpt.short_description(BY_KEY["invoice_hu"].what) == (
        "Supplier invoice (számla) ISSUED BY A HUNGARIAN business or private entrepreneur")
    assert detect_gpt.short_description(BY_KEY["proforma_invoice"].what) == (
        "Pro forma invoice or payment request (díjbekérő, proforma számla, előlegbekérő) that asks for payment BEFORE the "
        "invoice is issued")


def test_the_pro_forma_is_told_apart_by_its_own_title_and_an_advance_invoice_stays_an_invoice():
    pro, inv = BY_KEY["proforma_invoice"], BY_KEY["invoice_hu"]
    assert "own title" in pro.what and "DÍJBEKÉRŐ" in pro.what
    assert "előlegszámla" in pro.not_for and "invoice_hu" in pro.not_for
    assert "előlegszámla" in inv.what
    assert "proforma_invoice" in inv.not_for and "DÍJBEKÉRŐ" in inv.not_for
