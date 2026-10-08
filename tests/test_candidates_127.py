"""127 (5th group, round B): candidate-finder gaps behind the buyer, credit-note and receipt to-dos of the 68-invoice
sample, as general rules on synthetic lines.

- A party name that already ends in its legal form is complete: the address below it, or glued after it in the same
  cell, is not part of the name (the buyer to-dos were mostly "<Name> Kft." against "<Name> Kft. <street> 82. 1141").
- "részvénytársaság" is a legal form on Hungarian invoices too, so a two-line company name is joined.
- A party label is a whole word ("Vevőkód" is not "Vevő" + "kód"); "vásárló" and "ügyfél" are party labels.
- A greeting is not part of a name ("Dear <Name>,").
- Credit notes, credit memos and receipts: their own number labels (jóváírás száma, credit memo, payment id).

The identifiers are made up; only their shape follows the documents seen.
"""

from jav.candidates import find_all
from jav.models import CellLayout, LineLayout


def _line(no: int, *cells: tuple[str, float]) -> LineLayout:
    return LineLayout(no=no, page=1, text="   ".join(t for t, _ in cells),
                      cells=[CellLayout(text=t, x0=x, x1=x + 6 * len(t)) for t, x in cells])


def _names(lines: list[LineLayout], profile: str) -> set[str]:
    return {c.label for c in find_all(lines, profile)["name"]}


def _numbers(lines: list[LineLayout], profile: str) -> set[str]:
    return {c.label for c in find_all(lines, profile)["invoice_number"]}


# --- names ---------------------------------------------------------------------------------------------------------


def test_a_name_ending_in_its_legal_form_is_not_joined_with_the_address_below():
    lines = [_line(1, ("Vevő:", 30)), _line(2, ("Minta Adat Kft.", 30)), _line(3, ("Budapest Próba utca 82.", 30)),
             _line(4, ("1141", 30))]
    for profile in ("hu", "intl"):
        names = _names(lines, profile)
        assert "Minta Adat Kft." in names
        # (a letter-dominated address line may still be a private-person fallback candidate on its own, as before)
        assert not any(n.startswith("Minta Adat Kft.") and n != "Minta Adat Kft." for n in names), profile


def test_an_address_glued_after_the_legal_form_in_one_cell_is_cut():
    lines = [_line(1, ("Vevő: Minta Adat Kft. Próba utca 82. 1141", 30)),
             _line(2, ("Szállító: Példa Kereskedő Zrt. 1119 Budapest, Teszt út 4.", 30))]
    for profile in ("hu", "intl"):
        names = _names(lines, profile)
        assert {"Minta Adat Kft.", "Példa Kereskedő Zrt."} <= names, profile
        assert not any("utca" in n or "Budapest" in n for n in names), profile


def test_a_name_continued_after_its_legal_form_by_words_is_kept():
    # the continuation is not address-shaped, so it is not cut (a branch, a remark): unchanged behaviour
    lines = [_line(1, ("Minta Adat Kft. Fióktelep", 30))]
    assert "Minta Adat Kft. Fióktelep" in _names(lines, "hu")


def test_a_two_line_company_name_ending_in_reszvenytarsasag_is_joined():
    lines = [_line(1, ("Eladó:", 30)), _line(2, ("Példa Közlekedési Központ Zártkörűen Működő", 30)),
             _line(3, ("Részvénytársaság", 30)), _line(4, ("1075 Budapest, Minta utca 15.", 30))]
    for profile in ("hu", "intl"):
        assert "Példa Közlekedési Központ Zártkörűen Működő Részvénytársaság" in _names(lines, profile), profile


def test_the_existing_three_line_joins_still_work():
    lines = [_line(1, ("PELDADATA KERESKEDELMI ÉS", 28)), _line(2, ("SZOLGÁLTATÓ BETÉTI TÁRSASÁG", 28)),
             _line(3, ("Magyarország 1119 BUDAPEST", 28))]
    names = _names(lines, "hu")
    assert "PELDADATA KERESKEDELMI ÉS SZOLGÁLTATÓ BETÉTI TÁRSASÁG" in names
    assert not any("1119" in n for n in names)


def test_a_party_label_is_a_whole_word():
    lines = [_line(1, ("Vevőkód: Minta Adat Kft.", 30)), _line(2, ("Vásárló: Példa Bolt Kft.", 30)),
             _line(3, ("Ügyfél neve: Teszt Elek Bt.", 30))]
    names = _names(lines, "hu")
    assert "Példa Bolt Kft." in names and "Teszt Elek Bt." in names
    assert not any(n.startswith("kód") for n in names)  # "Vevőkód:" is not "Vevő" + "kód: …"
    assert not any(n.lower().startswith(("vásárló", "ügyfél")) for n in names)


def test_a_greeting_is_not_part_of_a_name():
    lines = [_line(1, ("Your receipt", 30)), _line(2, ("Dear Minta Person,", 30)), _line(3, ("Kedves Teszt Elek!", 30))]
    assert {"Minta Person", "Teszt Elek"} <= _names(lines, "intl")
    assert "Teszt Elek" in _names(lines, "hu")


# --- invoice numbers -------------------------------------------------------------------------------------------------


def test_the_own_number_of_a_hungarian_credit_note_is_a_candidate():
    lines = [_line(1, ("Jóváírási dokumentum - JV-2026-0012", 30)), _line(2, ("Minta Bolt Kft.", 30)),
             _line(3, ("Helyesbített számla: KI-2026-0417", 30))]
    assert "JV-2026-0012" in _numbers(lines, "hu")
    lines = [_line(1, ("Jóváíró számla sorszáma: JV-2026-0013", 30))]
    assert "JV-2026-0013" in _numbers(lines, "hu")


def test_credit_memo_and_localised_credit_note_labels_are_invoice_number_labels():
    lines = [_line(1, ("CREDIT MEMO # T500000123", 30)), _line(2, ("Original invoice T500000124", 30))]
    assert "T500000123" in _numbers(lines, "intl")
    lines = [_line(1, ("Jóváírás száma", 30), ("E0800ABCDE", 300)), _line(2, ("Számlázási időszak", 30))]
    assert "E0800ABCDE" in _numbers(lines, "intl")


def test_a_payment_id_is_an_invoice_number_candidate_on_a_receipt():
    lines = [_line(1, ("Transaction", 30)), _line(2, ("Payment ID: 51234567", 30)), _line(3, ("Total paid $12.00", 30))]
    assert "51234567" in _numbers(lines, "intl")
    lines = [_line(1, ("Transaction number: TX-2026-77", 30))]
    assert "TX-2026-77" in _numbers(lines, "intl")
