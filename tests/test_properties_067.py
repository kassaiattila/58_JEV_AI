"""067: véletlenszerű (tulajdonság-alapú) bemenetes tesztek a jelöltkeresőre, a pénzösszeg-, dátum- és azonosító-
olvasókra és a PDF-sorépítőre.

A kézzel írt tesztek egy-egy ismert esetet rögzítenek; ezek a tesztek szabályt: „bármilyen bemenetre igaz, hogy…”.
A `hypothesis` könyvtár kitalált bemenetek százait próbálja ki, és hiba esetén a legkisebb ellenpéldát adja. Minden
adat kitalált (generált szám, dátum, azonosító), valódi irat nincs benne.
"""

from __future__ import annotations

import os
import time
from datetime import date
from decimal import Decimal

from hypothesis import HealthCheck, given, settings, strategies as st

from jav.candidates import MAX_QUANTITY_OPTIONS, find_all, profile_of
from jav.models import CellLayout, LineLayout, money_label, normalize_date, normalize_tax_id, parse_money
from jav.pdf import build_layout, fix_lost_glyphs, text_layer_ok
from jav.validators import HU_TAXID_WEIGHTS, hu_tax_id, iban_check

PROFILES = ("hu", "intl", "utility")
# a tesztsorban 150 próba tesztenként; mélyebb kereséshez: JAV_HYPOTHESIS_EXAMPLES=5000 pytest tests/test_properties_067.py
FAST = settings(max_examples=int(os.environ.get("JAV_HYPOTHESIS_EXAMPLES", "150")), deadline=None,
                suppress_health_check=[HealthCheck.too_slow])


def _lines(*rows: str) -> list[LineLayout]:
    out = []
    for no, text in enumerate(rows, 1):
        cells = [CellLayout(text=t, x0=30 + 200 * k, x1=30 + 200 * k + 6 * len(t)) for k, t in enumerate(text.split("   "))]
        out.append(LineLayout(no=no, page=1, text=text, cells=cells))
    return out


# --- generátorok ------------------------------------------------------------------------------------------------------

# számla-szerű ábécé: számjegy, latin és magyar betű, elválasztók, pénznemjel, NUL, NBSP, nem ASCII kötőjelek
_ALPHABET = st.sampled_from(
    list("0123456789") * 4 + list("abcxyzABCHUXáéőűÁŐ") + list(" .,:-/#%$€£+()") + ["\x00", " ", "‐", "−"]
)
_line_text = st.text(alphabet=_ALPHABET, min_size=0, max_size=80)
_words = st.sampled_from([
    "Számla sorszáma:", "Invoice No:", "Order number:", "Total", "Fizetendő", "Nettó", "ÁFA", "Adószám:", "VAT ID:",
    "Kelt:", "Teljesítés:", "IBAN:", "Bankszámlaszám:", "Vevő:", "Eladó:", "Minta Kft.", "EUR", "Ft", "HUF", "db", "kWh",
])
_mixed_line = st.lists(st.one_of(_words, _line_text), min_size=1, max_size=6).map(lambda parts: "   ".join(parts))


@st.composite
def hu_tax_ids(draw) -> str:
    """Érvényes, kitalált magyar adószám: 7 jegy + ellenőrzőszám + áfakód (1–5) + megyekód."""
    base = draw(st.lists(st.integers(0, 9), min_size=7, max_size=7))
    check = (10 - sum(d * w for d, w in zip(base, HU_TAXID_WEIGHTS)) % 10) % 10
    vat = draw(st.integers(1, 5))
    county = draw(st.sampled_from([*range(2, 21), *range(22, 45), 51]))
    return "".join(map(str, base)) + str(check) + str(vat) + f"{county:02d}"


@st.composite
def hu_ibans(draw) -> str:
    """Érvényes, kitalált magyar IBAN (28 karakter, mod-97 ellenőrzőszámmal), szóköz nélkül."""
    bban = "".join(map(str, draw(st.lists(st.integers(0, 9), min_size=24, max_size=24))))
    check = 98 - int(bban + "173000") % 97  # H=17, U=30, „00” a helyén: ISO 13616 mod-97
    return f"HU{check:02d}{bban}"


