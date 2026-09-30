"""Session-indító ellenőrzés egy parancsban (`python -m jav.cli preflight`), API-hívás nélkül.

Lépések: pytest (alfolyamat) → a felület típusellenőrzése és tesztjei (`ui/`, ha telepítve van) → Burr-kontrakt lint → konfig-verziók + hash → handoff-frissesség (docs/handoffs/,
040 óta csak jelzés) → git-állapot → Ruff-racsni (`pyproject.toml` `max_findings`) → `docs/STATE.md` újragenerálása (a vezérlő képernyő fájlba). Kilépési kód 0 = minden zöld. A session-protokoll
(CLAUDE.md §2) ezt kéri elsőként; a handoff csak hivatkozza a STATE.md-t, nem másolja.
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


def run_pytest() -> tuple[bool, str]:
    """`pytest tests/ -q` alfolyamatban; visszaadja az összegző sort."""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    summary = lines[-1] if lines else (r.stderr or "").strip()[-200:]
    return r.returncode == 0, summary


def run_ui_checks() -> tuple[bool, str] | None:
    """A felület (040 K3): `tsc --noEmit` + `vitest run` + (057) fordítás-teljesség (`scripts/check-i18n.mjs` és
    `--audit`). Ha a Node-függőségek nincsenek telepítve, kihagyjuk (None)."""
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
    if handoff is None:  # 070: az átadó belső munkaanyag, friss klónban nincs meg - jelzés, nem hiba
        return True, "nincs helyi átadó a docs/handoffs/ alatt (belső munkaanyag; friss klón?)"
    minutes = (newest_watched_mtime() - handoff.stat().st_mtime) / 60
    rel = handoff.relative_to(PROJECT_ROOT).as_posix()
    if minutes > 60:  # 040/4 döntés: átadó csak session végén / szakaszzáráskor kell, ezért ez jelzés, nem hiba
        return True, f"{rel} - a kód {minutes:.0f} perccel frissebb; session végén írd meg a {num + 1:03d}-at"
    return True, f"{rel} (friss; következő sorszám: {num + 1:03d})"


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
