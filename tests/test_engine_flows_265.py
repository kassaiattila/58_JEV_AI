"""265 (plan L, L4a): the flows read their engine from the registry, not a JEV on/off switch.

Until 265 every flow carried `jev: bool`, so a third engine would have been read as JEV. Now a flow's state names its
engine (`configs/engines.json`): the questions go to that engine's judgement service, its answers are judged by its
bands, and a question it cannot answer is its own to-do and end state. A state saved before 265 (`jev`) resumes with
the engine its switch meant. OpenAI Decisions answers through the real adapter over a local stand-in of its endpoint:
no paid call. Synthetic documents and emails only.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx2
import pytest
from burr.core import State
from openai import OpenAI

from jav.ai import engine as engines
from jav.ai import jev as jev_mod
from jav.ai.decisions import DecisionsAdapter
from jav.core import store
from jav.domains.email import flow_email
from jav.domains.email.emails import EmailMessage
from jav.flows import flow_detect, persistence
from tests.pdfgen import INVOICE_LINES, write_text_pdf

PREFERRED = ("invoice_hu", "szamlakuldes")


class Decisions:
    """A local stand-in of the Decisions endpoint that answers any request: a choice gets the preferred option (else
    its first), a predicate `probability`, a score its middle level. `status` other than 200 answers every request
    with that error."""

    def __init__(self, *, confidence: float = 0.97, probability: float = 0.95, status: int = 200) -> None:
        self.confidence, self.probability, self.status = confidence, probability, status
        self.requests: list[dict] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        assert request.url.path.endswith("/decisions")
        body = json.loads(request.content)
        self.requests.append(body)
        if self.status != 200:
            return httpx2.Response(self.status, json={"error": {"message": "synthetic", "type": "server_error",
                                                                "code": "synthetic_outage"}})
        answers = []
        for q in body["questions"]:
            if q["type"] == "choice":
                values = [c["value"] for c in q["choices"]]
                pick = next((v for v in PREFERRED if v in values), values[0])
                rest = round((1 - self.confidence) / max(len(values) - 1, 1), 6)
                answers.append({"type": "choice", "name": q["name"], "choice": pick, "confidence": self.confidence,
                                "probabilities": [{"value": v, "probability": self.confidence if v == pick else rest}
                                                  for v in values]})
            elif q["type"] == "predicate":
                answers.append({"type": "predicate", "name": q["name"], "probability": self.probability})
            else:
                n = len(q["levels"])
                answers.append({"type": "score", "name": q["name"], "score": 1.0, "confidence": 0.7, "probabilities": [
                    {"value": i, "label": str(i), "probability": 0.7 if i == 1 else round(0.3 / max(n - 1, 1), 6)}
                    for i in range(n)]})
        return httpx2.Response(200, json={
            "model": "gpt-6-luna", "answers": answers,
            "usage": {"input_tokens": 900, "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                      "output_tokens": 0, "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": 900}})

    def adapter(self, tmp_path: Path) -> DecisionsAdapter:
        client = OpenAI(api_key="synthetic-offline-key", max_retries=0,
                        http_client=httpx2.Client(transport=httpx2.MockTransport(self)))
        return DecisionsAdapter(client=client, cache_dir=tmp_path / "decisions-cache")


class _NoJev:
    """JEV's place in a test where JEV must not be asked."""
    judge = "jev"

    def ask(self, *a, **k):
        raise AssertionError("JEV was asked by a flow whose engine is OpenAI Decisions")


@pytest.fixture()
def pdf(tmp_path: Path):
    with store.use_store(tmp_path / "e.sqlite"):
        yield write_text_pdf(tmp_path / "invoice.pdf", INVOICE_LINES)


def _detect(tmp_path: Path, pdf: Path, service: Decisions):
    with jev_mod.use_adapter(service.adapter(tmp_path)), jev_mod.use_adapter(_NoJev()):
        return flow_detect.run_detect(str(pdf), run_id="r1", engine="decisions")


# --- the type recognition -------------------------------------------------------------------------------------------

def test_the_decisions_engine_asks_decisions_and_names_itself(tmp_path, pdf):
    service = Decisions()
    st = _detect(tmp_path, pdf, service)
    assert st.final_status == "done" and st.engine == "decisions"
    assert st.result.doc_type == "invoice_hu" and st.result.engine == "decisions"
    assert len(service.requests) >= 1 and service.requests[0]["model"] == "gpt-6-luna"
    with store.connect() as c:
        rows = c.execute("SELECT provider, model FROM ledger").fetchall()
        inputs = json.loads(c.execute("SELECT inputs FROM decision_trace WHERE point='detect.doc_type'").fetchone()[0])
    assert rows and {(r["provider"], r["model"]) for r in rows} == {("openai_decisions", "gpt-6-luna")}
    assert inputs["engine"] == "decisions"


