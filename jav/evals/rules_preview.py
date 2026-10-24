"""224 (plan G-process-core P3d): a rule file's candidate version tried on the decisions the trace holds - free.

Plain-language summary: before a rule changes (a threshold, a route, a family of the duplicate search), this shows
which of the machine's earlier decisions would come out otherwise. For every decision point that reads the rule file
(`jav.core.trace`, each point names its files) it counts the decisions the trace holds and how many would change, shows
a few of them (what the decision was about, and each part of the outcome now and with the candidate), and counts the
to-dos that would open or close. Each decision's rule is run on the inputs the trace stored twice: with the rule files
in use now and with the candidate in place of one of them, each in a process of its own, because the modules read
their rules when they are loaded; the candidate's process reads a copy of `configs/` with the candidate in it. So
nothing in the running process, the store or `configs/` changes, no AI is asked and no document is read again.

What it does not count: a decision the trace does not hold (made before the trace, in a measurement, or in a replay's
copy of the store) and what a changed decision does to the steps after it (the replay shows a whole item's effect,
`jav.evals.before_after_replay`). A decision whose stored outcome differs from today's rule on its inputs was made with
other rules or other code; it is counted (`differs_from_stored`) and compared from today's outcome. The candidate's
process honours every JSON rule file read through the config loader (`jav.core.cfg`), which is what the decision points
read.

- `preview(file, candidate, store_path=None, point=None, examples=5)`: the report.
- `replay(file, candidate, baseline=, work_dir=, out_dir=, size=150)`: a whole item's effect - the replay of a sample of
  a backup's items twice, with the rules in use now and with the candidate, and the views that differ between them.
- `from_ref(ref, file)`: a rule file's content in a git commit (`--ref`).
- `python -m jav.cli rules-preview <file> (--candidate PATH | --ref REF) [--store COPY] [--point P] [--examples N] [--json]`;
  with `--replay BACKUP --work DIR --out-dir DIR [--size N] [--jev-cache DIR]` the replay instead.

Layer: measurement; it reads the trace read-only and runs the registered rules (`jav.app.registrations`).
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from jav.core import cfg, store, todo_kinds, trace
from jav.core.config import PROJECT_ROOT

CHILD_TIMEOUT_S = 900  # the rules of a large trace, run once per process
REPLAY_TIMEOUT_S = 3600  # one replay of a sample (150 units by default)


class PreviewError(ValueError):
    """A preview that cannot be made: the candidate is no rule file, the file is not one of `configs/`, the store or the
    git reference is not there, or the rules could not be run."""


def _relative(file: str) -> str:
    return file.replace("\\", "/").removeprefix("configs/")


def _checked(candidate: bytes) -> dict[str, Any]:
    try:
        data = json.loads(candidate.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreviewError(f"the candidate is not JSON: {exc}") from None
    if not isinstance(data, dict) or not isinstance(data.get("meta"), dict) or "version" not in data["meta"]:
        raise PreviewError("the candidate has no meta.version (every rule file names its version)")
    return data


def from_ref(ref: str, file: str) -> bytes:
    """The rule file `configs/<file>` as it is in the git commit `ref`."""
    name = _relative(file)
    done = subprocess.run(["git", "show", f"{ref}:configs/{name}"], cwd=PROJECT_ROOT, capture_output=True, check=False)
    if done.returncode != 0:
        raise PreviewError(f"git has no configs/{name} at {ref}: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout


def _points(file: str, only: str | None) -> list[trace.Point]:
    from jav.app import registrations

    registrations.load_all()  # every module's decision points
    found = [p for p in trace.points() if any(fnmatch.fnmatchcase(file, pattern) for pattern in p.files)]
    if only is not None:
        found = [p for p in found if p.code == only]
        if not found:
            raise PreviewError(f"the decision point {only} does not read {file}")
    return found


def _rows(points: list[trace.Point], store_path: Path | None) -> dict[str, list[dict[str, Any]]]:
    if store_path is not None and not Path(store_path).is_file():
        raise PreviewError(f"no store at {store_path}")
    with store.use_store(Path(store_path)) if store_path is not None else nullcontext(), store.read_only():
        return {p.code: trace.rows(point=p.code) for p in points}


def _run(configs: Path, rows: list[dict[str, Any]], work: Path, label: str) -> dict[str, dict[str, Any]]:
    """Each row's rule run on its stored inputs in a process that reads its rules from `configs`: {id: {outcome} or
    {error}}."""
    given, taken = work / f"{label}-rows.json", work / f"{label}-outcomes.json"
    given.write_text(json.dumps([{"id": r["id"], "point": r["point"], "inputs": r["inputs"]} for r in rows],
                                ensure_ascii=False, default=str), encoding="utf-8")
    done = subprocess.run([sys.executable, "-m", "jav.evals.rules_preview", "--child", str(configs), str(given), str(taken)],
                          cwd=PROJECT_ROOT, capture_output=True, check=False, timeout=CHILD_TIMEOUT_S)
    if done.returncode != 0:
        tail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
        raise PreviewError(f"the rules could not be run with the {label} rule files: " + " | ".join(tail))
    return json.loads(taken.read_text(encoding="utf-8"))


def _changes(now: Any, then: Any) -> dict[str, list[Any]]:
    """The parts of two outcomes that differ: each key of an outcome, or the whole outcome."""
    if isinstance(now, dict) and isinstance(then, dict):
        return {k: [now.get(k), then.get(k)] for k in sorted(set(now) | set(then)) if now.get(k) != then.get(k)}
    return {"outcome": [now, then]}


def _reasons(outcome: Any) -> list[str]:
    reasons = outcome.get("reasons") if isinstance(outcome, dict) else None
    return [str(r) for r in reasons] if isinstance(reasons, list) else []


def _compare(code: str, rows: list[dict[str, Any]], now: dict[str, dict[str, Any]], then: dict[str, dict[str, Any]],
             examples: int) -> dict[str, Any]:
    out: dict[str, Any] = {"point": code, "decisions": len(rows), "changed": 0, "differs_from_stored": 0, "errors": 0,
                           "opened": Counter(), "closed": Counter(), "examples": [], "error_examples": []}
    for row in rows:
        a, b = now.get(str(row["id"]), {}), then.get(str(row["id"]), {})
        if "outcome" not in a or "outcome" not in b:
            out["errors"] += 1
            if len(out["error_examples"]) < examples:
                out["error_examples"].append({"subject": f"{row['subject_kind']}:{row['subject_id']}",
                                              "now": a.get("error"), "candidate": b.get("error")})
            continue
        if a["outcome"] != row["outcome"]:
            out["differs_from_stored"] += 1
        if a["outcome"] == b["outcome"]:
            continue
        out["changed"] += 1
        old, new = set(_reasons(a["outcome"])), set(_reasons(b["outcome"]))
        out["opened"].update(todo_kinds.code_of(r) for r in new - old)
        out["closed"].update(todo_kinds.code_of(r) for r in old - new)
        if len(out["examples"]) < examples:
            out["examples"].append({"subject": f"{row['subject_kind']}:{row['subject_id']}", "at": row["at"],
                                    "changes": _changes(a["outcome"], b["outcome"])})
    out["opened"], out["closed"] = dict(sorted(out["opened"].items())), dict(sorted(out["closed"].items()))
    return out


def preview(file: str, candidate: bytes, *, store_path: Path | None = None, point: str | None = None,
            examples: int = 5) -> dict[str, Any]:
    """The decisions of the trace (of the active store, or of the store at `store_path`, read only) that read the rule
    file `file` (its path under `configs/`), each with its rule run with the file in use now and with `candidate` in
    its place: per point the decisions, how many would change, the to-dos that would open and close and a few
    examples. `PreviewError` when it cannot be made."""
    name = _relative(file)
    data = _checked(candidate)
    current_path = cfg.CONFIG_DIR / name
    if not current_path.is_file():
        raise PreviewError(f"no rule file configs/{name}")
    current = current_path.read_bytes()
    points = _points(name, point)
    rows = _rows(points, store_path)
    every = [r for code in rows for r in rows[code]]
    work = Path(tempfile.mkdtemp(prefix="jav-rules-preview-"))
    try:
        configs = work / "configs"
        shutil.copytree(cfg.CONFIG_DIR, configs)
        (configs / name).write_bytes(candidate)
        then = _run(configs, every, work, "candidate")  # also when the trace holds none: the candidate must load
        now = _run(cfg.CONFIG_DIR, every, work, "current") if every else {}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    compared = [_compare(p.code, rows[p.code], now, then, examples) for p in points]
    return {"file": name, "store": str(store_path) if store_path is not None else str(store.active_path()),
            "current": {"version": str(json.loads(current.decode("utf-8"))["meta"]["version"]),
                        "sha256": hashlib.sha256(current).hexdigest()},
            "candidate": {"version": str(data["meta"]["version"]), "sha256": hashlib.sha256(candidate).hexdigest()},
            "same_content": candidate == current, "points": compared,
            "total": {k: sum(p[k] for p in compared) for k in ("decisions", "changed", "errors")}}


def _run_replay(configs: Path, baseline: Path, work_dir: Path, out: Path, size: int, jev_cache: Path | None,
                work: Path, label: str) -> dict[str, Any]:
    """The replay in a process that reads its rules from `configs`: its counts and its gate."""
    taken = work / f"{label}-replay.json"
    done = subprocess.run([sys.executable, "-m", "jav.evals.rules_preview", "--replay-child", str(configs), str(baseline),
                           str(work_dir), str(out), str(size), str(jev_cache) if jev_cache is not None else "-", str(taken)],
                          cwd=PROJECT_ROOT, capture_output=True, check=False, timeout=REPLAY_TIMEOUT_S)
    if done.returncode != 0:
        tail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
        raise PreviewError(f"the replay with the {label} rule files failed: " + " | ".join(tail))
    return json.loads(taken.read_text(encoding="utf-8"))


def replay(file: str, candidate: bytes, *, baseline: Path, work_dir: Path, out_dir: Path, size: int = 150,
           jev_cache: Path | None = None, show: int = 20) -> dict[str, Any]:
    """A whole item's effect of the candidate: the replay of a sample of `baseline`'s items
    (`before_after_replay.running_snapshot`: from earlier answers only, nothing can reach a provider) twice on the same
    fresh copy in `work_dir`, with the rule files in use now and with `candidate` in place of `file`, each in a process
    of its own. Writes both snapshots (`out_dir/current.jsonl`, `out_dir/candidate.jsonl`; outside git) and returns
    both replays' counts and gates and the views that differ between them (`before_after.diff`)."""
    from jav.evals import before_after

    name = _relative(file)
    data = _checked(candidate)
    current_path = cfg.CONFIG_DIR / name
    if not current_path.is_file():
        raise PreviewError(f"no rule file configs/{name}")
    if not _points(name, None):
        raise PreviewError(f"no decision point reads {name}")
    outs = {side: Path(out_dir) / f"{side}.jsonl" for side in ("current", "candidate")}
    if taken := [str(p) for p in outs.values() if p.exists()]:
        raise PreviewError(f"the replay's output already exists: {', '.join(taken)}")
    work = Path(tempfile.mkdtemp(prefix="jav-rules-replay-"))
    try:
        configs = work / "configs"
        shutil.copytree(cfg.CONFIG_DIR, configs)
        (configs / name).write_bytes(candidate)
        replays = {"current": _run_replay(cfg.CONFIG_DIR, baseline, work_dir, outs["current"], size, jev_cache, work, "current"),
                   "candidate": _run_replay(configs, baseline, work_dir, outs["candidate"], size, jev_cache, work, "candidate")}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    differences = before_after.diff(outs["current"], outs["candidate"])
    current = current_path.read_bytes()
    return {"file": name, "current": {"version": str(json.loads(current.decode("utf-8"))["meta"]["version"]),
                                      "sha256": hashlib.sha256(current).hexdigest()},
            "candidate": {"version": str(data["meta"]["version"]), "sha256": hashlib.sha256(candidate).hexdigest()},
            "replays": replays, "outputs": {side: str(p) for side, p in outs.items()}, "differing": len(differences),
            "summary": {kind: dict(counts) for kind, counts in before_after.summary(differences).items()},
            "differences": [{"key": d.key, "kind": d.kind, "places": list(d.places)} for d in differences[:show]]}