_amounts = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("99999999.99"), places=2, allow_nan=False)


def _hu_money(d: Decimal) -> str:
    whole, frac = f"{d:.2f}".split(".")
    return f"{int(whole):,}".replace(",", " ") + "," + frac


def _intl_money(d: Decimal) -> str:
    return f"{d:,.2f}"


# --- 1. a jelöltkereső semmilyen szövegen nem hibázik, és a kimenete a szerződés szerinti -----------------------------


@FAST
@given(rows=st.lists(_mixed_line, min_size=1, max_size=12), profile=st.sampled_from(PROFILES))
def test_candidate_finder_is_total_and_well_formed(rows, profile):
    lines = _lines(*rows)
    out = find_all(lines, profile)
    prof = profile_of(profile)
    for kind, cands in out.items():
        labels = [c.label for c in cands]
        assert len(labels) == len(set(labels)), f"{kind}: ismétlődő jelölt"
        for c in cands:
            assert 1 <= c.line_no <= len(lines)
            assert c.label.strip() == c.label and c.label
    assert len(out["money"]) <= prof.max_money_options
    assert len(out["quantity"]) <= MAX_QUANTITY_OPTIONS
    for c in out["money"]:
        assert money_label(Decimal(c.label)) == c.label
        if c.raw != "reverse charge":
            assert c.raw in lines[c.line_no - 1].text


# --- 2. a végösszeg jelölt marad, bármilyen azonosító-, dátum- vagy szövegsor kerül mellé (a 066 Á03 hibaosztálya) ------

_noise = st.lists(st.one_of(
    _words,
    st.from_regex(r"(Számla sorszáma|Invoice No|Order number|Sorszám): [A-Z]{2,4}-\d{3,6}", fullmatch=True),
    st.from_regex(r"(Kelt|Teljesítés|Date): 20\d\d\.(0[1-9]|1[0-2])\.(0[1-9]|1\d|2[0-8])\.", fullmatch=True),
    st.from_regex(r"[A-Za-zÁÉÖőű ]{0,30}", fullmatch=True),
), min_size=0, max_size=6)


@FAST
@given(amount=_amounts, before=_noise, after=_noise)
def test_hu_total_survives_unrelated_lines(amount, before, after):
    total = f"Fizetendő   {_hu_money(amount)} Ft"
    labels = [c.label for c in find_all(_lines(*before, total, *after), "hu")["money"]]
    assert money_label(amount) in labels


@FAST
@given(amount=_amounts, before=_noise, after=_noise)
def test_intl_total_survives_unrelated_lines(amount, before, after):
    total = f"Total   {_intl_money(amount)} EUR"
    labels = [c.label for c in find_all(_lines(*before, total, *after), "intl")["money"]]
    assert money_label(amount) in labels


# --- 3. pénzösszeg-olvasó: a nyomtatott alak visszaadja az értéket ------------------------------------------------------


@FAST
@given(amount=_amounts)
def test_parse_money_reads_hungarian_and_english_formats(amount):
    assert parse_money(_hu_money(amount)).value == amount
    assert parse_money(_hu_money(amount).replace(" ", ".")).value == amount
    assert parse_money(f"{_hu_money(amount)} Ft").value == amount
    assert parse_money(_intl_money(amount), intl=True).value == amount
    assert parse_money(f"${_intl_money(amount)}", intl=True).value == amount
    got = parse_money(f"€{_intl_money(amount)}", intl=True)
    assert got.value == amount and not got.ambiguous


@FAST
@given(raw=st.text(max_size=40))
def test_parse_money_never_raises(raw):
    got = parse_money(raw)
    if got.value is not None:
        assert money_label(got.value)


# --- 4. dátum: a szokásos magyar alakok visszaadják a napot -------------------------------------------------------------


@FAST
@given(d=st.dates(min_value=date(2000, 1, 1), max_value=date(2099, 12, 31)))
def test_normalize_date_reads_hungarian_formats(d):
    assert normalize_date(f"{d.year}.{d.month:02d}.{d.day:02d}.") == d
    assert normalize_date(f"{d.year}-{d.month:02d}-{d.day:02d}") == d
    assert normalize_date(f"{d.year}. {d.month:02d}. {d.day:02d}.") == d
    labels = [c.label for c in find_all(_lines(f"Kelt:   {d.year}.{d.month:02d}.{d.day:02d}."), "hu")["date"]]
    assert labels == [d.isoformat()]


