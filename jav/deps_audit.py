"""Regular dependency audit (075): known vulnerabilities in the pinned packages, with a date.

Two checks, both free and read-only (they query public vulnerability databases, not our data):
- Python: `pip-audit -r requirements.lock --no-deps` (the installed `pip-audit`, or `uvx pip-audit` when only uv is
  present);
- UI: `npm audit --json` in `ui/` (the pinned `package-lock.json`).

The result goes to `runs/deps-audit.json` (not in git). The start-up check reports its age and findings, the System
page shows it, and the scheduled daily backup refreshes it when it is older than `MAX_AGE_DAYS` (`refresh_if_stale`).
A missing tool or network error is recorded as a failed audit, never raised: the audit must not stop a backup.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jav.config import PROJECT_ROOT

STATUS_PATH = PROJECT_ROOT / "runs" / "deps-audit.json"
MAX_AGE_DAYS = 7
TIMEOUT_S = 600


@dataclass(frozen=True)
class Finding:
    ecosystem: str  # "python" | "npm"
    package: str
    version: str
    advisory: str
    severity: str | None = None
    fix: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pip_audit_cmd() -> list[str] | None:
    exe = shutil.which("pip-audit")
    if exe:
        return [exe]
    uvx = shutil.which("uvx")
    return [uvx, "pip-audit"] if uvx else None


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=TIMEOUT_S, env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def parse_pip_audit(report: dict[str, Any]) -> tuple[int, list[Finding]]:
    """(number of packages checked, findings) from `pip-audit --format json`."""
    deps = report.get("dependencies") or []
    found = [Finding("python", d["name"], d.get("version", ""), v.get("id", "?"), None, ", ".join(v.get("fix_versions") or []) or None)
             for d in deps for v in d.get("vulns") or []]
    return len(deps), found


def parse_npm_audit(report: dict[str, Any]) -> tuple[int, list[Finding]]:
    """(number of packages checked, findings) from `npm audit --json` (report version 2)."""
    total = int(((report.get("metadata") or {}).get("dependencies") or {}).get("total") or 0)
    found = []
    for name, v in (report.get("vulnerabilities") or {}).items():
        via = [x for x in v.get("via") or [] if isinstance(x, dict)]
        advisory = ", ".join(sorted({str(x.get("url") or x.get("source") or x.get("title") or "?") for x in via})) or "via dependency"
        fix = v.get("fixAvailable")
        found.append(Finding("npm", name, str(v.get("range") or ""), advisory, v.get("severity"),
                             "available" if fix else None))
    return total, found


def _python(root: Path) -> dict[str, Any]:
    cmd = _pip_audit_cmd()
    if cmd is None:
        return {"ok": False, "error": "pip-audit not found (install it, or install uv for uvx)"}
    try:
        proc = _run([*cmd, "-r", "requirements.lock", "--no-deps", "--format", "json", "--progress-spinner", "off"], root)
        count, found = parse_pip_audit(json.loads(proc.stdout or "{}"))
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    if count == 0:
        return {"ok": False, "error": (proc.stderr or "no report").strip().splitlines()[-1][:200]}
    return {"ok": True, "packages": count, "findings": [f.__dict__ for f in found]}


def _npm(root: Path) -> dict[str, Any]:
    npm = shutil.which("npm")
    ui = root / "ui"
    if npm is None or not (ui / "package-lock.json").is_file():
        return {"ok": False, "error": "npm or ui/package-lock.json not found"}
    try:
        proc = _run([npm, "audit", "--json"], ui)
        count, found = parse_npm_audit(json.loads(proc.stdout or "{}"))
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    if count == 0:
        return {"ok": False, "error": (proc.stderr or "no report").strip().splitlines()[-1][:200] if proc.stderr else "empty report"}
    return {"ok": True, "packages": count, "findings": [f.__dict__ for f in found]}


def run(root: Path = PROJECT_ROOT, *, status_path: Path | None = None) -> dict[str, Any]:
    """Runs both audits and writes the status file; returns the status."""
    status = {"checked_at": _now().isoformat(timespec="seconds"), "python": _python(root), "npm": _npm(root)}
    path = status_path or STATUS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    return status


def status(*, status_path: Path | None = None, now: datetime | None = None) -> dict[str, Any] | None:
    """The last audit with its age and a verdict, or None if there has been none."""
    path = status_path or STATUS_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        checked = datetime.fromisoformat(data["checked_at"])
    except (OSError, ValueError, KeyError):
        return None
    age = ((now or _now()) - checked).total_seconds() / 86400
    findings = [f for part in ("python", "npm") for f in (data.get(part) or {}).get("findings") or []]
    errors = [f"{part}: {data[part]['error']}" for part in ("python", "npm") if not (data.get(part) or {}).get("ok")]
    return {**data, "age_days": round(age, 1), "stale": age > MAX_AGE_DAYS, "finding_count": len(findings), "errors": errors}


def refresh_if_stale(root: Path = PROJECT_ROOT, *, status_path: Path | None = None) -> dict[str, Any] | None:
    """For the scheduled daily backup: runs the audit only if the last one is missing, stale or failed."""
    current = status(status_path=status_path)
    if current is not None and not current["stale"] and not current["errors"]:
        return None
    return run(root, status_path=status_path)


def verdict(current: dict[str, Any] | None) -> tuple[bool, str]:
    """(passes, one line) for the start-up check: a finding fails; a missing, stale or failed audit is only a notice."""
    if current is None:
        return True, "no audit yet (python -m jav.cli deps-audit)"
    line = (f"{current['checked_at'][:10]} ({current['age_days']:g} days ago): {current['finding_count']} known vulnerabilities"
            f" in {(current.get('python') or {}).get('packages', 0)} Python and {(current.get('npm') or {}).get('packages', 0)} UI packages")
    if current["errors"]:
        line += f"; incomplete: {'; '.join(current['errors'])}"
    if current["stale"]:
        line += f"; older than {MAX_AGE_DAYS} days (python -m jav.cli deps-audit)"
    return current["finding_count"] == 0, line
