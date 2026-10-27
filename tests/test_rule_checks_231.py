"""231 (stage D, D-c7b): the code's checks of a proposed rule, before any model judges it.

The 16 rules a careful person reads from the invented insurer's documents pass with nothing blocking; where the
document does not print a number literally (no claims as "claim-free", a band of one or two claims below "three or
more"), a person is asked to confirm it, and a number written as a word (four), derived from a stated percentage
(a 10 % discount as 0.9) or a factor of 1 stands. One planted error per check is caught: a wrong page, clause, document
or quote, a number not in the document, a fact the catalogue does not have, a page its marking keeps out, a number read
by text recognition. The same holds when the documents are read back from their PDFs. Invented data; no paid call.
"""

from __future__ import annotations

import copy

import pytest

from jav.app import product_sets, rule_checks
from jav.app.product_rules import Rule
from jav.core import cfg
from jav.documents import page_text

SET = product_sets.load()
MARKERS = cfg.load("rule_proposals")["skip_page_markers"]


def _pages(doc_id: str, **changes) -> page_text.DocumentPages:
    pages = page_text.from_rows(product_sets.document_pages(SET, doc_id), MARKERS)
    return page_text.DocumentPages(**(pages.__dict__ | changes))


def _check(rule: Rule, *, registered: bool = True, pages: page_text.DocumentPages | None = None,
           read_from: str | None = None) -> rule_checks.RuleCheck:
    doc_id = read_from or rule.source.document.split("@")[0]
    document = SET.documents[doc_id].content if registered else None
    return rule_checks.check(rule, pages or _pages(doc_id), document_ref=f"{doc_id}@1", document=document)


def _changed(ident: str, **changes) -> Rule:
    data = copy.deepcopy(SET.rules[ident].model_dump(mode="json"))
    for path, value in changes.items():
        node = data
        keys = path.split("__")
        for key in keys[:-1]:
            node = node[int(key)] if key.isdigit() else node[key]
        node[int(keys[-1]) if keys[-1].isdigit() else keys[-1]] = value
    return Rule.model_validate(data)


def _texts(result: rule_checks.RuleCheck) -> list[str]:
    return [f"{f.severity}: {f.text}" for f in result.findings]


def test_the_expected_rules_pass_and_only_unprinted_numbers_ask_for_a_person() -> None:
    attention = {}
    for ident, rule in SET.rules.items():
        result = _check(rule)
        assert not result.blocking, (ident, _texts(result))
        if result.findings:
            attention[ident] = _texts(result)
    assert attention == {"inv_claims_factor": ["attention: 0 is not in the document: a person confirms it",
                                               "attention: 1 is not in the document: a person confirms it"]}


def test_where_each_number_stands() -> None:
    seen = {n.value: (n.where, n.page) for n in _check(SET.rules["inv_claims_factor"]).numbers}
    assert seen == {"0": ("not_found", None), "0.9": ("derived", None), "1": ("not_found", None), "2": ("derived", None),
                    "1.0": ("neutral", None), "1.25": ("derived", None)}
    assert {n.value: n.where for n in _check(SET.rules["inv_claims_history"]).numbers} == {"4": "word", "10000000 HUF": "quote"}
    in_place = {n.value: (n.where, n.page) for n in _check(SET.rules["inv_class_in_place"]).numbers}
    assert in_place["5000000 HUF"] == ("elsewhere", 1) and in_place["50000000 HUF"] == ("page", 2)
    codes = {n.value: n.where for n in _check(SET.rules["inv_excluded_activities"]).numbers}
    assert codes == {"1610": "page", "2011": "page", "2051": "page", "3821": "page", "3822": "page"}


@pytest.mark.parametrize(("rule", "registered", "found"), [
    (_changed("inv_flood_high", source__page=4), True,
     ["blocking: clause 6.1 is on page 3, not on page 4", "attention: its quote is on page 3, not on page 4"]),
    (_changed("inv_flood_high", source__quote="az árvízkár mindig biztosított"), True, ["blocking: its quote is not in the document"]),
    (_changed("inv_flood_high", source__clause="9.9"), True, ["blocking: it cites clause 9.9, which the document does not have"]),
    (_changed("inv_flood_high", source__page=9), True,
     ["blocking: it cites page 9, which the document does not have", "blocking: clause 6.1 is on page 3, not on page 9",
      "attention: its quote is on page 3, not on page 9"]),
    (_changed("inv_flood_high", source__clause="7"), False, ["attention: clause 7 is not found on page 3"]),
    (_changed("inv_flood_high", source__quote=None), True, ["attention: it quotes nothing"]),
    (_changed("inv_valuables_sublimit", table__rows__0__then__sublimit={"amount": "2500000", "currency": "HUF"}), True,
     ["attention: 2500000 HUF is not in the document: a person confirms it"]),
    (_changed("inv_flood_high", facts=["flood_zone", "colour"]), True,
     ["blocking: reads colour, which the catalogue property does not have"]),
])
def test_a_planted_error_is_caught(rule, registered, found) -> None:
    assert _texts(_check(rule, registered=registered)) == found


def test_a_rule_citing_another_document_than_it_was_read_from_is_blocked() -> None:
    rule = _changed("inv_flood_high", source__document="inv_security_rules@1")
    assert _texts(_check(rule, read_from="inv_general_conditions")) == [
        "blocking: it cites inv_security_rules@1, not the document it was read from (inv_general_conditions@1)"]


