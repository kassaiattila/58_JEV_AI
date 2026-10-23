"""158 (the second half of review item C7, 153): the dependency audit also says when the Python runtime is behind the
latest patch release of its version line.

Found on 2026-10-16: the runtime had been moved to 3.12.13 that morning, while 3.12.15 had been out since 2026-10-01;
uv 0.11.2 (March 2026) offered 3.12.13 as the newest, as its download list is built in. The audit now asks a public,
read-only release list (endoflife.date) for the runtime's version line; nothing of ours is sent. A runtime behind is a
notice, not a failure; an unreachable list makes the audit incomplete, as a missing tool does.

The release list is replaced by canned answers; no network.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from jav.runtime import deps_audit
from tests.test_deps_audit_075 import NPM_CLEAN, PIP_CLEAN, _fake_run

RELEASES = {"schema_version": "1.2.1", "result": {"name": "3.12", "isMaintained": True, "eolFrom": "2028-10-31",
                                                   "latest": {"name": "3.12.15", "date": "2026-10-01"}}}


@pytest.fixture
def tools(monkeypatch, tmp_path):
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "package-lock.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(deps_audit.shutil, "which", lambda name: f"/tools/{name}")
    monkeypatch.setattr(deps_audit, "_run", _fake_run(PIP_CLEAN, NPM_CLEAN, []))
    return tmp_path


def test_the_running_patch_is_compared_with_the_latest_of_its_line():
    behind = deps_audit.parse_runtime(RELEASES, "3.12.13")
    assert behind == {"ok": True, "running": "3.12.13", "latest": "3.12.15", "latest_date": "2026-10-01", "outdated": True,
                      "maintained": True, "eol_from": "2028-10-31"}
    assert deps_audit.parse_runtime(RELEASES, "3.12.15")["outdated"] is False
    assert deps_audit.parse_runtime(RELEASES, "3.12.16")["outdated"] is False  # newer than the list: not behind


def test_the_list_of_the_runtimes_own_version_line_is_asked(tools, monkeypatch):
    asked = []
    monkeypatch.setattr(deps_audit, "_fetch_json", lambda url: asked.append(url) or RELEASES)
    monkeypatch.setattr(deps_audit.platform, "python_version", lambda: "3.12.13")
    status = deps_audit.run(tools, status_path=tools / "status.json")
    assert asked == ["https://endoflife.date/api/v1/products/python/releases/3.12"]
    assert status["runtime"]["outdated"] is True


def test_a_runtime_behind_is_a_notice_not_a_failure(tools, monkeypatch):
    monkeypatch.setattr(deps_audit, "_fetch_json", lambda url: RELEASES)
    monkeypatch.setattr(deps_audit.platform, "python_version", lambda: "3.12.13")
    path = tools / "status.json"
    deps_audit.run(tools, status_path=path)
    current = deps_audit.status(status_path=path)
    ok, line = deps_audit.verdict(current)
    assert ok and not current["errors"]
    assert "Python 3.12.13 is behind the latest patch of its line, 3.12.15 (2026-10-01)" in line


def test_an_unreachable_release_list_makes_the_audit_incomplete(tools, monkeypatch):
    def offline(url):
        raise OSError("network unreachable")

    monkeypatch.setattr(deps_audit, "_fetch_json", offline)
    path = tools / "status.json"
    deps_audit.run(tools, status_path=path)
    current = deps_audit.status(status_path=path)
    ok, line = deps_audit.verdict(current)
    assert ok and current["errors"] == ["runtime: OSError: network unreachable"] and "incomplete" in line


def test_an_audit_written_before_the_runtime_check_reads_as_before(tmp_path):
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "python": {"ok": True, "packages": 2, "findings": []},
                                "npm": {"ok": True, "packages": 137, "findings": []}}), encoding="utf-8")
    current = deps_audit.status(status_path=path)
    assert current["errors"] == [] and deps_audit.verdict(current)[0]
    assert "behind" not in deps_audit.verdict(current)[1]
