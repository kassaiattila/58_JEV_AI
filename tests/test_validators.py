"""Validátorok - offline. A golden elvárt datapoint-ok mind át kell menjenek (ha elérhetők)."""

import json
from datetime import date
from decimal import Decimal

import pytest

from jav.config import GOLDEN_EXPECTED_DIR, GOLDEN_MANIFEST
from jav.models import InvoiceHU, InvoiceLLM, llm_to_invoice
from jav.validators import date_order, hu_tax_id, iban_check, run_all, vat_consistency


def test_vat_consistency_huf_tolerance():
    inv = InvoiceHU(currency="HUF", net_total=Decimal("100000"), vat_total=Decimal("27000"), gross_total=Decimal("127001"))
    assert vat_consistency(inv).code == "totals.ok"
    inv.gross_total = Decimal("127002")
    assert vat_consistency(inv).code == "totals.mismatch"


def test_vat_consistency_eur_tolerance():
    inv = InvoiceHU(currency="EUR", net_total=Decimal("100.00"), vat_total=Decimal("27.00"), gross_total=Decimal("127.02"))
    assert vat_consistency(inv).code == "totals.ok"
    inv.gross_total = Decimal("127.03")
    assert vat_consistency(inv).code == "totals.mismatch"


def test_vat_consistency_missing():
    assert vat_consistency(InvoiceHU(net_total=Decimal("1"))).code == "totals.unparseable"


def test_date_order():
    inv = InvoiceHU(issue_date=date(2022, 2, 10), due_date=date(2022, 2, 18))
    assert date_order(inv).code == "dates.ok"
    inv.due_date = date(2022, 2, 1)
    assert date_order(inv).code == "dates.due_before_issue"
    assert date_order(InvoiceHU(issue_date=date(2022, 2, 10))).code == "dates.unparseable"


@pytest.mark.parametrize(
    "value, code",
    [
        ("12121216-2-42", "taxid.ok"),
        ("24681353-1-43", "taxid.ok"),
        ("12121215-2-42", "taxid.checkdigit"),
        ("12121216-7-42", "taxid.vatcode"),
        ("12121216-2-99", "taxid.county"),
        ("IE8256796U", "taxid.foreign"),
        ("", "taxid.missing"),
    ],
)
def test_hu_tax_id(value, code):
    assert hu_tax_id(value).code == code


@pytest.mark.parametrize(
    "value, code",
    [
        ("HU50100000012000000200000000", "iban.ok"),
        ("HU50 1000 0001 2000 0002 0000 0000", "iban.ok"),
        ("HU50100000012000000200000001", "iban.checksum"),
        ("HU501000000120000002", "iban.hu_length"),
        ("10000001-30000003", "account.hu_domestic"),
        ("10000001-30000003-00000000", "account.hu_domestic"),
        ("1000000130000003", "account.hu_domestic"),
        ("12345", "account.format"),
        ("", "account.missing"),
    ],
)
def test_iban_check(value, code):
    assert iban_check(value).code == code


def _golden_datapoints():
    if not GOLDEN_MANIFEST.exists():
        return []
    manifest = json.loads(GOLDEN_MANIFEST.read_text(encoding="utf-8"))
    out = []
    for case in manifest.get("cases", []):
        if case.get("type_key") != "invoice_hu":
            continue
        name = case["id"].split("/")[1]
        expected = GOLDEN_EXPECTED_DIR / case.get("expected_ref", f"expected/{name}.json")
        if expected.exists():
            out.append((name, json.loads(expected.read_text(encoding="utf-8"))))
    return out


@pytest.mark.parametrize("name, expected", _golden_datapoints(), ids=lambda x: x if isinstance(x, str) else "")
def test_golden_datapoints_pass_core_validators(name, expected):
    dp = {k: v for k, v in expected["datapoints"].items() if k != "line_items"}
    inv, reasons = llm_to_invoice(InvoiceLLM(**dp))
    assert not [r for r in reasons if "unparseable" in r], reasons
    results = {r.name: r for r in run_all(inv)}
    assert results["vat_consistency"].code == "totals.ok", results["vat_consistency"]
    assert results["date_order"].code == "dates.ok", results["date_order"]
    # real_komar szándékosan hibás ellenőrzőszámú (a régi golden is így rögzíti) - ez nem hiba itt
    if name != "real_komar":
        tax = results.get("tax_id:supplier_tax_id")  # 069: tax_id néven
        assert tax is None or tax.ok, tax