def test_a_detailed_type_the_service_chose_names_the_service(tmp_path, pdf):
    st = _detect(tmp_path, pdf, Decisions())
    if st.detail is not None and st.detail.method not in ("issuer", "single", "anchors", "no_candidate"):
        assert st.detail.method == "decisions"


def test_an_unanswered_question_is_the_services_own_to_do_and_end_state(tmp_path, pdf):
    st = _detect(tmp_path, pdf, Decisions(status=500))
    assert st.result is None and st.final_status == "decisions_unavailable"
    assert any(r.startswith("decisions_unavailable:") for r in st.review_reasons)
    assert not any(r.startswith("jev_unavailable:") for r in st.review_reasons)


def test_the_engine_bands_fall_back_to_jevs_until_one_of_their_own_is_set():
    from jav.ai import policy

    decisions = engines.get("decisions")
    assert policy.band_name(decisions.band_key("detect.doc_type")) == policy.band_name("detect.doc_type")
    assert policy.band_name(decisions.band_key("email.intent")) == policy.band_name("email.intent")
    assert flow_detect.doc_type_rule({"engine": "decisions", "doc_type": "invoice_hu", "confidence": 0.97,
                                      "probabilities": {"invoice_hu": 0.97}, "measured": True}) == \
        flow_detect.doc_type_rule({"engine": "jev", "doc_type": "invoice_hu", "confidence": 0.97,
                                   "probabilities": {"invoice_hu": 0.97}, "measured": True})


# --- the email intent ---------------------------------------------------------------------------------------------

def _message(tmp_path: Path, pdf: Path) -> EmailMessage:
    return EmailMessage(message_id="m-265@example.test", sender="billing@example.test", subject="Invoice",
                        body="Please find our invoice attached.", attachments=[{"filename": pdf.name, "path": str(pdf)}])


def test_an_email_and_its_attachment_are_recognised_with_the_same_engine(tmp_path, pdf):
    service = Decisions()
    with jev_mod.use_adapter(service.adapter(tmp_path)), jev_mod.use_adapter(_NoJev()):
        app = flow_email.build_app(message=_message(tmp_path, pdf), engine="decisions")
        _, _, state = app.run(halt_after=flow_email.TERMINALS)
    st = state.data
    assert st.engine == "decisions" and st.result is not None and st.result.engine == "decisions"
    assert st.message.attachments[0].doc_type == "invoice_hu"  # the attachment was recognised, by Decisions
    assert len(service.requests) >= 2


def test_an_email_whose_service_does_not_answer_ends_in_its_state(tmp_path, pdf):
    with jev_mod.use_adapter(Decisions(status=500).adapter(tmp_path)), jev_mod.use_adapter(_NoJev()):
        app = flow_email.build_app(message=_message(tmp_path, pdf), engine="decisions", detect_attachments=False)
        _, _, state = app.run(halt_after=flow_email.TERMINALS)
    assert state.data.final_status == "decisions_unavailable"
    assert any(r.startswith("decisions_unavailable:") for r in state.data.review_reasons)


# --- a state saved before 265 -------------------------------------------------------------------------------------

@pytest.mark.parametrize("partition", [flow_detect.PARTITION, flow_email.PARTITION, "native", "invoice"])
@pytest.mark.parametrize("flag, engine", [(True, "jev"), (False, "gpt")])
def test_a_state_saved_with_the_jev_switch_resumes_with_its_engine(partition, flag, engine):
    # the extraction and native flows register their renamed keys on import
    import jav.flows.flow
    import jav.flows.flow_native  # noqa: F401

    loaded = persistence._renamed(partition, State({"jev": flag, "run_id": "r"}))
    assert loaded.get_all() == {"engine": engine, "run_id": "r"}


def test_a_state_with_both_keys_keeps_its_engine():
    loaded = persistence._renamed(flow_detect.PARTITION, State({"jev": True, "engine": "decisions"}))
    assert loaded.get_all() == {"engine": "decisions"}


# --- the worker and the native reader -----------------------------------------------------------------------------

@pytest.mark.parametrize("params, engine, arm", [
    ({"engine": "decisions", "arm": "S"}, "decisions", "S"),
    ({"jev": "off", "arm": "S"}, "gpt", "G"),
    ({"jev": "on", "arm": "auto"}, "jev", "auto"),
    ({}, "jev", "auto"),
])
def test_the_worker_hands_a_flow_the_settings_engine(monkeypatch, params, engine, arm):
    from jav import flows
    from jav.runtime import worker

    assert worker._requested_arm(params) == arm
    built = {}

    class _Spec:
        build = staticmethod(lambda mod, b: built.update(engine=b.engine) or SimpleNamespace())

        def load(self):
            return SimpleNamespace(TERMINALS=["done"])

    monkeypatch.setattr(flows, "get", lambda name: _Spec())
    worker._build({"flow": "doc_detect"}, params, "x.pdf", "app", None)
    assert built["engine"] == engine