def replay_text(report: dict[str, Any]) -> list[str]:
    """The replay's report in plain lines, for the command line."""
    lines = [f"rule file {report['file']}: in use {report['current']['version']}, candidate {report['candidate']['version']}"]
    for side, r in report["replays"].items():
        lines.append(f"{side}: {r['units']} units, {r['items']} items, {r['views']} views; answers missing (a to-do "
                     f"instead of a call): {r['missing_answers']}; live calls: {r['live_calls']}")
    lines.append(f"views that differ: {report['differing']}")
    for kind, counts in sorted(report["summary"].items()):
        lines.append(f"  {kind}: {', '.join(f'{k} {v}' for k, v in sorted(counts.items()))}")
    for d in report["differences"]:
        lines.append(f"- {d['key']} [{d['kind']}]")
        lines.extend(f"    {place}" for place in d["places"])
    lines.append(f"written: {report['outputs']['current']}, {report['outputs']['candidate']}")
    return lines


def _counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{k} {n}" for k, n in counts.items()) or "none"


def text(report: dict[str, Any]) -> list[str]:
    """The report in plain lines, for the command line."""
    cur, cand = report["current"], report["candidate"]
    lines = [f"rule file {report['file']}: in use {cur['version']} ({cur['sha256'][:12]}), candidate {cand['version']} "
             f"({cand['sha256'][:12]})" + (" - the same content" if report["same_content"] else ""),
             f"store: {report['store']}"]
    if not report["points"]:
        lines.append("no decision point reads this file")
    for p in report["points"]:
        line = f"{p['point']}: {p['decisions']} decisions, {p['changed']} would change"
        if p["differs_from_stored"]:
            line += f" ({p['differs_from_stored']} were made with other rules or code than today's)"
        if p["errors"]:
            line += f"; {p['errors']} could not be run"
        lines.append(line)
        if p["opened"] or p["closed"]:
            lines.append(f"  to-dos opened: {_counts(p['opened'])}; closed: {_counts(p['closed'])}")
        for e in p["examples"]:
            changes = "; ".join(f"{k}: {json.dumps(v[0], ensure_ascii=False)} -> {json.dumps(v[1], ensure_ascii=False)}"
                                for k, v in e["changes"].items())
            lines.append(f"  {e['subject']}: {changes}")
        for e in p["error_examples"]:
            lines.append(f"  {e['subject']}: could not be run (now: {e['now']}; candidate: {e['candidate']})")
    t = report["total"]
    lines.append(f"total: {t['decisions']} decisions, {t['changed']} would change; no AI call, nothing written")
    return lines


