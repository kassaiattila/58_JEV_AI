"""156: a 16-digit Hungarian account number and its 24-digit / IBAN forms are one bank-account candidate.

A 16-digit domestic number is the 24-digit number with eight trailing zeros, and a Hungarian IBAN is the 24-digit
number behind the country code and two check digits. The candidate finder used to merge forms on their last 16
digits, so the short form and the long forms of one account became two candidates and split the probability.

The numbers are invented with wrong check digits (the finder does not check them, and they cannot be real accounts).
"""

from jav.ai.candidates import INTL, find_all
from jav.ai.models import CellLayout, LineLayout, account_key

SHORT = "12345678-87654321"
LONG = "12345678-87654321-00000000"
IBAN = "HU00 1234 5678 8765 4321 0000 0000"
OTHER = "12345678-87654321-55555555"  # the same first 16 digits with a non-zero tail: another account


def _line(no: int, *cells: tuple[str, float]) -> LineLayout:
    return LineLayout(no=no, page=1, text="   ".join(t for t, _ in cells),
                      cells=[CellLayout(text=t, x0=x, x1=x + 6 * len(t)) for t, x in cells])


def _ibans(*texts: str) -> list[str]:
    lines = [_line(i + 1, (t, 30)) for i, t in enumerate(texts)]
    return [c.label for c in find_all(lines)["iban"]]


def test_short_domestic_number_and_its_iban_are_one_candidate():
    assert _ibans(f"Account number: {SHORT}", f"IBAN: {IBAN}") == [SHORT]  # the form seen first is the label


def test_short_and_long_domestic_numbers_are_one_candidate():
    assert _ibans(f"Account: {LONG}", f"Bank account: {SHORT}") == [LONG]


def test_a_number_split_across_cells_still_joins_its_full_form():
    # the reader puts a 24-digit number printed with a wide gap into two cells; its tail looks like a 16-digit number
    head, tail = OTHER.split("-", 1)
    lines = [_line(1, (f"Account: {OTHER}", 30)), _line(2, (head, 30), (tail, 120))]
    assert [c.label for c in find_all(lines)["iban"]] == [OTHER]


def test_a_short_number_with_a_non_zero_tail_is_another_account():
    assert len(_ibans(f"Account: {OTHER}", f"Bank account: {SHORT}")) == 2


def test_foreign_iban_forms_are_still_merged():
    lines = [_line(1, ("IBAN: DE00 3704 0044 0532 0130 00", 30)), _line(2, ("DE00370400440532013000", 30))]
    assert len(find_all(lines, INTL)["iban"]) == 1


def test_account_key_is_the_24_digit_domestic_number():
    assert account_key(IBAN) == account_key(SHORT) == account_key(LONG) == "123456788765432100000000"
    assert account_key("1234 **** 5678") == ""
