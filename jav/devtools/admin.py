"""Control screen (`python -m jav.cli admin`): everything that shows the framework's state and tuning, in one place.

Blocks: configs (version, hash), models and prices (`configs/models.json`), Burr contract lint, store statistics,
the latest golden result per flow (`runs/*.jsonl`), the open review queue. Read-only; no API calls.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from jav.flows import contract
from jav.core import cfg, config, store, values
from jav.core.config import PROJECT_ROOT, RUNS_DIR
from jav.ai.typepack import LEGACY_DOC_TYPE

STATE_PATH = PROJECT_ROOT / "docs" / "STATE.md"  # generated state snapshot; the handoff links to it, never copies it


def score_text(ok: int, scored: int) -> str:
    """067 (066 Á45): "ok/scored = ratio"; with no cases "nincs eset" (no cases), not a misleading 0.0%."""
    return f"{ok}/{scored} = {ok / scored:.1%}" if scored else "nincs eset"


def _low_conf(flow: str) -> float:
    """066 Á38: the "would go to manual review" threshold comes from the policy (configs/policy.json), not the code."""
    from jav.ai import policy

    return policy.DETECT_LOW_CONFIDENCE if flow == "doc_detect" else policy.INTENT_HUMAN_MAX_CONF


def _latest(pattern: str) -> Path | None:
    files = sorted(RUNS_DIR.glob(pattern))
    return files[-1] if files else None


def _informational(doc_type: str) -> tuple[str, ...]:
    try:
        from jav.ai.typepack import get

        return get(doc_type).informational_fields
    except Exception:  # noqa: BLE001 - unknown / deleted pack: every scored field counts
        return ()


def _failure_reason(rows: list[dict[str, Any]]) -> str:
    """The most common first review reason of a run in which no case produced data (e.g. a missing API key)."""
    reasons = Counter((r.get("review_reasons") or ["?"])[0] for r in rows)
    return reasons.most_common(1)[0][0] if reasons else "?"


def last_golden_results() -> list[dict[str, Any]]:
    """The latest golden result per flow. A run in which every case failed (no case produced data, e.g. it ran without
    an API key) is not a measurement: the latest run that produced data is shown, and the skipped failed run is named
    next to it (076), so the report does not look as if there were no measurement at all."""
    out: list[dict[str, Any]] = []
    for arm in ("S", "G"):
        # the latest golden file per type (type pack): the rows' `doc_type` says which pack (old file = invoice_hu)
        latest_by_type: dict[str, tuple[Path, list[dict[str, Any]]]] = {}
        failed_newer: dict[str, tuple[Path, str]] = {}
        for p in sorted(RUNS_DIR.glob(f"*_golden_{arm}.jsonl")):
            rows = values.json_lines(p)
            if not rows:
                continue
            doc_type = rows[0].get("doc_type", LEGACY_DOC_TYPE)
            if any(r.get("datapoints") is not None for r in rows):
                latest_by_type[doc_type] = (p, rows)
                failed_newer.pop(doc_type, None)
            else:
                failed_newer[doc_type] = (p, _failure_reason(rows))
                latest_by_type.setdefault(doc_type, (p, rows))
        for doc_type, (p, all_rows) in sorted(latest_by_type.items()):
            rows = [r for r in all_rows if r.get("datapoints") is not None]
            informational = set(_informational(doc_type))
            vals = [v for r in rows for f, v in r["scores"].items() if v is not None and f not in informational]
            failed = failed_newer.get(doc_type)
            skipped = None if failed is None or failed[0] == p else {"file": failed[0].name, "reason": failed[1]}
            out.append({"flow": f"{doc_type} {arm}-kar", "file": p.name, "n": len(rows), "ok": sum(vals), "scored": len(vals),
                        "review": sum(r.get("route") == "human" for r in rows), "skipped_failed": skipped})
    for flow, pat, exp, got in (("doc_detect", "*_detect_golden.jsonl", "expected", "got"), ("email_intent", "*_email_golden.jsonl", "expected", "got")):
        p = _latest(pat)
        if p:
            rows = [r for r in values.json_lines(p) if r.get(got) is not None]
            out.append({"flow": flow, "file": p.name, "n": len(rows), "ok": sum(r[exp] == r[got] for r in rows), "scored": len(rows),
                        "review": sum((r.get("confidence") or 0) < _low_conf(flow) for r in rows)})
    return out


def golden_set_lines() -> list[str]:
    """188: every registered golden set with its latest result from the shared measurement command's receipts
    (`jav/evals/goldens.py`), so a logic pack's golden set shows next to the type packs'."""
    from jav.evals import goldens

    latest = goldens.latest_results()
    lines = ["| golden set | cases | as expected | without a result | receipt (commit) |", "|---|---|---|---|---|"]
    for g in goldens.sets():
        r = latest.get(g.key)
        if r is None:
            lines.append(f"| {g.key} | - | not measured with `measure` yet | - | - |")
            continue
        tree = "" if r.get("clean") else ", uncommitted changes"
        lines.append(f"| {g.key} | {r['cases']} | {score_text(r['right'], r['scored'])} {r['unit']} | "
                     f"{r['cases'] - r['answered']} | {r['receipt']} ({r.get('commit')}{tree}, {r.get('engine')}) |")
    return lines


def flow_lint_targets() -> list[tuple[Any, Any]]:
    """Every flow module with a live graph built for the contract lint (`flows`, the admin report); 173: the flows
    and their lint graphs come from the flow registry (`jav.flows`), in its order."""
    from jav import flows

    targets = []
    for spec in flows.specs():
        if spec.lint is not None:
            module = spec.load()
            targets.append((module, spec.lint(module)))
    return targets


def flow_lint_summary() -> list[tuple[str, bool, int]]:
    out = []
    for module, app in flow_lint_targets():
        r = contract.lint_flow(module.CONTRACT, app, module)
        out.append((r["name"], r["passed"], sum(1 for _, ok, _ in r["checks"] if not ok)))
    return out


def admin_report() -> str:
    """187 (backlog: the live-store check): the store is only read (`store.read_only`), so the report never runs the
    checked-out code's schema or migrations on it, and a store that does not exist yet is not created."""
    with store.read_only():
        return _report(store.current_path().is_file())


