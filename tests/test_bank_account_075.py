"""075 (repeated security audit, F01): a Hungarian bank account number must pass its two check digits.

The giro rule of the Hungarian central bank: the first 8 digits and the remaining 8 or 16 digits each carry a check
digit; with the weights 9-7-3-1 repeating, the weighted sum of each part is divisible by 10. Before 075 every 16- or
24-digit number passed as a domestic account. The data guard uses the same function. Synthetic numbers only.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from jav import data_guard, validators
from jav.models import InvoiceHU
from tests.test_properties_067 import hu_account

GOOD_16 = "1000000130000003"
GOOD_24 = "100000013000000300000000"


def _iban(country: str, bban: str) -> str:
    """An IBAN whose mod-97 check digits are right for any BBAN (so for HU only the giro digits can fail); computed
    here, so that no real-looking IBAN is written into the repository (data guard)."""
    expanded = "".join(str(ord(c) - 55) if c.isalpha() else c for c in bban + country + "00")
    return f"{country}{98 - int(expanded) % 97:02d}{bban}"


@pytest.mark.parametrize("digits", [GOOD_16, GOOD_24, "10000001-30000003", "10000001-30000003-00000000"])
def test_valid_domestic_accounts_pass(digits):
    result = validators.iban_check(digits)
    assert result.ok and result.code == "account.hu_domestic"


@pytest.mark.parametrize("digits", [
    "1234567812345678",          # the audit's example: the first group is wrong
    "123456781234567812345678",  # the same, 24 digits
    "1000000130000004",          # only the second group is wrong
    "100000013000000300000001",  # the second group of a 24-digit account is wrong
])
def test_wrong_check_digit_fails(digits):
    result = validators.iban_check(digits)
    assert not result.ok and result.code == "account.hu_checksum"


def test_hu_iban_with_a_wrong_inner_account_fails():
    good, bad = _iban("HU", GOOD_24), _iban("HU", "123456781234567812345678")
    assert validators.iban_check(good).code == "iban.ok"
    result = validators.iban_check(bad)
    assert not result.ok and result.code == "iban.hu_account_checksum"


def test_foreign_iban_is_unchanged():
    assert validators.iban_check(_iban("DE", "0" * 18)).code == "iban.ok"


def test_the_data_guard_uses_the_same_rule():
    assert data_guard._real_account(GOOD_16) and data_guard._real_account("10000001-30000003-00000000")
    assert not data_guard._real_account("1234567812345678")
    assert not data_guard._real_iban(_iban("HU", "123456781234567812345678"))
    assert validators.hu_account_check_digits_ok(GOOD_24)
    assert not validators.hu_account_check_digits_ok("12345")


def test_a_wrong_account_on_an_invoice_is_a_failed_check():
    inv = InvoiceHU(payment_iban="1234567812345678")
    results = validators.run_checks(inv, [{"check": "iban_check", "field": "payment_iban", "optional": True}])
    assert [(r.ok, r.code) for r in results] == [(False, "account.hu_checksum")]


@given(digits=st.lists(st.integers(0, 9), min_size=22, max_size=22), pos=st.integers(0, 23), delta=st.integers(1, 9),
       short=st.booleans())
def test_any_single_digit_error_is_caught(digits, pos, delta, short):
    """The weights 9, 7, 3 and 1 are all coprime with 10, so every single-digit error changes the sum's last digit."""
    account = hu_account(digits[:14] if short else digits)  # 14 free digits: a 16-digit account (8 + 8)
    pos %= len(account)
    assert validators.iban_check(account).code == "account.hu_domestic"
    wrong = account[:pos] + str((int(account[pos]) + delta) % 10) + account[pos + 1:]
    assert validators.iban_check(wrong).code == "account.hu_checksum"
