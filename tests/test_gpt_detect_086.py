"""086: type recognition with GPT, for processing without JEV (backlog item F-jev, step K4).

Synthetic documents and a stand-in model only; no paid call. The stand-in returns token log-probabilities shaped like
the OpenAI chat API's, so the probability arithmetic is tested on the exact structure the live call returns.
"""

import json
import math
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from jav import detect_detail, detect_gpt, flow_detect, store
from jav.adapters import jev as jev_mod
from jav.doc_types import DOC_TYPE_KEYS
from jav.runtime import calls
from tests.pdfgen import INVOICE_LINES, write_text_pdf


def _tokens(*parts):
    """`parts`: (text, logprob, [(alternative, logprob), ...]) -> the provider's logprob list."""
    out = []
    for text, lp, alts in parts:
        top = [{"token": text, "logprob": lp}] + [{"token": a, "logprob": alp} for a, alp in alts]
        out.append({"token": text, "logprob": lp, "bytes": list(text.encode("utf-8")), "top_logprobs": top})
    return out


# {"doc_type":"invoice_hu","issuer_is_hungarian":"yes","language":"hu"}
DETECT_TOKENS = _tokens(
    ('{"', 0.0, []), ("doc", 0.0, []), ("_type", 0.0, []), ('":"', 0.0, []),
    ("invoice", -0.01, [("utility", -5.0)]), ("_h", -0.2, [("_foreign", -1.8)]), ('u', 0.0, []),
    ('","', 0.0, []), ("issuer", 0.0, []), ("_is", 0.0, []), ("_h", 0.0, []), ("ungarian", 0.0, []), ('":"', 0.0, []),
    ("yes", -0.05, [("no", -3.0)]), ('","', 0.0, []), ("language", 0.0, []), ('":"', 0.0, []),
    ("hu", -0.02, [("en", -4.0)]), ('"}', 0.0, []),
)


def _content(tokens):
    return "".join(t["token"] for t in tokens)


class _FakeAgent:
    """A GPT stand-in: parses the content of the given tokens through the requested output model."""

    def __init__(self, output_model, tokens, *, logprobs=True):
        self.output_model, self.tokens, self.logprobs, self.prompts = output_model, tokens, logprobs, []

    def run_sync(self, prompt, **_kw):
        self.prompts.append(prompt)
        details = {"logprobs": self.tokens} if self.logprobs else {}
        out = self.output_model.model_validate(json.loads(_content(self.tokens)))
        return SimpleNamespace(output=out, usage=SimpleNamespace(input_tokens=900, output_tokens=30),
                               response=SimpleNamespace(model_name="gpt-5.4-mini", provider_details=details))


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "a.sqlite"):
        yield tmp_path


def _factory(tokens, seen=None, **kw):
    def make(output_model, instructions):
        agent = _FakeAgent(output_model, tokens, **kw)
        if seen is not None:
            seen.append((instructions, agent))
        return agent
    return make


# --- the probability of a chosen option from the token log-probabilities ------------------------------------


def test_the_chosen_option_gets_the_product_of_its_token_probabilities():
    choice, conf, probs = detect_gpt.field_probabilities(DETECT_TOKENS, "doc_type", list(DOC_TYPE_KEYS))
    assert choice == "invoice_hu"
    assert conf == pytest.approx(math.exp(-0.01 - 0.2), abs=1e-4)
    # the branch at "_h" -> "_foreign" leads to invoice_foreign only; "utility" to utility_bill_hu only
    assert probs["invoice_foreign"] == pytest.approx(math.exp(-0.01 - 1.8), abs=1e-4)
    assert probs["utility_bill_hu"] == pytest.approx(math.exp(-5.0), abs=1e-4)
    assert max(probs, key=probs.get) == "invoice_hu"


def test_a_yes_no_answer_and_the_language_get_their_probabilities_too():
    assert detect_gpt.field_probabilities(DETECT_TOKENS, "issuer_is_hungarian", ["yes", "no"])[1] == pytest.approx(math.exp(-0.05), abs=1e-4)
    choice, conf, probs = detect_gpt.field_probabilities(DETECT_TOKENS, "language", ["hu", "en", "de", "other"])
    assert choice == "hu" and conf == pytest.approx(math.exp(-0.02), abs=1e-4) and "en" in probs


