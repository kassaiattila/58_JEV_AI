"""The application's version in one place (071 S-verzió, 070 plan 2.1, audit A08 / §1).

- `VERSION`: the `[project] version` field of `pyproject.toml`, the single source. The UI package descriptor
  (`ui/package.json`, `ui/package-lock.json`) and the README's "Current stable version" line are bumped with it at
  release; `tests/test_version_071.py` checks that they match. Between two releases the version is the latest
  release's, and the development state is identified by the commit.
- `commit_info`: the working tree's commit (short id) and whether there are uncommitted changes. The service records
  this at start-up, so the health endpoint shows the code that actually runs in the process.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

from jav.config import PROJECT_ROOT

VERSION: str = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def commit_info(root: Path | None = None) -> dict[str, str | bool | None]:
    """`{"commit": short id, "dirty": uncommitted changes}`; without git or outside a git repository both are None."""
    cwd = root or PROJECT_ROOT
    try:
        head = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=cwd, capture_output=True, text=True,
                              timeout=10)
        if head.returncode != 0:
            return {"commit": None, "dirty": None}
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=cwd,
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return {"commit": None, "dirty": None}
    return {"commit": head.stdout.strip(), "dirty": bool(status.stdout.strip()) if status.returncode == 0 else None}


__all__ = ["VERSION", "commit_info"]