def test_the_native_limits_reserve_for_the_engines_service():
    from jav.ai import native_processing

    assert set(native_processing.estimate_limits({"engine": "decisions"}).provider_limits_usd) == {"openai", "openai_decisions"}
    assert set(native_processing.estimate_limits({"jev": "on"}).provider_limits_usd) == {"openai", "jev"}
    assert set(native_processing.estimate_limits({"jev": "off"}).provider_limits_usd) == {"openai"}
    limits = native_processing.estimate_limits({"engine": "decisions"}).provider_limits_usd
    assert Decimal(0) < limits["openai_decisions"] < Decimal("0.1")


# --- the measurements ---------------------------------------------------------------------------------------------

def test_a_decisions_measurement_is_a_flow_of_its_own_in_the_report():
    from jav.evals import eval_report

    assert eval_report.flow_of("20261101_120000_detect_golden_decisions.jsonl") == "doc_detect_decisions"
    assert eval_report.flow_of("20261101_120000_detect_determinism_decisions.jsonl") == "doc_detect_decisions"
    assert eval_report.flow_of("20261101_120000_invoice_hu_golden_G_decisions.jsonl") == "invoice_G_decisions"
    assert eval_report.flow_of("20261101_120000_detect_determinism.jsonl") == "doc_detect"  # JEV's as before
    [j, *_] = eval_report.EXTRACTORS["doc_detect_decisions"]({"case_id": "c", "got": "invoice_hu", "expected": "invoice_hu",
                                                              "confidence": 0.9, "top3": {"invoice_hu": 0.9}, "status": "done"})
    assert j.flow == "doc_detect_decisions" and j.callsite == "detect.doc_type.decisions"


def test_a_decisions_measurement_spends_from_the_openai_budget():
    from jav.evals import goldens

    options = goldens.Options(engine="decisions", budget_usd=Decimal("0.5"))
    assert options.answering_budget("the types") == (Decimal("0.5"), None)
    refused, why = goldens.Options(engine="decisions", jev_budget_usd=Decimal("0.5")).answering_budget("the types")
    assert refused is None and "--budget-usd" in why
    assert goldens.Options(engine="jev", jev_budget_usd=Decimal("0.2")).answering_budget("x") == (Decimal("0.2"), None)


def test_the_s_path_takes_any_engine_with_a_judgement_service(capsys):
    from jav.cli import cli_options

    assert not cli_options.s_without_judge(SimpleNamespace(arm="S", engine="decisions"))
    assert cli_options.s_without_judge(SimpleNamespace(arm="S", engine="gpt"))
    assert "judgement service" in capsys.readouterr().out


def test_the_commands_offer_the_registrys_engines():
    import argparse

    from jav.cli import cli_options

    p = argparse.ArgumentParser()
    cli_options.engine_args(p, measurement=True)
    assert p.parse_args(["--engine", "decisions"]).engine == "decisions"
    assert p.parse_args([]).engine == engines.default_id()
    assert p.parse_args(["--no-jev"]).engine == "gpt"


def test_a_determinism_keeps_the_engines_saved_answers_untouched(tmp_path):
    adapter = Decisions().adapter(tmp_path)
    with jev_mod.use_adapter(adapter):
        assert adapter.write_cache
        with engines.no_cache_write("decisions"):
            assert not adapter.write_cache
        assert adapter.write_cache
        with engines.no_cache_write("gpt"):
            assert adapter.write_cache  # an engine without a judgement service has no saved answers to keep


def test_a_decision_recorded_before_265_is_read_with_its_engine():
    from jav.ai import policy

    assert engines.of_record({"jev": False}).id == "gpt" and engines.of_record({"jev": True}).id == "jev"
    assert engines.of_record({"engine": "decisions", "jev": True}).id == "decisions"
    old = {"arm": "G", "jev": False, "has_record": True}
    new = {"arm": "G", "engine": "gpt", "has_record": True}
    assert engines.of_record(old).judged == engines.of_record(new).judged is False
    assert policy.issuer_mismatch_reason("invoice_hu", None, 0.01, engine="gpt") == \
        "detect:issuer_mismatch:invoice_hu"  # GPT's own issuer band (`.gpt`), as before 265
    assert policy.issuer_mismatch_reason("invoice_hu", None, 0.01, engine="decisions") is None  # not a listed engine
