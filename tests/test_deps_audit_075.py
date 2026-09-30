"""075: the regular dependency audit — report parsing, status file, age and verdict.

The external tools are replaced by canned reports; no network.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from jav import deps_audit

PIP_CLEAN = {"dependencies": [{"name": "fastapi", "version": "0.120.0", "vulns": []},
                              {"name": "httpx2", "version": "2.13.0", "vulns": []}]}
PIP_VULN = {"dependencies": [{"name": "demo-lib", "version": "1.0.0",
                              "vulns": [{"id": "PYSEC-0000-0", "fix_versions": ["1.0.1"]}]}]}
NPM_CLEAN = {"auditReportVersion": 2, "vulnerabilities": {},
             "metadata": {"dependencies": {"total": 137}, "vulnerabilities": {"total": 0}}}
NPM_VULN = {"auditReportVersion": 2,
            "vulnerabilities": {"demo-ui": {"severity": "high", "range": "<2.0.0", "fixAvailable": True,
                                            "via": [{"url": "https://example.invalid/advisory/1", "title": "demo"}]}},
            "metadata": {"dependencies": {"total": 137}, "vulnerabilities": {"total": 1}}}


def test_parse_reports():
    assert deps_audit.parse_pip_audit(PIP_CLEAN) == (2, [])
    count, found = deps_audit.parse_pip_audit(PIP_VULN)
    assert count == 1 and found[0].advisory == "PYSEC-0000-0" and found[0].fix == "1.0.1"
    assert deps_audit.parse_npm_audit(NPM_CLEAN) == (137, [])
    count, found = deps_audit.parse_npm_audit(NPM_VULN)
    assert count == 137 and found[0].severity == "high" and found[0].advisory == "https://example.invalid/advisory/1"


def _fake_run(pip_report, npm_report, calls):
    def run(cmd, cwd):
        calls.append(cmd)
        report = npm_report if "audit" in cmd and "pip-audit" not in " ".join(cmd) else pip_report
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(report), stderr="")
    return run


@pytest.fixture
def fake_tools(monkeypatch, tmp_path):
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "package-lock.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(deps_audit.shutil, "which", lambda name: f"/tools/{name}")
    return tmp_path


def test_run_writes_status_and_verdict_passes_when_clean(fake_tools, monkeypatch):
    calls: list = []
    monkeypatch.setattr(deps_audit, "_run", _fake_run(PIP_CLEAN, NPM_CLEAN, calls))
    path = fake_tools / "status.json"
    deps_audit.run(fake_tools, status_path=path)
    current = deps_audit.status(status_path=path)
    assert current["finding_count"] == 0 and not current["errors"] and not current["stale"]
    ok, line = deps_audit.verdict(current)
    assert ok and "0 known vulnerabilities in 2 Python and 137 UI packages" in line
    assert any("requirements.lock" in cmd for cmd in calls)


def test_a_finding_fails_the_verdict(fake_tools, monkeypatch):
    monkeypatch.setattr(deps_audit, "_run", _fake_run(PIP_VULN, NPM_VULN, []))
    path = fake_tools / "status.json"
    deps_audit.run(fake_tools, status_path=path)
    ok, line = deps_audit.verdict(deps_audit.status(status_path=path))
    assert not ok and "2 known vulnerabilities" in line


def test_missing_tool_is_recorded_not_raised(fake_tools, monkeypatch):
    monkeypatch.setattr(deps_audit.shutil, "which", lambda name: None)
    path = fake_tools / "status.json"
    deps_audit.run(fake_tools, status_path=path)
    current = deps_audit.status(status_path=path)
    ok, line = deps_audit.verdict(current)
    assert ok and len(current["errors"]) == 2 and "incomplete" in line


def test_stale_audit_is_a_notice_and_refresh_reruns_it(fake_tools, monkeypatch):
    path = fake_tools / "status.json"
    old = (datetime.now(timezone.utc) - timedelta(days=deps_audit.MAX_AGE_DAYS + 1)).isoformat(timespec="seconds")
    path.write_text(json.dumps({"checked_at": old, "python": {"ok": True, "packages": 2, "findings": []},
                                "npm": {"ok": True, "packages": 137, "findings": []}}), encoding="utf-8")
    ok, line = deps_audit.verdict(deps_audit.status(status_path=path))
    assert ok and "older than 7 days" in line
    calls: list = []
    monkeypatch.setattr(deps_audit, "_run", _fake_run(PIP_CLEAN, NPM_CLEAN, calls))
    assert deps_audit.refresh_if_stale(fake_tools, status_path=path) is not None
    assert calls and deps_audit.refresh_if_stale(fake_tools, status_path=path) is None  # fresh now: no second run


def test_no_audit_yet():
    assert deps_audit.verdict(None) == (True, "no audit yet (python -m jav.cli deps-audit)")


def test_the_service_only_reads_the_last_result(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from jav import api

    path = tmp_path / "deps-audit.json"
    monkeypatch.setattr(deps_audit, "STATUS_PATH", path)
    monkeypatch.setattr(deps_audit, "run", lambda *a, **k: pytest.fail("the service must not run the audit"))
    client = TestClient(api.create_app(store_path=tmp_path / "w.sqlite"), base_url="http://127.0.0.1:8930")
    assert client.get("/api/system/deps-audit").json() == {"status": None, "max_age_days": deps_audit.MAX_AGE_DAYS}
    path.write_text(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "python": {"ok": True, "packages": 2, "findings": []},
                                "npm": {"ok": True, "packages": 137, "findings": []}}), encoding="utf-8")
    body = client.get("/api/system/deps-audit").json()["status"]
    assert body["finding_count"] == 0 and body["python"]["packages"] == 2 and not body["stale"]