# --- 5. adószám és IBAN: az ellenőrzőszám az érvényeset elfogadja, az egyjegyű hibát elkapja ---------------------------


@FAST
@given(tax=hu_tax_ids())
def test_valid_hu_tax_id_is_accepted_and_found(tax):
    formatted = f"{tax[:8]}-{tax[8]}-{tax[9:]}"
    assert hu_tax_id(tax).code == "taxid.ok"
    assert hu_tax_id(formatted).code == "taxid.ok"
    assert normalize_tax_id(tax) == formatted
    for profile in ("hu", "utility"):
        labels = [c.label for c in find_all(_lines(f"Adószám:   {formatted}"), profile)["tax_id"]]
        assert formatted in labels


@FAST
@given(tax=hu_tax_ids(), pos=st.integers(0, 7), delta=st.integers(1, 9))
def test_single_digit_error_in_hu_tax_id_base_is_caught(tax, pos, delta):
    wrong = tax[:pos] + str((int(tax[pos]) + delta) % 10) + tax[pos + 1:]
    assert hu_tax_id(wrong).code == "taxid.checkdigit"


@FAST
@given(iban=hu_ibans())
def test_valid_hu_iban_is_accepted_and_found(iban):
    grouped = " ".join(iban[i:i + 4] for i in range(0, 28, 4))
    assert iban_check(iban).code == "iban.ok"
    assert iban_check(grouped).code == "iban.ok"
    cands = find_all(_lines(f"IBAN:   {grouped}"), "hu")["iban"]
    assert any("".join(c.label.split()) == iban for c in cands)


@FAST
@given(iban=hu_ibans(), pos=st.integers(4, 27), delta=st.integers(1, 9))
def test_single_digit_error_in_iban_is_caught(iban, pos, delta):
    wrong = iban[:pos] + str((int(iban[pos]) + delta) % 10) + iban[pos + 1:]
    assert iban_check(wrong).code == "iban.checksum"


# --- 6. PDF-sorépítés és szövegjavítás ----------------------------------------------------------------------------------


@FAST
@given(text=st.text(alphabet=st.sampled_from(list("ab1-_ \x00é")), max_size=40))
def test_fix_lost_glyphs_keeps_length_and_is_idempotent(text):
    fixed = fix_lost_glyphs(text)
    assert len(fixed) == len(text)
    assert fix_lost_glyphs(fixed) == fixed


_word_box = st.builds(
    lambda text, x0, w, top: {"text": text, "x0": x0, "x1": x0 + w, "top": top},
    st.text(alphabet=_ALPHABET, min_size=0, max_size=12),
    st.floats(0, 600, allow_nan=False), st.floats(0.1, 120, allow_nan=False), st.floats(0, 800, allow_nan=False),
)


@FAST
@given(pages=st.lists(st.lists(_word_box, max_size=30), min_size=1, max_size=3))
def test_build_layout_keeps_every_word_once(pages):
    layout = build_layout(pages)
    kept = [w for page in pages for w in page if w["text"]]
    assert all("line_no" in w for w in kept)
    assert [ln.no for ln in layout] == list(range(1, len(layout) + 1))
    joined = sorted(t for ln in layout for c in ln.cells for t in c.text.split(" ") if t)
    expected = sorted(t for w in kept for t in w["text"].split(" ") if t)
    assert joined == expected
    text_layer_ok("\n".join(ln.text for ln in layout))


# --- 7. hosszú, ismétlődő sor: a keresés nem lassul el robbanásszerűen ------------------------------------------------


def test_long_repetitive_lines_stay_fast():
    patterns = ["1 ", "1.", "1,", "12.345,", "a-", "HU00 0000 ", "Adószám: 1", "Invoice No: A1 ", "1/", "-1", "\x001"]
    for profile in PROFILES:
        for pat in patterns:
            line = pat * (20000 // len(pat))
            start = time.perf_counter()
            find_all(_lines(line, line), profile)
            assert time.perf_counter() - start < 5.0, (profile, pat)
