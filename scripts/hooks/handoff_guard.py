"""Claude Code hook: a sorszámozott handoff (docs/handoffs/NNN-ÉÉÉÉ-HH-NN-handoff.md) őre. Csak stdlib.

Használat (a .claude/settings.json hívja, a projekt gyökeréből):
  python scripts/hooks/handoff_guard.py session-start   # SessionStart: a legfrissebb handoff a kontextusba (stdout)
  python scripts/hooks/handoff_guard.py pre-compact     # PreCompact: figyelmeztetés, ha a handoff elavult
  python scripts/hooks/handoff_guard.py stop            # Stop: nem enged leállni, ha friss kód mellett régi a handoff

Szabály: a handoff "elavult", ha a jav/, tests/ vagy configs/ alatt van nála STALE_MINUTES perccel frissebb fájl.
2026-09-27 (040, a felhasználó döntése): a Stop-hook már NEM blokkol óránként. Átadó csak session végén és
szakaszzáráskor kell; a finom történetet a git viszi. Elavult átadónál a Stop csak emlékeztet (systemMessage):
hány commit készült a legutóbbi átadó óta, és van-e commitolatlan változás.
A SessionStart a TELJES legfrissebb handoffot adja a kontextusba (2026-09-20-tól; korábban csak az első 40 sort), és a
`preflight` parancsot ajánlja. A Stop-hook a `docs/STATE.md` állapot-pillanatképet is frissíti (best-effort, a venv
Pythonjával), hogy a handoff mindig friss generált állapotra hivatkozhasson.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HANDOFFS = ROOT / "docs" / "handoffs"
STATE = ROOT / "docs" / "STATE.md"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
WATCH = [ROOT / "jav", ROOT / "tests", ROOT / "configs", ROOT / "docs" / "ROADMAP.md", ROOT / "README.md"]
STALE_MINUTES = 60
_NUM = re.compile(r"^(\d{3})-\d{4}-\d{2}-\d{2}-handoff\.md$")


def latest_handoff() -> tuple[Path | None, int]:
    files = sorted((p for p in HANDOFFS.glob("*-handoff.md") if _NUM.match(p.name)), key=lambda p: p.name)
    if not files:
        return None, 0
    return files[-1], int(_NUM.match(files[-1].name).group(1))


def newest_code_mtime() -> float:
    newest = 0.0
    for w in WATCH:
        paths = [w] if w.is_file() else (p for p in w.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        for p in paths:
            try:
                newest = max(newest, p.stat().st_mtime)
            except OSError:
                pass
    return newest


def staleness_minutes(handoff: Path | None) -> float:
    """Hány perccel frissebb a legfrissebb figyelt fájl a handoffnál (negatív: a handoff a frissebb)."""
    if handoff is None:
        return float("inf")
    return (newest_code_mtime() - handoff.stat().st_mtime) / 60


def git(*args: str) -> str | None:
    """Egy git-parancs kimenete (strip), vagy None, ha nincs git / nem repó / hiba. Sosem dob."""
    try:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def git_summary(handoff: Path | None) -> dict | None:
    """Ág, HEAD, commitolatlan fájlok száma, és a legutóbbi átadó megírása óta készült commitok száma.

    070 (döntés 2026-09-29): az átadó belső munkaanyag, nincs commitban, ezért a számolás az átadó fájl írási idejétől
    indul (a commit ideje szerint)."""
    head = git("rev-parse", "--short", "HEAD")
    if head is None:
        return None
    status = git("status", "--porcelain") or ""
    since = None
    if handoff is not None:
        written = datetime.fromtimestamp(handoff.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        n = git("rev-list", "--count", f"--since={written}", "HEAD")
        since = int(n) if n and n.isdigit() else None
    return {"branch": git("branch", "--show-current") or "?", "head": head,
            "dirty": len([line for line in status.splitlines() if line.strip()]), "commits_since_handoff": since}


def format_git_line(g: dict | None) -> str:
    if g is None:
        return "git: nem elérhető"
    since = ("az átadó óta készült commitok száma nem állapítható meg" if g["commits_since_handoff"] is None
             else f"{g['commits_since_handoff']} commit a legutóbbi átadó óta")
    return f"git: ág {g['branch']} @ {g['head']}, {g['dirty']} commitolatlan fájl, {since}"


def stop_message(stale: float, g: dict | None, next_num: int) -> str | None:
    """Nem blokkoló emlékeztető a Stop-hookhoz, vagy None. Csak elavult átadónál szól."""
    if stale <= STALE_MINUTES:
        return None
    parts = [f"[handoff-guard] {format_git_line(g)}."]
    if g is not None and g["dirty"]:
        parts.append("Commitold a kész logikai egységet (docs/guides/DEVELOPMENT.md).")
    parts.append(f"Session végén vagy szakaszzáráskor írd meg a(z) {next_num:03d}-as átadót (docs/handoffs/TEMPLATE.md).")
    return " ".join(parts)


def refresh_state(timeout_s: float = 15.0) -> str:
    """`docs/STATE.md` újragenerálása a venv Pythonjával, ha a kód frissebb nála. Sosem dob; rövid státusz-szöveget ad."""
    if not VENV_PY.exists():
        return "STATE.md: a venv hiányzik, nem frissült"
    if STATE.exists() and STATE.stat().st_mtime >= newest_code_mtime():
        return "STATE.md friss"
    try:
        r = subprocess.run([str(VENV_PY), "-m", "jav.cli", "admin", "--write"], cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout_s)
        return "STATE.md frissítve" if r.returncode == 0 else f"STATE.md frissítés hibával: {(r.stderr or '').strip()[-160:]}"
    except (OSError, subprocess.SubprocessError) as exc:
        return f"STATE.md nem frissült: {exc}"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows cp1250 csapda: a hook kimenete UTF-8
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    event = sys.argv[1] if len(sys.argv) > 1 else "session-start"
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        payload = {}
    handoff, num = latest_handoff()
    stale = staleness_minutes(handoff)
    rel = handoff.relative_to(ROOT).as_posix() if handoff else "(nincs handoff)"

    if event == "session-start":
        state_age = f"{(time.time() - STATE.stat().st_mtime) / 60:.0f} perce" if STATE.exists() else "HIÁNYZIK"
        lines = [f"[handoff-guard] Legfrissebb handoff: {rel} - a következő sorszám: {num + 1:03d}. docs/STATE.md: {state_age}.",
                 "Session-protokoll (CLAUDE.md §2): 1. `.venv\\Scripts\\python.exe -m jav.cli preflight` (pytest + lint + konfigok +"
                 " handoff-frissesség + STATE.md), 2. olvasd a handoffot (lent teljes), docs/BACKLOG.md, docs/DECISIONS.md, docs/GLOSSARY.md (fogalomtár: minden felhasználónak szóló szöveg ennek a nyelvén, CLAUDE.md §8),"
                 " 3. 5-8 soros összefoglaló + nyitott döntések, és kérdezd meg a felhasználót, mielőtt építesz.",
                 f"[handoff-guard] {format_git_line(git_summary(handoff))}."]
        if stale > STALE_MINUTES:
            lines.append(f"FIGYELEM: a kód {stale:.0f} perccel frissebb a handoffnál - az állapot-leírás elavult lehet, ellenőrizd.")
        if handoff:
            body = handoff.read_text(encoding="utf-8").splitlines()
            lines += ["", f"--- {rel} (teljes, {len(body)} sor) ---", *body, f"--- {rel} vége ---"]
        print("\n".join(lines))
        return 0

    if event == "pre-compact":
        trigger = payload.get("trigger") or payload.get("matcher") or "?"
        if stale > STALE_MINUTES or handoff is None:
            msg = (f"[handoff-guard] Kontextus-tömörítés ({trigger}) jön, és a handoff elavult ({rel}, a kód {stale:.0f} perccel"
                   f" frissebb). Tömörítés után az első teendő: írd meg a {num + 1:03d}-as handoffot a docs/handoffs/ mappába.")
        else:
            msg = f"[handoff-guard] Kontextus-tömörítés ({trigger}); a handoff friss ({rel})."
        print(json.dumps({"systemMessage": msg}, ensure_ascii=False))
        return 0

    if event == "stop":
        if payload.get("stop_hook_active"):
            return 0
        msg = stop_message(stale, git_summary(handoff), num + 1)
        if msg:
            refresh_state()
            print(json.dumps({"systemMessage": msg}, ensure_ascii=False))
        return 0

    print(f"[handoff-guard] ismeretlen esemény: {event}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
