"""160-D (plan F-csak-gpt, Sz5): `--engine jev|gpt` on every command that asks AI; `--no-jev` stays as its alias.

A processing command (one document, a corpus walk, one email, an inbox walk, the M2 flow on one PDF) follows the
application's AI engine when it names none, as a work package does; a measurement (golden sets, determinism, the
injection probe) measures JEV and GPT unless told otherwise, so that its run file says what it measured. The S path
needs JEV, so `--engine gpt` with `--arm S` is refused before anything runs.

No AI call: the functions behind the commands are replaced by recorders.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jav import app_settings, cli, evals, evals_detect, evals_email, flow, flow_detect, flow_email, store


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "c.sqlite"):
        yield tmp_path


class Recorder:
    def __init__(self, result=None):
        self.calls: list[dict] = []
        self.result = result

    def __call__(self, *args, **kwargs):
        self.calls.append(kwargs)
        return self.result

    @property
    def jev(self):
        return self.calls[-1].get("jev", True)


def _detect_state():
    return SimpleNamespace(final_status="done", doc_id="d" * 64, run_id="r", result=None)


@pytest.mark.parametrize("argv, expected", [
    ([], True), (["--engine", "gpt"], False), (["--engine", "jev"], True), (["--no-jev"], False),
])
def test_detect_takes_the_engine(db, monkeypatch, capsys, argv, expected):
    rec = Recorder(_detect_state())
    monkeypatch.setattr(flow_detect, "run_detect", rec)
    assert cli.main(["detect", "x.pdf", *argv]) == 0
    assert rec.jev is expected


def test_a_processing_command_follows_the_applications_engine(db, monkeypatch, capsys):
    app_settings.save_engine_default("gpt", actor="tester")
    rec = Recorder(_detect_state())
    monkeypatch.setattr(flow_detect, "run_detect", rec)
    assert cli.main(["detect", "x.pdf"]) == 0
    assert rec.jev is False
    assert cli.main(["detect", "x.pdf", "--engine", "jev"]) == 0
    assert rec.jev is True


def test_a_measurement_measures_jev_and_gpt_unless_told(db, monkeypatch, capsys):
    """The application's engine does not change what a measurement measures."""
    app_settings.save_engine_default("gpt", actor="tester")
    golden = Recorder([])
    monkeypatch.setattr(evals_detect, "detect_golden", golden)
    assert cli.main(["detect-golden"]) == 0
    assert golden.jev is True
    assert cli.main(["detect-golden", "--engine", "gpt"]) == 0
    assert golden.jev is False


@pytest.mark.parametrize("command, target, attr", [
    (["detect-corpus", "root"], evals_detect, "detect_corpus"),
    (["detect-determinism"], evals_detect, "detect_determinism"),
    (["email-inbox", "root"], evals_email, "email_inbox"),
    (["email-determinism"], evals_email, "email_determinism"),
    (["email-golden"], evals_email, "email_golden"),
    (["email-injection-probe"], evals_email, "email_injection_probe"),
    (["determinism", "--arm", "G"], evals, "determinism"),
    (["golden", "--arm", "G"], evals, "golden"),
])
def test_every_ai_command_takes_the_engine(db, monkeypatch, capsys, command, target, attr):
    rec = Recorder([])
    monkeypatch.setattr(target, attr, rec)
    assert cli.main([*command, "--engine", "gpt"]) == 0
    assert rec.jev is False
    assert cli.main([*command, "--no-jev"]) == 0
    assert rec.jev is False
    assert cli.main([*command, "--engine", "jev"]) == 0
    assert rec.jev is True


def test_one_email_takes_the_engine(db, monkeypatch, capsys):
    message = SimpleNamespace(message_id="m", sender="s", subject="x", attachments=[])
    call = SimpleNamespace(request_id="q", input_tokens=1, cost_usd=0.0, seconds=0.1, cached=False)
    result = SimpleNamespace(intent="other", confidence=0.9, signals={}, probabilities={"other": 0.9}, call=call)
    rec = Recorder(SimpleNamespace(result=result, message=message, next_flow=None, uncertain=False))
    monkeypatch.setattr(flow_email, "run_email", rec)
    assert cli.main(["email", "folder", "--engine", "gpt"]) == 0
    assert rec.jev is False


