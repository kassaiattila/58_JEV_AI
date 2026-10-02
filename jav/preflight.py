"""Session-start check in one command (`python -m jav.cli preflight`), without API calls.

Steps: pytest (subprocess) → type check and tests of the UI (`ui/`, if installed) → Burr contract lint → config
versions + hash → handoff freshness (docs/handoffs/, only a notice since 040) → git state → data guard (071) →
language guard (073) → dependency audit age and findings (075) → Ruff ratchet (`pyproject.toml` `max_findings`) → regeneration of `docs/STATE.md` (the control
screen, written to a file). Exit code 0 = everything green. The session protocol (CLAUDE.md §2) asks for this first;
the handoff only references STATE.md, it does not copy it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from jav import cfg, devstate
from jav.admin import STATE_PATH, flow_lint_summary, write_state
from jav.config import PROJECT_ROOT

HANDOFFS = PROJECT_ROOT / "docs" / "handoffs"
UI_DIR = PROJECT_ROOT / "ui"
WATCH = [PROJECT_ROOT / "jav", PROJECT_ROOT / "tests", PROJECT_ROOT / "configs", UI_DIR / "src"]
_NUM = re.compile(r"^(\d{3})-\d{4}-\d{2}-\d{2}-handoff\.md$")


PREFLIGHT_RUNS = PROJECT_ROOT / "runs" / "preflight"
KEEP_LOGS = 20
_LOG_DIR = re.compile(r"^\d{8}_\d{6}$")


def run_pytest() -> tuple[bool, str]:
    """`pytest tests/ -q` in a subprocess; returns the summary line, and on a failure the failed tests' names too (086:
    an intermittent failure could not be identified from the summary line alone). 092 (audit T1): the raw output and a
    JUnit file are kept under `runs/preflight/<timestamp>/` (the latest `KEEP_LOGS`); a failure names the folder."""
    folder = PREFLIGHT_RUNS / time.strftime("%Y%m%d_%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider", "-rfE", f"--junitxml={folder / 'junit.xml'}"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    (folder / "pytest.txt").write_text((r.stdout or "") + (f"\n--- stderr ---\n{r.stderr}" if r.stderr else ""), encoding="utf-8")
    _prune_logs(PREFLIGHT_RUNS)
    lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    summary = lines[-1] if lines else (r.stderr or "").strip()[-200:]
    failed = [ln.split(" - ")[0] for ln in lines if ln.startswith(("FAILED ", "ERROR "))]
    if failed:
        summary += "; " + ", ".join(failed[:5]) + (f" (+{len(failed) - 5})" if len(failed) > 5 else "")
    if r.returncode != 0:
        summary += f"; log: {folder}"
    return r.returncode == 0, summary


def _prune_logs(root: Path) -> None:
    """Keeps the latest `KEEP_LOGS` timestamped log folders; anything else in the folder is left alone."""
    logs = sorted(p for p in root.iterdir() if p.is_dir() and _LOG_DIR.match(p.name))
    for old in logs[:-KEEP_LOGS]:
        shutil.rmtree(old)


def run_ui_checks() -> tuple[bool, str] | None:
    """The UI (040 K3): `tsc --noEmit` + `vitest run` + (057) translation completeness (`scripts/check-i18n.mjs` and
    `--audit`). Skipped (None) if the Node dependencies are not installed."""
    npx = shutil.which("npx")
    if npx is None or not (UI_DIR / "node_modules").is_dir():
        return None
    tsc = subprocess.run([npx, "tsc", "--noEmit"], cwd=UI_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if tsc.returncode != 0:
        first = next((ln for ln in (tsc.stdout or "").splitlines() if ln.strip()), "tsc hiba")
        return False, f"típusellenőrzés: {first[:160]}"
    node = shutil.which("node")
    for extra in (["--audit"], []):
        if node is None:
            break
        i18n = subprocess.run([node, "scripts/check-i18n.mjs", *extra], cwd=UI_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if i18n.returncode != 0:
            last = [ln for ln in (i18n.stderr or "").splitlines() if ln.strip()]
            return False, f"fordítás: {(last[-1] if last else 'check-i18n hiba')[:160]}"
    r = subprocess.run([npx, "vitest", "run"], cwd=UI_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tests = next((ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip().startswith("Tests")), "")
    return r.returncode == 0, f"típusellenőrzés és fordítás OK; {re.sub(r'\s+', ' ', tests) or 'vitest: nincs összegzés'}"


def latest_handoff() -> tuple[Path | None, int]:
    files = sorted((p for p in HANDOFFS.glob("*-handoff.md") if _NUM.match(p.name)), key=lambda p: p.name)
    return (files[-1], int(_NUM.match(files[-1].name).group(1))) if files else (None, 0)


def newest_watched_mtime() -> float:
    newest = 0.0
    for w in WATCH:
        for p in w.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                newest = max(newest, p.stat().st_mtime)
    return newest


def handoff_status() -> tuple[bool, str]:
    handoff, num = latest_handoff()
    if handoff is None:  # 070: the handoff is an internal document, absent in a fresh clone - a notice, not an error
        return True, "nincs helyi átadó a docs/handoffs/ alatt (belső munkaanyag; friss klón?)"
    minutes = (newest_watched_mtime() - handoff.stat().st_mtime) / 60
    rel = handoff.relative_to(PROJECT_ROOT).as_posix()
    if minutes > 60:  # decision 040/4: a handoff is due only at session end / stage close, so a notice, not an error
        return True, f"{rel} - a kód {minutes:.0f} perccel frissebb; session végén írd meg a {num + 1:03d}-at"
    return True, f"{rel} (friss; következő sorszám: {num + 1:03d})"


def data_guard_status() -> tuple[bool, str]:
    """071 S-adatőr: whether the versioned hooks are enabled, and whether the tracked files contain a blocking
    finding."""
    from jav import data_guard

    try:
        found = data_guard.scan_tracked(PROJECT_ROOT, data_guard.load_guard(PROJECT_ROOT))
    except data_guard.DataGuardError as e:
        return True, f"nem ellenőrizhető ({e})"
    stop = data_guard.blocking(found)
    parts = [f"{len(stop)} megállító, {len(found) - len(stop)} tűrt találat a verziókövetett fájlokban"]
    if stop:
        parts.append("átnézés: python -m jav.cli data-guard")
    installed = data_guard.hooks_installed(PROJECT_ROOT)
    if not installed:
        parts.insert(0, "a horgok nincsenek bekapcsolva (python -m jav.cli hooks-install)")
    return installed and not stop, "; ".join(parts)


def lang_guard_status() -> tuple[bool, str]:
    """073 language guard: no tracked file has more Hungarian lines than its baseline (configs/lang_guard.json)."""
    from jav import lang_guard

    try:
        guard = lang_guard.load_guard(PROJECT_ROOT)
        counts = lang_guard.scan(PROJECT_ROOT, guard)
    except lang_guard.LangGuardError as e:
        return True, f"cannot check ({e})"
    over = lang_guard.excess(counts, guard)
    msg = f"{sum(counts.values())} Hungarian lines in {len(counts)} files (baseline {sum(guard.baseline.values())})"
    if over:
        msg += f"; over the baseline: {', '.join(e.path for e in over[:5])}{' …' if len(over) > 5 else ''} (python -m jav.cli lang-guard)"
    return not over, msg


def preflight(*, skip_pytest: bool = False) -> int:
    t0 = time.perf_counter()
    results: list[tuple[str, bool, str]] = []

    if not skip_pytest:
        ok, summary = run_pytest()
        results.append(("pytest", ok, summary))
        ui = run_ui_checks()
        results.append(("felület", ui[0], ui[1]) if ui else ("felület", True, "kihagyva (ui/node_modules nincs telepítve)"))

    lint = flow_lint_summary()
    results.append(("kontrakt-lint", all(ok for _, ok, _ in lint), ", ".join(f"{n}: {'PASS' if ok else f'FAIL({f})'}" for n, ok, f in lint)))

    rows = cfg.report()
    results.append(("konfigok", True, ", ".join(f"{r['name']} {r['version']} {r['hash'][:8]}" for r in rows)))

    ok, msg = handoff_status()
    results.append(("handoff", ok, msg))

    g = devstate.git_state()
    results.append(("git", True, g.line() if g else "nem git-repó / git nem érhető el"))

    ok, msg = data_guard_status()
    results.append(("adatőr", ok, msg))

    ok, msg = lang_guard_status()
    results.append(("language guard", ok, msg))

    from jav import deps_audit

    ok, msg = deps_audit.verdict(deps_audit.status())
    results.append(("dependency audit", ok, msg))

    found = devstate.ruff_findings()
    ok, msg = devstate.lint_verdict(found[0] if found else None, devstate.lint_limit())
    results.append(("ruff", ok, msg))

    path = write_state()
    results.append(("STATE.md", True, path.relative_to(PROJECT_ROOT).as_posix()))

    print(f"# preflight ({time.perf_counter() - t0:.1f} s)\n")
    for name, ok, detail in results:
        print(f"- {'OK  ' if ok else 'FAIL'} {name}: {detail}")
    print(f"\nÁllapot-pillanatkép: {STATE_PATH.relative_to(PROJECT_ROOT).as_posix()} · teendők: docs/BACKLOG.md · döntések: docs/DECISIONS.md")
    return 0 if all(ok for _, ok, _ in results) else 1
