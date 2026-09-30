"""Jev keret-kör 1 / közös eval-modul (BACKLOG 3) - offline, szintetikus runs/*.jsonl sorokon.

Flow-független bemenet: a négy golden-formátum (invoice S/G, detect, email) + determinizmus-fájlok -> egységes
ítélet-lista (`Judgment`), ebből: kérdésenkénti pontosság és sáv-eloszlás, kalibrációs görbe (bin-enként P vs.
találat, ECE), top-prob vs. confidence, policy-sáv újraértékelés hívás nélkül, determinizmus-szórás.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jav import eval_report as er


def _write(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def runs(tmp_path: Path) -> dict[str, Path]:
    s_rows = [
        {"case_id": "c1", "arm": "S", "run_no": 1, "route": "auto", "review_reasons": [],
         "scores": {"supplier_name": True, "gross_total": True, "invoice_number": False},
         "picks": {"supplier_name": {"label": "A", "confidence": 0.99, "n_options": 3, "top3": {"A": 0.99, "none": 0.01}},
                   "gross_total": {"label": "100", "confidence": 0.90, "n_options": 4, "top3": {"100": 0.9, "90": 0.05, "none": 0.05}},
                   "invoice_number": {"label": "X-1", "confidence": 0.70, "n_options": 2, "top3": {"X-1": 0.55, "X-2": 0.45}}},
         "verdicts": None},
        {"case_id": "c2", "arm": "S", "run_no": 1, "route": "human", "review_reasons": ["pick:low_conf:gross_total:0.50"],
         "scores": {"supplier_name": True, "gross_total": False, "invoice_number": True},
         "picks": {"supplier_name": {"label": "B", "confidence": 0.95, "n_options": 3, "top3": {"B": 0.96, "none": 0.04}},
                   "gross_total": {"label": "5", "confidence": 0.50, "n_options": 4, "top3": {"5": 0.5, "6": 0.4, "none": 0.1}},
                   "invoice_number": {"label": "Y", "confidence": 0.90, "n_options": 2, "top3": {"Y": 0.9, "Z": 0.1}}},
         "verdicts": None},
    ]
    g_rows = [
        {"case_id": "c1", "arm": "G", "run_no": 1, "route": "human", "review_reasons": ["jev:off_target:gross_total:0.80"],
         "scores": {"supplier_name": True, "gross_total": False}, "picks": {},
         "verdicts": {"flags": {"supplier_name": {"off_target": 0.05, "incomplete": 0.50}, "gross_total": {"off_target": 0.80},
                                "supplier_address": {"incomplete": 0.68}},
                      "doc_flags": {"parties_swapped": 0.03}, "unsupported": [], "model": "jev-1.13.0"}},
    ]
    d_rows = [
        {"case_id": "d1", "expected": "invoice_hu", "got": "invoice_hu", "confidence": 0.99, "issuer_hu": 0.97, "language": "hu", "status": "done", "top3": {"invoice_hu": 1.0, "receipt": 0.0}},
        {"case_id": "d2", "expected": "invoice_foreign", "got": "invoice_hu", "confidence": 0.62, "issuer_hu": 0.5, "language": "en", "status": "done", "top3": {"invoice_hu": 0.55, "invoice_foreign": 0.45}},
        {"case_id": "d3", "expected": "contract", "got": "contract", "confidence": 0.55, "issuer_hu": 0.1, "language": "hu", "status": "done", "top3": {"contract": 0.5, "other": 0.3, "unknown": 0.2}},
    ]
    e_rows = [
        {"case_id": "e1", "expected": "szamlakuldes", "got": "szamlakuldes", "confidence": 0.99, "signals": {"requires_action": 0.82, "tone_urgent": 0.05}, "next_flow": "m1:detect", "top3": {"szamlakuldes": 1.0, "other": 0.0}},
        {"case_id": "e2", "expected": "other", "got": "business_correspondence", "confidence": 0.70, "signals": {"requires_action": 0.5, "tone_urgent": 0.9}, "next_flow": "human:inbox", "top3": {"business_correspondence": 0.6, "other": 0.4}},
    ]
    det_rows = [
        {"case_id": "e1", "expected": "szamlakuldes", "got": "szamlakuldes", "confidence": 0.99, "signals": {"requires_action": 0.80, "tone_urgent": 0.05}, "next_flow": "m1:detect", "top3": {"szamlakuldes": 1.0}},
        {"case_id": "e1", "expected": "szamlakuldes", "got": "szamlakuldes", "confidence": 0.97, "signals": {"requires_action": 0.90, "tone_urgent": 0.06}, "next_flow": "m1:detect", "top3": {"szamlakuldes": 0.98}},
        {"case_id": "e2", "expected": "other", "got": "other", "confidence": 0.70, "signals": {"requires_action": 0.5, "tone_urgent": 0.9}, "next_flow": "human:inbox", "top3": {"other": 0.6}},
        {"case_id": "e2", "expected": "other", "got": "business_correspondence", "confidence": 0.65, "signals": {"requires_action": 0.5, "tone_urgent": 0.9}, "next_flow": "human:inbox", "top3": {"business_correspondence": 0.55}},
    ]
    return {
        "S": _write(tmp_path / "20260101_000000_golden_S.jsonl", s_rows),
        "G": _write(tmp_path / "20260101_000001_golden_G.jsonl", g_rows),
        "detect": _write(tmp_path / "20260101_000002_detect_golden.jsonl", d_rows),
        "email": _write(tmp_path / "20260101_000003_email_golden.jsonl", e_rows),
        "email_det": _write(tmp_path / "20260101_000004_email_determinism.jsonl", det_rows),
    }


def test_flow_is_inferred_from_filename(runs: dict[str, Path]):
    assert er.flow_of(runs["S"]) == "invoice_S" and er.flow_of(runs["G"]) == "invoice_G"
    assert er.flow_of(runs["detect"]) == "doc_detect" and er.flow_of(runs["email"]) == "email_intent"
    assert er.flow_of(runs["email_det"]) == "email_intent" and er.is_determinism(runs["email_det"]) and not er.is_determinism(runs["email"])
    assert er.flow_of(Path("x/whatever.jsonl")) is None


def test_judgments_cover_every_question(runs: dict[str, Path]):
    js = er.judgments_from_file(runs["S"])
    assert len(js) == 6 and {j.kind for j in js} == {"choice"} and {j.callsite for j in js} == {"invoice.pick", "invoice.pick.high_stakes"}
    j = next(j for j in js if j.case_id == "c1" and j.question == "invoice_number")
    assert j.correct is False and j.confidence == 0.70 and j.top_prob == 0.55 and j.second_prob == 0.45 and j.route_recorded == "auto"
    assert next(j for j in js if j.question == "gross_total" and j.case_id == "c1").callsite == "invoice.pick.high_stakes"

    jg = er.judgments_from_file(runs["G"])
    assert {j.kind for j in jg} == {"noul"} and len(jg) == 5  # 4 mező-flag + 1 doc_flag
    off = next(j for j in jg if j.question == "off_target" and j.field == "gross_total")
    assert off.p == 0.80 and off.expected == "yes" and off.label == "yes" and off.correct is True  # a mező rossz, a flag jelzett
    inc = next(j for j in jg if j.question == "incomplete" and j.field == "supplier_name")
    assert inc.expected == "no" and inc.label == "yes" and inc.correct is False  # p 0.5 -> "yes" címke, de a mező jó
    assert next(j for j in jg if j.field == "supplier_address").expected is None  # nem pontozott mező: nincs igazság
    assert next(j for j in jg if j.question == "parties_swapped").field is None

    jd = er.judgments_from_file(runs["detect"])
    assert len(jd) == 6  # doc_type Choice + issuer_hu Noul esetenként
    d2 = next(j for j in jd if j.case_id == "d2" and j.kind == "choice")
    assert d2.correct is False and d2.callsite == "detect.doc_type" and d2.second_prob == 0.45

    je = er.judgments_from_file(runs["email"])
    assert len(je) == 6  # intent + 2 signal esetenként
    assert next(j for j in je if j.case_id == "e2" and j.kind == "choice").route_recorded == "human:inbox"
    assert {j.callsite for j in je if j.kind == "noul"} == {"email.signal"}


def test_bands_and_per_question_summary(runs: dict[str, Path]):
    js = er.judgments_from_file(runs["S"]) + er.judgments_from_file(runs["G"])
    assert er.band_of(next(j for j in js if j.case_id == "c1" and j.question == "invoice_number")) == "uncertain"  # rés 0.10 < 0.20
    assert er.band_of(next(j for j in js if j.case_id == "c2" and j.question == "gross_total")) == "human"
    assert er.band_of(next(j for j in js if j.case_id == "c1" and j.question == "supplier_name" and j.kind == "choice")) == "auto"
    assert er.band_of(next(j for j in js if j.kind == "noul" and j.question == "incomplete" and j.field == "supplier_name")) == "uncertain"

    rows = er.per_question(js)
    gt = next(r for r in rows if r["flow"] == "invoice_S" and r["question"] == "gross_total")
    assert gt["n"] == 2 and gt["correct"] == 1 and gt["bands"] == {"auto": 1, "human": 1} and gt["acc_by_band"] == {"auto": 1.0, "human": 0.0}
    inc = next(r for r in rows if r["flow"] == "invoice_G" and r["question"] == "incomplete")
    assert inc["n"] == 2 and inc["n_scored"] == 1  # supplier_address flag igazság nélkül


def test_calibration_bins_and_ece():
    js = [er.Judgment(flow="f", case_id=str(i), question="q", kind="choice", callsite="email.intent", label="a", expected="a" if ok else "b",
                      correct=ok, confidence=c, top_prob=c, second_prob=None, p=None, route_recorded=None)
          for i, (c, ok) in enumerate([(0.95, True), (0.96, True), (0.97, True), (0.98, False), (0.55, True), (0.58, False), (0.75, True), (0.72, False)])]
    cal = er.calibration(js, key="top_prob")
    b95 = next(b for b in cal["bins"] if b["lo"] == 0.95)
    assert b95["n"] == 4 and b95["hit_rate"] == 0.75 and abs(b95["mean_p"] - 0.965) < 1e-9
    b50 = next(b for b in cal["bins"] if b["lo"] == 0.5)
    assert b50["n"] == 2 and b50["hit_rate"] == 0.5
    assert cal["n"] == 8 and 0 < cal["ece"] < 0.3
    assert er.calibration([], key="top_prob")["n"] == 0


def test_policy_reeval_counts_cases_that_would_change(runs: dict[str, Path]):
    js = er.judgments_from_file(runs["S"]) + er.judgments_from_file(runs["detect"]) + er.judgments_from_file(runs["email"])
    pe = er.policy_reeval(js)
    s = next(r for r in pe if r["flow"] == "invoice_S")
    assert s["cases"] == 2 and s["cases_human"] == 1 and s["cases_uncertain_only"] == 1  # c1: invoice_number rés 0.10 -> ha uncertain_review, review lenne
    assert s["uncertain_only_accuracy"] == 0.0  # c1 invoice_number pontatlan: a sáv jelzése helyes
    d = next(r for r in pe if r["flow"] == "doc_detect")
    assert d["cases"] == 3 and d["cases_human"] == 1 and d["cases_uncertain_only"] == 1  # d3 human (0.55), d2 uncertain (rés 0.10)
    e = next(r for r in pe if r["flow"] == "email_intent")
    assert e["cases_uncertain_only"] == 0  # e2: rés 0.20, nem < 0.20


def test_determinism_summary(runs: dict[str, Path]):
    js = er.judgments_from_file(runs["email_det"])
    rows = er.determinism_summary(js)
    intent = next(r for r in rows if r["question"] == "intent")
    assert intent["cases"] == 2 and intent["flips"] == 1 and intent["std_max"] > 0
    ra = next(r for r in rows if r["question"] == "requires_action")
    assert ra["flips"] == 0 and abs(ra["std_max"] - 0.05) < 1e-9


def test_markdown_report_has_every_section(runs: dict[str, Path]):
    md = er.report_markdown(list(runs.values()))
    for h in ("## Források", "## Kérdésenként", "## Kalibráció", "## top-prob vs. confidence", "## Policy-sáv újraértékelés", "## Determinizmus"):
        assert h in md, h
    assert "invoice_S" in md and "email_intent" in md and "ECE" in md
    assert "uncertain_review" in md  # a döntéshez szükséges kapcsoló neve szerepel


def test_default_inputs_pick_latest_per_pattern(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(er, "RUNS_DIR", tmp_path)
    for name in ("20260101_000000_golden_S.jsonl", "20260102_000000_golden_S.jsonl", "20260101_000000_detect_golden.jsonl", "20260101_000000_email_determinism.jsonl"):
        (tmp_path / name).write_text("", encoding="utf-8")
    picked = [p.name for p in er.default_inputs()]
    assert "20260102_000000_golden_S.jsonl" in picked and "20260101_000000_golden_S.jsonl" not in picked
    assert "20260101_000000_detect_golden.jsonl" in picked and "20260101_000000_email_determinism.jsonl" in picked
