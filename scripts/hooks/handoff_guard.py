"""Claude Code / Codex hook: guard of the numbered project handoff. Stdlib only.

Usage (called by the host's hook configuration; resolves paths from this file):
  python scripts/hooks/handoff_guard.py session-start   # SessionStart: the latest handoff into the context (stdout)
  python scripts/hooks/handoff_guard.py pre-compact     # PreCompact: warning if the handoff is stale
  python scripts/hooks/handoff_guard.py stop            # Stop: non-blocking reminder if the handoff is stale
  python scripts/hooks/handoff_guard.py autopilot on --plan <path> | off | status   # 231: the autopilot switch

231 (DECISIONS 231, the owner's decision of 2026-10-24): the autopilot. While it is on, the Stop hook of Claude Code
(only its hooks pass `--host claude`; the Codex hooks never block) does not let Claude stop between the steps of an
approved plan: it answers `{"decision": "block", "reason": ...}` and Claude carries on. The stop goes through when the
owner has to decide (Claude wrote the decision marker `.claude/autopilot/needs_owner.md`), when a background task is
still running (its notification wakes Claude), and after `IDLE_STOPS` stops in a row with nothing changed (stuck). At a
session start, after a compaction too, the hook adds the autopilot's state, a pending question and the end of the
plan's progress section to the context.

Rule: the handoff is "stale" if a file under jav/, tests/ or configs/ (or docs/ROADMAP.md, README.md) is more than
STALE_MINUTES minutes newer than it.
2026-09-27 (040, the owner's decision): the Stop hook NO longer blocks every hour. A handoff is needed only at the end
of a session and when a stage closes; git carries the fine-grained history. With a stale handoff the Stop hook only
reminds (systemMessage): how many commits were made since the latest handoff, and whether there are uncommitted changes.
SessionStart puts the FULL latest handoff into the context (since 2026-09-20; earlier only the first 40 lines) and
recommends the `preflight` command. With a stale handoff the Stop hook also refreshes the `docs/STATE.md` state snapshot
(best-effort, with the venv's Python), so that the handoff can always refer to a freshly generated state.
"""

from __future__ import annotations

import hashlib
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

AUTOPILOT_DIR = ROOT / ".claude" / "autopilot"
AUTOPILOT_STATE = AUTOPILOT_DIR / "state.json"
NEEDS_OWNER = AUTOPILOT_DIR / "needs_owner.md"
IDLE_STOPS = 2  # stops in a row with nothing changed before the autopilot lets the stop through
PROGRESS_LINES = 60  # the end of the plan's progress section shown at a session start
_PROGRESS = re.compile(r"^##\s+(Haladás|Progress)\b")
BLOCK = ("Autopilot (DECISIONS 231): do not stop yet. Continue with the next step of the approved plan ({plan}) under "
         "the autopilot rules of CLAUDE.md §2: commit each finished slice, run the full suite in the test worktree "
         "before a merge, and record the progress in the plan's progress section. Stop only for a genuine owner "
         "decision: write .claude/autopilot/needs_owner.md (the question, the options, your recommendation), send a "
         "push notification, then ask.")
BLOCK_IDLE = ("Autopilot: nothing changed since the last stop. If the plan has a next step, do it now. If the owner has "
              "to decide, write .claude/autopilot/needs_owner.md first. If the plan is finished, write the handoff and "
              "the marker with the next decision.")


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
    """How many minutes newer the newest watched file is than the handoff (negative: the handoff is newer)."""
    if handoff is None:
        return float("inf")
    return (newest_code_mtime() - handoff.stat().st_mtime) / 60


def git(*args: str) -> str | None:
    """The output of a git command (stripped), or None if there is no git / no repository / an error. Never raises."""
    try:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def git_summary(handoff: Path | None) -> dict | None:
    """Branch, HEAD, number of uncommitted files, and the number of commits made since the latest handoff was written.

    070 (decision of 2026-09-29): the handoff is an internal working document and not committed, so the count starts
    from the handoff file's write time (by commit time)."""
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
    """Non-blocking reminder for the Stop hook, or None. It speaks up only for a stale handoff."""
    if stale <= STALE_MINUTES:
        return None
    parts = [f"[handoff-guard] {format_git_line(g)}."]
    if g is not None and g["dirty"]:
        parts.append("Commitold a kész logikai egységet (docs/guides/DEVELOPMENT.md).")
    parts.append(f"Session végén vagy szakaszzáráskor írd meg a(z) {next_num:03d}-as átadót (docs/handoffs/TEMPLATE.md).")
    return " ".join(parts)


def refresh_state(timeout_s: float = 15.0) -> str:
    """Regenerates `docs/STATE.md` with the venv's Python if the code is newer. Never raises; returns a short status."""
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


def autopilot_state() -> dict | None:
    """The autopilot's state while it is on, else None (no file, a broken file, or switched off)."""
    try:
        state = json.loads(AUTOPILOT_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) and state.get("enabled") else None


