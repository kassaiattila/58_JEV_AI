"""Burr-gráf = kontrakt: fázisok, lépések, élek, lépés-fajta egy adatszerkezetben; ebből generált FLOW.md + Mermaid,
és lint, ami a deklarált kontraktot az élő Burr-gráffal és a flow forrásával veti össze.

Port a régi 10_AIFLOW_V4 keretből (`orchestrator/framework/graph.py` + `lint.py`), a mi szabályainkra szűkítve:
- minden élő akció deklarált lépés és fordítva; minden deklarált él létezik az élő gráfban és fordítva;
- lépés-fajták: `det` (kód), `jev` (Jev az adapteren át), `llm` (generatív, Pydantic AI), `store` (SQLite-írás),
  `flow` (másik gráf hívása), `terminal`; a fajtához illő hívás megjelenik az akció forrásában;
- a flow-modul nem importál SDK-t közvetlenül (typesafe_sdk / openai / pydantic_ai) - csak az adapter;
- additív review-latch: a flow forrásában nincs `needs_review = False`;
- a `jev` / `llm` lépések továbbadják a `run_id`-t (ledger).

Kontrakt-alak (a flow-modulban `CONTRACT` néven):
    {"name": "invoice_hu", "phases": [...], "steps": [(step, phase), ...], "edges": [(a, b[, label]), ...],
     "step_meta": {step: {"kind": ..., "note": ...}}, "terminals": [...], "doc_note": "..."}
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from types import ModuleType
from typing import Any

from jav.config import PROJECT_ROOT

FLOWS_DOC_DIR = PROJECT_ROOT / "docs" / "flows"
KINDS = ("det", "jev", "llm", "store", "flow", "terminal")
_KIND_MARKERS = {  # a fajtához illő hívás nyoma az akció forrásában (bármelyik elég)
    "jev": ("get_adapter", "jev", "detect(", "classify(", "select_fields(", "verify("),
    "llm": ("extract_llm", "extract(", "Agent", "openai"),
    "store": ("store.",),
    "flow": ("run_detect(", "run_email(", "run_one("),
}
_FORBIDDEN_IMPORTS = ("typesafe_sdk", "openai", "pydantic_ai")
_UNLATCH = re.compile(r"needs_review\s*=\s*False")


def overview_mermaid(contract: dict[str, Any]) -> str:
    """Fázisonként csoportosított Mermaid (subgraph fázisonként), címkézett élekkel."""
    by_phase: dict[str, list[str]] = {p: [] for p in contract["phases"]}
    for name, ph in contract["steps"]:
        by_phase.setdefault(ph, []).append(name)
    out = ["flowchart TD"]
    for ph in contract["phases"]:
        out.append(f'  subgraph ph_{ph}["{ph}"]')  # a subgraph-azonosító nem eshet egybe csomópont-névvel
        for name in by_phase.get(ph, []):
            kind = contract.get("step_meta", {}).get(name, {}).get("kind", "")
            out.append(f'    {name}["{name}{f" ({kind})" if kind else ""}"]')
        out.append("  end")
    for edge in contract["edges"]:
        a, b = edge[0], edge[1]
        label = f"|{edge[2]}|" if len(edge) > 2 and edge[2] else ""
        out.append(f"  {a} -->{label} {b}")
    return "\n".join(out)


def flow_md(contract: dict[str, Any]) -> str:
    """FLOW.md a kontraktból - ember-olvasható, drift-mentes doksi (ne szerkeszd kézzel, generáld)."""
    by_phase: dict[str, list[str]] = {p: [] for p in contract["phases"]}
    meta = contract.get("step_meta", {})
    for name, ph in contract["steps"]:
        by_phase.setdefault(ph, []).append(name)
    lines = [f"# FLOW — {contract['name']}", "",
             "> A flow-modul `CONTRACT`-jából generálva (`jav/contract.py`, `python -m jav.cli flows`). Ne szerkeszd kézzel -",
             "> generáld újra. A fázisonként csoportosított gráf a FLOW.mmd.", "", "## Fázisok és lépések", ""]
    for ph in contract["phases"]:
        lines.append(f"### {ph}")
        for name in by_phase.get(ph, []):
            m = meta.get(name, {})
            kind, note = m.get("kind", ""), m.get("note", "")
            lines.append(f"- **{name}**{f' _({kind})_' if kind else ''}{(' — ' + note) if note else ''}")
        lines.append("")
    if contract.get("terminals"):
        lines += [f"Terminális lépések: {', '.join(contract['terminals'])}", ""]
    if contract.get("doc_note"):
        lines += [f"> {contract['doc_note']}", ""]
    lines += ["## Gráf (Mermaid)", "", "```mermaid", overview_mermaid(contract), "```", ""]
    return "\n".join(lines)


def write_artifacts(contract: dict[str, Any], out_dir: Path | None = None) -> dict[str, str]:
    d = (out_dir or FLOWS_DOC_DIR) / contract["name"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "FLOW.mmd").write_text(overview_mermaid(contract) + "\n", encoding="utf-8")
    (d / "FLOW.md").write_text(flow_md(contract), encoding="utf-8")
    return {"mmd": str(d / "FLOW.mmd"), "md": str(d / "FLOW.md")}


# --- lint -----------------------------------------------------------------------------------


def _live_edges(app: Any) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for t in getattr(app.graph, "transitions", []):
        a = getattr(getattr(t, "from_", None), "name", None)
        b = getattr(getattr(t, "to", None), "name", None)
        if a and b:
            edges.add((a, b))
    return edges


def lint_flow(contract: dict[str, Any], app: Any, module: ModuleType) -> dict[str, Any]:
    """Kontrakt <-> élő Burr-gráf <-> forrás. Visszatér: {"checks": [(név, ok, részlet)], "passed": bool}."""
    checks: list[tuple[str, bool, str]] = []
    src = inspect.getsource(module)
    declared = [name for name, _ in contract["steps"]]
    declared_set = set(declared)

    # 1. lépések: az élő gráf minden akciója deklarált, és minden deklarált lépés él
    live = {a.name for a in app.graph.actions}
    checks.append(("kontrakt lefedi az élő gráfot", live == declared_set,
                   f"élő: {len(live)}, deklarált: {len(declared_set)}; hiányzó: {sorted(live - declared_set) or '-'}, felesleges: {sorted(declared_set - live) or '-'}"))

    # 2. élek: deklarált == élő (címke nélkül)
    decl_edges = {(e[0], e[1]) for e in contract["edges"]}
    live_edges = _live_edges(app)
    checks.append(("élek egyeznek", decl_edges == live_edges,
                   f"hiányzó a kontraktból: {sorted(live_edges - decl_edges) or '-'}; nincs az élő gráfban: {sorted(decl_edges - live_edges) or '-'}"))

    # 3. fázisok: minden lépés létező fázisban van; duplikált lépés nincs
    phases = set(contract["phases"])
    bad_phase = [n for n, ph in contract["steps"] if ph not in phases]
    checks.append(("fázisok érvényesek, lépés egyszer szerepel", not bad_phase and len(declared) == len(declared_set),
                   f"rossz fázis: {bad_phase or '-'}"))

    # 4. lépés-fajták: ismert fajta, és a fajtához illő hívás megjelenik az akció forrásában
    meta = contract.get("step_meta", {})
    kind_problems: list[str] = []
    for name in declared:
        kind = meta.get(name, {}).get("kind")
        if kind not in KINDS:
            kind_problems.append(f"{name}:ismeretlen({kind})")
            continue
        fn = getattr(module, name, None)
        fn_src = inspect.getsource(getattr(fn, "fn", fn)) if fn is not None else ""
        markers = _KIND_MARKERS.get(kind, ())
        if markers and not any(m in fn_src for m in markers):
            kind_problems.append(f"{name}:{kind} nyoma hiányzik")
        if kind in ("jev", "llm") and "run_id" not in fn_src:
            kind_problems.append(f"{name}:{kind} run_id nélkül (ledger)")
    checks.append(("lépés-fajták és nyomaik", not kind_problems, ", ".join(kind_problems) or "rendben"))

    # 5. csak adapteren át: a flow-modul nem importál SDK-t
    direct = [m for m in _FORBIDDEN_IMPORTS if re.search(rf"^\s*(from|import)\s+{m}", src, re.M)]
    checks.append(("adapter-only (nincs közvetlen SDK-import)", not direct, f"közvetlen: {direct or '-'}"))

    # 6. additív review-latch
    checks.append(("additív latch (nincs needs_review = False)", not _UNLATCH.search(src), "require_review() csak False->True"))

    # 7. terminálisok: a kontrakt és a modul TERMINALS listája egyezik, és deklarált lépések
    terms = set(contract.get("terminals", []))
    mod_terms = set(getattr(module, "TERMINALS", []))
    checks.append(("terminálisok egyeznek", terms == mod_terms and terms <= declared_set,
                   f"kontrakt: {sorted(terms)}, modul: {sorted(mod_terms)}"))

    return {"name": contract["name"], "checks": checks, "passed": all(ok for _, ok, _ in checks)}


def format_report(result: dict[str, Any]) -> str:
    lines = [f"### {result['name']} - {'PASS' if result['passed'] else 'FAIL'}"]
    for name, ok, detail in result["checks"]:
        lines.append(f"- [{'x' if ok else ' '}] {name} — {detail}")
    return "\n".join(lines)
