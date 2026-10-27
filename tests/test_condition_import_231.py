"""231 (stage U, U-A2; the owner's decisions of 2026-10-27): a condition document read from its PDF into the
registry's form, by code.

The invented insurer's condition documents, written as the PDFs a rule proposal reads, are read back into exactly the
clauses the product set holds (each clause's number, page and title) and the day they are in force; a numbered item in
a clause's text or a number printed again is no new clause; a day printed after "hatályos" is read in the forms a
publisher prints it, a text recognition's misread letters included; a file without one says so. The machine adds the
document as a draft, once. Invented data; no AI call.
"""

from __future__ import annotations

from datetime import date

import pytest

from jav.app import condition_import, product_rules, product_sets
from jav.core import store
from jav.documents import page_text
from jav.documents.synthetic_pdf import write_unicode_pdf_pages

SET = product_sets.load()


@pytest.mark.parametrize("ident", sorted(SET.documents))
def test_an_invented_document_reads_back_into_its_clauses(tmp_path, ident: str) -> None:
    path = product_sets.write_documents(SET, tmp_path)[ident]
    entry = SET.documents[ident].content
    got = condition_import.read(path, kind=entry.kind, title=entry.title, valid_from=entry.valid_from)
    assert [(s.clause, s.page, s.title) for s in got.content.sections] == [(s.clause, s.page, s.title) for s in entry.sections]
    assert got.problems == []


def test_a_numbered_item_or_a_repeated_number_is_no_new_clause() -> None:
    pages = {1: "1. A biztosítás tárgya\nszöveg\n2. Kizárások\n1. az első felsorolt eset\n2. a második\n3. Önrész",
             2: "3.1. Önrész mértéke\n3.1. Önrész mértéke\n4. Díj"}
    assert [(s.clause, s.page, s.title) for s in condition_import.sections_of(pages)] == [
        ("1", 1, "A biztosítás tárgya"), ("2", 1, "Kizárások"), ("3", 1, "Önrész"), ("3.1", 2, "Önrész mértéke"), ("4", 2, "Díj")]


@pytest.mark.parametrize(("printed", "day"), [
    ("Vállalati Vagyonbiztosítások\nHATÁLYOS\n2019. november 1-jétől", date(2019, 11, 1)),
    ("HATALYOS\n2024.09.01-t6l\nKülönös feltételek", date(2024, 9, 1)),
    ("Hatályos: 2021. december 31-től", date(2021, 12, 31)),
])
def test_the_day_in_force_is_read_after_hatalyos(printed: str, day: date) -> None:
    assert condition_import.valid_from_of(printed) == day


def test_a_file_without_a_day_in_force_says_so_and_the_machine_adds_it_once(tmp_path) -> None:
    path = write_unicode_pdf_pages(tmp_path / "terms.pdf", [["Feltételek", "1. Tárgy", "szöveg"], ["2. Kizárások", "szöveg"]])
    got = condition_import.read(path, kind="special", title="Feltételek")
    assert got.problems == ["the day it is in force is not printed after 'hatályos' on its first page: give it"]
    with store.use_store(tmp_path / "registry.sqlite"):
        fixed = condition_import.read(path, kind="special", title="Feltételek", valid_from=date(2026, 1, 1))
        ref = condition_import.install("terms", fixed)
        assert condition_import.install("terms", fixed) == ref == "terms@1"
        row = product_rules.get("document", "terms", 1)
        assert row["state"] == "draft" and row["made_by_id"] == condition_import.MACHINE.id
        assert [s["clause"] for s in row["content"]["sections"]] == ["1", "2"]


def _two_columns(left: list[str], right: list[str]) -> list[str]:
    """Rows of a page set in two columns: each row's left text, an empty middle cell, and its right text (at 330 pt)."""
    sep = "   "
    return [f"{a}{sep}{sep}{b}" if b else a for a, b in zip(left, right + [""] * (len(left) - len(right)))]