def _child(configs: Path, given: Path, taken: Path) -> int:
    """The process of one side: every rule read from `configs` (set before any rule module is loaded), each row's rule
    run on its stored inputs; a row whose rule raises is reported with its error, not left out."""
    cfg.CONFIG_DIR, cfg.CALLSITE_DIR, cfg.TYPES_DIR = configs, configs / "callsites", configs / "types"
    cfg.reload()
    from jav.app import registrations

    registrations.load_all()
    results: dict[str, dict[str, Any]] = {}
    for row in json.loads(given.read_text(encoding="utf-8")):
        try:
            results[str(row["id"])] = {"outcome": trace.replay(row)}
        except Exception as exc:  # reported per decision in the preview, not left out
            results[str(row["id"])] = {"error": f"{type(exc).__name__}: {exc}"}
    taken.write_text(json.dumps(results, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


def _replay_child(configs: Path, baseline: Path, work_dir: Path, out: Path, size: int, jev_cache: Path | None,
                  taken: Path) -> int:
    """The process of one replay: every rule read from `configs` (set before any rule module is loaded)."""
    cfg.CONFIG_DIR, cfg.CALLSITE_DIR, cfg.TYPES_DIR = configs, configs / "callsites", configs / "types"
    cfg.reload()
    from jav.evals import before_after_replay

    result = before_after_replay.running_snapshot(baseline, work_dir, out, size=size, jev_cache=jev_cache)
    taken.write_text(json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--child":
        sys.exit(_child(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])))
    if len(sys.argv) == 9 and sys.argv[1] == "--replay-child":
        sys.exit(_replay_child(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5]), int(sys.argv[6]),
                               None if sys.argv[7] == "-" else Path(sys.argv[7]), Path(sys.argv[8])))
    sys.exit("usage: python -m jav.evals.rules_preview --child CONFIGS ROWS OUTCOMES | --replay-child CONFIGS BASELINE "
             "WORK OUT SIZE CACHE RESULT (run by jav.cli rules-preview)")
