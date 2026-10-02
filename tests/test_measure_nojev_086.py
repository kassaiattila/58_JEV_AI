"""086: the measurement commands of processing without JEV (backlog item F-jev, M-c). Synthetic documents and stand-in
models only; no paid call. The paid measurement runs under a hard OpenAI budget (the owner's sub-budget); JEV and
Azure get none, so they cannot be called."""

from decimal import Decimal
from pathlib import Path

import pytest

from jav import detect_gpt, evals, evals_detect, store
from jav.adapters import jev as jev_mod
from jav.runtime import calls
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_gpt_detect_086 import DETAIL_TOKENS, DETECT_TOKENS, _FakeAgent


class _NoJev:
    def ask(self, *a, **k):
        raise AssertionError("JEV was called in a measurement without JEV")


@pytest.fixture()
def golden_env(tmp_path: Path, monkeypatch):
    pdf = write_text_pdf(tmp_path / "szamla.pdf", INVOICE_LINES)
    monkeypatch.setattr(evals_detect, "load_detect_cases",
                        lambda: [evals_detect.DetectCase(case_id="c1", path=pdf, expected="invoice_hu", old_type="invoice_hu")])
    monkeypatch.setattr(evals_detect, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(evals_detect, "print_detect_report", lambda rows: None)
    seen = []

    def factory(output_model, instructions):
        seen.append(instructions)
        return _FakeAgent(output_model, DETAIL_TOKENS if "detail_type" in output_model.model_fields else DETECT_TOKENS)

    with store.use_store(tmp_path / "m.sqlite"), jev_mod.use_adapter(_NoJev()), detect_gpt.use_agent_factory(factory):
        yield {"tmp": tmp_path, "seen": seen}


def test_detect_golden_without_jev_runs_under_the_measurement_budget(golden_env):
    rows = evals_detect.detect_golden(jev=False, budget_usd=Decimal("1.00"))
    assert [(r["got"], r["engine"], r["measured"]) for r in rows] == [("invoice_hu", "gpt", True)]
    assert list((golden_env["tmp"] / "runs").glob("*_detect_golden_gpt.jsonl"))
    with store.connect() as c:
        scopes = {r["budget_scope"]: r["provider"] for r in c.execute("SELECT budget_scope, provider FROM invocations")}
        limits = {(r["scope"], r["provider"]) for r in c.execute("SELECT scope, provider FROM budgets")}
    assert set(scopes.values()) == {"openai"} and all(s.startswith("measure-") for s in scopes)
    assert {p for _s, p in limits} == {"openai"}  # no JEV or Azure budget: those cannot be called


def test_the_keys_only_variant_offers_the_bare_type_keys(golden_env):
    evals_detect.detect_golden(jev=False, descriptions=False, budget_usd=Decimal("1.00"))
    detect_instructions = next(i for i in golden_env["seen"] if "Document types:" in i)
    assert "- invoice_hu\n" in detect_instructions and "- invoice_hu:" not in detect_instructions
    assert list((golden_env["tmp"] / "runs").glob("*_detect_golden_gpt_keys.jsonl"))
    assert "- invoice_hu:" in detect_gpt.detect_instructions()  # the switch is undone after the measurement


def test_a_spent_budget_stops_the_calls_and_says_so(golden_env):
    rows = evals_detect.detect_golden(jev=False, budget_usd=Decimal("0.000001"))
    assert rows[0]["got"] is None and "detect:gpt_failed:BudgetExceeded" in rows[0]["review_reasons"]
    with store.connect() as c:  # refused at the reservation: the request was never sent
        assert c.execute("SELECT COUNT(*) FROM invocations").fetchone()[0] == 0


def test_golden_without_jev_asks_the_flow_for_the_code_check_and_names_the_run(monkeypatch, tmp_path):
    seen, names = [], []
    monkeypatch.setattr(evals, "load_cases", lambda type_key: [type("Case", (), {"pdf": tmp_path / "a.pdf", "case_id": "c1"})()])
    monkeypatch.setattr(evals, "_state_row", lambda case, state, run_no, seconds, pack: {"case_id": case.case_id})
    monkeypatch.setattr(evals, "_dump_rows", lambda rows, name: names.append(name) or tmp_path / "x.jsonl")
    monkeypatch.setattr(evals, "print_golden_report", lambda rows, arm, pack: None)

    def run_one(*args, **kwargs):
        seen.append(kwargs.get("jev", True))
        assert calls.current() is not None and calls.current().budget_scope.startswith("measure-")
        return type("State", (), {"final_status": "done", "route": "auto"})()

    with store.use_store(tmp_path / "g.sqlite"):
        evals.golden("G", run_one, jev=False, budget_usd=Decimal("0.60"))
    assert seen == [False] and names == ["golden_G_nojev"]
