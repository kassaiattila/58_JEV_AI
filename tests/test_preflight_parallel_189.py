"""The full check runs the tests in several processes and the UI checks beside them (189).

Plain-language summary: the full check took about half an hour, almost all of it the Python tests run one after the
other. They now run in several processes at once (pytest-xdist), and the UI's checks run at the same time. These
tests use stand-ins for the subprocesses, so no real test run starts.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from jav import preflight

DONE = SimpleNamespace(stdout="3 passed in 1.00s\n", stderr="", returncode=0)


def test_the_tests_run_in_the_chosen_number_of_processes_with_the_slowest_listed(tmp_path, monkeypatch):
    seen: list = []
    monkeypatch.setattr(preflight, "PREFLIGHT_RUNS", tmp_path / "preflight")
    monkeypatch.setattr(preflight, "parallel_workers", lambda: 4)
    monkeypatch.setattr(preflight.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or DONE)
    ok, summary = preflight.run_pytest()
    assert ok and summary == "3 passed in 1.00s"
    cmd = seen[0]
    assert cmd[cmd.index("-n") + 1] == "4" and cmd[cmd.index("--dist") + 1] == "worksteal"
    assert f"--durations={preflight.SLOWEST_SHOWN}" in cmd


def test_without_parallel_processes_the_tests_run_in_one_as_before(tmp_path, monkeypatch):
    seen: list = []
    monkeypatch.setattr(preflight, "PREFLIGHT_RUNS", tmp_path / "preflight")
    monkeypatch.setattr(preflight, "parallel_workers", lambda: 0)
    monkeypatch.setattr(preflight.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or DONE)
    preflight.run_pytest()
    assert "-n" not in seen[0] and "--dist" not in seen[0]


def test_the_number_of_processes_leaves_two_cores_free_and_stays_within_the_cap(monkeypatch):
    monkeypatch.setattr(preflight.importlib.util, "find_spec", lambda name: object())
    for cores, workers in ((16, preflight.MAX_TEST_WORKERS), (8, 6), (5, 3), (4, 2), (3, 0), (None, 0)):
        monkeypatch.setattr(preflight.os, "cpu_count", lambda c=cores: c)
        assert preflight.parallel_workers() == workers, cores


def test_without_pytest_xdist_the_tests_run_in_one_process(monkeypatch):
    monkeypatch.setattr(preflight.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(preflight.os, "cpu_count", lambda: 16)
    assert preflight.parallel_workers() == 0


def test_the_ui_checks_run_while_the_tests_do(tmp_path, monkeypatch):
    """Each stand-in waits until the other has started: run one after the other, the first would wait in vain."""
    started = {"tests": threading.Event(), "ui": threading.Event()}

    def tests(folder):
        started["tests"].set()
        return started["ui"].wait(timeout=10), "tests"

    def ui(folder):
        started["ui"].set()
        return started["tests"].wait(timeout=10), "ui"

    monkeypatch.setattr(preflight, "run_pytest", tests)
    monkeypatch.setattr(preflight, "run_ui_checks", ui)
    assert preflight.run_tests(tmp_path) == ((True, "tests"), (True, "ui"))
