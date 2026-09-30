"""047 T1.0: a csomagformátum tételes listákkal, igen/nem mezővel és felsorolt értékekkel (mesterséges adat)."""

from datetime import date
from decimal import Decimal

from jav.models import record_from_llm

FIELDS = {"account_iban": "iban", "closing_balance": "money", "statement_type": "text", "is_blank_form": "boolean",
          "transactions": "list", "attendees": "list"}
LISTS = {
    "transactions": {"booking_date": "date", "direction": "text", "amount": "money", "description": "text"},
    "attendees": {"*": "name"},
}
ENUMS = {"statement_type": ["monthly", "interim"], "transactions[].direction": ["debit", "credit"]}


def test_list_fields_are_normalized_by_their_item_kinds():
    rec, reasons = record_from_llm({
        "account_iban": "HU42 1177 3016 1111 1018 0000 0000", "closing_balance": "1200.50", "statement_type": "monthly",
        "is_blank_form": "false",
        "transactions": [{"booking_date": "2026.01.05.", "direction": "debit", "amount": "-300.00", "description": " Díj "},
                         {"booking_date": "2026-01-06", "direction": "credit", "amount": "abc", "description": None}],
        "attendees": ["Minta Anna", "  Teszt Elek "],
    }, FIELDS, list_fields=LISTS, enums=ENUMS)
    tx = rec.extra["transactions"]
    assert tx[0] == {"booking_date": date(2026, 1, 5), "direction": "debit", "amount": Decimal("-300.00"), "description": "Díj"}
    assert tx[1]["amount"] is None and "transactions[1].amount:unparseable:'abc'" in reasons
    assert rec.extra["attendees"] == ["Minta Anna", "Teszt Elek"]
    assert rec.extra["is_blank_form"] is False
    dp = rec.to_datapoints(("account_iban", "closing_balance", "statement_type", "is_blank_form", "transactions", "attendees"))
    assert dp["transactions"][0] == {"booking_date": "2026-01-05", "direction": "debit", "amount": "-300", "description": "Díj"}
    assert dp["attendees"] == ["Minta Anna", "Teszt Elek"] and dp["closing_balance"] == "1200.5"


def test_enum_violation_is_a_review_reason_not_an_error():
    rec, reasons = record_from_llm({"statement_type": "yearly", "transactions": [{"direction": "sideways"}]}, FIELDS,
                                   list_fields=LISTS, enums=ENUMS)
    assert rec.extra["statement_type"] == "yearly"
    assert "statement_type:not_in_enum:'yearly'" in reasons
    assert "transactions[0].direction:not_in_enum:'sideways'" in reasons


def test_missing_list_is_empty_and_scalar_fields_unchanged():
    rec, reasons = record_from_llm({"account_iban": None}, FIELDS, list_fields=LISTS, enums=ENUMS)
    assert rec.extra["transactions"] == [] and rec.extra["attendees"] == [] and reasons == []
    assert rec.extra["is_blank_form"] is None
