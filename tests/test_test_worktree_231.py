"""231 (DECISIONS 231): the full test suite in a separate git worktree.

The main working tree stays free while the suite runs: the test worktree gets the checked-out commit plus every changed
and new file, loses the deleted ones, and gets the local-only inputs (the OCR language data and the UI's packages
linked, the internal documents copied). A synthetic repository; nothing of the project is touched.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from jav.devtools import test_worktree


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / ".gitignore").write_text("tools/tessdata/\ndocs/BACKLOG.md\n", encoding="utf-8")
    (root / "a.txt").write_text("a1\n", encoding="utf-8")
    (root / "b.txt").write_text("b1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "start")
    (root / "a.txt").write_text("a2\n", encoding="utf-8")  # changed
    (root / "b.txt").unlink()  # deleted
    (root / "c.txt").write_text("c1\n", encoding="utf-8")  # new
    (root / "tools" / "tessdata").mkdir(parents=True)  # ignored, local-only input
    (root / "tools" / "tessdata" / "hun.traineddata").write_text("x", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "BACKLOG.md").write_text("internal\n", encoding="utf-8")  # internal document
    return root


def test_the_work_beyond_the_commit_is_the_changed_new_and_deleted_files(repo) -> None:
    present, deleted = test_worktree.changed_paths(repo)
    assert present == ["a.txt", "c.txt"]
    assert deleted == ["b.txt"]


def test_the_test_worktree_gets_the_work_and_the_local_only_inputs(repo, tmp_path) -> None:
    worktree = tmp_path / "wt"
    path, head, changed = test_worktree.prepare(worktree, root=repo)
    assert path == worktree and len(head) == 40 and changed == 3
    assert (worktree / "a.txt").read_text(encoding="utf-8") == "a2\n"
    assert (worktree / "c.txt").read_text(encoding="utf-8") == "c1\n"
    assert not (worktree / "b.txt").exists()
    assert (worktree / "tools" / "tessdata" / "hun.traineddata").read_text(encoding="utf-8") == "x"
    assert (worktree / "docs" / "BACKLOG.md").read_text(encoding="utf-8") == "internal\n"
    # the main tree is untouched
    assert (repo / "a.txt").read_text(encoding="utf-8") == "a2\n" and not (repo / "b.txt").exists()


def test_a_second_run_refreshes_the_worktree(repo, tmp_path) -> None:
    worktree = tmp_path / "wt"
    test_worktree.prepare(worktree, root=repo)
    (repo / "c.txt").unlink()
    (repo / "a.txt").write_text("a3\n", encoding="utf-8")
    test_worktree.prepare(worktree, root=repo)
    assert (worktree / "a.txt").read_text(encoding="utf-8") == "a3\n"
    assert not (worktree / "c.txt").exists()  # an untracked file gone from the work is gone from the worktree


def test_the_worktree_may_not_be_the_project_or_inside_it(repo) -> None:
    with pytest.raises(test_worktree.WorktreeError):
        test_worktree.prepare(repo, root=repo)
    with pytest.raises(test_worktree.WorktreeError):
        test_worktree.prepare(repo / "inner", root=repo)
