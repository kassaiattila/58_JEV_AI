"""160-D (F-csak-gpt L7): the eval report reads the measurements made without JEV, offline, on synthetic rows.

The GPT measurements have their own file names (`*_detect_golden_gpt.jsonl`, `*_email_golden_gpt.jsonl`,
`*_golden_G_nojev.jsonl`, their determinism files and the injection probe). Their judgments use the GPT call sites
(`.gpt`), so the bands are the ones the flows apply without JEV. A GPT field's confidence is a judgment of its own
kind, calibrated against the field's score; its band is `auto` at or above the policy's `review_below`. The silent
errors section counts the wrong answers the recorded run left without a to-do.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jav import eval_report as er
from jav import policy


def _write(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def gpt_runs(tmp_path: Path) -> dict[str, Path]:
    detect = [
        {"case_id": "d1", "expected": "invoice_hu", "got": "invoice_hu", "confidence": 1.0, "issuer_hu": 1.0, "status": "done",
         "top3": {"invoice_hu": 1.0}, "engine": "gpt", "measured": True, "review_reasons": []},
        # wrong with full confidence and no to-do: a silent error
        {"case_id": "d2", "expected": "invoice_foreign", "got": "invoice_hu", "confidence": 0.99, "issuer_hu": 0.9, "status": "done",
         "top3": {"invoice_hu": 0.99, "invoice_foreign": 0.01}, "engine": "gpt", "measured": True, "review_reasons": []},
        # wrong, but the type contradiction rule left a to-do
        {"case_id": "d3", "expected": "receipt", "got": "invoice_hu", "confidence": 0.995, "issuer_hu": 0.1, "status": "done",
         "top3": {"invoice_hu": 0.995}, "engine": "gpt", "measured": True, "review_reasons": ["detect:issuer_mismatch"]},
        # an answer without log-probabilities: no confidence, so a to-do band and no calibration point
        {"case_id": "d4", "expected": "contract", "got": "contract", "confidence": 1.0, "issuer_hu": None, "status": "done",
         "top3": {"contract": 1.0}, "engine": "gpt", "measured": False, "review_reasons": []},
    ]
    email = [
        {"case_id": "e1", "expected": "szamlakuldes", "got": "szamlakuldes", "confidence": 1.0, "top3": {"szamlakuldes": 1.0},
         "signals": {"requires_action": 0.99, "prompt_injection": 0.001},
         "scores": {"urgency": {"level": 1, "score": 1.0, "confidence": 0.99, "probabilities": {"1": 0.99, "2": 0.01}}},
         "next_flow": "m1:detect", "review_reasons": [], "engine": "gpt", "measured": True},
        # wrong in the to-do band: the flow's own low-confidence to-do is not among the row's reasons, the band tells
        {"case_id": "e2", "expected": "other", "got": "business_correspondence", "confidence": 0.55,
         "top3": {"business_correspondence": 0.55, "other": 0.45}, "signals": {"requires_action": 0.4}, "scores": {},
         "next_flow": "human:inbox", "review_reasons": [], "engine": "gpt", "measured": True},
    ]
    g_rows = [
        {"case_id": "g1", "doc_type": "invoice_hu", "flow_label": "invoice_G", "arm": "G", "run_no": 1,
         "review_reasons": ["gpt:low_conf:net_total:0.97"],
         "scores": {"supplier_name": True, "net_total": False, "gross_total": False, "due_date": None},
         "field_confidence": {"supplier_name": 0.999, "net_total": 0.9707, "gross_total": 0.999, "due_date": 1.0,
                              "buyer_address": 0.56, "line_items": None},
         "verdicts": {"flags": {}, "doc_flags": {}, "unsupported": [], "model": None, "source": "code"}},
        # the budget left the case without an extraction: nothing to judge
        {"case_id": "g2", "doc_type": "invoice_hu", "flow_label": "invoice_G", "arm": "G", "run_no": 1,
         "review_reasons": ["llm:failed:BudgetExceeded"], "scores": {"supplier_name": None},
         "field_confidence": {"supplier_name": None}, "verdicts": None},
    ]
    foreign = [
        {"case_id": "f1", "doc_type": "invoice_foreign", "flow_label": "invoice_foreign_G", "arm": "G", "run_no": 1,
         "review_reasons": [], "scores": {"invoice_number": True}, "field_confidence": {"invoice_number": 0.99},
         "verdicts": {"flags": {}, "doc_flags": {}, "source": "code"}},
    ]
    g_det = [dict(g_rows[0], run_no=1), dict(g_rows[0], run_no=2, field_confidence={**g_rows[0]["field_confidence"], "net_total": 0.5})]
    return {
        "detect": _write(tmp_path / "20261017_000000_detect_golden_gpt.jsonl", detect),
        "detect_keys": _write(tmp_path / "20261017_000001_detect_golden_gpt_keys.jsonl", detect[:1]),
        "detect_det": _write(tmp_path / "20261017_000002_detect_determinism_gpt.jsonl", detect[:1] * 2),
        "email": _write(tmp_path / "20261017_000003_email_golden_gpt.jsonl", email),
        "email_det": _write(tmp_path / "20261017_000004_email_determinism_gpt.jsonl", email[:1] * 2),
        "probe": _write(tmp_path / "20261017_000005_email_injection_probe_gpt.jsonl",
                        [dict(email[0], variant="clean"), dict(email[0], variant="tampered")]),
        "G": _write(tmp_path / "20261017_000006_golden_G_nojev.jsonl", g_rows),
        "foreign": _write(tmp_path / "20261017_000007_invoice_foreign_golden_G_nojev.jsonl", foreign),
        "G_det": _write(tmp_path / "20261017_000008_determinism_G_n2_nojev.jsonl", g_det),
    }


def test_gpt_files_have_flows_of_their_own(gpt_runs: dict[str, Path]):
    assert er.flow_of(gpt_runs["detect"]) == "doc_detect_gpt" == er.flow_of(gpt_runs["detect_keys"])
    assert er.flow_of(gpt_runs["detect_det"]) == "doc_detect_gpt" and er.is_determinism(gpt_runs["detect_det"])
    assert er.flow_of(gpt_runs["email"]) == "email_intent_gpt" == er.flow_of(gpt_runs["email_det"])
    assert er.flow_of(gpt_runs["probe"]) == "email_injection_probe_gpt"
    assert er.flow_of(gpt_runs["G"]) == "invoice_G_gpt" == er.flow_of(gpt_runs["foreign"]) == er.flow_of(gpt_runs["G_det"])
    # the JEV files keep their flows
    assert er.flow_of(Path("20261017_000000_detect_golden.jsonl")) == "doc_detect"
    assert er.flow_of(Path("20261017_000000_detect_determinism.jsonl")) == "doc_detect"
    assert er.flow_of(Path("20261017_000000_email_determinism.jsonl")) == "email_intent"
    assert er.flow_of(Path("20261017_000000_golden_G.jsonl")) == "invoice_G"


def test_gpt_detect_and_email_use_the_gpt_call_sites(gpt_runs: dict[str, Path]):
    js = er.judgments_from_file(gpt_runs["detect"])
    types = [j for j in js if j.question == "doc_type"]
    assert {j.callsite for j in types} == {"detect.doc_type.gpt"} and {j.flow for j in js} == {"doc_detect_gpt"}
    assert {j.callsite for j in js if j.question == "issuer_is_hungarian"} == {"detect.issuer_is_hungarian.gpt"}
    unmeasured = next(j for j in types if j.case_id == "d4")
    assert unmeasured.confidence is None and unmeasured.top_prob is None and er.band_of(unmeasured) == "human"
    assert [j.correct for j in types] == [True, False, False, True]
    assert [j.flagged for j in types] == [False, False, True, True]
    es = er.judgments_from_file(gpt_runs["email"])
    assert {j.callsite for j in es if j.question == "intent"} == {"email.intent.gpt"}
    assert {j.callsite for j in es if j.kind == "noul"} == {"email.signal.gpt"}
    assert {j.callsite for j in es if j.kind == "score"} == {"email.urgency.gpt"}
    assert {j.flow for j in es} == {"email_intent_gpt"}
    # a GPT call site resolves to the band set the flow applies
    assert policy.band_name("detect.doc_type.gpt") == "gpt_detect" and policy.band_name("email.intent.gpt") == "gpt_intent"


def test_gpt_injection_probe_keeps_the_known_truth(gpt_runs: dict[str, Path]):
    js = er.judgments_from_file(gpt_runs["probe"])
    probe = {j.case_id: j for j in js if j.question == "prompt_injection"}
    assert {j.flow for j in js} == {"email_injection_probe_gpt"}
    assert probe["e1/clean"].expected == "no" and probe["e1/clean"].correct is True
    assert probe["e1/tampered"].expected == "yes" and probe["e1/tampered"].correct is False


def test_gpt_field_confidence_is_a_judgment_with_the_field_score_as_truth(gpt_runs: dict[str, Path]):
    js = er.judgments_from_file(gpt_runs["G"])
    by_field = {j.question: j for j in js}
    # a field without a measured confidence is not a judgment; the budget-skipped case has none
    assert set(by_field) == {"supplier_name", "net_total", "gross_total", "due_date", "buyer_address"}
    assert {j.kind for j in js} == {"field"} and {j.flow for j in js} == {"invoice_G_gpt"}
    assert {j.callsite for j in js} == {"invoice.gpt_field"}
    assert by_field["net_total"].correct is False and by_field["net_total"].flagged is True
    assert by_field["gross_total"].correct is False and by_field["gross_total"].flagged is False
    assert by_field["due_date"].correct is None and by_field["buyer_address"].correct is None
    assert by_field["net_total"].confidence == by_field["net_total"].top_prob == 0.9707
    review_below = policy.GPT_FIELD_CONFIDENCE["review_below"]
    assert er.band_of(by_field["gross_total"]) == "auto" and er.band_of(by_field["net_total"]) == "human"
    assert review_below == 0.98  # the band follows the policy, whatever its value
    foreign = er.judgments_from_file(gpt_runs["foreign"])
    assert {j.flow for j in foreign} == {"invoice_foreign_G_gpt"}


def test_gpt_field_calibration_uses_the_fine_bins_near_one(gpt_runs: dict[str, Path]):
    js = er.judgments_from_file(gpt_runs["G"])
    cal = er.calibration(js, key="confidence", edges=er.GPT_CAL_BIN_EDGES)
    assert cal["n"] == 3  # the three fields with a known truth
    top = [b for b in cal["bins"] if b["n"]]
    assert [(b["lo"], b["hi"], b["n"]) for b in top] == [(0.95, 0.98, 1), (0.99, 1.0, 2)]


def test_silent_errors_count_the_wrong_answers_without_a_to_do(gpt_runs: dict[str, Path]):
    js = (er.judgments_from_file(gpt_runs["detect"]) + er.judgments_from_file(gpt_runs["email"])
          + er.judgments_from_file(gpt_runs["G"]))
    rows = {r["flow"]: r for r in er.silent_errors(js)}
    assert rows["doc_detect_gpt"] == {"flow": "doc_detect_gpt", "scored": 4, "wrong": 2, "flagged": 1, "silent": 1,
                                      "silent_cases": ["d2 doc_type"]}
    assert rows["email_intent_gpt"]["wrong"] == 1 and rows["email_intent_gpt"]["silent"] == 0
    assert rows["invoice_G_gpt"]["scored"] == 3 and rows["invoice_G_gpt"]["silent_cases"] == ["g1 gross_total"]


def test_gpt_determinism_counts_field_spread(gpt_runs: dict[str, Path]):
    rows = {r["question"]: r for r in er.determinism_summary(er.judgments_from_file(gpt_runs["G_det"]))}
    assert rows["net_total"]["runs"] == 2 and rows["net_total"]["std_max"] > 0
    assert rows["supplier_name"]["std_max"] == 0


def test_report_has_the_gpt_sections(gpt_runs: dict[str, Path]):
    md = er.report_markdown(list(gpt_runs.values()))
    assert "doc_detect_gpt" in md and "invoice_G_gpt" in md and "email_intent_gpt" in md
    assert "## Silent errors" in md and "d2 doc_type" in md
    assert "**invoice_G_gpt · confidence**" in md and "| 0.95–0.98 | 1 |" in md
    assert "**invoice_G_gpt · top_prob**" not in md  # a field's confidence and top probability are the same number


def test_default_inputs_include_the_latest_gpt_measurements(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for name in ("20261001_detect_golden_gpt.jsonl", "20261002_detect_golden_gpt.jsonl", "20261002_golden_G_nojev.jsonl",
                 "20261002_email_golden_gpt.jsonl", "20261002_detect_golden.jsonl"):
        (tmp_path / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(er, "RUNS_DIR", tmp_path)
    names = {p.name for p in er.default_inputs()}
    assert {"20261002_detect_golden_gpt.jsonl", "20261002_golden_G_nojev.jsonl", "20261002_email_golden_gpt.jsonl",
            "20261002_detect_golden.jsonl"} <= names
    assert "20261001_detect_golden_gpt.jsonl" not in names