def _report(have_store: bool) -> str:
    L: list[str] = ["# jav admin - keretrendszer-állapot", ""]
    L += ["## Konfigok (configs/, `config_hash` a ledgerben)", "", "| konfig | verzió | hash |", "|---|---|---|"]
    for r in cfg.report():
        L.append(f"| {r['name']} | {r['version']} | `{r['hash']}` |")
    L += ["", "## Modellek (configs/models.json v" + config.MODELS_VERSION + ")", "",
          f"- Jev: `{config.JEV_MODEL}`, timeout {config.JEV_TIMEOUT_S:.0f} s, ${config.JEV_USD_PER_MTOK}/M input token, cache-verzió {config.JEV_CACHE_VERSION}",
          f"- OpenAI (G-kar, Pydantic AI): `{config.OPENAI_MODEL}`, {config.OPENAI_SETTINGS}, árak {config.OPENAI_USD_PER_MTOK}",
          f"- Burr tracker-projektek: {config.TRACKER_PROJECTS}", ""]
    L += ["## Burr-kontraktok (lint)", ""]
    for name, ok, fails in flow_lint_summary():
        L.append(f"- {name}: {'PASS' if ok else f'FAIL ({fails} ellenőrzés)'}")
    no_store = "- no store yet (the first run creates it)"
    L += ["", "## Adattár (store/jav.sqlite)", ""]
    if have_store:
        st = store.stats()
        L += [f"- documents {st['documents']} · datapoints {st['datapoints']} · emails {st['emails']} · ledger {st['ledger']} · golden_labels {st['golden_labels']}",
              f"- review_queue nyitott: **{st['review_open']}**",
              "- ledger szolgáltatónként: " + "; ".join(f"{r['provider']}: {r['n']} hívás, {r['cached']} cache, ${r['usd']:.4f}" for r in st["ledger_by_provider"]),
              "- doc_type eloszlás: " + ", ".join(f"{r['doc_type']}×{r['n']}" for r in st["doc_types"][:8]),
              "- intent eloszlás: " + (", ".join(f"{r['intent']}×{r['n']}" for r in st.get("intents", [])[:8]) or "-")]
    else:
        L.append(no_store)
    L += ["", "## Utolsó golden-eredmény flow-nként (runs/)", "", "| flow | fájl | eset | pontos | review / < 0,6 |", "|---|---|---|---|---|"]
    for g in last_golden_results():
        skipped = g.get("skipped_failed")
        note = f" (newer failed run skipped: {skipped['file']}, {skipped['reason']})" if skipped else ""
        L.append(f"| {g['flow']} | {g['file']}{note} | {g['n']} | {score_text(g['ok'], g['scored'])} | {g['review']} |")
    L += ["", "## Every golden set, latest shared measurement (`measure`, runs/*_measure.jsonl)", "", *golden_set_lines()]
    L += ["", "## Nyitott review-sor", ""]
    if have_store:
        with store.connect() as c:
            rq = [dict(r) for r in c.execute("SELECT subject_kind, reasons FROM review_queue WHERE status='open'")]
        kinds = Counter(r["subject_kind"] for r in rq)
        reasons = Counter(json.loads(r["reasons"])[0].split(":")[0] if r["reasons"] else "?" for r in rq)
        by_kind = reasons_by_run_kind()
        L += [f"- alany szerint: {dict(kinds) or '-'}", f"- fő ok szerint: {dict(reasons) or '-'}",
              f"- open reasons by the kind of run that raised them: live {by_kind['live']} · trial {by_kind['trial']}"
              f" · without a run {by_kind['no_run']}",
              "- open human tasks by kind (215: each open item above has one): "
              + (" · ".join(f"{k} {n}" for k, n in open_tasks_by_kind().items()) or "-"),
              snapshot_line(), trace_line()]
    else:
        L.append(no_store)
    L += ["", "Parancsok: `configs`, `flows [--check]`, `docs`, `store`, golden / determinism / email-golden / detect-golden (README).", ""]
    return "\n".join(L)


