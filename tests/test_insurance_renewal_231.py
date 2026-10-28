"""231 (stage D, D-g; the owner's decision of 2026-10-26): the second small composition, the insurance renewal.

The renewal pack (`configs/processes/insurance_renewal.json`) is composed of the very capabilities the insurance quote
uses, in another structure and with no code of its own: no company register, no wait for missing facts, a stricter risk
rule (only a risk the rules allow is renewed; one they refer goes to the full quote and the case closes as referred), a
lower limit above which another person decides the premium, and the renewal's own letter frame. The reference set is
renewed and its letter sent into the output folder; the referred set goes to the full quote. Invented data; no paid
call.
"""

from __future__ import annotations

import email
import time
from email.policy import default
from pathlib import Path

import pytest

from jav.app import (app_settings, case_decisions, case_views, document_processing, field_check, letters, process_packs,
                     process_runtime, product_sets, work, work_runs)
from jav.core import connectors, store, trace
from jav.core.process import cases, engine
from jav.devtools import invented_services
from jav.evals import property_documents as pd

ANNA, BELA = "Minta Anna", "Minta Bela"
ROOT = Path(__file__).resolve().parents[1]
_CLOCK = [time.time()]


@pytest.fixture()
def renewal(tmp_path, monkeypatch):
    """A renewal case of an invented set's documents, read as a correct reading gives them, its facts frozen."""
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(app_settings, "output_folder", lambda: str(out))
    with store.use_store(tmp_path / "renewal.sqlite"), connectors.use_transport(invented_services.transport()):
        product_sets.install(product_sets.load(), maker=ANNA, approver=BELA)

        def start(set_id: str) -> str:
            doc_set = next(s for s in pd.load().sets if s.id == set_id)
            case = next(c for c in product_sets.load().cases if c.id == doc_set.case)
            folder = tmp_path / set_id
            folder.mkdir()
            from jav.documents.synthetic_pdf import write_unicode_pdf_pages

            for document in doc_set.documents:
                write_unicode_pdf_pages(folder / f"{document.id}.pdf", pd.pages(document))
            case_id = process_runtime.start_case("insurance_renewal", {"source": {"kind": "folder", "folder": str(folder)}},
                                                 name=doc_set.documents[0].values["policyholder_name"], actor=ANNA)
            _turn(case_id)
            case_views.act(case_id, "documents", "start_run", ANNA)
            wp = document_processing.package_of(case_id, "documents")
            [run] = work_runs.run_rows(wp)
            by_name = {d.id: d for d in doc_set.documents}
            for item in work.get(wp)["items"]:
                document = by_name[str(item["source_path"]).replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".pdf")]
                flow = work_runs.flow_run_id(run["run_id"], item["item_id"])
                store.insert_datapoints(run_id=flow, doc_id=item["item_id"], doc_type=document.pack, arm="G",
                                        datapoints=document.values, field_conf={}, validation=[], route="auto",
                                        review_reasons=[], final_status="done")
                work_runs.record_item_result(run["run_id"], item["item_id"], status="done", final_status="done", flow_run_id=flow)
            with store.connect() as c:  # the run's jobs done, as the worker leaves them
                c.execute("UPDATE jobs SET status='done' WHERE run_id=?", (run["run_id"],))
            work_runs.refresh_run_status(run["run_id"])
            _turn(case_id)
            work_runs.approve_run(run["run_id"], actor=ANNA)
            _turn(case_id, 3)
            view = field_check.view(case_id, "check")
            case_views.act(case_id, "check", "freeze", ANNA, values={"cover_start": case.input["cover_start"],
                                                                     "expected_state": view["state"]})
            _turn(case_id, 3)
            return case_id

        yield start, out


def _turn(case_id: str, n: int = 2) -> dict:
    for _ in range(n):
        _CLOCK[0] = max(_CLOCK[0], time.time()) + 10  # never behind the real time the steps' timers are set from
        engine.turn(case_id, now=_CLOCK[0])
    return engine.state(case_id)


