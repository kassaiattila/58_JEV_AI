"""231 (stage U, U-A6): the real corporate property product's quote, from its documents to the offer document.

A case of the pack `allianz_property_offer` starts on a folder of the invented metalworks' documents (PDFs, printed on
the product's form). The product is made active as the owner will make it: here with one invented condition document
and one invented eligibility rule (the real rules are the owner's decisions on the proposals), its tariff the example
one. The run's results are what a correct reading gives (written as the worker would, without asking a model). The
facts are offered with where each was printed, the registers agree, a person freezes the facts, the rule allows the
risk, nothing is missing, a person accepts the risk, the premium is the hand-computed one, and as the total sum insured
is above the authority's plan value, another person accepts it; the offer's Word document is printed. Invented data;
no paid call.
"""

from __future__ import annotations

import io
import time

import pytest

from jav.app import (case_decisions, case_views, document_processing, field_check, package_release, process_runtime,
                     product_rules, product_sets, product_sources, work, work_runs)
from jav.app import approved_document
from jav.core import connectors, store
from jav.core.process import engine
from jav.devtools import invented_services
from jav.evals import property_documents as pd

ANNA, BELA = "Minta Anna", "Minta Bela"
DOCS = pd.load("golden_allianz_property_documents")
SET = next(s for s in DOCS.sets if s.id == "az-metalworks")
DOCUMENT = {"kind": "general", "title": "Kitalált próbafeltétel", "valid_from": "2024-09-01",
            "sections": [{"clause": "1", "page": 1, "title": "Biztosíthatóság"}]}
RULE = {"catalogue": "allianz_property", "kind": "eligibility", "title": "An active company not on a sanctions list",
        "level": "holder", "facts": ["company_status", "sanctions_listed"],
        "table": {"hit": "first", "rows": [
            {"when": {"company_status": {"eq": "active"}, "sanctions_listed": {"eq": False}}, "then": {"verdict": "allow"}},
            {"when": {}, "then": {"verdict": "refer"}}]},
        "source": {"document": "az_test_conditions@1", "page": 1, "clause": "1"}}


def _product() -> None:
    """The product made active as the owner will: a draft of one person, made active by another."""
    for kind, ident, content in (("document", "az_test_conditions", DOCUMENT), ("rule", "az_test_eligibility", RULE)):
        product_rules.add(kind, ident, content, actor=ANNA)
        product_rules.activate(kind, ident, 1, actor=BELA)
    frame = product_sources.load("allianz_property").product
    product_rules.add("product", "az_corporate_property", {
        "name": frame.name, "catalogue": frame.catalogue, "modules": [m.model_dump(mode="json") for m in frame.modules],
        "documents": ["az_test_conditions@1"], "rules": ["az_test_eligibility@1"], "tariff": "az_corporate_property_tariff"},
        actor=ANNA)
    product_rules.activate("product", "az_corporate_property", 1, actor=BELA)


@pytest.fixture()
def folder(tmp_path):
    with store.use_store(tmp_path / "allianz.sqlite"), connectors.use_transport(invented_services.transport()):
        product_sets.install(product_sets.load("product_set_allianz_tariff"), maker=ANNA, approver=BELA)
        _product()
        out = tmp_path / "documents"
        out.mkdir()
        from jav.documents.synthetic_pdf import write_unicode_pdf_pages

        for document in SET.documents:
            write_unicode_pdf_pages(out / f"{document.id}.pdf", pd.pages(document, DOCS.form))
        yield out


_CLOCK = [time.time()]


def _turn(case_id: str, n: int = 2) -> dict:
    for _ in range(n):
        _CLOCK[0] = max(_CLOCK[0], time.time()) + 10  # never behind the real time the steps' timers are set from
        engine.turn(case_id, now=_CLOCK[0])
    return engine.state(case_id)


