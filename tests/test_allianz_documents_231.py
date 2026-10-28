"""231 (stage U, U-A6): the real corporate property product's invented customers and the facts their documents hold.

Three sets of invented documents - a quote request form on the product's form (its covers as printed boxes), a property
schedule and a claims history statement each - are kept as what a correct reading gives, like the invented insurer's.
Their printed pages are made from those values, the request's three new fields among them (the chosen deductible, the
contract's term, the waiting days), and the code's own source check finds every value on its page. Read through the
product's fact readings, each set gives the facts it records; priced by the product's tariff, the metalworks' total sum
insured is above the authority's plan value, and the cold store's schedule says nothing of a cold alarm, so its cold
store cover has no premium until a person gives it. The measurement scores them with stand-ins. Invented data; no
paid call.
"""

from __future__ import annotations

import pytest

from jav.ai import typepack
from jav.ai.jev_verify import site_for
from jav.app import fact_readings, facts, product_sets, product_sources, rating, rule_evaluation
from jav.core import cfg
from jav.documents.layout import LineLayout
from jav.evals import property_documents as pd

NAME = "golden_allianz_property_documents"
DOCS = pd.load(NAME)
READINGS = fact_readings.load(DOCS.readings)
TARIFF = product_sets.load("product_set_allianz_tariff").tariffs["az_corporate_property_tariff"]
PLAN_LIMIT = cfg.load("case_decisions")["limits"]["az_authority_sum_insured_plan"]["above"]


def test_three_sets_of_nine_documents_on_the_product_s_form_and_readings() -> None:
    documents = [d for s in DOCS.sets for d in s.documents]
    assert (len(DOCS.sets), len(documents)) == (3, 9) and len({d.id for d in documents}) == 9
    assert {d.pack for d in documents} == {"insurance_request", "property_schedule", "claims_history"}
    assert READINGS.catalogue == "allianz_property" and DOCS.key == "insurance_application:allianz_documents"
    modules = {m.code: m.name for m in product_sources.load("allianz_property").product.modules}
    assert all(cover in modules.values() for cover in DOCS.form.covers)  # the form prints the product's module names


@pytest.mark.parametrize("document", [d for s in DOCS.sets for d in s.documents], ids=lambda d: d.id)
def test_each_documents_values_are_a_reading_its_pack_takes_and_are_printed_on_its_page(document) -> None:
    typepack.get(document.pack).llm_model().model_validate(document.values)
    lines = [LineLayout(no=i, page=p, text=t) for i, (p, t) in enumerate(
        ((p, t) for p, page in enumerate(pd.pages(document, DOCS.form), start=1) for t in page), start=1)]
    _evidence, unsupported = site_for(document.pack).code_evidence(lines, document.values)
    assert unsupported == []


def test_the_request_prints_its_new_fields_and_the_product_s_covers() -> None:
    request = next(d for d in DOCS.sets[0].documents if d.pack == "insurance_request")
    text = "\n".join(line for page in pd.pages(request, DOCS.form) for line in page)
    assert "Vállalati vagyonbiztosítás" in text and "[X] Villámcsapás okozta túlfeszültség" in text
    assert "[ ] Üvegtörés" in text and "Választott önrész: 500 000 Ft" in text
    assert "Szerződés tartama: határozatlan" in text and "Üzemszüneti időönrész: 3 munkanap" in text
    invented = pd.load()  # the invented insurer's forms print none of them and keep their own covers
    text = "\n".join(line for page in pd.pages(invented.sets[0].documents[0]) for line in page)
    assert "Választott önrész" not in text and "Vállalkozói vagyonbiztosítás" in text and "[X] túlfeszültség" in text


@pytest.mark.parametrize("doc_set", DOCS.sets, ids=lambda s: s.id)
def test_each_set_records_the_facts_its_documents_give(doc_set) -> None:
    units, unread, conflicts = pd.facts_of(doc_set, READINGS)
    assert units == [u.model_dump() for u in doc_set.units]
    assert unread == [] and conflicts == []


def _priced(doc_set) -> tuple[rating.Calculation, int]:
    ids = {u.key: f"u-{n:010d}" for n, u in enumerate(doc_set.units, start=1)}
    units = [{"unit_id": ids[u.key], "level": u.level, "parent_id": ids.get(u.parent) if u.parent else None,
              "facts": {k: v for k, v in u.facts.items() if k in facts.catalogue("allianz_property").facts}}
             for u in doc_set.units]
    checked = facts.checked_input({"catalogue": "allianz_property", "product": "az_corporate_property@1",
                                   "cover_start": "2027-01-01", "units": units})
    modules = tuple(doc_set.units[0].facts["requested_modules"])
    evaluation = rule_evaluation.evaluate([], checked, modules=modules)
    total = sum(int(u.facts["sum_insured"]["amount"]) for u in doc_set.units if "sum_insured" in u.facts)
    return rating.calculate(TARIFF, "az_corporate_property_tariff@1", checked, evaluation, modules=modules), total


def test_the_sets_facts_are_priced_by_the_product_s_tariff() -> None:
    sets = {s.id: s for s in DOCS.sets}
    metalworks, total = _priced(sets["az-metalworks"])
    assert metalworks.blockers == () and metalworks.total is not None
    assert total > int(PLAN_LIMIT["amount"])  # the authority's plan value: the premium is another person's
    retail, total = _priced(sets["az-retail"])
    assert retail.blockers == () and total < int(PLAN_LIMIT["amount"])
    cold, _total = _priced(sets["az-cold-store"])
    assert cold.total is None
    assert cold.blockers == ("u-0000000005: no cold_alarm factor: the fact cold_alarm_monitored is missing",)


def test_the_measurement_with_a_correct_reading_has_every_judgement_right(tmp_path, monkeypatch) -> None:
    from jav.evals import goldens

    monkeypatch.setattr(pd, "RUNS_DIR", tmp_path)
    packs = {d.id: d.pack for s in DOCS.sets for d in s.documents}
    out = pd.measure(goldens.Options(engine="jev"), read=lambda document, path: dict(document.values),
                     recognise=lambda path: (pd.BROAD, packs[path.stem]), name=NAME)
    assert (out.cases, out.answered, out.unit) == (9, 9, "judgements")
    assert out.right == out.scored and out.failures == ()
    assert list(tmp_path.glob("*_allianz_property_documents_jev.jsonl"))
