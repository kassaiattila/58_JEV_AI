"""Burr graph = contract: phases, steps, edges and step kind in one data structure; FLOW.md + Mermaid are generated from
it, and a lint compares the declared contract with the live Burr graph and the flow's source.

Ported from the legacy 10_AIFLOW_V4 framework (`orchestrator/framework/graph.py` + `lint.py`), narrowed to our rules:
- every live action is a declared step and vice versa; every declared edge exists in the live graph and vice versa;
- step kinds: `det` (code), `jev` (JEV through the adapter), `llm` (generative, Pydantic AI), `store` (SQLite write),
  `flow` (calls another graph), `terminal`; a call matching the kind appears in the action's source;
- the flow module does not import an SDK directly (typesafe_sdk / openai / pydantic_ai) - only the adapter does;
- additive review latch: the flow's source contains no `needs_review = False`;
- the `jev` / `llm` steps pass on the `run_id` (ledger).

Contract shape (named `CONTRACT` in the flow module):
    {"name": "invoice_hu", "phases": [...], "steps": [(step, phase), ...], "edges": [(a, b[, label]), ...],
     "step_meta": {step: {"kind": ..., "note": ...}}, "terminals": [...], "doc_note": "..."}
"""

from __future__ import annotations

import inspect
import ast
import re
import textwrap
from pathlib import Path
from types import ModuleType
from typing import Any

from jav.config import PROJECT_ROOT

FLOWS_DOC_DIR = PROJECT_ROOT / "docs" / "flows"
KINDS = ("det", "jev", "llm", "store", "flow", "terminal")
_KIND_MARKERS = {  # trace of a call matching the kind in the action's source (any one is enough)
    "jev": ("get_adapter", "jev", "detect(", "classify(", "select_fields(", "verify("),
    "llm": ("extract_llm", "extract(", "Agent", "openai"),
    "store": ("store.",),
    "flow": ("run_detect(", "run_email(", "run_one("),
}
_APPLICATION_CALLS = {
    "llm": {"native_processing.interpret"},
    "store": {"native_results.prepare_reading", "native_results.publish"},
}
_FORBIDDEN_IMPORTS = ("typesafe_sdk", "openai", "pydantic_ai")
_UNLATCH = re.compile(r"needs_review\s*=\s*False")


def overview_mermaid(contract: dict[str, Any]) -> str:
    """Mermaid grouped by phase (one subgraph per phase), with labelled edges."""
    by_phase: dict[str, list[str]] = {p: [] for p in contract["phases"]}
    for name, ph in contract["steps"]:
        by_phase.setdefault(ph, []).append(name)
    out = ["flowchart TD"]
    for ph in contract["phases"]:
        out.append(f'  subgraph ph_{ph}["{ph}"]')  # the subgraph id must not clash with a node name
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
    """FLOW.md from the contract - human-readable, drift-free documentation (do not edit by hand, regenerate it)."""
    by_phase: dict[str, list[str]] = {p: [] for p in contract["phases"]}
    meta = contract.get("step_meta", {})
    for name, ph in contract["steps"]:
        by_phase.setdefault(ph, []).append(name)
    lines = [f"# FLOW — {contract['name']}", "",
             "> Generated from the flow module's `CONTRACT` (`jav/contract.py`, `python -m jav.cli flows`).",
             "> Regenerate this file instead of editing it. FLOW.mmd groups the graph by phase.", "", "## Phases and steps", ""]
    for ph in contract["phases"]:
        lines.append(f"### {ph}")
        for name in by_phase.get(ph, []):
            m = meta.get(name, {})
            kind, note = m.get("kind", ""), m.get("note", "")
            lines.append(f"- **{name}**{f' _({kind})_' if kind else ''}{(' — ' + note) if note else ''}")
        lines.append("")
    if contract.get("terminals"):
        lines += [f"Terminal steps: {', '.join(contract['terminals'])}", ""]
    if contract.get("doc_note"):
        lines += [f"> {contract['doc_note']}", ""]
    lines += ["## Graph (Mermaid)", "", "```mermaid", overview_mermaid(contract), "```", ""]
    return "\n".join(lines)


