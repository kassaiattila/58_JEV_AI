"""231 (stage D, D-e2): the invented insurance application documents and the facts they hold.

Eight sets of invented documents - a quote request form, a property schedule per site and a claims history statement
- are kept as what a correct reading gives. Their printed pages are made from those values, and the code's own source
check finds every value on its page; every document's values are a reading its type pack takes. Read through the fact
readings, each set gives the facts it records; the five sets of the product set's reference cases give that case's very
facts (and the covers it asks for), with the company's name, tax number and the site's address beside them. Words no
code table knows are not read, and a tax number two documents give differently is a disagreement. Invented data; no
paid call.
"""

from __future__ import annotations

import pytest

from jav.ai import typepack
from jav.ai.jev_verify import site_for
from jav.app import fact_readings, facts, product_sets
from jav.documents.layout import LineLayout
from jav.documents.pdf import read_document
from jav.evals import property_documents as pd

DOCS = pd.load()
READINGS = fact_readings.load()
CASES = {c.id: c for c in product_sets.load().cases}
EXTRA = {"company_name", "tax_number", "site_address", "requested_modules"}  # what the documents add to a case's facts


def test_eight_sets_of_23_documents_use_the_three_packs() -> None:
    documents = [d for s in DOCS.sets for d in s.documents]
    assert (len(DOCS.sets), len(documents)) == (8, 23)
    assert {d.pack for d in documents} == {"insurance_request", "property_schedule", "claims_history"}
    assert len({d.id for d in documents}) == len(documents)


@pytest.mark.parametrize("document", [d for s in DOCS.sets for d in s.documents], ids=lambda d: d.id)
def test_each_documents_values_are_a_reading_its_pack_takes_and_are_printed_on_its_page(document) -> None:
    pack = typepack.get(document.pack)
    pack.llm_model().model_validate(document.values)
    lines = [LineLayout(no=i, page=p, text=t) for i, (p, t) in enumerate(
        ((p, t) for p, page in enumerate(pd.pages(document), start=1) for t in page), start=1)]
    _evidence, unsupported = site_for(document.pack).code_evidence(lines, document.values)
    assert unsupported == []


@pytest.mark.parametrize("doc_set", DOCS.sets, ids=lambda s: s.id)
def test_each_set_records_the_facts_its_documents_give(doc_set) -> None:
    units, unread, conflicts = pd.facts_of(doc_set, READINGS)
    assert units == [u.model_dump() for u in doc_set.units]
    assert [tuple(u) for u in unread] == [tuple(u) for u in doc_set.unread]
    assert [tuple(c) for c in conflicts] == [tuple(c) for c in doc_set.conflicts]


@pytest.mark.parametrize("doc_set", [s for s in DOCS.sets if s.case], ids=lambda s: s.id)
def test_a_reference_cases_documents_hold_its_facts(doc_set) -> None:
    case = CASES[doc_set.case]
    cat = facts.catalogue("property")
    got = {u.key: u for u in doc_set.units}
    case_units = case.input["units"]
    keys = {}  # the case's unit ids by the keys the documents give them
    for unit in case_units:
        if unit["level"] == "holder":
            keys[unit["unit_id"]] = "holder"
        elif unit["level"] == "site":
            keys[unit["unit_id"]] = "site:1"
    groups = [u for u in case_units if u["level"] == "asset_group"]
    keys |= {u["unit_id"]: f"site:1/{i}" for i, u in enumerate(groups, start=1)}
    assert set(got) == set(keys.values())
    for unit in case_units:
        mine = got[keys[unit["unit_id"]]]
        assert mine.level == unit["level"]
        for fact, value in unit["facts"].items():
            d = cat.facts[fact]
            assert facts.typed_value(fact, d, mine.facts.get(fact)) == facts.typed_value(fact, d, value), (mine.key, fact)
        assert set(mine.facts) - set(unit["facts"]) <= EXTRA, (mine.key, set(mine.facts) - set(unit["facts"]))
    assert tuple(got["holder"].facts["requested_modules"]) == case.modules
    assert not doc_set.unread and not doc_set.conflicts


def test_a_schedule_on_two_pages_and_the_odd_sets() -> None:
    sets = {s.id: s for s in DOCS.sets}
    two = next(d for d in sets["referred"].documents if d.layout == "two_pages")
    assert len(pd.pages(two)) == 2
    assert sets["conflict"].conflicts == (("holder", "tax_number"),)
    assert sets["unknown_code"].unread == (("site:1", "flood_zone"), ("site:1/5", "asset_group"))
    assert [u.key for u in sets["two_sites"].units if u.level == "site"] == ["site:1", "site:2"]


def test_the_documents_are_written_as_pdfs_with_their_text(tmp_path) -> None:
    paths = pd.write_pdfs(tmp_path)
    assert len(paths) == 23
    text = read_document(str(next(p for p in paths if p.name == "reference-schedule-1.pdf"))).text
    assert "VAGYONADATLAP" in text and "180 000 000 Ft" in text and "Minta Kereskedő Kft." in text
