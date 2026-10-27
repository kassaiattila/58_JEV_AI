"""The rule proposals measured on the invented insurer's condition documents (231, stage D, D-c7h).

Plain-language summary: the invented insurer's set (`configs/golden_products.json`) holds the 16 rules a careful person
reads from its five condition documents: the expected answer of a rule proposal. This measurement writes the documents
as PDFs, has the proposer read each (GPT within the round's OpenAI budget; with the JEV engine, JEV judges each proposal
within its budget; without a budget only earlier answers count, so a document without one has no result), and compares
every proposal with the expected rules. A proposal is matched to an expected rule by the clause it cites (and, among
several, by its kind); it is exact when its kind, level, facts, cover modules, way of deciding, every row (the values
typed by the catalogue, a list as a set) and its page are the expected rule's, and otherwise it differs, in what. An
expected rule nothing matched is missed; a proposal that matches none is extra. The measurement also counts what the
code's checks blocked and how JEV's marks fall: a "supported" on a proposal that differs is a false acceptance. The
stand-in proposer scores 16 of 16 by construction, which tests the scorer; the paid round (stage D-h) asks GPT.

- `measure(options)`: the golden set's measurement (`goldens.Outcome`), with its raw rows in `runs/`.
- `propose_set(product_set, folder, proposer_for, verifier_for)`, `score(product_set, proposed)`: the two halves.

Layer: measurement (beside the stack); no AI call of its own (the proposer and JEV are asked through the application).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from jav.ai import gpt_answer
from jav.app import facts, product_sets, rule_proposals, rule_support
from jav.app.product_rules import Rule
from jav.core import calls, cfg, versions
from jav.core.config import RUNS_DIR
from jav.documents import page_text

__all__ = ["RuleScore", "Score", "count", "measure", "propose_set", "score"]

SET = "golden_products"
CATALOGUE = "property"
PRODUCT = "inv_business_property"
Verdict = Literal["exact", "differs", "missed"]


@dataclass(frozen=True)
class RuleScore:
    expected: str  # the expected rule's identifier
    document: str
    verdict: Verdict
    proposal: str | None = None  # the matched proposal's title
    differences: tuple[str, ...] = ()
    blocking: bool = False  # the code's checks blocked the matched proposal
    support: str | None = None  # JEV's mark of the matched proposal


@dataclass(frozen=True)
class Score:
    rules: tuple[RuleScore, ...]
    extra: tuple[str, ...]  # the proposals that match no expected rule ("<document>: <title>")
    documents: int
    answered: tuple[str, ...]  # the documents that got an answer

    def count(self, verdict: Verdict) -> int:
        return sum(1 for r in self.rules if r.verdict == verdict)

    @property
    def false_acceptances(self) -> int:
        return sum(1 for r in self.rules if r.verdict == "differs" and r.support == "supported")


def count() -> int:
    return len(product_sets.load(SET).rules)


def _typed(d: Any, name: str, op: str, value: Any) -> Any:
    try:
        if op in ("in", "not_in"):
            return frozenset(repr(facts.typed_value(name, d, v)) for v in value)
        if op == "between":
            return tuple(repr(facts.typed_value(name, d, v)) for v in value)
        if op in ("present", "absent"):
            return bool(value)
        return repr(facts.typed_value(name, d, value))
    except (facts.FactError, TypeError, ValueError):
        return ("raw", json.dumps(value, sort_keys=True, default=str))


def _rows(rule: Rule, cat: facts.Catalogue) -> list[tuple[Any, Any]]:
    out = []
    for row in rule.table.rows:
        when = {f: {op: _typed(facts.compared_as(cat.facts[f]) if f in cat.facts else None, f, op, v) for op, v in cond.items()}
                for f, cond in row.when.items()}  # U-A3: a list of codes compared by single codes, as the evaluation does
        then = {o: _typed(cat.outcomes.get(o), o, "eq", v) for o, v in row.then.items()}
        out.append((json.dumps(when, sort_keys=True, default=sorted), json.dumps(then, sort_keys=True, default=str)))
    return out


def _differences(proposed: Rule, expected: Rule, cat: facts.Catalogue) -> tuple[str, ...]:
    out = []
    for name, a, b in (("kind", proposed.kind, expected.kind), ("level", proposed.level, expected.level),
                       ("facts", set(proposed.facts), set(expected.facts)), ("modules", set(proposed.modules), set(expected.modules)),
                       ("hit", proposed.table.hit, expected.table.hit), ("page", proposed.source.page, expected.source.page)):
        if a != b:
            out.append(name)
    if _rows(proposed, cat) != _rows(expected, cat):
        out.append("rows")
    return tuple(out)


def score(product_set: product_sets.ProductSet, proposed: dict[str, list[rule_proposals.Proposal]]) -> Score:
    """Every expected rule matched with the proposals for its document, and the proposals left over."""
    cat = facts.catalogue(CATALOGUE)
    results: list[RuleScore] = []
    extra: list[str] = []
    for doc_id in product_set.documents:
        mine = list(proposed.get(doc_id, []))
        used: set[int] = set()
        for ident, expected in product_set.rules.items():
            if versions.split(expected.source.document)[0] != doc_id:
                continue
            candidates = [i for i, p in enumerate(mine) if i not in used and p.rule is not None
                          and p.rule.source.clause == expected.source.clause]
            pick = next((i for i in candidates if mine[i].rule.kind == expected.kind), candidates[0] if candidates else None)
            if pick is None:
                results.append(RuleScore(ident, doc_id, "missed"))
                continue
            used.add(pick)
            p = mine[pick]
            found = _differences(p.rule, expected, cat)
            results.append(RuleScore(ident, doc_id, "differs" if found else "exact", p.rule.title, found,
                                     bool(p.check and p.check.blocking), p.support.mark if p.support else None))
        extra += [f"{doc_id}: {p.record.title}" for i, p in enumerate(mine) if i not in used]
    return Score(tuple(results), tuple(extra), len(product_set.documents), tuple(sorted(proposed)))


def propose_set(product_set: product_sets.ProductSet, folder: Path, *, proposer_for: Callable[[str], rule_proposals.Proposer],
                verifier_for: Callable[[str], rule_proposals.Verifier | None]) -> tuple[dict[str, list[rule_proposals.Proposal]], dict[str, str]]:
    """Each document written as a PDF and proposed from; the proposals by document, and why a document has none."""
    markers = cfg.load("rule_proposals")["skip_page_markers"]
    modules = {m.code: m.name for m in product_set.products[PRODUCT].modules} if PRODUCT in product_set.products else {}
    written = product_sets.write_documents(product_set, folder)
    proposed: dict[str, list[rule_proposals.Proposal]] = {}
    failed: dict[str, str] = {}
    for doc_id, path in written.items():
        ref = versions.ref(doc_id, product_sets.FIRST)
        try:
            pages = page_text.read_pages(path, markers)
            proposed[doc_id] = rule_proposals.propose(ref, pages, CATALOGUE, proposer=proposer_for(ref), modules=modules,
                                                      document=product_set.documents[doc_id].content, verifier=verifier_for(ref))
        except (calls.BudgetExceeded, calls.UncertainAttempt, gpt_answer.NoBudget) as exc:
            failed[doc_id] = f"{type(exc).__name__}: {exc}"
    return proposed, failed


def _rows_out(s: Score, failed: dict[str, str], meta: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"kind": "rule", **asdict(r)} for r in s.rules]
    out += [{"kind": "extra", "proposal": e} for e in s.extra]
    out += [{"kind": "unanswered", "document": d, "why": why} for d, why in failed.items()]
    out.append({"kind": "summary", **meta, "exact": s.count("exact"), "differs": s.count("differs"), "missed": s.count("missed"),
                "extra": len(s.extra), "false_acceptances": s.false_acceptances,
                "blocked": sum(1 for r in s.rules if r.blocking)})
    return out


def measure(options: Any, *, stand_in: bool = False) -> Any:
    """The golden set's measurement, as `python -m jav.cli measure rules:proposals` runs it (`stand_in`: the free
    stand-in proposer, which tests the scorer)."""
    from jav.evals import goldens

    product_set = product_sets.load(SET)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    limits = {p: Decimal(str(v)) for p, v in (("openai", options.budget_usd), ("jev", options.jev_budget_usd if options.jev else None))
              if v is not None}
    folder = RUNS_DIR / "rule_proposal_documents"
    with calls.measurement(f"rule-proposals-{stamp}", limits, reuse=options.use_cache) as scope:
        def proposer_for(ref: str) -> rule_proposals.Proposer:
            return rule_proposals.set_proposer(product_set) if stand_in else rule_proposals.gpt_proposer(scope)

        def verifier_for(ref: str) -> rule_proposals.Verifier | None:
            if not options.jev:
                return None
            return lambda rule, pages: rule_support.support(rule, pages, run_id=scope, use_cache=options.use_cache)

        proposed, failed = propose_set(product_set, folder, proposer_for=proposer_for, verifier_for=verifier_for)
        usage = calls.scope_calls(scope)
    s = score(product_set, proposed)
    meta = {"engine": options.engine, "stand_in": stand_in, "scope": scope, "live_calls": usage["live"],
            "cost_usd": str(usage["live_cost_usd"]), "reused": usage["reused"],
            "config_hash": cfg.config_hash("rule_proposals", f"gpt_{rule_proposals.SITE}", f"callsite:{rule_support.REQUEST_ID}")}
    rows = _rows_out(s, failed, meta)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out = RUNS_DIR / f"{stamp}_rule_proposals_{'stand_in' if stand_in else options.engine}.jsonl"
    out.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows), encoding="utf-8")
    answered = [r for r in s.rules if r.document in s.answered]
    print(f"rule proposals ({'stand-in' if stand_in else options.engine}): {s.count('exact')}/{len(s.rules)} exact, "
          f"{s.count('differs')} differing, {s.count('missed')} missed, {len(s.extra)} extra, "
          f"{s.false_acceptances} false acceptance(s) by JEV; {len(failed)} document(s) without an answer -> {out}")
    return goldens.Outcome(cases=len(s.rules), answered=len(answered), right=s.count("exact"), scored=len(s.rules), unit="rules",
                           failures=tuple(f"{r.expected}: {r.verdict}" + (f" ({', '.join(r.differences)})" if r.differences else "")
                                          for r in s.rules if r.verdict != "exact" and r.document in s.answered))