def test_without_log_probabilities_the_confidence_is_unknown_not_zero():
    assert detect_gpt.field_probabilities([], "doc_type", list(DOC_TYPE_KEYS)) == (None, None, {})


def test_the_short_description_is_the_first_clause():
    assert detect_gpt.short_description("Hungarian utility bill (közüzemi számla): electricity, gas") == "Hungarian utility bill (közüzemi számla)"
    assert detect_gpt.short_description("Contract or terms; ÁSZF. More text") == "Contract or terms"
    assert detect_gpt.short_description("No separator here") == "No separator here"


# --- detection --------------------------------------------------------------------------------------------


def _pdf(tmp_path):
    from jav.pdf import read_pdf

    path = write_text_pdf(tmp_path / "szamla.pdf", INVOICE_LINES)
    return path, read_pdf(path)


def test_detect_returns_the_type_the_issuer_and_the_language_with_probabilities(isolated):
    path, pdf = _pdf(isolated)
    seen = []
    with detect_gpt.use_agent_factory(_factory(DETECT_TOKENS, seen)):
        r = detect_gpt.detect(pdf, path, run_id="r1")
    assert r.engine == "gpt" and r.measured
    assert r.doc_type == "invoice_hu" and r.confidence == pytest.approx(math.exp(-0.21), abs=1e-3)
    assert r.issuer_hu == pytest.approx(math.exp(-0.05), abs=1e-3)
    assert r.language == "hu"
    instructions, agent = seen[0]
    # the short description of every type and `unknown` are offered; the long description is not sent
    assert "Hungarian utility bill (közüzemi számla)" in instructions and "unknown" in instructions
    assert "electricity (villamos energia" not in instructions
    assert "L01:" in agent.prompts[0]  # the same document excerpt as the JEV question


def test_detect_without_log_probabilities_is_marked_unmeasured(isolated):
    path, pdf = _pdf(isolated)
    with detect_gpt.use_agent_factory(_factory(DETECT_TOKENS, logprobs=False)):
        r = detect_gpt.detect(pdf, path, run_id="r1")
    assert r.doc_type == "invoice_hu" and not r.measured and r.confidence == 0.0


def test_detect_in_a_run_goes_through_the_call_log_and_the_openai_budget(isolated):
    path, pdf = _pdf(isolated)
    calls.set_budget("run-1", "openai", Decimal("1"))
    with detect_gpt.use_agent_factory(_factory(DETECT_TOKENS)), calls.use_run(budget_scope="run-1"):
        detect_gpt.detect(pdf, path, run_id="run-1")
    rows = calls.journal("run-1")
    assert [(r["provider"], r["status"]) for r in rows] == [("openai", "succeeded")]
    assert rows[0]["step_id"].startswith("openai:detect:")


def test_detect_without_an_openai_budget_sends_nothing(isolated):
    path, pdf = _pdf(isolated)
    seen = []
    with detect_gpt.use_agent_factory(_factory(DETECT_TOKENS, seen)), calls.use_run(budget_scope="run-2"), \
            pytest.raises(calls.BudgetExceeded):
        detect_gpt.detect(pdf, path, run_id="run-2")
    assert not seen or not seen[0][1].prompts


# --- the detailed type ------------------------------------------------------------------------------------


def test_detail_choice_without_jev_uses_gpt_when_the_anchors_do_not_decide(isolated, monkeypatch):
    monkeypatch.setattr(detect_detail, "candidates", lambda broad: ["foldgaz_szamla", "viz_szamla"])
    tokens = _tokens(('{"', 0.0, []), ("detail", 0.0, []), ("_type", 0.0, []), ('":"', 0.0, []),
                     ("viz", -0.1, [("fold", -2.5)]), ("_sz", 0.0, []), ("amla", 0.0, []), ('"}', 0.0, []))
    with detect_gpt.use_agent_factory(_factory(tokens)):
        d = detect_detail.resolve("utility_bill_hu", "szamla szoveg kulcsszo nelkul", jev=None, run_id="r1",
                                  chooser=detect_gpt.choose_detail)
    assert d.method == "gpt" and d.key == "viz_szamla"
    assert d.confidence == pytest.approx(math.exp(-0.1), abs=1e-3)
    assert d.probabilities["foldgaz_szamla"] == pytest.approx(math.exp(-2.5), abs=1e-3)


