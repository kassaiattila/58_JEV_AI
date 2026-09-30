"""Control screen (`python -m jav.cli admin`): everything that shows the framework's state and tuning, in one place.

Blocks: configs (version, hash), models and prices (`configs/models.json`), Burr contract lint, store statistics,
the latest golden result per flow (`runs/*.jsonl`), the open review queue. Read-only; no API calls.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from jav import cfg, config, contract, store
from jav.config import PROJECT_ROOT, RUNS_DIR

STATE_PATH = PROJECT_ROOT / "docs" / "STATE.md"  # generated state snapshot; the handoff links to it, never copies it


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def score_text(ok: int, scored: int) -> str:
    """067 (066 Á45): "ok/scored = ratio"; with no cases "nincs eset" (no cases), not a misleading 0.0%."""
    return f"{ok}/{scored} = {ok / scored:.1%}" if scored else "nincs eset"


def _low_conf(flow: str) -> float:
    """066 Á38: the "would go to manual review" threshold comes from the policy (configs/policy.json), not the code."""
    from jav import policy

    return policy.DETECT_LOW_CONFIDENCE if flow == "doc_detect" else policy.INTENT_HUMAN_MAX_CONF


def _latest(pattern: str) -> Path | None:
    files = sorted(RUNS_DIR.glob(pattern))
    return files[-1] if files else None


def _informational(doc_type: str) -> tuple[str, ...]:
    try:
        from jav.typepack import get

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
            rows = _rows(p)
            if not rows:
                continue
            doc_type = rows[0].get("doc_type", "invoice_hu")
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
            rows = [r for r in _rows(p) if r.get(got) is not None]
            out.append({"flow": flow, "file": p.name, "n": len(rows), "ok": sum(r[exp] == r[got] for r in rows), "scored": len(rows),
                        "review": sum((r.get("confidence") or 0) < _low_conf(flow) for r in rows)})
    return out


def flow_lint_summary() -> list[tuple[str, bool, int]]:
    from jav import flow, flow_detect, flow_email, flow_learning, flow_email_learning

    apps = [
        (flow, flow.build_app("lint.pdf", "lint", "S", tracker=False)),
        (flow_detect, flow_detect.build_app("lint.pdf", tracker=False)),
        (flow_email, flow_email.build_app(source_dir="lint", tracker=False)),
        (flow_learning, flow_learning.build_app()),
        (flow_email_learning, flow_email_learning.build_app()),
    ]
    out = []
    for module, app in apps:
        r = contract.lint_flow(module.CONTRACT, app, module)
        out.append((r["name"], r["passed"], sum(1 for _, ok, _ in r["checks"] if not ok)))
    return out


def admin_report() -> str:
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
    st = store.stats()
    L += ["", "## Adattár (store/jav.sqlite)", "",
          f"- documents {st['documents']} · datapoints {st['datapoints']} · emails {st['emails']} · ledger {st['ledger']} · golden_labels {st['golden_labels']}",
          f"- review_queue nyitott: **{st['review_open']}**",
          "- ledger szolgáltatónként: " + "; ".join(f"{r['provider']}: {r['n']} hívás, {r['cached']} cache, ${r['usd']:.4f}" for r in st["ledger_by_provider"]),
          "- doc_type eloszlás: " + ", ".join(f"{r['doc_type']}×{r['n']}" for r in st["doc_types"][:8]),
          "- intent eloszlás: " + (", ".join(f"{r['intent']}×{r['n']}" for r in st.get("intents", [])[:8]) or "-"), ""]
    L += ["## Utolsó golden-eredmény flow-nként (runs/)", "", "| flow | fájl | eset | pontos | review / < 0,6 |", "|---|---|---|---|---|"]
    for g in last_golden_results():
        skipped = g.get("skipped_failed")
        note = f" (newer failed run skipped: {skipped['file']}, {skipped['reason']})" if skipped else ""
        L.append(f"| {g['flow']} | {g['file']}{note} | {g['n']} | {score_text(g['ok'], g['scored'])} | {g['review']} |")
    with store.connect() as c:
        rq = [dict(r) for r in c.execute("SELECT subject_kind, reasons FROM review_queue WHERE status='open'")]
    kinds = Counter(r["subject_kind"] for r in rq)
    reasons = Counter(json.loads(r["reasons"])[0].split(":")[0] if r["reasons"] else "?" for r in rq)
    L += ["", "## Nyitott review-sor", "", f"- alany szerint: {dict(kinds) or '-'}", f"- fő ok szerint: {dict(reasons) or '-'}", "",
          "Parancsok: `configs`, `flows [--check]`, `docs`, `store`, golden / determinism / email-golden / detect-golden (README).", ""]
    return "\n".join(L)


def write_state(path: Path = STATE_PATH) -> Path:
    """Writes the control screen to a file (`docs/STATE.md`): a generated state snapshot, never edited by hand.

    The `preflight` command and the Stop hook refresh it; the handoff and the BACKLOG refer to it, so the state
    description does not go stale in hand-written text.
    """
    from datetime import datetime

    from jav.devstate import git_state

    g = git_state()
    head = [
        f"<!-- GENERÁLT: python -m jav.cli admin --write · {datetime.now():%Y-%m-%d %H:%M} · ne szerkeszd kézzel -->",
        f"<!-- git: {g.line() if g else 'nem elérhető'} -->",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\n".join(head) + admin_report()).encode("utf-8"))  # LF line endings (040: .gitattributes)
    return path
