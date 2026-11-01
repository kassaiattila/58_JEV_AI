"""272 (K2, the check of SEC-03): a push carries only what is built on the repository's current root commit.

CLAUDE.md 2.3: GitHub receives `main`, the release tags and stage branches built on the repository's current root
commit. 265 (SEC-03) checked the refs a push carries by name and refused a history listed as forbidden, so any other
history (an unrelated branch, a fresh orphan) could still go under a stage branch's name. The hook now also requires
every pushed branch and tag to contain the root named in `push.root` (configs/data_guard.json). A throwaway
repository in a temporary folder; no push is made.
"""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path

from jav.devtools import data_guard as dg


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "a.txt").write_text("first\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "root")
    root = _git(repo, "rev-parse", "HEAD")
    (repo / "a.txt").write_text("second\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "on the root")
    built = _git(repo, "rev-parse", "HEAD")
    return repo, root, built


def _guard(root: str) -> dg.Guard:
    conf = copy.deepcopy(dg.load_config())
    conf["push"]["root"] = root
    conf["forbidden_history"] = []
    return dg.Guard(conf, env_secrets={}, env_sources=())


def _orphan(repo: Path) -> str:
    _git(repo, "switch", "-q", "--orphan", "elsewhere")
    (repo / "b.txt").write_text("unrelated\n", encoding="utf-8")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-q", "-m", "another history")
    return _git(repo, "rev-parse", "HEAD")


def test_a_branch_built_on_the_root_may_go(tmp_path: Path) -> None:
    repo, root, built = _repo(tmp_path)
    line = f"refs/heads/stage {built} refs/heads/stage {dg.ZERO_SHA}"
    assert [f for f in dg.check_push(repo, _guard(root), [line]) if f.kind == "push_root"] == []


def test_a_branch_of_another_history_is_refused(tmp_path: Path) -> None:
    repo, root, _built = _repo(tmp_path)
    other = _orphan(repo)
    line = f"refs/heads/elsewhere {other} refs/heads/elsewhere {dg.ZERO_SHA}"
    assert [f.path for f in dg.check_push(repo, _guard(root), [line]) if f.kind == "push_root"] == ["refs/heads/elsewhere"]


def test_a_root_this_clone_cannot_find_is_said(tmp_path: Path) -> None:
    repo, _root, built = _repo(tmp_path)
    line = f"refs/heads/stage {built} refs/heads/stage {dg.ZERO_SHA}"
    found = [f for f in dg.check_push(repo, _guard("2" * 40), [line]) if f.kind == "push_root"]
    assert [f.path for f in found] == ["push.root"]


def test_the_repository_s_root_is_named() -> None:
    assert dg.load_config()["push"]["root"] == "6c863ef1c14721f56f8d02484b0d8bfcbf2e4fb2"
