"""Normalisers - offline, no API."""

from datetime import date
from decimal import Decimal

import pytest

from jav.models import (
    InvoiceLLM,
    llm_to_invoice,
    money_label,
    normalize_date,
    normalize_tax_id,
    parse_money,
)


@pytest.mark.parametrize(
    "raw, expected, ambiguous",
    [
        ("1 234 567", Decimal("1234567"), False),
        ("1.234.567", Decimal("1234567"), False),
        ("12.345", Decimal("12345"), False),  # HU thousands dot
        ("20 619,05", Decimal("20619.05"), False),
        ("12.345,67", Decimal("12345.67"), False),
        ("12,345.67", Decimal("12345.67"), False),  # English style
        ("12.34", Decimal("12.34"), True),  # undecidable
        ("127000", Decimal("127000"), False),
        ("127 000 Ft", Decimal("127000"), False),
        ("12 000,-", Decimal("12000"), False),
        ("0", Decimal("0"), False),
        ("-19 556", Decimal("-19556"), False),
        ("1234.56", Decimal("1234.56"), True),  # the LLM output format (decimal point) is also flagged ambiguous
        ("", None, False),
        ("n/a", None, False),
    ],
)
def test_parse_money(raw, expected, ambiguous):
    parsed = parse_money(raw)
    assert parsed.value == expected
    assert parsed.ambiguous is ambiguous


def test_money_label_canonical():
    assert money_label(Decimal("127000.00")) == "127000"
    assert money_label(Decimal("20619.050")) == "20619.05"
    assert money_label(Decimal("0")) == "0"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2022.02.10.", date(2022, 2, 10)),
        ("2022. 02. 10.", date(2022, 2, 10)),
        ("2022-02-10", date(2022, 2, 10)),
        ("2022/02/10", date(2022, 2, 10)),
        ("2022. február 10.", date(2022, 2, 10)),
        ("2022. febr. 10.", date(2022, 2, 10)),
        ("2021. március 19.", date(2021, 3, 19)),
        ("Kelt: 2022.02.10", date(2022, 2, 10)),
        ("2022.02.30.", None),  # non-existent day: no guessing
        ("22.02.10", None),  # two-digit year: deliberately not
        ("INF-2022-3", None),  # invoice number, not a date (only two components)
        (None, None),
    ],
)
def test_normalize_date(raw, expected):
    assert normalize_date(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("12121216-2-42", "12121216-2-42"),
        ("12121216242", "12121216-2-42"),
        ("12121216 2 42", "12121216-2-42"),
        ("HU12121216", "HU12121216"),  # EU form: as printed
        ("IE8256796U", "IE8256796U"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_tax_id(raw, expected):
    assert normalize_tax_id(raw) == expected


def test_llm_to_invoice_collects_reasons_instead_of_raising():
    llm = InvoiceLLM(
        supplier_name="  Szintetikus   Szállító Kft. ",
        supplier_tax_id="12121216242",
        issue_date="2026-01-05",
        due_date="nincs",
        currency="huf",
        net_total="100000",
        vat_total="27000",
        gross_total="abc",
    )
    inv, reasons = llm_to_invoice(llm)
    assert inv.supplier_name == "Szintetikus Szállító Kft."
    assert inv.supplier_tax_id == "12121216-2-42"
    assert inv.issue_date == date(2026, 1, 5)
    assert inv.due_date is None
    assert inv.currency == "HUF"
    assert inv.gross_total is None
    assert "due_date:unparseable:'nincs'" in reasons
    assert "gross_total:unparseable:'abc'" in reasons
