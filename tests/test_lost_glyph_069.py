"""069 (066 Á10, döntés 2026-09-29): az elveszett betűjel (NUL) kötőjel-pótlása csak számot tartalmazó, azonosító-alakú
szóban. A helyi 988 iratban a NUL szinte mindig azonosító közepén állt (két szám között 163-szor, betű és szám között
61-szer), két betű között és pénznem–összeg helyzetben 0-szor. A példák kitaláltak, csak az alakjuk követi a felmérést."""

from jav.pdf import fix_lost_glyphs


def test_identifier_shaped_words_keep_the_hyphen():
    assert fix_lost_glyphs("AB12CD34\x000008") == "AB12CD34-0008"  # Stripe-alakú számlaszám
    assert fix_lost_glyphs("MINTAKFT\x000001") == "MINTAKFT-0001"  # csupa betű előtag + sorszám
    assert fix_lost_glyphs("91000\x004477") == "91000-4477"  # kötőjeles irányítószám
    assert fix_lost_glyphs("123\x00456\x007890") == "123-456-7890"


def test_currency_code_and_amount_are_not_joined_by_a_minus():
    # a pénznem és az összeg közti szóköz veszett el: a kötőjel negatív összeget adna
    assert "-" not in fix_lost_glyphs("USD\x0049.00")
    assert "-" not in fix_lost_glyphs("EUR\x001,250.00")
    assert "-" not in fix_lost_glyphs("HUF\x0012500")


def test_amount_after_the_lost_glyph_is_not_a_negative_number():
    assert "-" not in fix_lost_glyphs("Total\x0049.00")


def test_letters_only_word_gets_no_hyphen():
    # elveszett betűpár a névben: hihető, de hamis kötőjel lenne
    assert "-" not in fix_lost_glyphs("Mint\x00a")
    assert "-" not in fix_lost_glyphs("Kov\x00cs")


def test_word_boundary_is_still_left_alone():
    assert fix_lost_glyphs("Minta\x00") == "Minta\x00" and fix_lost_glyphs("\x001") == "\x001"