def _read_as_correct(run_id: str, wp_id: str) -> None:
    by_name = {d.id: d for d in SET.documents}
    for item in work.get(wp_id)["items"]:
        document = by_name[str(item["source_path"]).replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".pdf")]
        flow = work_runs.flow_run_id(run_id, item["item_id"])
        store.insert_datapoints(run_id=flow, doc_id=item["item_id"], doc_type=document.pack, arm="G", datapoints=document.values,
                                field_conf={}, validation=[], route="auto", review_reasons=[], final_status="done")
        work_runs.record_item_result(run_id, item["item_id"], status="done", final_status="done", flow_run_id=flow)
    with store.connect() as c:
        c.execute("UPDATE jobs SET status='done' WHERE run_id=?", (run_id,))
    work_runs.refresh_run_status(run_id)


def _decide(case_id: str, step: str, actor: str) -> None:
    case_views.act(case_id, step, "decide", actor, values={"choice": "accept",
                                                          "expected_basis": case_decisions.view(case_id, step)["basis"]})


def test_the_metalworks_quote_runs_to_the_offer_with_a_second_person_above_the_plan_value(folder) -> None:
    case_id = process_runtime.start_case("allianz_property_offer", {"source": {"kind": "folder", "folder": str(folder)}},
                                         name="Minta Fémmegmunkáló Kft.", actor=ANNA)
    _turn(case_id)
    case_views.act(case_id, "documents", "start_run", ANNA)
    wp = document_processing.package_of(case_id, "documents")
    [run] = work_runs.run_rows(wp)
    _read_as_correct(run["run_id"], wp)
    _turn(case_id)
    work_runs.approve_run(run["run_id"], actor=ANNA)
    steps = _turn(case_id, 3)["steps"]
    assert [steps[s]["state"] for s in ("documents", "facts", "company", "sanctions")] == ["done"] * 4
    assert len(steps["facts"]["result"]["documents"]) == 3
    assert not any(d["unread"] for d in steps["facts"]["result"]["documents"])
    assert steps["company"]["result"]["answer"]["company"]["activity_code"] == "2562"

    view = field_check.view(case_id, "check")
    holder = next(u for u in view["units"] if u["level"] == "holder")
    assert holder["facts"]["company_status"] == "active" and holder["facts"]["sanctions_listed"] is False
    assert holder["facts"]["requested_modules"] == ["property_ar", "VIL", "IKO", "burglary", "interruption"]
    assert holder["facts"]["chosen_deductible"] == {"amount": "500000", "currency": "HUF"}
    assert not [c for c in view["claims"] if c["open"]]
    case_views.act(case_id, "check", "freeze", ANNA, values={"cover_start": "2027-01-01", "expected_state": view["state"]})
    steps = _turn(case_id, 3)["steps"]
    evaluated = steps["evaluate"]["result"]
    assert evaluated["verdict"] == "allow" and steps["missing"]["state"] == "done"
    assert evaluated["sums"] == {"sum_insured_total": {"amount": "241500000", "currency": "HUF"}}

    _decide(case_id, "risk", ANNA)
    steps = _turn(case_id, 3)["steps"]
    # all risks 173 880 + surge 3 000 (its minimum) + machinery breakage 48 000 + burglary 114 307 + interruption 90 000
    assert steps["rate"]["result"]["total"] == {"amount": "429200", "currency": "HUF"}
    second = case_decisions.view(case_id, "premium")["second_person"]
    assert second["needed"] is True and second["amount"] == {"amount": "241500000", "currency": "HUF"}
    with pytest.raises(case_decisions.AnotherDeciderNeeded):
        _decide(case_id, "premium", ANNA)
    _decide(case_id, "premium", BELA)
    state = _turn(case_id, 3)
    assert state["steps"]["premium"]["state"] == "done"

    printed = state["steps"]["document"]
    assert printed["state"] == "done" and printed["result"]["output"] == "rated_offer"
    assert printed["result"]["version"] == package_release.own_approval(case_id, step="premium")["active"]["version"]
    content, _name = approved_document.step_file(case_id, "document")
    from docx import Document

    text = "\n".join(p.text for p in Document(io.BytesIO(content)).paragraphs)
    cells = [c.text for t in Document(io.BytesIO(content)).tables for row in t.rows for c in row.cells]
    assert "Minta Fémmegmunkáló Kft." in text and "Allianz vállalati vagyonbiztosítás" in text and "Minta Bela" in text
    assert "Betöréses lopás és rablás" in cells and "Gépek külső okból bekövetkező törése" in cells
