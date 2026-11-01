"""Development state: Ruff ratchet and git line (040, K0)."""

from jav.core import devstate


def test_lint_verdict_ratchet():
    assert devstate.lint_verdict(190, 189)[0] is False
    ok, msg = devstate.lint_verdict(180, 189)
    assert ok and "can be lowered to 180" in msg
    assert devstate.lint_verdict(189, 189) == (True, "189 finding(s) (limit 189)")


def test_lint_verdict_another_ruff_version_fails():
    # 265 (code review TOOL-09): the ratchet is counted with the pinned version
    ok, msg = devstate.lint_verdict(0, 0, version="0.17.0", pinned="0.16.4")
    assert ok is False and "uv tool install ruff==0.16.4" in msg
    assert devstate.lint_verdict(0, 0, version="0.16.4", pinned="0.16.4")[0] is True


def test_a_ruff_that_runs_but_fails_is_an_error(monkeypatch):
    # 265 (code review TOOL-09): it passed as "not available" before
    import subprocess

    import pytest

    monkeypatch.setattr(devstate, "ruff_executable", lambda: "ruff")
    monkeypatch.setattr(devstate, "_run", lambda *a, **k: subprocess.CompletedProcess(a, 2, "", "a broken setting"))
    with pytest.raises(devstate.RuffFailed, match="a broken setting"):
        devstate.ruff_findings()
    monkeypatch.setattr(devstate, "_run", lambda *a, **k: None)
    with pytest.raises(devstate.RuffFailed):
        devstate.ruff_findings()


def test_lint_verdict_missing_tool_is_not_failure():
    assert devstate.lint_verdict(None, 189)[0] is True
    assert devstate.lint_verdict(5, None)[0] is True


def test_lint_limit_reads_pyproject(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text("[tool.jav.lint]\nmax_findings = 7\n", encoding="utf-8")
    assert devstate.lint_limit(p) == 7
    assert devstate.lint_limit(tmp_path / "nincs.toml") is None


def test_git_state_line():
    assert devstate.GitState("main", "abc1234", 0).line() == "branch main @ abc1234, clean working tree"
    assert "3 uncommitted" in devstate.GitState("k0", "abc1234", 3).line()
