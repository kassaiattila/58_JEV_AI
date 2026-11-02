"""Session-start check in one command (`python -m jav.cli preflight`), without API calls.

Steps: pytest (subprocess; 189: in several processes with pytest-xdist) and, at the same time, the type check and tests
of the UI (`ui/`, if installed) → Burr contract lint → config
versions + hash → handoff freshness (docs/handoffs/, only a notice since 040) → git state → data guard (071) →
language guard (073) → dependency audit age and findings (075) → the pinned JEV version against the provider's moving
name (200, a notice) → Ruff ratchet (`pyproject.toml` `max_findings`) → regeneration of `docs/STATE.md` (the control
screen, written to a file). Exit code 0 = everything green. The session protocol (CLAUDE.md §2) asks for this first;
the handoff only references STATE.md, it does not copy it.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from xml.etree import ElementTree

from jav.core import cfg, devstate
from jav.devtools.admin import flow_lint_summary, write_state
from jav.core.config import PROJECT_ROOT

HANDOFFS = devstate.docs_root() / "docs" / "handoffs"  # 265 (code review TOOL-18): the main checkout's from a worktree
UI_DIR = PROJECT_ROOT / "ui"
WATCH = [PROJECT_ROOT / "jav", PROJECT_ROOT / "tests", PROJECT_ROOT / "configs", UI_DIR / "src"]
_NUM = re.compile(r"^(\d{3})-\d{4}-\d{2}-\d{2}-handoff\.md$")


PREFLIGHT_RUNS = PROJECT_ROOT / "runs" / "preflight"
KEEP_LOGS = 20
# 272 (K5): a full test run's folders carry the process too (`<time>_<pid>`, 265 TOOL-06), and are pruned as well
_LOG_DIR = re.compile(r"^\d{8}_\d{6}(_\d+)?$")
# 189: pytest-xdist runs the tests in this many processes at most (the full suite took 30 min in one, under 5 in six)
MAX_TEST_WORKERS = 6
GB_PER_TEST_WORKER = 1.5  # 265 (code review TOOL-05): what one pytest process may take at its peak
UI_TEST_WORKERS = 2  # 265 (TOOL-05): the UI's test processes beside the Python ones (vitest took 7 of 8 cores)
SLOWEST_SHOWN = 25  # the slowest tests listed in the raw output, so a new time sink shows


def parallel_workers() -> int:
    """189: how many processes run the tests at once: every core but two (the UI checks run beside them), at most
    `MAX_TEST_WORKERS`; 0 means one process, as before (pytest-xdist not installed, or too few cores to gain)."""
    if importlib.util.find_spec("xdist") is None:
        return 0
    workers = min(MAX_TEST_WORKERS, (os.cpu_count() or 1) - 2)
    free = available_memory_gb()
    if free is not None:  # 265 (code review TOOL-05): no more processes than the free memory holds
        workers = min(workers, int(free // GB_PER_TEST_WORKER))
    return workers if workers >= 2 else 0


def available_memory_gb() -> float | None:
    """The machine's free physical memory in GB (Windows: `GlobalMemoryStatusEx`; elsewhere `sysconf`), or None."""
    try:
        if os.name == "nt":
            import ctypes

            class _Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong), ("total_page", ctypes.c_ulonglong),
                            ("avail_page", ctypes.c_ulonglong), ("total_virtual", ctypes.c_ulonglong),
                            ("avail_virtual", ctypes.c_ulonglong), ("avail_ext", ctypes.c_ulonglong)]

            status = _Status()
            status.length = ctypes.sizeof(_Status)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return status.avail / 1e9
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1e9
    except (AttributeError, OSError, ValueError):
        return None


