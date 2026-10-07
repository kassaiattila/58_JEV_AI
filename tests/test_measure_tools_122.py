"""122 (GPT round, A5): measurement tools - the detection measurement on a local case list, a budget for the engine
that answers, the injection probe's detection-only and GPT arms, and extraction on a case list. Stand-ins only; no
paid calls."""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from jav import evals_detect
from jav.experiments import document_injection_probe as probe
from jav.experiments import extract_cases


def _case_file(tmp_path, rows):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"cases": rows}), encoding="utf-8")
    return path


def test_a_case_file_lists_paths_with_their_expected_types(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    path = _case_file(tmp_path, [{"case_id": "c1", "path": str(pdf), "expected": "receipt", "expected_detail": "invoice_foreign"},
                                 {"case_id": "c2", "path": str(tmp_path / "missing.pdf"), "expected": "other"}])
    cases = evals_detect.load_case_file(path)
    assert [(c.case_id, c.expected, c.expected_detail) for c in cases] == [("c1", "receipt", "invoice_foreign")]


class _Spy:
    def __init__(self):
        self.limits, self.calls = [], []

    def measurement(self, scope, limits):
        from contextlib import nullcontext

        self.limits.append(limits)
        return nullcontext(scope)


def _fake_state(doc_type, detail):
    result = SimpleNamespace(doc_type=doc_type, confidence=0.9, issuer_hu=0.1, language="en", probabilities={doc_type: 0.9},
                             parent=None, parent_prob=None, engine="jev", measured=True, call=SimpleNamespace(cost_usd=0.0))
    return SimpleNamespace(result=result, detail=SimpleNamespace(key=detail, method="issuer", confidence=None),
                           final_status="done", review_reasons=[], detail_reasons=[])


@pytest.mark.parametrize("jev, provider", [(True, "jev"), (False, "openai")])
def test_the_budget_goes_to_the_engine_that_answers(tmp_path, monkeypatch, jev, provider):
    from jav import flow_detect
    from jav.runtime import calls

    spy = _Spy()
    monkeypatch.setattr(calls, "measurement", spy.measurement)
    monkeypatch.setattr(flow_detect, "run_detect", lambda path, **kw: _fake_state("receipt", "invoice_foreign"))
    monkeypatch.setattr(evals_detect, "RUNS_DIR", tmp_path)
    case = evals_detect.DetectCase(case_id="c1", path=tmp_path / "a.pdf", expected="receipt", old_type="",
                                   expected_detail="invoice_foreign")
    rows = evals_detect.detect_golden(jev=jev, budget_usd=Decimal("0.07"), cases=[case], label="targeted")
    assert spy.limits == [{provider: Decimal("0.07")}]
    assert rows[0]["expected_detail"] == "invoice_foreign" and rows[0]["detail_type"] == "invoice_foreign"
    assert list(tmp_path.glob("*_detect_targeted*.jsonl"))


def test_the_probe_can_run_detection_only_and_without_jev():
    cfg = probe.load_config()
    only = probe.plan(cfg, flows={"detect"})
    assert only and {c.flow for c in only} == {"detect"}
    without = probe.plan(cfg, jev=False)
    assert "S" not in {c.flow for c in without}  # the S path needs JEV
    est = probe.estimate(cfg, flows={"detect"}, jev=False)
    assert est["jev"] == 0 and est["openai"] > 0


def test_extraction_on_a_case_list_uses_the_expected_pack_and_a_budget(tmp_path, monkeypatch):
    from jav import flow
    from jav.runtime import calls

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    path = _case_file(tmp_path, [{"case_id": "c1", "path": str(pdf), "expected": "receipt", "expected_detail": "invoice_foreign"}])
    seen, spy = [], _Spy()
    monkeypatch.setattr(calls, "measurement", spy.measurement)

    def fake_run_one(source_path, case_id, arm, **kw):
        seen.append((case_id, arm, kw["doc_type"], kw["jev"]))
        return SimpleNamespace(run_id="r1", invoice=None, needs_review=True, review_reasons=["x"], final_status="done")

    monkeypatch.setattr(flow, "run_one", fake_run_one)
    rows = extract_cases.run(path, arm="G", jev=False, budget_usd=Decimal("0.03"), out_dir=tmp_path)
    assert seen == [("x122-c1", "G", "invoice_foreign", False)]
    assert spy.limits == [{"openai": Decimal("0.03")}]
    assert rows[0]["needs_review"] is True and (tmp_path / "rows.jsonl").exists()
