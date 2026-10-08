"""127: the S path's golden measurement and the email intent measurement take a hard JEV budget (`--jev-budget-usd`).

Until now only an OpenAI budget could be given, so a paid JEV measurement ran without a call log or a stop at the
sub-budget. With a JEV budget only, OpenAI and Azure get none, so they cannot be called. Offline: stand-in flows.
"""

import argparse
from decimal import Decimal

from jav import cli, evals, evals_email, store
from jav.runtime import calls


def _budgets(scope_prefix: str) -> dict[str, str]:
    with store.connect() as c:
        rows = c.execute("SELECT provider, limit_usd FROM budgets WHERE scope LIKE ?", (f"{scope_prefix}%",)).fetchall()
    return {p: v for p, v in rows}


def test_golden_with_a_jev_budget_runs_under_that_budget_only(monkeypatch, tmp_path):
    scopes = []
    monkeypatch.setattr(evals, "load_cases", lambda type_key: [type("Case", (), {"pdf": tmp_path / "a.pdf", "case_id": "c1"})()])
    monkeypatch.setattr(evals, "_state_row", lambda case, state, run_no, seconds, pack: {"case_id": case.case_id})
    monkeypatch.setattr(evals, "_dump_rows", lambda rows, name: tmp_path / "x.jsonl")
    monkeypatch.setattr(evals, "print_golden_report", lambda rows, arm, pack: None)

    def run_one(*args, **kwargs):
        scopes.append(calls.current().budget_scope)
        return type("State", (), {"final_status": "done", "route": "auto"})()

    with store.use_store(tmp_path / "g.sqlite"):
        evals.golden("S", run_one, jev_budget_usd=Decimal("0.40"))
        assert len(scopes) == 1 and scopes[0].startswith("measure-")
        assert _budgets(scopes[0]) == {"jev": "0.40"}


def test_golden_without_any_budget_keeps_the_free_path(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(evals, "load_cases", lambda type_key: [type("Case", (), {"pdf": tmp_path / "a.pdf", "case_id": "c1"})()])
    monkeypatch.setattr(evals, "_state_row", lambda case, state, run_no, seconds, pack: {"case_id": case.case_id})
    monkeypatch.setattr(evals, "_dump_rows", lambda rows, name: tmp_path / "x.jsonl")
    monkeypatch.setattr(evals, "print_golden_report", lambda rows, arm, pack: None)

    def run_one(*args, **kwargs):
        seen.append(calls.current())
        return type("State", (), {"final_status": "done", "route": "auto"})()

    with store.use_store(tmp_path / "g.sqlite"):
        evals.golden("S", run_one)
    assert seen == [None]


def test_golden_command_passes_the_jev_budget(monkeypatch):
    got = {}
    monkeypatch.setattr(evals, "golden", lambda *a, **k: got.update(k) or [])
    args = argparse.Namespace(store=None, arm="S", tracker=False, no_cache=False, type="invoice_hu", no_jev=False,
                              budget_usd=None, jev_budget_usd="0.40")
    assert cli.cmd_golden(args) == 0
    assert got["jev_budget_usd"] == Decimal("0.40") and got["budget_usd"] is None


def test_the_verifier_probe_with_a_jev_budget_runs_under_that_budget_only(monkeypatch, tmp_path):
    scopes = []
    monkeypatch.setattr(evals, "_verifier_probe", lambda cases, use_cache, type_key: scopes.append(calls.current()) or [])
    with store.use_store(tmp_path / "v.sqlite"):
        evals.verifier_probe(type_key="invoice_foreign", jev_budget_usd=Decimal("0.05"))
        evals.verifier_probe(type_key="invoice_foreign")
        assert scopes[0] is not None and scopes[0].measurement and _budgets(scopes[0].budget_scope) == {"jev": "0.05"}
        assert scopes[1] is None  # without a budget: the earlier, free path


def test_email_golden_with_a_jev_budget_runs_under_that_budget_only(monkeypatch, tmp_path):
    scopes = []
    monkeypatch.setattr(evals_email, "_cases", lambda limit: [type("Case", (), {"case_id": "c1"})()])

    def run_case(case, *, use_cache, jev):
        scopes.append(calls.current().budget_scope)
        return {"case_id": case.case_id, "got": "other", "confidence": 1.0}

    monkeypatch.setattr(evals_email, "_run_case", run_case)
    monkeypatch.setattr(evals_email, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(evals_email, "print_email_report", lambda rows: None)
    with store.use_store(tmp_path / "e.sqlite"):
        evals_email.email_golden(jev_budget_usd=Decimal("0.03"))
        assert len(scopes) == 1
        assert _budgets(scopes[0]) == {"jev": "0.03"}
