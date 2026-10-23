"""160 (review AI-8): a command that can make paid calls never runs without a budget.

`detect`, `detect-corpus`, `email`, `email-inbox`, `run`, the determinism commands, and the golden measurements without
`--budget-usd` ran outside the call log: a JEV, OpenAI or Azure call had no budget to stop at (a large scanned folder
could escalate to Azure without limit). Now every such command runs under a measurement budget: the sub-budgets given
(`--jev-budget-usd`, `--budget-usd` for OpenAI; Azure never), and without any only earlier answers count (the JEV
cache): a live call is refused and becomes a to-do. Stand-ins only, no paid call.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from jav import cli, evals, evals_email
from jav.core import store
from jav.adapters import jev as jev_mod
from jav.core import calls
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_runtime_worker import FakeClient


class _Seen(Exception):
    pass


def _budgets(scope: str) -> dict[str, Decimal]:
    return {p: Decimal(str(v["limit_usd"])) for p, v in calls.budget_usage(scope)["providers"].items()}


COMMANDS = [
    (["run", "x.pdf"], "jav.flow.run_one"),
    (["detect", "x.pdf"], "jav.flow_detect.run_detect"),
    (["detect-corpus", "folder"], "jav.evals_detect.detect_corpus"),
    (["detect-determinism"], "jav.evals_detect.detect_determinism"),
    (["determinism", "--arm", "S"], "jav.evals.determinism"),
    (["email", "folder"], "jav.domains.email.flow_email.run_email"),
    (["email-inbox", "folder"], "jav.evals_email.email_inbox"),
    (["email-determinism"], "jav.evals_email.email_determinism"),
]


@pytest.mark.parametrize(("argv", "target"), COMMANDS, ids=[c[0][0] for c in COMMANDS])
def test_without_a_budget_a_paid_command_cannot_call_a_provider(argv, target, monkeypatch, tmp_path, capsys):
    seen = []

    def record(*_a, **_k):
        seen.append(calls.current())
        raise _Seen

    monkeypatch.setattr(target, record)
    with store.use_store(tmp_path / "c.sqlite"):
        with pytest.raises(_Seen):
            cli.main(argv)
        ctx = seen[0]
        assert ctx is not None and ctx.measurement and _budgets(ctx.budget_scope) == {}
    assert "No budget given" in capsys.readouterr().out


@pytest.mark.parametrize(("argv", "target"), COMMANDS, ids=[c[0][0] for c in COMMANDS])
def test_with_budgets_a_paid_command_spends_from_them_only(argv, target, monkeypatch, tmp_path):
    seen = []

    def record(*_a, **_k):
        seen.append(calls.current())
        raise _Seen

    monkeypatch.setattr(target, record)
    with store.use_store(tmp_path / "c.sqlite"):
        with pytest.raises(_Seen):
            cli.main([*argv, "--jev-budget-usd", "0.02", "--budget-usd", "0.03"])
        assert _budgets(seen[0].budget_scope) == {"jev": Decimal("0.02"), "openai": Decimal("0.03")}


def test_detect_without_a_budget_answers_from_the_cache_only(tmp_path, capsys):
    pdf = write_text_pdf(tmp_path / "invoice.pdf", INVOICE_LINES)
    client = FakeClient()
    adapter = jev_mod.JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")
    with store.use_store(tmp_path / "c.sqlite"), jev_mod.use_adapter(adapter):
        assert cli.main(["detect", str(pdf)]) == 0
        assert client.calls == 0 and "jev_unavailable" in capsys.readouterr().out  # refused, not sent
        assert cli.main(["detect", str(pdf), "--jev-budget-usd", "0.05"]) == 0
        assert client.calls > 0
        calls_before = client.calls
        assert cli.main(["detect", str(pdf)]) == 0  # the earlier answer, from the cache, without a budget
        assert client.calls == calls_before


def _golden_stand_ins(monkeypatch, tmp_path):
    monkeypatch.setattr(evals, "load_cases", lambda type_key: [type("Case", (), {"pdf": tmp_path / "a.pdf", "case_id": "c1"})()])
    monkeypatch.setattr(evals, "_state_row", lambda case, state, run_no, seconds, pack: {"case_id": case.case_id})
    monkeypatch.setattr(evals, "_dump_rows", lambda rows, name: tmp_path / "x.jsonl")
    monkeypatch.setattr(evals, "print_golden_report", lambda rows, arm, pack: None)


def test_the_golden_measurement_without_a_budget_uses_earlier_answers_only(monkeypatch, tmp_path):
    seen = []
    _golden_stand_ins(monkeypatch, tmp_path)

    def run_one(*args, **kwargs):
        seen.append(calls.current())
        return type("State", (), {"final_status": "done", "route": "auto"})()

    with store.use_store(tmp_path / "g.sqlite"):
        evals.golden("S", run_one, type_key="invoice_hu")
        assert seen[0].measurement and _budgets(seen[0].budget_scope) == {}


def test_the_other_measurements_without_a_budget_use_earlier_answers_only(monkeypatch, tmp_path):
    scopes = []
    monkeypatch.setattr(evals, "_verifier_probe", lambda cases, use_cache, type_key: scopes.append(calls.current()) or [])
    monkeypatch.setattr(evals_email, "_cases", lambda limit: [type("Case", (), {"case_id": "c1"})()])
    monkeypatch.setattr(evals_email, "_run_case", lambda case, *, use_cache, jev: scopes.append(calls.current()) or
                        {"case_id": case.case_id, "got": "other", "confidence": 1.0})
    monkeypatch.setattr(evals_email, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(evals_email, "print_email_report", lambda rows: None)
    with store.use_store(tmp_path / "m.sqlite"):
        evals.verifier_probe(type_key="invoice_foreign")
        evals_email.email_golden()
        assert all(s is not None and s.measurement and _budgets(s.budget_scope) == {} for s in scopes) and len(scopes) == 2


def test_a_measurement_name_used_again_keeps_no_earlier_budget(tmp_path):
    """Two measurements of the same name started within one second (the name carries the second) used to share the
    budget rows: the one without a budget inherited the other's, and could spend. A rerun with the same budget still
    continues the same scope, so it cannot spend the sub-budget twice."""
    with store.use_store(tmp_path / "m.sqlite"):
        with calls.measurement("measure-same", {"jev": Decimal("0.05")}) as first:
            assert _budgets(first) == {"jev": Decimal("0.05")}
        with calls.measurement("measure-same", {}) as second:
            assert second != first and calls.current().budget_scope == second and _budgets(second) == {}
        with calls.measurement("measure-same", {"jev": Decimal("0.05")}) as again:
            assert again == first