PYTEST_TIMEOUT_S = 90 * 60
UI_STEP_TIMEOUT_S = 30 * 60
STUCK_TEST_S = 15 * 60
TIMED_OUT = -9
"""265 (code review TOOL-11): a check's subprocess is stopped after its time limit and reported as failed (one stuck test
held the whole check for good); a single test running longer than `STUCK_TEST_S` has every thread's stack written to
the log (pytest's `faulthandler_timeout`), so the stuck one can be named."""


def _bounded(cmd: list[str], *, timeout: int, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """The command with its output captured as text and a time limit; a run past it is stopped and returned with the
    code `TIMED_OUT` and what it printed until then. 272 (K5, the rest of TOOL-11): with every process it started (a
    `.cmd` wrapper's node kept the output open, so the check waited for it after stopping the wrapper alone)."""
    with subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          encoding="utf-8", errors="replace", start_new_session=os.name != "nt") as proc:
        try:
            out, err = proc.communicate(timeout=timeout)
            return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
        except subprocess.TimeoutExpired:
            _stop_tree(proc)
            try:
                out, err = proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:  # a process outside the tree still holds the output: give up on it
                out, err = "", ""
            return subprocess.CompletedProcess(cmd, TIMED_OUT, out or "",
                                               (err or "") + f"\nstopped after {timeout // 60} minutes without finishing")


