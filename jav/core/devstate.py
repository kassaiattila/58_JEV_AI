"""Development state for the preflight and STATE.md: git state and Ruff finding count (040, K0). No API calls.

The Ruff check is a ratchet: the total number of findings may not rise above `max_findings` in `[tool.jav.lint]` of
`pyproject.toml`; after a fix the value must be lowered. Findings in old code are fixed module by module as touched, not
in bulk. (The hook script has its own stdlib-only git helper, because it runs without the venv.)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from jav.core.config import PROJECT_ROOT

PYPROJECT = PROJECT_ROOT / "pyproject.toml"
LINT_PATHS = ("jav", "tests", "scripts", "smoke_test.py")


def _run(cmd: list[str], timeout: float = 60) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def docs_root(root: Path = PROJECT_ROOT, common_dir: str | None = None) -> Path:
    """265 (code review TOOL-18): where the internal documents are (handoffs, plans, STATE.md; not in git, 070). A
    linked git worktree has none of its own, so it uses the main checkout's, the folder of the shared git directory
    (`common_dir`, asked from git when not given); the main checkout, and a checkout whose main one has no handoffs, its
    own. The same rule as the hooks' (`scripts/hooks/handoff_guard.py`, which runs without the package)."""
    if common_dir is None:
        r = _run(["git", "rev-parse", "--git-common-dir"], timeout=10)
        common_dir = r.stdout.strip() if r is not None and r.returncode == 0 else None
    if common_dir:
        common = Path(common_dir)
        main = (common if common.is_absolute() else root / common).resolve().parent
        if main != root.resolve() and (main / "docs" / "handoffs").is_dir():
            return main
    return root


def shown_path(path: Path) -> str:
    """A path as preflight prints it: relative to the repository, or whole when it lies elsewhere (the main checkout's
    internal documents, seen from a worktree)."""
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


@dataclass(frozen=True)
class GitState:
    branch: str
    head: str
    dirty: int

    def line(self) -> str:
        tree = "clean working tree" if self.dirty == 0 else f"{self.dirty} uncommitted file(s)"
        return f"branch {self.branch} @ {self.head}, {tree}"


def git_state() -> GitState | None:
    """None if git is missing or this is not a repository."""
    head = _run(["git", "rev-parse", "--short", "HEAD"])
    if head is None or head.returncode != 0:
        return None
    branch = _run(["git", "branch", "--show-current"])
    status = _run(["git", "status", "--porcelain"])
    dirty = len([ln for ln in (status.stdout if status else "").splitlines() if ln.strip()])
    return GitState(branch=(branch.stdout.strip() if branch else "") or "?", head=head.stdout.strip(), dirty=dirty)


class RuffFailed(RuntimeError):
    """265 (code review TOOL-09): Ruff is installed but its check did not finish (an error, a timeout)."""


def _lint_settings(pyproject: Path = PYPROJECT) -> dict:
    if not pyproject.exists():
        return {}
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data.get("tool", {}).get("jav", {}).get("lint", {})


def lint_limit(pyproject: Path = PYPROJECT) -> int | None:
    return _lint_settings(pyproject).get("max_findings")


def ruff_pinned(pyproject: Path = PYPROJECT) -> str | None:
    """265 (code review TOOL-09): the Ruff version the ratchet is counted with (`ruff_version` in pyproject.toml)."""
    return _lint_settings(pyproject).get("ruff_version")


def ruff_version() -> str | None:
    """The installed Ruff's version (`ruff 0.16.4` -> `0.16.4`); None when Ruff is missing or does not answer."""
    exe = ruff_executable()
    r = _run([exe, "--version"], timeout=30) if exe else None
    if r is None or r.returncode != 0:
        return None
    return r.stdout.strip().removeprefix("ruff").strip() or None


def ruff_executable() -> str | None:
    found = shutil.which("ruff")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "ruff.exe"
    return str(local) if local.exists() else None


def ruff_findings() -> tuple[int, dict[str, int]] | None:
    """(total findings, per rule) with the pyproject settings; None if Ruff is not installed. 265 (code review TOOL-09):
    `RuffFailed` when it is installed but its check failed (it passed as "not available" before)."""
    exe = ruff_executable()
    if exe is None:
        return None
    r = _run([exe, "check", *LINT_PATHS, "--output-format", "json", "--no-cache", "--exit-zero"], timeout=120)
    if r is None:
        raise RuffFailed("the check did not finish (a timeout or the program could not start)")
    if r.returncode != 0:
        raise RuffFailed(f"exit code {r.returncode}: {(r.stderr or r.stdout).strip()[:300]}")
    items = json.loads(r.stdout or "[]")
    by_code: dict[str, int] = {}
    for it in items:
        by_code[it.get("code") or "?"] = by_code.get(it.get("code") or "?", 0) + 1
    return len(items), dict(sorted(by_code.items(), key=lambda kv: -kv[1]))


def lint_verdict(count: int | None, limit: int | None, *, version: str | None = None,
                 pinned: str | None = None) -> tuple[bool, str]:
    """The ratchet's verdict. A missing Ruff or limit is not an error, only a notice. 265 (code review TOOL-09): another
    Ruff version than the pinned one fails (its rules may count differently)."""
    if count is None:
        return True, f"Ruff is not available (install: uv tool install ruff{'==' + pinned if pinned else ''}) - skipped"
    if pinned and version and version != pinned:
        return False, f"Ruff {version} is not the pinned {pinned}: uv tool install ruff=={pinned}"
    if limit is None:
        return True, f"{count} finding(s) (no max_findings in pyproject.toml)"
    if count > limit:
        return False, f"{count} finding(s) > limit {limit}: a new finding entered the code; fix it"
    extra = f"; the limit can be lowered to {count}" if count < limit else ""
    return True, f"{count} finding(s) (limit {limit}{extra})"