def test_detail_choice_none_leaves_the_type_open(isolated, monkeypatch):
    monkeypatch.setattr(detect_detail, "candidates", lambda broad: ["foldgaz_szamla", "viz_szamla"])
    tokens = _tokens(('{"', 0.0, []), ("detail", 0.0, []), ("_type", 0.0, []), ('":"', 0.0, []), ("none", -0.3, []), ('"}', 0.0, []))
    with detect_gpt.use_agent_factory(_factory(tokens)):
        d = detect_detail.resolve("utility_bill_hu", "szoveg", jev=None, run_id="r1", chooser=detect_gpt.choose_detail)
    assert d.method == "gpt" and d.key is None


# --- the detection flow without JEV -----------------------------------------------------------------------


class _NoJev:
    def ask(self, *a, **k):
        raise AssertionError("JEV was called on the path without JEV")


DETAIL_TOKENS = _tokens(('{"', 0.0, []), ("detail", 0.0, []), ("_type", 0.0, []), ('":"', 0.0, []),
                        ("invoice", 0.0, []), ("_hu", -0.05, [("_out", -3.2)]), ('"}', 0.0, []))


def _by_question(output_model, instructions):
    """The stand-in answers each question with its own tokens: the detailed type, or the coarse detection."""
    return _FakeAgent(output_model, DETAIL_TOKENS if "detail_type" in output_model.model_fields else DETECT_TOKENS)


def test_detection_flow_without_jev_never_asks_jev(tmp_path, monkeypatch):
    # anchors that do not decide between the two Hungarian invoice packs: the detailed type is GPT's question too
    monkeypatch.setattr(detect_detail, "anchor_score", lambda detect, text: (True, 1.0))
    path = write_text_pdf(tmp_path / "szamla.pdf", INVOICE_LINES)
    with store.use_store(tmp_path / "f.sqlite"), detect_gpt.use_agent_factory(_by_question), jev_mod.use_adapter(_NoJev()):
        st = flow_detect.run_detect(str(path), run_id="r1", jev=False)
    assert st.final_status == "done"
    assert st.result.engine == "gpt" and st.result.doc_type == "invoice_hu"
    assert st.detail.method == "gpt" and st.detail.key == "invoice_hu"
    assert st.detail.probabilities["invoice_out"] == pytest.approx(math.exp(-3.2), abs=1e-3)
    assert st.detail_reasons == []


def test_detection_flow_without_jev_turns_a_gpt_failure_into_a_to_do(tmp_path):
    path = write_text_pdf(tmp_path / "szamla.pdf", INVOICE_LINES)

    class _Broken:
        def run_sync(self, *a, **k):
            raise RuntimeError("synthetic outage")

    with store.use_store(tmp_path / "f.sqlite"), detect_gpt.use_agent_factory(lambda m, i: _Broken()), \
            jev_mod.use_adapter(_NoJev()):
        st = flow_detect.run_detect(str(path), run_id="r1", jev=False)
    assert st.result is None and st.final_status == "gpt_unavailable"
    assert "detect:gpt_failed:RuntimeError" in st.review_reasons


def test_detection_flow_without_jev_flags_an_unmeasured_type(tmp_path):
    path = write_text_pdf(tmp_path / "szamla.pdf", INVOICE_LINES)
    with store.use_store(tmp_path / "f.sqlite"), detect_gpt.use_agent_factory(_factory(DETECT_TOKENS, logprobs=False)), \
            jev_mod.use_adapter(_NoJev()):
        st = flow_detect.run_detect(str(path), run_id="r1", jev=False)
        open_reasons = [r["reason"] for r in store.review_open_reasons("document", st.doc_id)]
    assert st.uncertain
    assert any(r.startswith("detect:confidence_unavailable:invoice_hu") for r in open_reasons), open_reasons
