"""265 (code review TOOL-02, TOOL-06): the test worktree takes a rename's old path as deleted, and one full test run
goes at a time on the machine.

- TOOL-02: the changed paths came from `git diff --name-only HEAD` with rename detection, so a renamed file's old path
  was neither copied nor deleted: it stayed in the test worktree and the suite could pass on it.
- TOOL-06: nothing enforced "one full run at a time"; two at once ran out of memory or wiped the shared test worktree.
  A machine-wide lock now guards it; each run writes into a log folder of its own.
A throwaway git repository; no tests are run.
"""

from __future__ import annotations

import subprocess

import pytest

from jav.devtools import preflight, test_worktree


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_a_renamed_file_s_old_path_is_deleted(tmp_path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "old_name.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "one")
    _git(tmp_path, "mv", "old_name.py", "new_name.py")
    present, deleted = test_worktree.changed_paths(tmp_path)
    assert present == ["new_name.py"] and deleted == ["old_name.py"]


def test_a_second_full_run_is_refused_while_one_goes(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(test_worktree, "_run", lambda **k: pytest.fail("a second run started"))
    with preflight.full_run_lock():
        with pytest.raises(test_worktree.WorktreeError, match="one at a time"):
            test_worktree.run(ui=False, worktree=tmp_path / "wt")
    with preflight.full_run_lock():  # released after the block: the next run may start
        pass


def test_the_test_processes_fit_the_free_memory(monkeypatch) -> None:
    """265 (code review TOOL-05): the Python processes by the free memory too, the UI's in two."""
    monkeypatch.setattr(preflight, "available_memory_gb", lambda: 4.0)
    monkeypatch.setattr(preflight.os, "cpu_count", lambda: 16)
    assert preflight.parallel_workers() in (0, 2)  # 4 GB holds two (0 without pytest-xdist)
    monkeypatch.setattr(preflight, "available_memory_gb", lambda: 2.0)
    assert preflight.parallel_workers() == 0
    assert preflight.UI_TEST_WORKERS == 2
