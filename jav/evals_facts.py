"""The general facts measured on a held-out family's labelled documents (197, plan 197 K1).

Plain-language summary: a document whose type has no type pack gets general facts (120): GPT proposes source-bound
facts, code checks each quote against the document's text, and JEV rates how well the source supports it. No golden
set measured that until now. Here the legacy golden documents of a type pack (`configs/golden_facts.json`: the ticket)
go straight to the general facts with their pack withheld, as a document of an unknown type would, and the pack's
scored fields are looked for among the facts by value, with the same comparison as the data point golden sets
(`jav/evals.py` `field_equal`). For each expected value the report says whether a fact that passed the code's check
carries it (found), whether JEV supports that fact (supported), and whether only a fact the code rejected carries it.
The fact's own name is free text, so a value is found by value, not by name; the names the facts used are kept in the
raw rows for the taught type (K2) to start from. A file repeated in the manifest is measured once.

The documents are split into a development and an evaluation half, fixed before any measurement; the report shows
both, because a taught type may learn from the development half only and is measured on the evaluation half (K2).

Raw rows: `runs/<stamp>_facts_<family>[_gpt].jsonl`. Budget (160): without one only earlier answers count (the native
path refuses a provider without a budget, so it gets a zero budget: an earlier answer is reused, a live call is
refused); a paid round measures one family, under the owner's sub-budget. A document takes the native graph's reading
and interpretation steps (`jav/documents/native_results.py` `prepare_reading`, `jav/ai/native_processing.py` `interpret`: the
local reader, GPT's facts, the code's check and JEV's support), as an unknown document does in a run; it is not
published and opens no to-do, because a publication belongs to a work run. The readings and outcomes stay in the store
under the measurement's own scope, as every golden run keeps its results; no work package or run is touched.

Layer: measurement (the native graph's steps); no store of its own.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from jav.ai import policy
from jav.core import cfg
from jav.core.config import RUNS_DIR
from jav.evals import GoldenCase, field_equal, load_cases
from jav.ai.typepack import TypePack
from jav.ai.typepack import get as get_pack

HALVES = ("development", "evaluation")


class FactsGoldenError(ValueError):
    """The facts golden set's configuration does not fit its documents."""


@dataclass(frozen=True)
class FactCase:
    case: GoldenCase
    sha256: str
    half: str


def families() -> list[str]:
    return list(cfg.load("golden_facts")["families"])


def _split(family: str) -> dict[str, str]:
    halves = cfg.load("golden_facts")["families"][family]
    return {sha: half for half in HALVES for sha in halves[half]}


def cases(family: str) -> list[FactCase]:
    """The family's distinct documents with their half, in the manifest's order (a repeated file once); a document
    outside the fixed split is refused, so the halves cannot drift."""
    split, seen, out = _split(family), set(), []
    for case in load_cases(family):
        sha = hashlib.sha256(case.pdf.read_bytes()).hexdigest()
        if sha in seen:
            continue
        if sha not in split:
            raise FactsGoldenError(f"{family}: a golden document outside the fixed split ({sha[:12]})")
        seen.add(sha)
        out.append(FactCase(case=case, sha256=sha, half=split[sha]))
    return out


def count(family: str) -> int:
    """The number of distinct documents; 0 without the legacy project (no golden case)."""
    try:
        return len(cases(family))
    except OSError:
        return 0


def _band(support: float | None) -> str | None:
    from jav.flow_native import SUPPORT_BAND

    return None if support is None else policy.noul_band(support, SUPPORT_BAND)


def score(facts: list[dict[str, Any]], expected: dict[str, Any], pack: TypePack) -> dict[str, dict[str, Any]]:
    """Per scored field with an expected value: `found` (a fact the code's check passed, stated, carries the value),
    `supported` (JEV's support of such a fact is in the `yes` band; None when JEV was not asked), `rejected_only` (only
    a fact the code rejected carries it) and the names of the facts that carry it. `facts` are the interpretation's
    checked facts as plain data (`CheckedFact.model_dump()`)."""
    out: dict[str, dict[str, Any]] = {}
    for field in pack.strict_scored:
        value = expected.get(field)
        if value in (None, ""):
            continue
        carrying = [f for f in facts if field_equal(field, f["proposal"]["value"], value, pack.kind(field))]
        checked = [f for f in carrying if f["grounding"] == "literal_match" and f["proposal"]["state"] == "stated"]
        bands = [_band(f["semantic_support"]) for f in checked]
        out[field] = {"found": bool(checked),
                      "supported": None if checked and all(b is None for b in bands) else "yes" in bands,
                      "rejected_only": bool(carrying) and not checked,
                      "names": sorted({f"{f['proposal']['entity']}.{f['proposal']['property']}" for f in carrying})}
    return out


def _fact_counts(facts: list[dict[str, Any]]) -> dict[str, int]:
    return {"facts": len(facts), "checked": sum(f["grounding"] == "literal_match" for f in facts),
            "rejected": sum(f["grounding"] == "rejected" for f in facts),
            "not_stated": sum(f["proposal"]["state"] != "stated" for f in facts),
            "supported": sum(_band(f["semantic_support"]) == "yes" for f in facts if f["grounding"] == "literal_match")}


