"""265 (code review DOM-04): an amount of 27 digits or more on a statement is unreadable, not a server error.

Quantising such an amount to cents raised `InvalidOperation` (the decimal context holds 28 digits), so one damaged
line failed the survey of the whole folder with a 500 error. Now the shared rule (`statement_common._cents`) reads it
as unreadable, and every reader of statement amounts goes through it.
"""

from __future__ import annotations

from decimal import Decimal

from jav.domains.finance import statement_common, statement_ledger, statement_text

HUGE = "1" * 27


def test_a_huge_amount_is_unreadable_in_every_reader() -> None:
    assert statement_common._cents(Decimal(HUGE)) is None
    assert statement_common._money(HUGE) is None
    assert statement_text._comma_amount(HUGE + ",00") is None
    assert statement_ledger._ledger_amount("-" + HUGE, {"amounts": "machine"}) is None


def test_an_ordinary_amount_still_reads() -> None:
    assert statement_common._cents(Decimal("1234.50")) == Decimal("1234.50")
    assert statement_text._comma_amount("1000,000") == Decimal("1000.00")
    assert statement_ledger._ledger_amount("-7291.00", {"amounts": "machine"}) == Decimal("-7291.00")