def write_artifacts(contract: dict[str, Any], out_dir: Path | None = None) -> dict[str, str]:
    d = (out_dir or FLOWS_DOC_DIR) / contract["name"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "FLOW.mmd").write_text(overview_mermaid(contract) + "\n", encoding="utf-8", newline="\n")
    (d / "FLOW.md").write_text(flow_md(contract), encoding="utf-8", newline="\n")
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


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _step_trace(source: str, kind: str) -> tuple[bool, bool]:
    """Find actual calls and ledger identifiers; comments and string literals are not execution evidence."""
    tree = ast.parse(textwrap.dedent(source))
    calls = {_call_name(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    wrappers = _APPLICATION_CALLS.get(kind, set())
    markers = _KIND_MARKERS.get(kind, ())
    matched = bool(calls & wrappers) or any(marker.rstrip("(") in name for name in calls for marker in markers)
    ledger = any((isinstance(node, ast.Name) and "run_id" in node.id)
                 or (isinstance(node, ast.Attribute) and "run_id" in node.attr)
                 or (isinstance(node, ast.keyword) and node.arg in {"run_id", "work_run_id"})
                 for node in ast.walk(tree))
    return matched, ledger


def lint_flow(contract: dict[str, Any], app: Any, module: ModuleType) -> dict[str, Any]:
    """Contract <-> live Burr graph <-> source. Returns: {"checks": [(name, ok, detail)], "passed": bool}."""
    checks: list[tuple[str, bool, str]] = []
    src = inspect.getsource(module)
    declared = [name for name, _ in contract["steps"]]
    declared_set = set(declared)

    # 1. steps: every action of the live graph is declared, and every declared step is live
    live = {a.name for a in app.graph.actions}
    checks.append(("kontrakt lefedi az élő gráfot", live == declared_set,
                   f"élő: {len(live)}, deklarált: {len(declared_set)}; hiányzó: {sorted(live - declared_set) or '-'}, felesleges: {sorted(declared_set - live) or '-'}"))

    # 2. edges: declared == live (without labels)
    decl_edges = {(e[0], e[1]) for e in contract["edges"]}
    live_edges = _live_edges(app)
    checks.append(("élek egyeznek", decl_edges == live_edges,
                   f"hiányzó a kontraktból: {sorted(live_edges - decl_edges) or '-'}; nincs az élő gráfban: {sorted(decl_edges - live_edges) or '-'}"))

    # 3. phases: every step is in an existing phase; no step is duplicated
    phases = set(contract["phases"])
    bad_phase = [n for n, ph in contract["steps"] if ph not in phases]
    checks.append(("fázisok érvényesek, lépés egyszer szerepel", not bad_phase and len(declared) == len(declared_set),
                   f"rossz fázis: {bad_phase or '-'}"))

    # 4. step kinds: a known kind, and a call matching the kind appears in the action's source
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
        matched, ledger = _step_trace(fn_src, kind)
        if markers and not matched:
            kind_problems.append(f"{name}:{kind} nyoma hiányzik")
        if kind in ("jev", "llm") and not ledger:
            kind_problems.append(f"{name}:{kind} run_id nélkül (ledger)")
    checks.append(("lépés-fajták és nyomaik", not kind_problems, ", ".join(kind_problems) or "rendben"))

    # 5. adapter only: the flow module imports no SDK
    direct = [m for m in _FORBIDDEN_IMPORTS if re.search(rf"^\s*(from|import)\s+{m}", src, re.M)]
    checks.append(("adapter-only (nincs közvetlen SDK-import)", not direct, f"közvetlen: {direct or '-'}"))

    # 6. additive review latch
    checks.append(("additív latch (nincs needs_review = False)", not _UNLATCH.search(src), "require_review() csak False->True"))

    # 7. terminals: the contract's and the module's TERMINALS lists match, and they are declared steps
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