def _stop_tree(proc: subprocess.Popen[str]) -> None:
    """272 (K5): the process and every process it started (Windows: `taskkill /T`; elsewhere its session's group)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # it ended meanwhile
    proc.kill()


def _stopped(r: subprocess.CompletedProcess[str], what: str, timeout: int) -> str | None:
    return f"{what} stopped after {timeout // 60} minutes without finishing" if r.returncode == TIMED_OUT else None


def log_folder() -> Path:
    """A new timestamped folder under `runs/preflight/` for one full check's raw outputs (092, 149)."""
    folder = PREFLIGHT_RUNS / time.strftime("%Y%m%d_%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def run_pytest(folder: Path | None = None, *, root: Path = PROJECT_ROOT, env: dict[str, str] | None = None) -> tuple[bool, str]:
    """`pytest tests/ -q` in a subprocess; returns the summary line, and on a failure the failed tests' names too (086:
    an intermittent failure could not be identified from the summary line alone). 092 (audit T1): the raw output and a
    JUnit file are kept under `runs/preflight/<timestamp>/` (the latest `KEEP_LOGS`); a failure names the folder. 231: `root`
    and `env` run it in another working tree (`jav/devtools/test_worktree.py`)."""
    folder = folder or log_folder()
    workers = parallel_workers()
    # 189: in several processes, each free test going to the first idle one, and with the slowest tests listed
    parallel = ["-n", str(workers), "--dist", "worksteal"] if workers else []
    r = _bounded(
        [sys.executable, "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider", "-rfE", *parallel,
         f"--durations={SLOWEST_SHOWN}", f"--junitxml={folder / 'junit.xml'}", "-o", f"faulthandler_timeout={STUCK_TEST_S}"],
        cwd=root, env=env, timeout=PYTEST_TIMEOUT_S,
    )
    (folder / "pytest.txt").write_text((r.stdout or "") + (f"\n--- stderr ---\n{r.stderr}" if r.stderr else ""), encoding="utf-8")
    _prune_logs(folder.parent)
    lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    summary = _stopped(r, "pytest", PYTEST_TIMEOUT_S) or (lines[-1] if lines else (r.stderr or "").strip()[-200:])
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


def _failed_ui_tests(junit: Path) -> list[str]:
    """`file > test name` of every failed or errored test case in vitest's JUnit file (149)."""
    try:
        root = ElementTree.parse(junit).getroot()
    except (OSError, ElementTree.ParseError):
        return []
    return [f"{case.get('classname')} > {case.get('name')}" for case in root.iter("testcase")
            if case.find("failure") is not None or case.find("error") is not None]


def local_bin(ui_dir: Path, name: str) -> Path | None:
    """265 (code review TOOL-12): a UI tool from the UI's own `node_modules/.bin` (`.cmd` on Windows), or None. `npx`
    with a partial `node_modules` could fetch an unrelated package of that name from the network, unasked."""
    for candidate in (ui_dir / "node_modules" / ".bin" / f"{name}.cmd", ui_dir / "node_modules" / ".bin" / name):
        if candidate.is_file():
            return candidate
    return None


def run_ui_checks(folder: Path | None = None, *, ui_dir: Path = UI_DIR) -> tuple[bool, str] | None:
    """The UI (040 K3): `tsc --noEmit` + (265, code review UI-14) ESLint + `vitest run` + (057) translation completeness
    (`scripts/check-i18n.mjs` and `--audit`). Skipped (None) if the Node dependencies are not installed. 149: the vitest output and a JUnit file are
    kept next to the pytest log, and a failure names the failed tests and the folder (an intermittent UI failure could
    not be identified before)."""
    if not (ui_dir / "node_modules").is_dir():
        return None
    tsc_bin, vitest_bin = local_bin(ui_dir, "tsc"), local_bin(ui_dir, "vitest")
    if tsc_bin is None or vitest_bin is None:
        return False, "the UI's tsc or vitest is not installed in ui/node_modules (npm ci)"
    tsc = _bounded([str(tsc_bin), "--noEmit"], cwd=ui_dir, timeout=UI_STEP_TIMEOUT_S)
    if tsc.returncode != 0:
        first = next((ln for ln in (tsc.stdout or "").splitlines() if ln.strip()), "tsc error")
        return False, _stopped(tsc, "type check", UI_STEP_TIMEOUT_S) or f"type check: {first[:160]}"
    eslint_bin = local_bin(ui_dir, "eslint")
    if eslint_bin is None:
        return False, "the UI's eslint is not installed in ui/node_modules (npm ci)"
    lint = _bounded([str(eslint_bin), "."], cwd=ui_dir, timeout=UI_STEP_TIMEOUT_S)
    if lint.returncode != 0:
        said = [ln.strip() for ln in (lint.stdout or lint.stderr or "").splitlines() if ln.strip()]
        first = next((ln for ln in said if " error " in f" {ln} "), said[0] if said else "eslint error")
        return False, (_stopped(lint, "ESLint", UI_STEP_TIMEOUT_S)
                       or f"ESLint: {(said[-1] if said else '')[:80]} - {first[:120]}")
    node = shutil.which("node")
    for extra in (["--audit"], []):
        if node is None:
            break
        i18n = _bounded([node, "scripts/check-i18n.mjs", *extra], cwd=ui_dir, timeout=UI_STEP_TIMEOUT_S)
        if i18n.returncode != 0:
            last = [ln for ln in (i18n.stderr or "").splitlines() if ln.strip()]
            return False, (_stopped(i18n, "translations", UI_STEP_TIMEOUT_S)
                           or f"translations: {(last[-1] if last else 'check-i18n error')[:160]}")
    folder = folder or log_folder()
    junit = folder / "vitest-junit.xml"
    r = _bounded(
        [str(vitest_bin), "run", f"--maxWorkers={UI_TEST_WORKERS}", "--reporter=default", "--reporter=junit",
         f"--outputFile.junit={junit}"],
        cwd=ui_dir, timeout=UI_STEP_TIMEOUT_S,
    )
    (folder / "vitest.txt").write_text((r.stdout or "") + (f"\n--- stderr ---\n{r.stderr}" if r.stderr else ""), encoding="utf-8")
    tests = next((ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip().startswith("Tests")), "")
    summary = f"type check, ESLint and translations OK; {_stopped(r, 'vitest', UI_STEP_TIMEOUT_S) or re.sub(r'\s+', ' ', tests) or 'vitest: no summary'}"
    if r.returncode != 0:
        failed = _failed_ui_tests(junit)
        if failed:
            summary += "; " + ", ".join(failed[:5]) + (f" (+{len(failed) - 5})" if len(failed) > 5 else "")
        summary += f"; log: {folder}"
    return r.returncode == 0, summary


def run_tests(folder: Path, *, root: Path = PROJECT_ROOT, env: dict[str, str] | None = None) -> tuple[tuple[bool, str], tuple[bool, str] | None]:
    """189: pytest and the UI checks at the same time (both are subprocesses, each waited for in its own thread), their
    raw outputs in the same folder: (pytest's result, the UI's result or None when it is not installed). 231: `root`
    and `env` run both in another working tree."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        tests = pool.submit(run_pytest, folder, root=root, env=env)
        ui = pool.submit(run_ui_checks, folder, ui_dir=root / "ui")
        return tests.result(), ui.result()


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
        return True, "no local handoff under docs/handoffs/ (internal working documents; a fresh clone?)"
    minutes = (newest_watched_mtime() - handoff.stat().st_mtime) / 60
    rel = devstate.shown_path(handoff)
    if minutes > 60:  # decision 040/4: a handoff is due only at session end / stage close, so a notice, not an error
        return True, f"{rel} - the code is {minutes:.0f} minute(s) newer; write {num + 1:03d} at the end of the session"
    return True, f"{rel} (fresh; next number: {num + 1:03d})"


def data_guard_status() -> tuple[bool, str]:
    """071 S-adatőr: whether the versioned hooks are enabled, and whether the tracked files contain a blocking
    finding."""
    from jav.devtools import data_guard

    try:
        found = data_guard.scan_tracked(PROJECT_ROOT, data_guard.load_guard(PROJECT_ROOT))
    except data_guard.DataGuardError as e:
        return True, f"cannot be checked ({e})"
    stop = data_guard.blocking(found)
    parts = [f"{len(stop)} blocking, {len(found) - len(stop)} tolerated finding(s) in the tracked files"]
    if stop:
        parts.append("review: python -m jav.cli data-guard")
    installed = data_guard.hooks_installed(PROJECT_ROOT)
    if not installed:
        parts.insert(0, "a horgok nincsenek bekapcsolva (python -m jav.cli hooks-install)")
    return installed and not stop, "; ".join(parts)


def lang_guard_status() -> tuple[bool, str]:
    """073 language guard: no tracked file has more Hungarian lines than its baseline (configs/lang_guard.json)."""
    from jav.devtools import lang_guard

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


def ocr_status() -> tuple[bool, str]:
    """278: the native recogniser and its language packs, as a fresh installation needs to see them. It is a notice,
    never a failure: a machine that reads no scanned document works without them, and the tests that need them say so
    when they skip. 279: and Azure's state (set up or not, switched off, the last free check), as a notice too."""
    from jav.documents import ocr

    s = ocr.status()
    azure = azure_notice(s["azure"])
    if not s.get("engine"):
        return True, f"no OCR engine: {s.get('error', 'not found')} (install Tesseract 5: docs/guides/SETUP.md section 3); {azure}"
    msg = f"{s['engine']} {s.get('engine_version', '')}".strip()
    if s.get("engine") != "native":
        return True, f"{msg}; {azure}"
    if s["tessdata_missing"]:
        return True, (f"{msg}; language pack(s) {', '.join(s['tessdata_missing'])} missing from {s['tessdata_dir']} "
                      f"(python -m jav.cli ocr --fetch-langs); {azure}")
    msg += f"; language packs {', '.join(s['tessdata'])}"
    if s["tessdata_differs"]:
        msg += f" ({', '.join(s['tessdata_differs'])} not the pinned file)"
    return True, f"{msg}; {azure}"


def azure_notice(azure: dict) -> str:
    """279: Azure in one phrase, without a call: not set up, switched off, or set up with its last free check."""
    if not azure["enabled"]:
        return "Azure switched off here (JAV_PROVIDERS_OFF)"
    if not azure["configured"]:
        return "Azure not set up (no AZURE_DI_ENDPOINT and AZURE_DI_KEY; docs/guides/SETUP.md section 3)"
    last = azure.get("last_check")
    if not last:
        return f"Azure set up ({azure['host']}), not checked yet (python -m jav.cli ocr --check-azure)"
    if last.get("ok"):
        return f"Azure set up ({azure['host']}), checked {last.get('at')}"
    return f"Azure set up ({azure['host']}), last check failed: {last.get('reason')} at {last.get('at')}"


FULL_RUN_LOCK = Path(tempfile.gettempdir()) / "jav-full-test-run.lock"


def full_run_lock():
    """265 (code review TOOL-06): one full test run at a time on this machine (the start-up check's and the test
    worktree's, from any folder): two at once ran out of memory, and one wiped the other's shared test worktree. A lock
    file in the system's temporary folder (`FULL_RUN_LOCK`); `lock.AlreadyRunning` when another run holds it. 265 (R4-b):
    a before/after snapshot or replay holds it too: beside a full test run it slowed the isolated readers and the timers
    of six tests into failures."""
    from jav.core import lock

    return lock.single_instance(FULL_RUN_LOCK)


def preflight(*, skip_pytest: bool = False) -> int:
    t0 = time.perf_counter()
    results: list[tuple[str, bool, str]] = []

    if not skip_pytest:
        with full_run_lock():
            (ok, summary), ui = run_tests(log_folder())
        results.append(("pytest", ok, summary))
        results.append(("interface", ui[0], ui[1]) if ui else ("interface", True, "skipped (ui/node_modules is not installed)"))

    lint = flow_lint_summary()
    results.append(("kontrakt-lint", all(ok for _, ok, _ in lint), ", ".join(f"{n}: {'PASS' if ok else f'FAIL({f})'}" for n, ok, f in lint)))

    from jav.devtools import engine_matrix

    ok, msg = engine_matrix.status()  # 160: every JEV call site has a counterpart without JEV or a stated exception
    results.append(("engine matrix", ok, msg))

    rows = cfg.report()
    results.append(("konfigok", True, ", ".join(f"{r['name']} {r['version']} {r['hash'][:8]}" for r in rows)))

    ok, msg = handoff_status()
    results.append(("handoff", ok, msg))

    g = devstate.git_state()
    results.append(("git", True, g.line() if g else "not a git repository / git is not available"))

    ok, msg = ocr_status()
    results.append(("OCR", ok, msg))

    ok, msg = data_guard_status()
    results.append(("data guard", ok, msg))

    ok, msg = lang_guard_status()
    results.append(("language guard", ok, msg))

    from jav.runtime import deps_audit

    ok, msg = deps_audit.verdict(deps_audit.status())
    results.append(("dependency audit", ok, msg))

    from jav.ai import jev_version

    ok, msg = jev_version.verdict(jev_version.status())  # 200: a newer version is a notice, the pinned one answers
    results.append(("JEV version", ok, msg))

    try:
        found = devstate.ruff_findings()
        ok, msg = devstate.lint_verdict(found[0] if found else None, devstate.lint_limit(),
                                        version=devstate.ruff_version() if found else None, pinned=devstate.ruff_pinned())
    except devstate.RuffFailed as exc:  # 265 (code review TOOL-09): installed but failed is an error
        ok, msg = False, f"Ruff failed: {exc}"
    results.append(("ruff", ok, msg))

    path = write_state()
    results.append(("STATE.md", True, devstate.shown_path(path)))

    print(f"# preflight ({time.perf_counter() - t0:.1f} s)\n")
    for name, ok, detail in results:
        print(f"- {'OK  ' if ok else 'FAIL'} {name}: {detail}")
    print(f"\nState snapshot: {devstate.shown_path(path)} · backlog: docs/BACKLOG.md · decisions: docs/DECISIONS.md")
    return 0 if all(ok for _, ok, _ in results) else 1