def _run_case(fc: FactCase, *, scope: str, jev: bool, use_cache: bool) -> dict[str, Any]:
    """One document through the native graph's reading and interpretation, its pack withheld, as an unknown document
    continues (120): a text PDF read as it is."""
    from jav.ai import native_processing
    from jav.documents import native_results

    pdf = fc.case.pdf
    limits = native_processing.estimate_limits({"jev": "on" if jev else "off", "arm": "G"})
    reading = native_results.prepare_reading(pdf, original_name=pdf.name, expected_sha256=fc.sha256,
                                             limits=limits.read_limits)
    outcome_id = native_processing.interpret(work_run_id=scope, item_id=fc.sha256, graph_id=f"{scope}:{fc.sha256[:16]}",
                                             reading_id=reading.reading_id, jev=jev, use_cache=use_cache, limits=limits)
    _, outcome, interpretation = native_results.load_outcome(outcome_id)
    facts = [f.model_dump(mode="json") for f in interpretation.facts] if interpretation is not None else None
    return {"outcome": outcome.status, "reason": outcome.reason, "reading": reading.reading.status, "facts": facts}


def measure(family: str, *, jev: bool = True, use_cache: bool = True, budget_usd: Decimal | None = None,
            jev_budget_usd: Decimal | None = None) -> list[dict[str, Any]]:
    """Every distinct document of the family through the general facts, scored against its expected values."""
    from jav.core import calls

    pack = get_pack(family)
    if budget_usd is None and jev_budget_usd is None:
        print(calls.NO_BUDGET_NOTE)
    limits = {"openai": budget_usd or Decimal(0)} | ({"jev": jev_budget_usd or Decimal(0)} if jev else {})
    rows: list[dict[str, Any]] = []
    name = f"facts_{family}" + ("" if jev else "_gpt")
    with calls.measurement(f"measure-{datetime.now():%Y%m%d_%H%M%S}-{name}", limits, reuse=use_cache) as scope:
        for fc in cases(family):
            t0 = time.perf_counter()
            run = _run_case(fc, scope=scope, jev=jev, use_cache=use_cache)
            facts = run.pop("facts")
            row = {"case_id": fc.case.case_id, "sha256": fc.sha256, "half": fc.half, **run,
                   "counts": _fact_counts(facts) if facts is not None else None,
                   "scores": score(facts, fc.case.expected, pack) if facts is not None else None,
                   "seconds": round(time.perf_counter() - t0, 2)}
            rows.append(row)
            s = row["scores"]
            print(f"  {fc.case.case_id:40} {fc.half:11} " + (f"{sum(v['found'] for v in s.values())}/{len(s)} found"
                                                            if s is not None else f"without a result ({row['outcome']})"))
    path = _dump(rows, name)
    print_report(rows, pack, jev=jev)
    print(f"\nRaw rows: {path}")
    return rows


def _dump(rows: list[dict[str, Any]], name: str) -> Path:
    RUNS_DIR.mkdir(exist_ok=True)
    path = RUNS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{name}.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows), encoding="utf-8")
    return path


def totals(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Over the documents with a result: the expected values, those found, supported and carried by a rejected fact
    only."""
    vals = [v for r in rows if r["scores"] is not None for v in r["scores"].values()]
    return {"documents": len(rows), "answered": sum(r["scores"] is not None for r in rows), "expected": len(vals),
            "found": sum(v["found"] for v in vals), "supported": sum(v["supported"] is True for v in vals),
            "rejected_only": sum(v["rejected_only"] for v in vals)}


def print_report(rows: list[dict[str, Any]], pack: TypePack, *, jev: bool) -> None:
    print(f"\n### General facts - {pack.key}, its type pack withheld ({'GPT + JEV' if jev else 'GPT only'})\n")
    print("| field | found | supported by JEV | only in a rejected fact |\n|---|---|---|---|")
    for field in pack.strict_scored:
        vals = [r["scores"][field] for r in rows if r["scores"] is not None and field in r["scores"]]
        if vals:
            print(f"| {field} | {sum(v['found'] for v in vals)}/{len(vals)} | "
                  f"{sum(v['supported'] is True for v in vals) if jev else '-'} | {sum(v['rejected_only'] for v in vals)} |")
    for half in HALVES:
        t = totals([r for r in rows if r["half"] == half])
        print(f"\n**{half.capitalize()} half:** {t['answered']}/{t['documents']} documents with a result; "
              f"{t['found']}/{t['expected']} expected values found"
              + (f", {t['supported']} of them supported by JEV" if jev else "") + f"; {t['rejected_only']} only in a rejected fact")
    t = totals(rows)
    print(f"\n**Together:** {t['found']}/{t['expected']} = {t['found'] / max(t['expected'], 1):.1%} expected values found")
    counted = [r["counts"] for r in rows if r["counts"] is not None]
    if counted:
        print("**Facts per document:** " + ", ".join(f"{k} {sum(c[k] for c in counted)}" for k in counted[0]))
    failed = [r for r in rows if r["scores"] is None]
    for r in failed:
        print(f"  - {r['case_id']}: without a result ({r['outcome']}: {r['reason']})")
