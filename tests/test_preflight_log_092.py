"""092 (audit T1): every full check keeps its raw pytest output and a JUnit file, so an intermittent failure can be
looked up afterwards; the latest few are kept. A stand-in for the subprocess, no real test run."""

from __future__ import annotations

from types import SimpleNamespace

from jav import preflight

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
    monkeypatch.setattr(preflight.subprocess, "run", _fake(seen))
    ok, summary = preflight.run_pytest()
    [folder] = list((tmp_path / "preflight").iterdir())
    assert not ok and summary.startswith("1 failed, 3 passed in 1.00s; FAILED tests/test_a.py::test_x")
    assert str(folder) in summary  # where to look
    assert f"--junitxml={folder / 'junit.xml'}" in seen[0]
    text = (folder / "pytest.txt").read_text(encoding="utf-8")
    assert "AssertionError: boom" in text and "a warning" in text


def test_only_the_latest_logs_are_kept(tmp_path, monkeypatch):
    root = tmp_path / "preflight"
    for n in range(preflight.KEEP_LOGS + 3):
        (root / f"20260101_0000{n:02d}").mkdir(parents=True)
    (root / "notes").mkdir()  # not a log folder: left alone
    monkeypatch.setattr(preflight, "PREFLIGHT_RUNS", root)
    monkeypatch.setattr(preflight.subprocess, "run", _fake([]))
    preflight.run_pytest()
    logs = sorted(p.name for p in root.iterdir() if p.name != "notes")
    assert len(logs) == preflight.KEEP_LOGS and (root / "notes").is_dir()
    assert "20260101_000000" not in logs  # the oldest went
