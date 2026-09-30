"""Az alkalmazás verziója egy helyen (071 S-verzió, 070 terv 2.1, audit A08 / §1).

- `VERSION`: a `pyproject.toml` `[project] version` mezője, az egyetlen forrás. A felület csomagleírója
  (`ui/package.json`, `ui/package-lock.json`) és a README „Jelenlegi stabil változat” sora a kiadáskor vele együtt lép;
  a `tests/test_version_071.py` figyeli, hogy egyezzenek. Két kiadás között a verzió a legutóbbi kiadásé, a fejlesztői
  állapotot a commit azonosítja.
- `commit_info`: a munkafa commitja (rövid azonosító) és az, hogy van-e commitolatlan változás. A szolgáltatás ezt az
  induláskor rögzíti, így az egészség-végpont azt a kódot mutatja, amely a folyamatban ténylegesen fut.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

from jav.config import PROJECT_ROOT

VERSION: str = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def commit_info(root: Path | None = None) -> dict[str, str | bool | None]:
    """`{"commit": rövid azonosító, "dirty": commitolatlan változás}`; git nélkül vagy nem git-tárban mindkettő None."""
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
