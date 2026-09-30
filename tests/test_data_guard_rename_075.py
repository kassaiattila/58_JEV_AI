"""075 (repeated security audit, S05): the data guard checks the whole content of a renamed or copied file under its
new path before a commit, not only the changed lines.

Before 075 git's rename detection showed a pure rename without added lines, so a value tolerated only in its original
file could be committed under a new name (the push check and the full scan did catch it). Synthetic markers only; the
temporary repositories run without hooks, only the guard functions are called.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from jav import data_guard

MARKER = "syntheticprivatemarker"


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True, encoding="utf-8").stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Synthetic tester")
    git(root, "config", "user.email", "tester@example.invalid")
    git(root, "config", "core.autocrlf", "false")
    git(root, "config", "core.hooksPath", str(root / "no-hooks"))
    return root


@pytest.fixture
def guard():
    conf = data_guard.load_config()
    entry = data_guard.deny_entry(MARKER)
    conf["deny"] = [entry]
    conf["known"] = [{"sha256": entry["sha256"], "paths": ["original.txt"]}]
    conf["allowed_binary"] = ["assets/*.bin"]
    return data_guard.Guard(conf, env_secrets={})


def _commit_baseline(repo: Path, name: str, data: bytes) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    git(repo, "add", name)
    git(repo, "commit", "-qm", "baseline")


def test_rename_is_checked_under_the_new_path(repo, guard):
    _commit_baseline(repo, "original.txt", f"{MARKER}\n".encode())
    git(repo, "mv", "original.txt", "public-copy.txt")
    found = data_guard.blocking(data_guard.check_staged(repo, guard))
    assert [f.path for f in found] == ["public-copy.txt"]


def test_copy_is_checked_under_the_new_path(repo, guard):
    _commit_baseline(repo, "original.txt", f"{MARKER}\n".encode())
    (repo / "public-copy.txt").write_text(f"{MARKER}\n", encoding="utf-8")
    git(repo, "add", "public-copy.txt")
    assert data_guard.blocking(data_guard.check_staged(repo, guard))


def test_binary_rename_out_of_its_allowed_folder_is_blocked(repo, guard):
    _commit_baseline(repo, "assets/sample.bin", b"\x00\x01binary")
    (repo / "public").mkdir()
    git(repo, "mv", "assets/sample.bin", "public/sample.bin")
    found = data_guard.blocking(data_guard.check_staged(repo, guard))
    assert [(f.path, f.kind) for f in found] == [("public/sample.bin", "binary_file")]


def test_staged_content_counts_not_the_working_tree(repo, guard):
    _commit_baseline(repo, "notes.txt", b"clean\n")
    (repo / "notes.txt").write_text(f"clean\n{MARKER}\n", encoding="utf-8")
    git(repo, "add", "notes.txt")
    (repo / "notes.txt").write_text("clean\n", encoding="utf-8")  # the working tree is clean again, the index is not
    assert data_guard.blocking(data_guard.check_staged(repo, guard))


def test_rename_in_a_pushed_commit_is_blocked(repo, guard):
    _commit_baseline(repo, "original.txt", f"{MARKER}\n".encode())
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "mv", "original.txt", "public-copy.txt")
    git(repo, "commit", "-qm", "rename")
    head = git(repo, "rev-parse", "HEAD")
    found = data_guard.check_push(repo, guard, [f"refs/heads/main {head} refs/heads/main {base}"])
    assert [f.path for f in data_guard.blocking(found)] == ["public-copy.txt"]


def test_unchanged_tolerated_file_still_passes(repo, guard):
    (repo / "original.txt").write_text(f"{MARKER}\n", encoding="utf-8")
    git(repo, "add", "original.txt")
    assert not data_guard.blocking(data_guard.check_staged(repo, guard))
