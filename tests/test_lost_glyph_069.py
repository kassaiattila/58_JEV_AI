"""069 (066 Á10, decision of 2026-09-29): a lost glyph (NUL) is replaced with a hyphen only in an identifier-shaped
word that contains digits. In the 988 local documents the NUL almost always sat in the middle of an identifier
(163 times between two digits, 61 times between a letter and a digit), 0 times between two letters or between a
currency and an amount. The examples are fictitious; only their shape follows the survey."""

from jav.pdf import fix_lost_glyphs


def test_identifier_shaped_words_keep_the_hyphen():
    assert fix_lost_glyphs("AB12CD34\x000008") == "AB12CD34-0008"  # Stripe-style invoice number
    assert fix_lost_glyphs("MINTAKFT\x000001") == "MINTAKFT-0001"  # all-letter prefix + serial number
    assert fix_lost_glyphs("91000\x004477") == "91000-4477"  # hyphenated postcode
    assert fix_lost_glyphs("123\x00456\x007890") == "123-456-7890"


def test_currency_code_and_amount_are_not_joined_by_a_minus():
    # the space between the currency and the amount was lost: a hyphen would make the amount negative
    assert "-" not in fix_lost_glyphs("USD\x0049.00")
    assert "-" not in fix_lost_glyphs("EUR\x001,250.00")
    assert "-" not in fix_lost_glyphs("HUF\x0012500")


def test_amount_after_the_lost_glyph_is_not_a_negative_number():
    assert "-" not in fix_lost_glyphs("Total\x0049.00")


def test_letters_only_word_gets_no_hyphen():
    # a lost letter pair in a name: a hyphen would be plausible but false
    assert "-" not in fix_lost_glyphs("Mint\x00a")
    assert "-" not in fix_lost_glyphs("Kov\x00cs")


def test_word_boundary_is_still_left_alone():
    assert fix_lost_glyphs("Minta\x00") == "Minta\x00" and fix_lost_glyphs("\x001") == "\x001"
