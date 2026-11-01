"""092 (audit T1): every full check keeps its raw pytest output and a JUnit file, so an intermittent failure can be
looked up afterwards; the latest few are kept. A stand-in for the subprocess, no real test run."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from jav.devtools import preflight

OUT = ("..F.\n=========================== short test summary info ===========================\n"
       "FAILED tests/test_a.py::test_x - AssertionError: boom\n1 failed, 3 passed in 1.00s\n")


def _fake(seen):
    def run(cmd, **kw):
        seen.append(cmd)
        return SimpleNamespace(stdout=OUT, stderr="a warning\n", returncode=1)
    return run


def test_the_raw_output_and_a_junit_file_are_kept(tmp_path, monkeypatch):
    seen: list = []
    monkeypatch.setattr(preflight, "PREFLIGHT_RUNS", tmp_path / "preflight")
    monkeypatch.setattr(preflight, "_bounded", _fake(seen))
    ok, summary = preflight.run_pytest()
    [folder] = list((tmp_path / "preflight").iterdir())
    assert not ok and summary.startswith("1 failed, 3 passed in 1.00s; FAILED tests/test_a.py::test_x")
    assert str(folder) in summary  # where to look
    assert f"--junitxml={folder / 'junit.xml'}" in seen[0]
    text = (folder / "pytest.txt").read_text(encoding="utf-8")
    assert "AssertionError: boom" in text and "a warning" in text


JUNIT = """<?xml version="1.0" encoding="UTF-8" ?>
<testsuites name="vitest tests" tests="3" failures="1" errors="0">
  <testsuite name="src/views/a.test.tsx" tests="3" failures="1">
    <testcase classname="src/views/a.test.tsx" name="the list &gt; shows a row" time="0.1"/>
    <testcase classname="src/views/a.test.tsx" name="the list &gt; opens the card" time="1.2">
      <failure message="Unable to find an element" type="TestingLibraryElementError">stack</failure>
    </testcase>
    <testcase classname="src/views/a.test.tsx" name="the list &gt; filters" time="0.1"/>
  </testsuite>
</testsuites>
"""
VITEST_OUT = " FAIL  src/views/a.test.tsx > the list > opens the card\n Tests  1 failed | 2 passed (3)\n"


def _ui_bins(ui: Path) -> None:
    """265 (TOOL-12): the UI's own tsc, ESLint (UI-14) and vitest in node_modules/.bin, which the check runs."""
    (ui / "node_modules" / ".bin").mkdir(parents=True)
    for name in ("tsc", "eslint", "vitest"):
        (ui / "node_modules" / ".bin" / f"{name}.cmd").write_text("", encoding="utf-8")


def _fake_ui(seen):
    def run(cmd, **kw):
        seen.append(cmd)
        if Path(cmd[0]).stem == "vitest":  # 265 (TOOL-12): the UI's own binary, not npx
            junit = next(a.split("=", 1)[1] for a in cmd if a.startswith("--outputFile.junit="))
            Path(junit).write_text(JUNIT, encoding="utf-8")
            return SimpleNamespace(stdout=VITEST_OUT, stderr="", returncode=1)
        return SimpleNamespace(stdout="", stderr="", returncode=0)
    return run


def test_149_the_ui_test_output_is_kept_and_a_failure_is_named(tmp_path, monkeypatch):
    """149 (backlog Q-flaky-ui-test): an intermittent UI test failure could not be identified, because the vitest
    output was thrown away. It is now kept next to the pytest log, and the summary names the failed test."""
    seen: list = []
    _ui_bins(tmp_path / "ui")
    monkeypatch.setattr(preflight, "UI_DIR", tmp_path / "ui")
    monkeypatch.setattr(preflight, "PREFLIGHT_RUNS", tmp_path / "preflight")
    monkeypatch.setattr(preflight.shutil, "which", lambda name: name)
    monkeypatch.setattr(preflight, "_bounded", _fake_ui(seen))
    folder = preflight.log_folder()
    ok, summary = preflight.run_ui_checks(folder)
    assert not ok
    assert "src/views/a.test.tsx > the list > opens the card" in summary
    assert str(folder) in summary  # where to look
    assert (folder / "vitest.txt").read_text(encoding="utf-8") == VITEST_OUT
    assert (folder / "vitest-junit.xml").is_file()


def test_149_a_green_ui_run_reports_the_count_only(tmp_path, monkeypatch):
    def run(cmd, **kw):
        if Path(cmd[0]).stem == "vitest":  # 265 (TOOL-12): the UI's own binary, not npx
            return SimpleNamespace(stdout=" Tests  3 passed (3)\n", stderr="", returncode=0)
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    _ui_bins(tmp_path / "ui")
    monkeypatch.setattr(preflight, "UI_DIR", tmp_path / "ui")
    monkeypatch.setattr(preflight, "PREFLIGHT_RUNS", tmp_path / "preflight")
    monkeypatch.setattr(preflight.shutil, "which", lambda name: name)
    monkeypatch.setattr(preflight, "_bounded", run)
    ok, summary = preflight.run_ui_checks(preflight.log_folder())
    assert ok and summary.endswith("Tests 3 passed (3)") and "log:" not in summary


def test_only_the_latest_logs_are_kept(tmp_path, monkeypatch):
    root = tmp_path / "preflight"
    for n in range(preflight.KEEP_LOGS + 3):
        (root / f"20260101_0000{n:02d}").mkdir(parents=True)
    (root / "notes").mkdir()  # not a log folder: left alone
    monkeypatch.setattr(preflight, "PREFLIGHT_RUNS", root)
    monkeypatch.setattr(preflight, "_bounded", _fake([]))
    preflight.run_pytest()
    logs = sorted(p.name for p in root.iterdir() if p.name != "notes")
    assert len(logs) == preflight.KEEP_LOGS and (root / "notes").is_dir()
    assert "20260101_000000" not in logs  # the oldest went
