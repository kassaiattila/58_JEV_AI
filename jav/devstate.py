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

from jav.config import PROJECT_ROOT

PYPROJECT = PROJECT_ROOT / "pyproject.toml"
LINT_PATHS = ("jav", "tests", "scripts", "smoke_test.py")


def _run(cmd: list[str], timeout: float = 60) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


@dataclass(frozen=True)
class GitState:
    branch: str
    head: str
    dirty: int

    def line(self) -> str:
        tree = "tiszta munkafa" if self.dirty == 0 else f"{self.dirty} commitolatlan fájl"
        return f"ág {self.branch} @ {self.head}, {tree}"


def git_state() -> GitState | None:
    """None if git is missing or this is not a repository."""
    head = _run(["git", "rev-parse", "--short", "HEAD"])
    if head is None or head.returncode != 0:
        return None
    branch = _run(["git", "branch", "--show-current"])
    status = _run(["git", "status", "--porcelain"])
    dirty = len([ln for ln in (status.stdout if status else "").splitlines() if ln.strip()])
    return GitState(branch=(branch.stdout.strip() if branch else "") or "?", head=head.stdout.strip(), dirty=dirty)


def lint_limit(pyproject: Path = PYPROJECT) -> int | None:
    if not pyproject.exists():
        return None
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data.get("tool", {}).get("jav", {}).get("lint", {}).get("max_findings")


def ruff_executable() -> str | None:
    found = shutil.which("ruff")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "ruff.exe"
    return str(local) if local.exists() else None


def ruff_findings() -> tuple[int, dict[str, int]] | None:
    """(total findings, per rule) with the pyproject settings; None if Ruff is unavailable or failed."""
    exe = ruff_executable()
    if exe is None:
        return None
    r = _run([exe, "check", *LINT_PATHS, "--output-format", "json", "--no-cache", "--exit-zero"], timeout=120)
    if r is None or r.returncode != 0:
        return None
    items = json.loads(r.stdout or "[]")
    by_code: dict[str, int] = {}
    for it in items:
        by_code[it.get("code") or "?"] = by_code.get(it.get("code") or "?", 0) + 1
    return len(items), dict(sorted(by_code.items(), key=lambda kv: -kv[1]))


def lint_verdict(count: int | None, limit: int | None) -> tuple[bool, str]:
    """The ratchet's verdict. A missing Ruff or limit is not an error, only a notice."""
    if count is None:
        return True, "Ruff nem érhető el (telepítés: uv tool install ruff) - kihagyva"
    if limit is None:
        return True, f"{count} jelzés (nincs max_findings a pyproject.toml-ban)"
    if count > limit:
        return False, f"{count} jelzés > határ {limit}: új jelzés került a kódba, javítsd"
    extra = f"; a határ {count}-ra csökkenthető" if count < limit else ""
    return True, f"{count} jelzés (határ {limit}{extra})"