def reasons_by_run_kind() -> dict[str, int]:
    """150: the open to-do reasons by the kind of run that raised them: a live run, a trial run (never approved, so its
    reasons stay open) or no run (a command-line measurement). The queue count above counts documents and emails."""
    out = {"live": 0, "trial": 0, "no_run": 0}
    kind = {"apply": "live", "shadow": "trial"}
    with store.connect() as c:
        # 181 (backlog J-preflight-friss-tar): a fresh store of a process that never loaded the work packages has no
        # runs table; every open reason then counts as raised without a run
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'").fetchone() is None:
            out["no_run"] = c.execute("SELECT COUNT(*) FROM review_reasons WHERE status='open'").fetchone()[0]
            return out
        for r in c.execute("SELECT x.mode, COUNT(*) AS n FROM review_reasons r LEFT JOIN runs x"
                           " ON x.run_id = substr(r.run_id, 1, instr(r.run_id || ':', ':') - 1)"
                           " WHERE r.status='open' GROUP BY x.mode"):
            out[kind.get(r["mode"], "no_run")] += r["n"]
    return out


def open_tasks_by_kind() -> dict[str, int]:
    """215: the open human tasks of the process core by kind (a to-do item, a run's approval, a logic pack's own
    approval, a workflow step's budget); empty for a store without the table yet."""
    with store.connect() as c:
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='process_tasks'").fetchone() is None:
            return {}
        return {r["kind"]: r["n"] for r in c.execute(
            "SELECT kind, COUNT(*) AS n FROM process_tasks WHERE status='open' GROUP BY kind ORDER BY kind")}


def snapshot_line() -> str:
    """218: the calculation snapshots stored and what they are linked to; "-" for a store without them yet."""
    with store.connect() as c:
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='calc_snapshots'").fetchone() is None:
            return "- calculation snapshots (218): -"
        n = c.execute("SELECT COUNT(*) FROM calc_snapshots").fetchone()[0]
        links = " · ".join(f"{r['subject_kind']} {r['n']}" for r in c.execute(
            "SELECT subject_kind, COUNT(*) AS n FROM snapshot_links GROUP BY subject_kind ORDER BY subject_kind"))
    return f"- calculation snapshots (218): {n} stored · linked: {links or '-'}"


def trace_line() -> str:
    """218 (P3b): the decision trace's rows by decision point; "-" for a store without it yet."""
    with store.connect() as c:
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='decision_trace'").fetchone() is None:
            return "- decision trace (218): -"
        points = " · ".join(f"{r['point']} {r['n']}" for r in c.execute(
            "SELECT point, COUNT(*) AS n FROM decision_trace GROUP BY point ORDER BY point"))
    return f"- decision trace (218): {points or '-'}"


def write_state(path: Path = STATE_PATH) -> Path:
    """Writes the control screen to a file (`docs/STATE.md`): a generated state snapshot, never edited by hand.

    The `preflight` command and the Stop hook refresh it; the handoff and the BACKLOG refer to it, so the state
    description does not go stale in hand-written text.
    """
    from datetime import datetime

    from jav.core.devstate import git_state

    g = git_state()
    head = [
        f"<!-- GENERÁLT: python -m jav.cli admin --write · {datetime.now():%Y-%m-%d %H:%M} · ne szerkeszd kézzel -->",
        f"<!-- git: {g.line() if g else 'nem elérhető'} -->",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\n".join(head) + admin_report()).encode("utf-8"))  # LF line endings (040: .gitattributes)
    return path
