"""Vezérlő képernyő (`python -m jav.cli admin`): egy helyen minden, ami a keretrendszer állapotát és hangolását mutatja.

Blokkok: konfigok (verzió, hash), modellek és árak (`configs/models.json`), Burr-kontraktok lintje, store-statisztika,
az utolsó golden-eredmény flow-nként (`runs/*.jsonl`), nyitott review-sor. Csak olvas; API-hívás nincs.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from jav import cfg, config, contract, store
from jav.config import PROJECT_ROOT, RUNS_DIR

STATE_PATH = PROJECT_ROOT / "docs" / "STATE.md"  # generált állapot-pillanatkép; a handoff hivatkozza, nem másolja


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def score_text(ok: int, scored: int) -> str:
    """067 (066 Á45): „ok/pontozott = arány”; eset nélkül „nincs eset” (nem 0,0%, ami mindent rossznak mutatna)."""
    return f"{ok}/{scored} = {ok / scored:.1%}" if scored else "nincs eset"


def _low_conf(flow: str) -> float:
    """066 Á38: a „kézi ellenőrzésre menne” küszöb a policyból (configs/policy.json), nem beégetve."""
    from jav import policy

    return policy.DETECT_LOW_CONFIDENCE if flow == "doc_detect" else policy.INTENT_HUMAN_MAX_CONF


def _latest(pattern: str) -> Path | None:
    files = sorted(RUNS_DIR.glob(pattern))
    return files[-1] if files else None


def _informational(doc_type: str) -> tuple[str, ...]:
    try:
        from jav.typepack import get

        return get(doc_type).informational_fields
    except Exception:  # noqa: BLE001 - ismeretlen / törölt csomag: minden pontozott mező számít
        return ()


def last_golden_results() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for arm in ("S", "G"):
        # típusonként (típus-csomag) a legfrissebb golden-fájl: a sorok `doc_type`-ja mondja, melyik csomag (régi fájl = invoice_hu)
        latest_by_type: dict[str, Path] = {}
        for p in sorted(RUNS_DIR.glob(f"*_golden_{arm}.jsonl")):
            first = next((json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()), None)
            if first is not None:
                latest_by_type[first.get("doc_type", "invoice_hu")] = p
        for doc_type, p in sorted(latest_by_type.items()):
            all_rows = _rows(p)
            rows = [r for r in all_rows if r.get("datapoints") is not None]
            informational = set(_informational(doc_type))
            vals = [v for r in rows for f, v in r["scores"].items() if v is not None and f not in informational]
            out.append({"flow": f"{doc_type} {arm}-kar", "file": p.name, "n": len(rows), "ok": sum(vals), "scored": len(vals),
                        "review": sum(r.get("route") == "human" for r in rows)})
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
        L.append(f"| {g['flow']} | {g['file']} | {g['n']} | {score_text(g['ok'], g['scored'])} | {g['review']} |")
    with store.connect() as c:
        rq = [dict(r) for r in c.execute("SELECT subject_kind, reasons FROM review_queue WHERE status='open'")]
    kinds = Counter(r["subject_kind"] for r in rq)
    reasons = Counter(json.loads(r["reasons"])[0].split(":")[0] if r["reasons"] else "?" for r in rq)
    L += ["", "## Nyitott review-sor", "", f"- alany szerint: {dict(kinds) or '-'}", f"- fő ok szerint: {dict(reasons) or '-'}", "",
          "Parancsok: `configs`, `flows [--check]`, `docs`, `store`, golden / determinism / email-golden / detect-golden (README).", ""]
    return "\n".join(L)


def write_state(path: Path = STATE_PATH) -> Path:
    """A vezérlő képernyő fájlba (`docs/STATE.md`): generált, kézzel nem szerkesztett állapot-pillanatkép.

    A `preflight` parancs és a Stop-hook frissíti; a handoff és a BACKLOG erre hivatkozik, így az állapot-leírás
    nem avul el a kézzel írt szövegben.
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
    path.write_bytes(("\n".join(head) + admin_report()).encode("utf-8"))  # LF sorvég (040: .gitattributes)
    return path
