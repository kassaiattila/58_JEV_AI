"""069 (066 Á05, Á27, decision of 2026-09-29): tax number — a recognised form, otherwise a to-do; the label and the
prefix are stripped.

The survey (the extracted results in the local store, forms only): Hungarian tax number, Hungarian EU VAT number, Irish
(once printed with spaces, "IE 1234567 X"), EU one-stop shop (EU + 9 digits), Swedish, Dutch; the G path gave the form
"HU VAT HU…" four times. Every value is invented; the Hungarian examples have a correct check digit."""

import pytest

from jav import taxid
from jav.models import InvoiceHU, normalize_tax_id
from jav.typepack import get as get_pack
from jav.validators import run_all, tax_id


@pytest.mark.parametrize("value, code", [
    ("12121216-2-42", "taxid.ok"),
    ("12121216242", "taxid.ok"),
    ("12121215-2-42", "taxid.checkdigit"),
    ("HU12121216", "taxid.ok"),  # Hungarian EU VAT number: the same check digit
    ("HU12121215", "taxid.checkdigit"),
    ("IE8256796U", "taxid.foreign"),
    ("EU372000041", "taxid.foreign"),  # EU one-stop-shop registration
    ("SE123456789001", "taxid.foreign"),
    ("NL123456789B01", "taxid.foreign"),
    ("DE123456789", "taxid.foreign"),
    ("ATU12345678", "taxid.foreign"),
    ("CHE123456789", "taxid.foreign"),
    ("GB123456789", "taxid.foreign"),
    ("NO123456789MVA", "taxid.foreign"),
    ("12-3456789", "taxid.foreign"),  # US EIN
    ("+36 1 234 5678", "taxid.unrecognized"),  # phone number
    ("06-30-123-4567", "taxid.unrecognized"),
    ("NO12345678", "taxid.unrecognized"),  # the Norwegian number has 9 digits
    ("DE12345678", "taxid.unrecognized"),
    ("12345", "taxid.unrecognized"),
    ("ABN 12 345 678 901, GST AB123456789", "taxid.unrecognized"),  # two identifiers in one field
    ("", "taxid.missing"),
])
def test_tax_id_check(value, code):
    r = tax_id(value)
    assert r.code == code
    assert r.ok is (code in ("taxid.ok", "taxid.foreign"))


@pytest.mark.parametrize("raw, clean", [
    ("Adószám: 12121216-2-42", "12121216-2-42"),
    ("12121216 2 42", "12121216-2-42"),
    ("HU VAT HU12121216", "HU12121216"),
    ("Közösségi adószám: HU 12121216", "HU12121216"),
    ("VAT ID: IE 8256796 U", "IE8256796U"),
    ("IE 8256796 U", "IE8256796U"),
    ("CHE-123.456.789 MWST", "CHE123456789"),
    ("Tax ID 12-3456789", "12-3456789"),
    ("IE8256796U", "IE8256796U"),
    ("+36 1 234 5678", "+36 1 234 5678"),  # not a tax number: unchanged (the check gives a to-do)
    ("", None),
    (None, None),
])
def test_label_and_prefix_are_stripped(raw, clean):
    assert normalize_tax_id(raw) == clean


def test_foreign_invoice_checks_both_parties():
    inv = InvoiceHU(supplier_tax_id="+36 1 234 5678", buyer_tax_id="HU12121216", invoice_number="X-1")
    results = {r.name: r for r in run_all(inv, get_pack("invoice_foreign").validators)}
    assert results["tax_id:supplier_tax_id"].code == "taxid.unrecognized" and not results["tax_id:supplier_tax_id"].ok
    assert results["tax_id:buyer_tax_id"].ok


def test_hungarian_invoice_checks_the_buyer_too():
    inv = InvoiceHU(supplier_tax_id="12121216-2-42", buyer_tax_id="Adószám: 12345")
    results = {r.name: r for r in run_all(inv, get_pack("invoice_hu").validators)}
    assert results["tax_id:buyer_tax_id"].code == "taxid.unrecognized"


def _tax_labels(*rows: str) -> list[str]:
    from jav.candidates import find_all
    from tests.test_candidates_065 import _lines

    return [c.label for c in find_all(_lines(*rows), "intl")["tax_id"]]


def test_irish_vat_printed_with_spaces_is_one_candidate_with_its_letter():
    # on the real Microsoft invoices "IE 8256796 U"; the candidate finder used to give "IE 8256796" (letter cut off)
    assert _tax_labels("Adószám IE 8256796 U") == ["IE8256796U"]


def test_invoice_no_is_not_a_norwegian_vat_number():
    assert _tax_labels("INVOICE NO 123456789", "Date: Jan 5, 2026") == []
    assert _tax_labels("Org.nr NO 123 456 789 MVA") == ["NO123456789"]  # the Norwegian form with the MVA suffix


def test_german_article_ein_is_not_a_tax_label():
    assert _tax_labels("Dies ist ein Beleg 123456789") == []
    assert _tax_labels("EIN: 12-3456789") == ["12-3456789"]


def test_label_line_token_must_be_in_the_label_cell_or_the_next_one():
    # a number (phone) in a distant cell of the labelled line is not a tax-number candidate
    assert _tax_labels("VAT ID   DE123456789   Phone   0612345678") == ["DE123456789"]
    assert _tax_labels("Tax ID   1234567890") == ["1234567890"]


def test_recognize_reports_the_country():
    assert taxid.recognize("IE 8256796 U").country == "IE"
    assert taxid.recognize("12121216-2-42").country == "HU"
    assert taxid.recognize("+36 1 234 5678") is None
