"""167 (review S-3): a card number written with hyphens or dots, or a 15-digit American Express number, is masked and
stopped by the data guard too.

Only sixteen digits in one run or in four groups separated by spaces were recognised, so a hyphenated number (the
form GPT often returns), a dotted form and a 15-digit American Express number passed both the masking on save and
the data guard. Masking and the guard now share one pattern (`card_numbers.CARD`); the Luhn check digit and the
scheme's first digits still decide. Synthetic values: the schemes' published test numbers, built at run time so that
this file holds none.
"""

import re

import pytest

from jav.devtools import data_guard
from jav.core import card_numbers, cfg

MC = ["5555", "5555", "5555", "4444"]  # Mastercard's published test number
AMEX = ["3782", "822463", "10005"]  # American Express's published test number
VISA = ["4111", "1111", "1111", "1111"]  # on the data guard's allow list


def _guard() -> data_guard.Guard:
    return data_guard.Guard(data_guard.load_config(), env_secrets={})


@pytest.mark.parametrize("sep", ["", " ", "-", "."])
def test_a_sixteen_digit_number_is_masked_with_any_separator(sep):
    card = sep.join(MC)
    assert card_numbers.mask_text(f"paid with {card} at the shop") == "paid with 555555xxxxxx4444 at the shop"
    assert card_numbers.masked(card) == "555555xxxxxx4444"


@pytest.mark.parametrize("sep", ["", " ", "-", "."])
def test_an_american_express_number_is_masked(sep):
    card = sep.join(AMEX)
    assert card_numbers.mask_text(f"card {card};") == "card 378282xxxxx0005;"
    assert card_numbers.masked(card) == "378282xxxxx0005"
    assert card_numbers.masked("378282xxxxx0005") == "378282xxxxx0005"


def test_gpt_output_with_hyphens_is_masked_on_save():
    data = {"transactions": [{"memo": f"card {'-'.join(MC)}", "card_number": "-".join(MC)}]}
    assert card_numbers.mask_values(data) == {"transactions": [{"memo": "card 555555xxxxxx4444",
                                                                "card_number": "555555xxxxxx4444"}]}


@pytest.mark.parametrize("text", [
    "ref " + "-".join(["1234", "5678", "9012", "3456"]),  # no right check digit
    "ref " + "".join(AMEX)[:-1] + "1",  # an American Express shape with a wrong check digit
    "ref 123456789012347",  # fifteen digits with a right check digit, but no American Express prefix
    "ref " + "".join(MC) + "000",  # nineteen digits: not recognised (a question for the owner)
    "ref 12-" + "-".join(MC),  # four groups inside a longer hyphenated number
    "ref 1." + ".".join(MC),  # four groups inside a longer dotted number
    "ref " + "5555 5555-5555.4444",  # mixed separators
    "HU42 1177 3016 1111 1018 0000 0000",  # an IBAN printed in groups
])
def test_other_numbers_are_left_alone(text):
    assert card_numbers.mask_text(text) == text


def test_the_cib_detail_row_is_still_masked():
    row = f"{' '.join(MC)} 20260105 101500; SHOP"
    assert card_numbers.mask_text(row) == "555555xxxxxx4444 20260105 101500; SHOP"


@pytest.mark.parametrize("card", ["-".join(MC), ".".join(MC), " ".join(MC), "".join(AMEX), " ".join(AMEX), "-".join(AMEX)])
def test_the_data_guard_stops_every_form(card):
    found = _guard().scan_line("tests/example.py", 1, f'memo = "card {card}"')
    assert [f.kind for f in found] == ["card_number"]


def test_the_data_guard_still_allows_the_visa_test_number_and_masked_numbers():
    guard = _guard()
    for text in ("-".join(VISA), ".".join(VISA), " ".join(VISA), "555555xxxxxx4444", "378282xxxxx0005"):
        assert not guard.scan_line("tests/example.py", 1, f"card {text}"), text


def test_masking_and_the_guard_share_one_pattern():
    assert "card_number" not in cfg.load("data_guard")["patterns"]
    assert _guard().patterns["card_number"] is card_numbers.CARD
    assert isinstance(card_numbers.CARD, re.Pattern)
