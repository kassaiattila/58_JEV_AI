"""A measurement names the cases its budget left without a result (123, T-measurement-reservation).

In 122 a call's worst-case reservation (0.10-0.19 USD) did not fit a narrowing budget, so
four documents got no result and silently counted against the measurement.
"""
from jav import cli
from jav.eval_report import budget_skips, report_budget_skips


def rows():
    return [
        {"case_id": "ok", "review_reasons": ["pick:low_conf:total:0.4"]},
        {"case_id": "gpt", "review_reasons": ["llm:failed:BudgetExceeded"]},
        {"case_id": "jev", "review_reasons": ["jev_unavailable:budget_exceeded"]},
        {"case_id": "detect", "review_reasons": ["detect:gpt_failed:BudgetExceeded"]},
        {"case_id": "raised", "error": "BudgetExceeded: max cost 0.19 over the remaining 0.08"},
        # Azure has no measurement budget by design; the document itself was processed.
        {"case_id": "ocr", "review_reasons": ["ocr:escalation_blocked:budget_exceeded"]},
    ]


def test_budget_skips_names_every_provider_but_not_a_blocked_escalation():
    assert budget_skips(rows()) == ["gpt", "jev", "detect", "raised"]


def test_report_prints_a_warning_and_returns_the_count(capsys):
    assert report_budget_skips(rows()) == 4
    out = capsys.readouterr().out
    assert "Skipped for the budget: 4 of 6 cases" in out and "gpt, jev, detect, raised" in out
    assert report_budget_skips(rows()[:1]) == 0
    assert capsys.readouterr().out == ""


def test_golden_command_exits_with_three_when_the_budget_skipped_a_case(monkeypatch):
    import argparse

    from jav import evals
    monkeypatch.setattr(evals, "golden", lambda *a, **k: rows())
    args = argparse.Namespace(store=None, arm="G", tracker=False, no_cache=False, type="invoice_hu",
                              no_jev=True, budget_usd="0.05")
    assert cli.cmd_golden(args) == 3
    monkeypatch.setattr(evals, "golden", lambda *a, **k: rows()[:1])
    assert cli.cmd_golden(args) == 0


def test_detect_golden_command_exits_with_three_when_the_budget_skipped_a_case(monkeypatch):
    import argparse

    from jav import evals_detect
    monkeypatch.setattr(evals_detect, "detect_golden", lambda *a, **k: rows())
    args = argparse.Namespace(store=None, cases=None, no_cache=False, no_jev=True, keys_only=False, budget_usd="0.05")
    assert cli.cmd_detect_golden(args) == 3
