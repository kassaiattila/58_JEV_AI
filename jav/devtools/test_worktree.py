"""The full test suite in a separate git worktree (231, DECISIONS 231): `python -m jav.cli test-worktree`.

Plain-language summary: the full Python and UI test suites take about five minutes, and while they run nobody may
change the code, because the tests read the working tree. This command copies the current state of the work (the
checked-out commit plus every changed and new file) into a second working tree next to the project and runs both
suites there, so work goes on in the main folder meanwhile. The local-only inputs some tests need (the OCR language
data, the UI's installed packages, the internal documents) are linked or copied in, so the result is the same as in
the main folder. Each run's raw outputs are kept under `runs/test-worktree/<timestamp>/`.

- `prepare()` makes or refreshes the test worktree: the checked-out commit, the changed and new files copied, the
  deleted ones removed, the local-only inputs in place.
- `run()` prepares it and runs pytest and the UI checks there with the main folder's Python (`jav/devtools/preflight.py`
  `run_tests`), with the legacy project's location set, since its default is the folder next to the project.

Layer: development tool; it runs git and the test runners, never the store.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from jav.core import doc_scope
from jav.core.config import LEGACY_ROOT_ENV, OLD_PROJECT_ROOT, PROJECT_ROOT
from jav.devtools import preflight

WORKTREE = PROJECT_ROOT.parent / f"{PROJECT_ROOT.name}_worktrees" / "test-run"
RUNS = PROJECT_ROOT / "runs" / "test-worktree"
LINKED = ("tools/tessdata", "ui/node_modules")  # large, local-only and only read by the tests: linked, not copied


class WorktreeError(RuntimeError):
    """The test worktree could not be made or refreshed."""


def _git(*args: str, cwd: Path = PROJECT_ROOT) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise WorktreeError(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout


def changed_paths(root: Path = PROJECT_ROOT) -> tuple[list[str], list[str]]:
    """The work beyond the checked-out commit, as paths relative to `root`: (changed or new files, deleted files).
    Ignored files are not part of it."""
    tracked = [p for p in _git("diff", "--name-only", "-z", "HEAD", cwd=root).split("\0") if p]
    new = [p for p in _git("ls-files", "--others", "--exclude-standard", "-z", cwd=root).split("\0") if p]
    present = sorted({p for p in tracked + new if (root / p).is_file()})
    deleted = sorted({p for p in tracked if not (root / p).exists()})
    return present, deleted


def _link(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":  # a directory junction needs no special right on Windows
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(target), str(source)], capture_output=True, text=True)
        if r.returncode != 0:
            raise WorktreeError(f"junction {target} -> {source}: {(r.stderr or r.stdout).strip()}")
    else:
        target.symlink_to(source, target_is_directory=True)


def _internal_docs(worktree: Path, root: Path) -> None:
    """The internal documents, copied: a few tests read them, and git does not carry them (070)."""
    for path in doc_scope.internal_doc_files(root):
        target = worktree / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def prepare(worktree: Path = WORKTREE, root: Path = PROJECT_ROOT) -> tuple[Path, str, int]:
    """Makes or refreshes the test worktree of `root`; returns (its path, the commit, the number of changed files
    copied)."""
    if worktree.resolve() == root.resolve() or root.resolve() in worktree.resolve().parents:
        raise WorktreeError(f"the test worktree may not be the project or inside it: {worktree}")
    head = _git("rev-parse", "HEAD", cwd=root).strip()
    if not (worktree / ".git").exists():
        _git("worktree", "add", "--detach", str(worktree), head, cwd=root)
    else:
        _git("checkout", "--detach", "--force", head, cwd=worktree)
        _git("clean", "-fdq", cwd=worktree)  # untracked, not ignored files only: the links and the copies stay
    present, deleted = changed_paths(root)
    for rel in present:
        target = worktree / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, target)
    for rel in deleted:
        (worktree / rel).unlink(missing_ok=True)
    for rel in LINKED:
        if (root / rel).is_dir() and not (worktree / rel).exists():
            _link(root / rel, worktree / rel)
    _internal_docs(worktree, root)
    return worktree, head, len(present) + len(deleted)


def run(*, ui: bool = True, worktree: Path = WORKTREE) -> tuple[bool, list[str], Path]:
    """Runs pytest (and the UI checks) in the refreshed test worktree: (all green, report lines, the log folder)."""
    path, head, changed = prepare(worktree)
    folder = RUNS / time.strftime("%Y%m%d_%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, LEGACY_ROOT_ENV: str(OLD_PROJECT_ROOT)}
    if ui:
        (tests_ok, tests), ui_result = preflight.run_tests(folder, root=path, env=env)
    else:
        (tests_ok, tests), ui_result = preflight.run_pytest(folder, root=path, env=env), None
    lines = [f"commit {head[:7]} + {changed} changed file(s), worktree {path}", f"pytest: {tests}"]
    ok = tests_ok
    if ui_result is not None:
        ok = ok and ui_result[0]
        lines.append(f"UI: {ui_result[1]}")
    elif ui:
        lines.append("UI: not run (the UI's packages are not installed)")
    (folder / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ok, lines, folder


__all__ = ["LINKED", "RUNS", "WORKTREE", "WorktreeError", "changed_paths", "prepare", "run"]
