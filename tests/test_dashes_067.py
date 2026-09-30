"""066 Á33: non-ASCII dashes (the U+2010–2012 hyphen variants, U+2212 minus sign, U+FE63, U+FF0D) were not
normalised, so a tax number, bank account or invoice number printed with them did not become a candidate, and a
negative amount was not negative. 067 measurement: in the 284 documents of the local store they occur 0 times inside a
word (the current results do not change); the en dash (13 occurrences inside a word, periods and times too) is
deliberately kept."""

from jav.candidates import find_all
from jav.models import CellLayout, LineLayout
from jav.ocr import parse_tsv
from jav.pdf import normalize_dashes


def _lines(*rows):
    return [LineLayout(no=i, page=1, text=r, cells=[CellLayout(text=c, x0=30 + 200 * k, x1=30 + 200 * k + 6 * len(c))
                                                     for k, c in enumerate(r.split("   "))]) for i, r in enumerate(rows, 1)]


def test_unambiguous_dash_variants_become_a_hyphen_and_length_is_kept():
    for ch in "‐‑‒−﹣－":
        raw = f"12345676{ch}2{ch}41"
        assert normalize_dashes(raw) == "12345676-2-41" and len(normalize_dashes(raw)) == len(raw)
    assert normalize_dashes("2026.01.01–2026.01.31 — x") == "2026.01.01–2026.01.31 — x"


def test_a_tax_id_printed_with_a_non_ascii_hyphen_is_a_candidate():
    text = normalize_dashes("Adószám:   12345676‑2‑41")
    assert "12345676-2-41" in [c.label for c in find_all(_lines(text), "hu")["tax_id"]]


def test_ocr_words_are_normalized_too():
    tsv = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n" \
          "5\t1\t1\t1\t1\t1\t10\t10\t50\t10\t95\t−1 234\n"
    words, _ = parse_tsv(tsv)
    assert words[0]["text"].startswith("-1")