def test_the_m2_flow_on_one_pdf_takes_the_engine(db, monkeypatch, capsys):
    state = SimpleNamespace(final_status="done", route=None, arm="G", doc_type="invoice_hu", record=None, picks={},
                            verdicts=None, validation=[], review_reasons=[], jev_calls=[], run_id="r", doc_id="d" * 64)
    rec = Recorder(state)
    monkeypatch.setattr(flow, "run_one", rec)
    assert cli.main(["run", "x.pdf", "--arm", "G", "--engine", "gpt"]) == 0
    assert rec.jev is False


def test_the_s_path_without_jev_is_refused_before_anything_runs(db, monkeypatch, capsys):
    rec = Recorder()
    monkeypatch.setattr(flow, "run_one", rec)
    monkeypatch.setattr(evals, "golden", rec)
    monkeypatch.setattr(evals, "determinism", rec)
    for command in (["run", "x.pdf", "--arm", "S"], ["golden", "--arm", "S"], ["determinism", "--arm", "S"]):
        assert cli.main([*command, "--engine", "gpt"]) == 2
        assert "S path needs JEV" in capsys.readouterr().out
    assert rec.calls == []
    app_settings.save_engine_default("gpt", actor="tester")
    assert cli.main(["run", "x.pdf"]) == 2  # `run` defaults to the S path, and the application runs without JEV
    assert rec.calls == []


def test_a_determinism_without_jev_names_its_run_file(db, monkeypatch, tmp_path):
    """The run file of a determinism measurement without JEV says so, as the golden runs' do."""
    names: list[str] = []
    monkeypatch.setattr(evals, "_dump_rows", lambda rows, name: names.append(name) or tmp_path / name)
    monkeypatch.setattr(evals, "print_determinism_report", lambda *a, **k: None)
    monkeypatch.setattr(evals, "load_cases", lambda type_key: [])
    evals.determinism("G", 2, Recorder(), type_key="invoice_hu", jev=False)
    evals.determinism("G", 2, Recorder(), type_key="invoice_hu")
    assert names == ["determinism_G_n2_nojev", "determinism_G_n2"]


# --- the reconciliation's AI (Sz7) ------------------------------------------------------------------------------------


def _reconcile_run(monkeypatch):
    from jav import reconcile_ai

    rec = Recorder({"lines": 0, "counts": {}, "scope": "s", "usage": {}, "raw": None, "jev_config": "j", "gpt_config": "g"})
    monkeypatch.setattr(reconcile_ai, "run", rec)
    return rec


def test_the_reconciliation_proposals_follow_the_applications_engine(db, monkeypatch, capsys):
    rec = _reconcile_run(monkeypatch)
    assert cli.main(["reconcile-ai", "wp-000000000000", "--budget-usd", "0.01"]) == 2  # JEV and GPT: JEV needs its budget
    assert "no budget for: jev" in capsys.readouterr().out and rec.calls == []
    app_settings.save_engine_default("gpt", actor="tester")
    assert cli.main(["reconcile-ai", "wp-000000000000", "--budget-usd", "0.01"]) == 0
    assert rec.calls[-1]["engines"] == ["gpt"]
    assert cli.main(["reconcile-ai", "wp-000000000000", "--engine", "both", "--budget-usd", "0.01", "--jev-budget-usd", "0.01"]) == 0
    assert rec.calls[-1]["engines"] == ["jev", "gpt"]


def test_the_reconciliation_golden_measures_both_engines_unless_told(db, monkeypatch, capsys):
    from jav import reconcile_ai

    rec = Recorder({"cases": 0, "golden_version": "x", "jev_config": "j", "gpt_config": "g", "engines": {}, "scope": "s",
                    "usage": {}, "raw": None})
    monkeypatch.setattr(reconcile_ai, "golden", rec)
    app_settings.save_engine_default("gpt", actor="tester")
    assert cli.main(["reconcile-ai", "--golden"]) == 0
    assert rec.calls[-1]["engines"] == ["jev", "gpt"]
    assert cli.main(["reconcile-ai", "--golden", "--no-jev"]) == 0
    assert rec.calls[-1]["engines"] == ["gpt"]


def test_gpt_alone_never_makes_a_sure_ai_group():
    """Decision 163 (F-csak-gpt D4): with GPT only the quick review has no "AI sure" group; a sure proposal needs both
    engines to agree, so a confident GPT answer alone is still checked by a person."""
    from jav import reconcile_review

    line = {"id": "l1", "candidates": [], "allocated": None, "memo": "", "description": "",
            "ai": {"gpt": {"kind": "retail_purchase", "kind_probability": 0.9999, "suggested_mark": "retail"}}}
    assert reconcile_review._place(line, {}, 0.9)[0] == "ai_review"
