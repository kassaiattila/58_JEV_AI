"""Validators - offline. Synthetic expected records must pass the core validators, and a record broken in one way must
fail that check; the legacy golden set's expected records are checked the same way only on request."""

import json
import os
from datetime import date
from decimal import Decimal

import pytest

from jav.core.config import GOLDEN_EXPECTED_DIR, GOLDEN_MANIFEST
from jav.models import DocumentRecord, InvoiceLLM, record_from_llm
from jav.typepack import get as get_pack
from jav.validators import date_order, hu_tax_id, iban_check, run_all, vat_consistency


def test_vat_consistency_huf_tolerance():
    inv = DocumentRecord(currency="HUF", net_total=Decimal("100000"), vat_total=Decimal("27000"), gross_total=Decimal("127001"))
    assert vat_consistency(inv).code == "totals.ok"
    inv.gross_total = Decimal("127002")
    assert vat_consistency(inv).code == "totals.mismatch"


def test_vat_consistency_eur_tolerance():
    inv = DocumentRecord(currency="EUR", net_total=Decimal("100.00"), vat_total=Decimal("27.00"), gross_total=Decimal("127.02"))
    assert vat_consistency(inv).code == "totals.ok"
    inv.gross_total = Decimal("127.03")
    assert vat_consistency(inv).code == "totals.mismatch"


def test_vat_consistency_missing():
    assert vat_consistency(DocumentRecord(net_total=Decimal("1"))).code == "totals.unparseable"


def test_date_order():
    inv = DocumentRecord(issue_date=date(2022, 2, 10), due_date=date(2022, 2, 18))
    assert date_order(inv).code == "dates.ok"
    inv.due_date = date(2022, 2, 1)
    assert date_order(inv).code == "dates.due_before_issue"
    assert date_order(DocumentRecord(issue_date=date(2022, 2, 10))).code == "dates.unparseable"


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


# --- expected records through the core validators ----------------------------------------------------------------------
# 167 (review T-6): the expected records are synthetic and in the shape of the golden set's expected files (`datapoints`);
# before, the only such test read the legacy golden set and was silently left out wherever that is absent.

SYNTHETIC_EXPECTED = {
    "huf_full": {"datapoints": {
        "supplier_name": "Example Trading Ltd","supplier_tax_id": "12121216-2-42", "buyer_tax_id": "24681353-1-43",
        "invoice_number": "MK-2026-0042", "issue_date": "2026-03-02", "fulfillment_date": "2026-03-02",
        "due_date": "2026-03-10", "currency": "HUF", "net_total": "100000", "vat_total": "27000", "gross_total": "127000",
        "payment_iban": "HU50 1000 0001 2000 0002 0000 0000", "line_items": [{"description": "Consulting"}]}},
    "huf_printed_forms": {"datapoints": {
        "supplier_tax_id": "12121216-2-42", "issue_date": "2026.03.02.", "due_date": "2026.03.17.", "currency": "HUF",
        "net_total": "20 000", "vat_total": "3 200", "gross_total": "23 200"}},
    "huf_rounded_by_one": {"datapoints": {
        "issue_date": "2026-03-02", "due_date": "2026-03-02", "currency": "HUF", "net_total": "100000",
        "vat_total": "27000", "gross_total": "127001"}},
    "eur_cents": {"datapoints": {
        "issue_date": "2026-01-31", "due_date": "2026-01-31", "currency": "EUR", "net_total": "250.00",
        "vat_total": "67.50", "gross_total": "317.50"}},
}


def _core_results(expected: dict) -> tuple[dict, list[str]]:
    dp = {k: v for k, v in expected["datapoints"].items() if k != "line_items"}
    inv, reasons = record_from_llm(InvoiceLLM(**dp).model_dump(), get_pack("invoice_hu").fields)
    return {r.name: r for r in run_all(inv, get_pack("invoice_hu").validators)}, reasons


def _assert_passes_core_validators(name: str, expected: dict) -> None:
    results, reasons = _core_results(expected)
    assert not [r for r in reasons if "unparseable" in r], reasons
    assert results["vat_consistency"].code == "totals.ok", results["vat_consistency"]
    assert results["date_order"].code == "dates.ok", results["date_order"]
    # real_komar has a deliberately wrong check digit (the legacy golden set records it so too) - not an error here
    if name != "real_komar":
        tax = results.get("tax_id:supplier_tax_id")  # 069: named tax_id:<field>
        assert tax is None or tax.ok, tax


@pytest.mark.parametrize("name", sorted(SYNTHETIC_EXPECTED))
def test_synthetic_expected_records_pass_core_validators(name):
    _assert_passes_core_validators(name, SYNTHETIC_EXPECTED[name])


@pytest.mark.parametrize("change, check, code", [
    ({"gross_total": "127010"}, "vat_consistency", "totals.mismatch"),
    ({"due_date": "2026-03-01"}, "date_order", "dates.due_before_issue"),
    ({"supplier_tax_id": "12121215-2-42"}, "tax_id:supplier_tax_id", "taxid.checkdigit"),
])
def test_a_broken_expected_record_fails_the_check_it_breaks(change, check, code):
    """The positive cases above would also pass a validator that accepts everything."""
    record = {"datapoints": {**SYNTHETIC_EXPECTED["huf_full"]["datapoints"], **change}}
    results, _ = _core_results(record)
    assert results[check].code == code
    assert all(r.ok for name, r in results.items() if name != check and name.split(":")[0] in
               ("vat_consistency", "date_order", "tax_id"))


# The legacy golden set's expected records hold values read from real invoices: they are read only on request
# (`JAV_LEGACY_GOLDEN_TESTS=1`, docs/guides/DEVELOPMENT.md section 6), and a skip names why the check did not run.
LEGACY_GOLDEN_ENV = "JAV_LEGACY_GOLDEN_TESTS"


def _legacy_golden_datapoints():
    if os.environ.get(LEGACY_GOLDEN_ENV) != "1":
        return [pytest.param("-", None, marks=pytest.mark.skip(
            reason=f"legacy golden set not read: it holds values from real invoices; opt in with {LEGACY_GOLDEN_ENV}=1"))]
    if not GOLDEN_MANIFEST.exists():
        return [pytest.param("-", None, marks=pytest.mark.skip(
            reason=f"legacy golden set not found: {GOLDEN_MANIFEST} (JAV_LEGACY_ROOT)"))]
    manifest = json.loads(GOLDEN_MANIFEST.read_text(encoding="utf-8"))
    out = []
    for case in manifest.get("cases", []):
        if case.get("type_key") != "invoice_hu":
            continue
        name = case["id"].split("/")[1]
        expected = GOLDEN_EXPECTED_DIR / case.get("expected_ref", f"expected/{name}.json")
        if expected.exists():
            out.append(pytest.param(name, json.loads(expected.read_text(encoding="utf-8")), id=name))
    return out or [pytest.param("-", None, marks=pytest.mark.skip(
        reason=f"no Hungarian invoice expected record under {GOLDEN_EXPECTED_DIR}"))]


@pytest.mark.parametrize("name, expected", _legacy_golden_datapoints())
def test_legacy_golden_datapoints_pass_core_validators(name, expected):
    _assert_passes_core_validators(name, expected)