def test_a_page_its_marking_keeps_out_is_never_read_or_cited() -> None:
    rows = product_sets.document_pages(SET, "inv_general_conditions")
    rows[2] = [*rows[2], "Internal"]
    pages = page_text.from_rows(rows, MARKERS)
    assert pages.skipped == {3: "Internal"} and 3 not in pages.pages
    found = _texts(_check(SET.rules["inv_flood_high"], pages=pages))
    assert "blocking: it cites page 3, which was not read: its marking (Internal) keeps it out" in found
    assert "blocking: its quote is not in the document" in found


def test_a_number_read_by_text_recognition_asks_for_a_person() -> None:
    pages = _pages("inv_burglary_conditions", ocr_pages=frozenset({1}))
    result = _check(SET.rules["inv_valuables_sublimit"], pages=pages)
    assert _texts(result) == ["attention: 2000000 HUF was read by text recognition on page 1: a person confirms it"]


def test_the_documents_read_back_from_their_pdfs_give_the_same(tmp_path) -> None:
    written = product_sets.write_documents(SET, tmp_path)
    for ident, rule in SET.rules.items():
        doc_id = rule.source.document.split("@")[0]
        pages = page_text.read_pages(written[doc_id], MARKERS)
        assert pages.source == "pdf" and pages.sha256 and not pages.skipped
        from_pdf = rule_checks.check(rule, pages, document_ref=f"{doc_id}@1", document=SET.documents[doc_id].content)
        assert _texts(from_pdf) == _texts(_check(rule)), ident
        assert from_pdf.numbers == _check(rule).numbers, ident


def _misread(text: str) -> str:
    """Text recognition's kind of errors: an accent lost, one letter for another, two words run together."""
    return text.replace("á", "a", 2).replace("e", "c", 1).replace(" a ", " a", 1)


def test_a_quote_on_a_page_text_recognition_read_matches_roughly_for_a_person_to_compare() -> None:
    """U-A3 (the paid round's lesson): on the all risks conditions, read by text recognition, the model quoted the words
    as they are printed, while the recognised text had misread letters; 17 of 27 proposals were blocked as quoting words
    the document did not have. On a recognised page a close quote is found, for a person to compare; on a page with a
    text layer it must be there as printed, apart from a word broken at the line's end."""
    rule = SET.rules["inv_valuables_sublimit"]
    rows = product_sets.document_pages(SET, "inv_burglary_conditions")
    misread = [[_misread(line) for line in page] for page in rows]
    pages = page_text.DocumentPages(**(page_text.from_rows(misread, MARKERS).__dict__ | {"ocr_pages": frozenset({1, 2})}))
    texts = _texts(_check(rule, pages=pages))
    assert "attention: its quote matches page 1 only roughly (text recognition): a person compares it" in texts
    assert not any(t.startswith("blocking: its quote") for t in texts)
    as_text = page_text.from_rows(misread, MARKERS)  # the same words on a page with a text layer
    assert "blocking: its quote is not in the document" in _texts(_check(rule, pages=as_text))


def test_a_word_broken_at_the_line_s_end_is_the_same_word() -> None:
    """U-A3: "vagyon-\nvédelmi" in the page is "vagyonvédelmi" in a quote."""
    rule = _changed("inv_valuables_sublimit", source__quote="értéktárgyak")
    rows = product_sets.document_pages(SET, "inv_burglary_conditions")
    broken = [[line.replace("értéktárgyak", "érték-\ntárgyak") for line in page] for page in rows]
    assert not any("quote" in t for t in _texts(_check(rule, pages=page_text.from_rows(broken, MARKERS))))


def test_a_quote_with_an_omission_matches_when_each_part_stands_in_order() -> None:
    """U-A3 (the paid round): the model quoted with an omission ("A biztosító … nem áll be"); each part stands on the
    page as printed, in the order given, so the quote counts; parts out of order or one not printed do not."""
    rule = SET.rules["inv_valuables_sublimit"]
    words = rule.source.quote.split()
    head, tail = " ".join(words[:2]), " ".join(words[-2:])
    for quote, ok in ((f"{head} … {tail}", True), (f"{head} ... {tail}", True), (f"{tail} … {head}", False),
                      (f"{head} … nincs ilyen szó", False)):
        changed = _changed("inv_valuables_sublimit", source__quote=quote)
        assert (not any("quote" in t for t in _texts(_check(changed)))) is ok, quote


def test_a_code_a_rule_gives_that_the_catalogue_does_not_name_asks_a_person() -> None:
    """U-A3 (the paid round on the real conditions): accepted-looking proposals gave measures, excluded perils and
    required documents under codes of their own ("weekly_backup"); an outcome's list of codes is open, so it does not
    block, but a person decides on each code the catalogue does not name. A code it names says nothing."""
    known = list(SET.rules["inv_class_cash"].table.rows[0].then["measures"])
    result = _check(_changed("inv_class_cash", table__rows__0__then__measures=[*known, "weekly_backup"]))
    assert not result.blocking
    assert [t for t in _texts(result) if "weekly_backup" in t] == [
        "attention: it gives weekly_backup for measures, a code the catalogue does not name: a person decides on it"]
    assert not [t for t in _texts(_check(SET.rules["inv_class_cash"])) if "does not name" in t]
