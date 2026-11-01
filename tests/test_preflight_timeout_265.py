"""265 (code review TOOL-11): a stuck test does not hold the full check for good.

The test run and the UI checks ran without a time limit, so one stuck test held the check, and with it a merge,
forever. Each is now stopped after its limit and reported as failed, with what it printed until then kept in the log,
and a single test running too long has every thread's stack written to the log. A stand-in for the subprocess.
"""

from __future__ import annotations

import subprocess

from jav.devtools import preflight


def test_a_test_run_past_its_limit_is_stopped_and_failed(tmp_path, monkeypatch) -> None:
    seen: list = []

    def run(cmd, **kw):  # 272 (K5): the run's own seam; how a run past its limit is stopped: test_bounded_tree_272
        seen.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, preflight.TIMED_OUT, "....partial output",
                                           f"\nstopped after {kw['timeout'] // 60} minutes without finishing")

    monkeypatch.setattr(preflight, "PREFLIGHT_RUNS", tmp_path / "preflight")
    monkeypatch.setattr(preflight, "_bounded", run)
    ok, summary = preflight.run_pytest()
    [folder] = list((tmp_path / "preflight").iterdir())
    assert not ok and summary.startswith("pytest stopped after 90 minutes without finishing")
    assert str(folder) in summary
    cmd, kw = seen[0]
    assert kw["timeout"] == preflight.PYTEST_TIMEOUT_S and f"faulthandler_timeout={preflight.STUCK_TEST_S}" in cmd
    assert "partial output" in (folder / "pytest.txt").read_text(encoding="utf-8")
