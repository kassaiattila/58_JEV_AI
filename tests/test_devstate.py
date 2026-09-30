"""Fejlesztési állapot: Ruff-racsni és git-sor (040, K0)."""

from jav import devstate


def test_lint_verdict_ratchet():
    assert devstate.lint_verdict(190, 189)[0] is False
    ok, msg = devstate.lint_verdict(180, 189)
    assert ok and "180-ra csökkenthető" in msg
    assert devstate.lint_verdict(189, 189) == (True, "189 jelzés (határ 189)")


def test_lint_verdict_missing_tool_is_not_failure():
    assert devstate.lint_verdict(None, 189)[0] is True
    assert devstate.lint_verdict(5, None)[0] is True


def test_lint_limit_reads_pyproject(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text("[tool.jav.lint]\nmax_findings = 7\n", encoding="utf-8")
    assert devstate.lint_limit(p) == 7
    assert devstate.lint_limit(tmp_path / "nincs.toml") is None


def test_git_state_line():
    assert devstate.GitState("main", "abc1234", 0).line() == "ág main @ abc1234, tiszta munkafa"
    assert "3 commitolatlan" in devstate.GitState("k0", "abc1234", 3).line()
