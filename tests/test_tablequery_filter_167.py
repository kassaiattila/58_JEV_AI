"""167 (review 160 U-2): a typed number in a numeric column's filter is read by the Hungarian habit like any typed
number ("1.000.000" is a million, "1.234,50" is 1234.5); a form that can be read two ways is refused with its own
message instead of silently matching nothing."""

from __future__ import annotations

import pytest

from jav import numbers
from jav.tablequery import Column, Query, select

COLS = [Column("name", "Name"), Column("amount", "Amount", "money"), Column("qty", "Quantity", "number")]
ROWS = [{"_key": "a", "name": "a", "amount": "1000000.00", "qty": "1.5"},
        {"_key": "b", "name": "b", "amount": "1234.50", "qty": "1234"},
        {"_key": "c", "name": "c", "amount": "12.00", "qty": "2"}]


def keys(*filters: dict) -> list[str]:
    return [r["_key"] for r in select(COLS, ROWS, Query.model_validate({"filters": list(filters)}))]


@pytest.mark.parametrize(("typed", "want"), [
    ("1.000.000", ["a"]), ("1 000 000", ["a"]), ("1000000", ["a"]), ("1.234,50", ["b"]), ("1234,5", ["b"]), ("12", ["c"]),
])
def test_a_typed_amount_is_read_by_the_hungarian_habit(typed: str, want: list[str]) -> None:
    assert keys({"col": "amount", "op": "eq", "value": typed}) == want


def test_a_range_on_amounts() -> None:
    assert keys({"col": "amount", "op": "gte", "value": "1.000"}) == ["a", "b"]


def test_a_quantity_keeps_its_decimal_point_reading() -> None:
    assert keys({"col": "qty", "op": "eq", "value": "1,5"}) == ["a"]
    assert keys({"col": "qty", "op": "eq", "value": 2}) == ["c"]


def test_an_ambiguous_amount_is_refused_with_a_message_naming_the_column() -> None:
    with pytest.raises(numbers.AmbiguousNumber) as caught:
        keys({"col": "amount", "op": "eq", "value": "28,000"})
    assert caught.value.params == {"column": "Amount", "value": "28,000"}


def test_text_that_is_not_a_number_is_refused() -> None:
    with pytest.raises(ValueError, match="not a number") as caught:
        keys({"col": "amount", "op": "gte", "value": "sok"})
    assert caught.value.template.startswith("The filter of {{column}} is not a number")


def test_a_text_column_is_unchanged() -> None:
    assert keys({"col": "name", "op": "contains", "value": "b"}) == ["b"]


def test_an_item_whose_to_dos_were_settled_reads_settled() -> None:
    """167 (review 153 E): the run page's result column after a person settled every to-do of an item."""
    from jav.datasets import shown_final

    assert shown_final("needs_review", 0) == "settled"
    assert shown_final("needs_review", 2) == "needs_review"
    assert shown_final("done", 0) == "done"
    assert shown_final(None, 0) is None