def test_a_page_in_two_columns_is_read_column_by_column(tmp_path) -> None:
    """U-A2: the real condition documents are set in two columns; read line by line across both, their clauses came
    mixed (1.2, 1.13, 1.3, …). A page so set reads its left column, then its right one; a table stays line by line."""
    left = ["1. Tárgy", "a biztosítás", "tárgya", "2. Kizárások", "nem fedezett", "kár", "2.1. Árvíz", "árvízi kár"]
    right = ["3. Önrész", "az önrész", "3.1. Mérték", "százalék", "4. Díj", "a díj", "4.1. Fizetés", "félévente"]
    table = ["Vagyoncsoport   Összeg   Érték   Avultság"] + [f"tétel {i}   {i}00 000   új   10" for i in range(1, 9)]
    path = write_unicode_pdf_pages(tmp_path / "columns.pdf", [_two_columns(left, right), table])
    pages = page_text.read_pages(path).pages
    assert pages[1].splitlines() == left + right
    assert pages[2].splitlines()[0] == "Vagyoncsoport   Összeg   Érték   Avultság"
    assert [s.clause for s in condition_import.sections_of(pages)] == ["1", "2", "2.1", "3", "3.1", "4", "4.1"]


def test_a_stray_number_or_a_table_of_contents_takes_no_clause_away() -> None:
    """U-A2: of the lines that look like headings, the longest rising run counts: a table of contents (with or without
    its dot leaders) and a stray early number do not hide the body's clauses."""
    pages = {1: "1. Fogalmak ........ 3\n2. Tárgy ........ 4\n10. Megszűnés", 2: "1. Fogalmak\n2. Tárgy\n2.1. Kiterjesztés\n3. Díj"}
    assert [(s.clause, s.page) for s in condition_import.sections_of(pages)] == [("1", 2), ("2", 2), ("2.1", 2), ("3", 2)]


def _clauses(pages: dict[int, str]) -> list[str]:
    return [s.clause for s in condition_import.sections_of(pages)]


def test_an_extension_with_its_own_code_numbers_its_clauses_under_the_code() -> None:
    """U-A2 (the real all risks conditions): each extension is headed "… – KIEGÉSZÍTŐ BIZTOSÍTÁS (CODE)" and numbers
    its clauses from 1 again; under such a heading a clause is named with the code ("VIL 2"), so none is lost."""
    pages = {1: "1. Fogalmak\n2. A biztosítás tárgya\n2.1. Épületek",
             2: "VILLÁMCSAPÁS OKOZTA TÚLFESZÜLTSÉG – KIEGÉSZÍTŐ BIZTOSÍTÁS (VIL)\n1. Biztosítási esemény\n2. Önrész",
             3: "Vandalizmus – kiegészítő biztosítás (J21)\n1. Biztosítási esemény\n2. Kizárások\n3. Önrész"}
    assert _clauses(pages) == ["1", "2", "2.1", "VIL 1", "VIL 2", "J21 1", "J21 2", "J21 3"]


def test_roman_chapters_slash_points_and_a_missing_space_are_clauses() -> None:
    """U-A2: the cold-store conditions' Roman chapters ("II. 2." is "II.2"), the protection rules' "1/A." points, and a
    clause number run into its first word ("8.3.2.Ellenkező") are clauses too."""
    assert _clauses({1: "I. Fogalmak\nII. A biztosítás tárgya\nII. 2. Hűtött készlet", 2: "III. Kizárások\nIII. 1. Áramszünet"}) == [
        "I", "II", "II.2", "III", "III.1"]
    assert _clauses({1: "1/A. Védelmi osztályok\n1/B. Vagyoncsoportok\n1/C. Védelmi szintek"}) == ["1/A", "1/B", "1/C"]
    assert _clauses({1: "8. Díj\n8.3. Díjfizetés\n8.3.2.Ellenkező megállapodás hiányában\n8.4 A díj"}) == ["8", "8.3", "8.3.2", "8.4"]


def test_letter_points_stand_beside_numbered_annexes() -> None:
    """U-A2 (the real protection rules): its "1/A." points and its numbered annexes are both clauses, in printed order."""
    assert _clauses({1: "1/A. Védelmi osztályok\n1/B. Vagyoncsoportok", 2: "1. Melléklet\n2. Melléklet\n3. Melléklet"}) == [
        "1/A", "1/B", "1", "2", "3"]


def test_a_dash_after_the_number_and_a_misread_code_keep_their_clauses() -> None:
    """U-A3 (the paid round's lesson): text recognition printed "2.2. — Afelek …" (a dash before the title) and an
    extension's code as "(129)" for "(I29)"; the clause stays a clause, and the code is read as printed (the product's
    source maps it to the real code)."""
    pages = {1: "2. Tárgy\n2.1. Épületek\n2.2. — Afelek megállapodása hiányában",
             2: "KIEGÉSZÍTŐ BIZTOSÍTÁS (129)\n1. Jelen kiegészítő biztosítás szerint\n2. Kizárások"}
    assert _clauses(pages) == ["2", "2.1", "2.2", "129 1", "129 2"]