def _decide(case_id: str, step: str, choice: str, actor: str, note: str | None = None) -> None:
    case_views.act(case_id, step, "decide", actor, values={"choice": choice, "note": note,
                                                          "expected_basis": case_decisions.view(case_id, step)["basis"]})


def test_the_reference_set_is_renewed_and_its_letter_sent(renewal) -> None:
    start, out = renewal
    case_id = start("reference")
    steps = engine.state(case_id)["steps"]
    assert "company" not in steps and steps["evaluate"]["result"]["verdict"] == "allow"
    _decide(case_id, "risk", "renew", ANNA)
    steps = _turn(case_id, 3)["steps"]
    assert steps["rate"]["result"]["total"]["amount"] == "487000"
    second = case_decisions.view(case_id, "premium")["second_person"]  # the renewal's lower limit
    assert (second["needed"], second["above"]) == (True, {"amount": "100000", "currency": "HUF"})
    with pytest.raises(case_decisions.AnotherDeciderNeeded):
        _decide(case_id, "premium", "accept", ANNA)
    _decide(case_id, "premium", "accept", BELA)
    _turn(case_id, 3)
    shown = letters.view(case_id, "letter")
    draft = shown["draft"]
    assert draft["subject"] == "Biztosítás megújítása – Minta Kereskedő Kft." and "megújítási ajánlatunkat" in draft["body"]
    case_views.act(case_id, "letter", "accept", ANNA, values={**draft, "expected_basis": shown["basis"]})
    _turn(case_id)
    case_views.start_step(case_id, "send", ANNA)
    state = _turn(case_id)
    [placed] = list(out.rglob("*.eml"))
    message = email.message_from_bytes(placed.read_bytes(), policy=default)
    assert message["Subject"] == "Biztosítás megújítása – Minta Kereskedő Kft." and state["status"] == cases.CLOSED
    assert [a.get_filename().endswith(".docx") for a in message.iter_attachments()] == [True]
    assert all(trace.replay(r) == r["outcome"] for r in trace.rows(case_id=case_id))


def test_a_risk_the_rules_refer_goes_to_the_full_quote(renewal) -> None:
    start, _out = renewal
    case_id = start("referred")
    assert engine.state(case_id)["steps"]["evaluate"]["result"]["verdict"] == "refer"
    choices = {c["code"]: c["allowed"] for c in case_decisions.view(case_id, "risk")["choices"]}
    assert choices == {"renew": False, "full_quote": True}  # the renewal's stricter rule
    with pytest.raises(case_decisions.CaseDecisionError):
        _decide(case_id, "risk", "renew", ANNA)
    _decide(case_id, "risk", "full_quote", ANNA, note="a claims history to look at")
    state = _turn(case_id)
    with store.connect() as c:
        row = cases.find_case_in(c, case_id)
    assert (state["status"], row["status"]) == (cases.CLOSED, cases.CLOSED)
    # U1 (the owner's decision of 2026-10-28): the closed renewal offers the full quote from its documents
    [offer] = case_views.view(case_id)["follow_ups"]
    assert (offer["pack"], offer["case_id"]) == ("insurance_offer", None)
    full = process_runtime.follow_up(case_id, "insurance_offer", actor=ANNA)
    with store.connect() as c:
        started = cases.find_case_in(c, full)
    assert started["data"]["pack"] == "insurance_offer" and started["data"]["scope"] == row["data"]["scope"]


def test_it_is_composed_of_the_quote_s_capabilities_only() -> None:
    renewal, offer = process_packs.load("insurance_renewal"), process_packs.load("insurance_offer")
    assert {s.uses for s in renewal.steps} <= {s.uses for s in offer.steps}
    assert [s.id for s in renewal.steps] != [s.id for s in offer.steps]  # another structure: no register, no wait
    named = [p for p in (ROOT / "jav").rglob("*.py") if "insurance_renewal" in p.read_text(encoding="utf-8")]
    assert named == []  # no code of its own
