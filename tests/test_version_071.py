"""071 S-verzió (070 plan 2.1, audit A08 / §1): one version source, and the running service tells which code it runs.

The single source of the version is `pyproject.toml`; the UI package descriptor and the README's stable-version line
say the same (they are bumped together at release). The commit is fixed when the service starts: that is the code
running in the process.
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from jav import api, version

ROOT = Path(__file__).resolve().parents[1]


def test_single_version_source_is_consistent():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert version.VERSION == project
    assert re.fullmatch(r"\d+\.\d+\.\d+", project)
    pkg = json.loads((ROOT / "ui" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "ui" / "package-lock.json").read_text(encoding="utf-8"))
    assert pkg["version"] == lock["version"] == lock["packages"][""]["version"] == project
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"**Current stable version: `v{project}`**" in readme  # 073: the README is English


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_commit_info_reads_head_and_dirty_state(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "Teszt")
    (tmp_path / "a.txt").write_text("1\n", encoding="utf-8")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-q", "-m", "első")
    info = version.commit_info(tmp_path)
    assert info == {"commit": _git(tmp_path, "rev-parse", "--short=7", "HEAD"), "dirty": False}
    (tmp_path / "a.txt").write_text("2\n", encoding="utf-8")
    assert version.commit_info(tmp_path)["dirty"] is True


def test_commit_info_outside_git_is_unknown(tmp_path):
    assert version.commit_info(tmp_path / "nincs") == {"commit": None, "dirty": None}


def test_health_reports_version_and_the_commit_fixed_at_start(tmp_path, monkeypatch):
    monkeypatch.setattr(version, "commit_info", lambda root=None: {"commit": "abc1234", "dirty": False})
    c = TestClient(api.create_app(store_path=tmp_path / "w.sqlite"), base_url="http://127.0.0.1:8930")
    monkeypatch.setattr(version, "commit_info", lambda root=None: {"commit": "megvaltozott", "dirty": True})
    h = c.get("/api/health").json()
    assert h["ok"] is True and h["version"] == version.VERSION
    assert (h["commit"], h["dirty"]) == ("abc1234", False)  # the state at start-up, not the current working tree
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d.*", h["started_at"])
