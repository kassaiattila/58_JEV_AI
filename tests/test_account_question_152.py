"""152: the S path's account question asks for the account, never for one of its printed forms.

The candidate finder offers an account once, in the form it saw first, even when the document prints it both as an IBAN
and as a domestic account number. The outgoing invoice's question still said "if the same account is printed both as an
IBAN and as a domestic account number, choose the IBAN", so on every real outgoing invoice that printed both forms the
JEV split between the only option (the domestic form) and "none": 31 of the 43 invoices of the S-path measurement of
2026-10-12 got a low-confidence to-do, and none of the 12 that print no IBAN did. Synthetic data only, no model calls.
"""

import re

import pytest

from jav import cfg
from jav.candidates import find_all
from tests.test_candidates import _two_column_invoice

SELECT_SITES = ("select", "select_foreign", "select_invoice_out", "select_utility")
FORM_PREFERENCE = re.compile(r"(?i)\bchoose the (?:IBAN|domestic)\b")


def test_the_finder_offers_an_account_printed_in_two_forms_once():
    assert len(find_all(_two_column_invoice())["iban"]) == 1  # printed as an IBAN and as a domestic number


@pytest.mark.parametrize("site", SELECT_SITES)
def test_no_account_question_asks_for_a_form_the_options_may_not_carry(site):
    question = cfg.load(f"callsite:{site}")["instructions"].get("payment_iban", "")
    assert not FORM_PREFERENCE.search(question), site


def test_the_outgoing_question_names_the_two_forms_as_one_account():
    question = cfg.load("callsite:select_invoice_out")["instructions"]["payment_iban"]
    assert "one account" in question and "listed once" in question