def save_autopilot(state: dict) -> None:
    AUTOPILOT_DIR.mkdir(parents=True, exist_ok=True)
    AUTOPILOT_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def work_fingerprint() -> str:
    """What the work looks like now: HEAD, every changed or new file with its size and time, and the newest document
    under docs/ (the plans and the handoffs are not in git). Two stops with the same fingerprint changed nothing."""
    parts = [git("rev-parse", "HEAD") or ""]
    for line in (git("status", "--porcelain", "--untracked-files=all") or "").splitlines():
        try:
            st = (ROOT / line[3:].strip().strip('"')).stat()
            parts.append(f"{line}|{st.st_size}|{st.st_mtime_ns}")
        except OSError:
            parts.append(line)
    newest = 0
    for p in (ROOT / "docs").rglob("*"):
        try:
            newest = max(newest, p.stat().st_mtime_ns)
        except OSError:
            pass
    parts.append(str(newest))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def autopilot_stop(state: dict, payload: dict, *, needs_owner: bool, fingerprint: str) -> tuple[str | None, dict, str | None]:
    """The Stop decision while the autopilot is on: (the reason to block the stop, or None to let it through; the new
    state; a message for the person when the stop goes through)."""
    if needs_owner:
        return None, state, "[autopilot] waiting for the owner's decision: .claude/autopilot/needs_owner.md"
    if payload.get("background_tasks"):
        return None, state, None  # a background task's notification wakes Claude
    if fingerprint == state.get("fingerprint"):
        idle = int(state.get("idle", 0)) + 1
        new = {**state, "idle": idle}
        if idle >= IDLE_STOPS:
            return None, new, f"[autopilot] {idle} stops in a row with nothing changed: stopped (stuck?). Write a message to go on."
        return BLOCK_IDLE, new, None
    return BLOCK.format(plan=state.get("plan") or "the latest handoff"), {**state, "fingerprint": fingerprint, "idle": 0}, None


def plan_progress(plan: str | None) -> list[str]:
    """The end of the plan's progress section (its Hungarian or English heading, `_PROGRESS`), at most
    `PROGRESS_LINES` lines."""
    if not plan:
        return []
    try:
        lines = (ROOT / plan).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    start = next((i for i, line in enumerate(lines) if _PROGRESS.match(line)), None)
    if start is None:
        return []
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start:end][-PROGRESS_LINES:]


def autopilot_lines(state: dict) -> list[str]:
    """What a session start adds while the autopilot is on (after a compaction too)."""
    lines = ["", f"[autopilot] ON since {state.get('since')}; plan: {state.get('plan')}. Continue the plan without asking; "
                 "stop only through the decision marker (CLAUDE.md §2, autopilot)."]
    if NEEDS_OWNER.exists():
        lines += ["[autopilot] PENDING OWNER DECISION (.claude/autopilot/needs_owner.md):",
                  *NEEDS_OWNER.read_text(encoding="utf-8").splitlines()]
    progress = plan_progress(state.get("plan"))
    if progress:
        lines += ["", f"--- {state.get('plan')}: progress ---", *progress, "--- progress end ---"]
    return lines


def autopilot_command(args: list[str]) -> int:
    """`autopilot on --plan <path>` | `off` | `status`."""
    action = args[0] if args else "status"
    raw: dict = {}
    try:
        raw = json.loads(AUTOPILOT_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if action == "on":
        plan = args[args.index("--plan") + 1] if "--plan" in args[:-1] else None
        if plan is None or not (ROOT / plan).is_file():
            print("autopilot on needs --plan <an existing plan file, relative to the project root>", file=sys.stderr)
            return 2
        save_autopilot({"enabled": True, "since": datetime.now().astimezone().isoformat(timespec="seconds"),
                        "plan": plan, "fingerprint": None, "idle": 0})
        print(f"autopilot ON; plan: {plan}")
        return 0
    if action == "off":
        save_autopilot({**raw, "enabled": False})
        print("autopilot OFF")
        return 0
    if action == "status":
        on = bool(raw.get("enabled"))
        print(f"autopilot {'ON' if on else 'OFF'}; plan: {raw.get('plan')}; since: {raw.get('since')}; "
              f"idle stops: {raw.get('idle', 0)}; owner decision pending: {'yes' if NEEDS_OWNER.exists() else 'no'}")
        return 0
    print(f"unknown autopilot action: {action}", file=sys.stderr)
    return 2


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows cp1250 trap: the hook's output is UTF-8
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    event = sys.argv[1] if len(sys.argv) > 1 else "session-start"
    if event == "autopilot":
        return autopilot_command(sys.argv[2:])
    claude = "--host" in sys.argv[2:-1] and sys.argv[sys.argv.index("--host") + 1] == "claude"
    autopilot = autopilot_state() if claude else None
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
                 "Session protocol: read AGENTS.md and the shared CLAUDE.md rules, then the latest handoff below, "
                 "docs/BACKLOG.md, docs/DECISIONS.md and docs/GLOSSARY.md. Use `.venv\\Scripts\\python.exe -m jav.cli preflight` "
                 "for the required checks; reuse completed checks when the relevant code and environment are unchanged. "
                 "Summarise the current state and unresolved decisions. Continue already authorised work; "
                 "ask only about unresolved scope, policy or budget decisions.",
                 f"[handoff-guard] {format_git_line(git_summary(handoff))}."]
        if stale > STALE_MINUTES:
            lines.append(f"FIGYELEM: a kód {stale:.0f} perccel frissebb a handoffnál - az állapot-leírás elavult lehet, ellenőrizd.")
        if handoff:
            body = handoff.read_text(encoding="utf-8").splitlines()
            lines += ["", f"--- {rel} (teljes, {len(body)} sor) ---", *body, f"--- {rel} vége ---"]
        if autopilot:
            lines += autopilot_lines(autopilot)
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
        if autopilot:
            reason, state, message = autopilot_stop(autopilot, payload, needs_owner=NEEDS_OWNER.exists(),
                                                    fingerprint=work_fingerprint())
            save_autopilot(state)
            if reason:
                print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
                return 0
            if message:
                print(json.dumps({"systemMessage": message}, ensure_ascii=False))
                return 0
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
