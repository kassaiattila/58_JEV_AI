"""Rules proposed from a condition document (231, stage D, D-c7c).

Plain-language summary: the owner decided (2026-10-26) that a model proposes the rules from the condition documents,
code checks them and a person accepts, corrects or rejects each. A proposer reads a document's pages a few at a time
(never a page its marking keeps out), with the fact catalogue (its levels, facts, outcomes, the rule kinds and the
comparisons) and the product's cover modules, and answers with rule records: each a decision table, every value as JSON
text of the catalogue's type, with the page, clause and quoted words it was read from. Each record is turned into a
rule of the registry's form (one that does not fit is kept, with why) and checked by code (`rule_checks`). Two
proposers: GPT under a budget (`configs/gpt_rule_proposal.json`), and a stand-in that answers with a product set's rules
for that document, free, for the tests and a demonstration, and named as a stand-in wherever it shows.

- `propose(document_ref, pages, catalogue_id, proposer=, modules=, document=, verifier=)`: the `Proposal`s (the record as
  answered, the rule or why none, the code's check, and with a `verifier` (D-c7d: `rule_support.support`) JEV's mark
  for a proposal code found nothing blocking in).
- `gpt_proposer(run_id)`, `set_proposer(product_set)`: the two proposers.
- `to_rule(record, catalogue_id, document_ref, modules=)`, `record_of(rule)`: a record and a rule, each way; (231 U-A0)
  a record naming every module is the product's whole, an amount written as text is money.

Layer: application; it names no process and no business (the catalogue, the documents and the rules are data).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from jav.ai import gpt_answer
from jav.app import facts, rule_checks, rule_support
from jav.app.product_rules import OPS, ConditionDocument, Rule
from jav.core import cfg, numbers, versions
from jav.core.user_messages import Said, said
from jav.documents.page_text import DocumentPages

__all__ = ["SITE", "Proposal", "ProposedRule", "ProposedRules", "Request", "gpt_proposer", "propose", "record_of",
           "set_proposer", "to_rule"]

SITE = "rule_proposal"
STAND_IN = "stand_in"
KINDS = ("eligibility", "exclusion", "requirement", "sublimit", "deductible", "premium_factor", "valuation", "obligation")


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProposedCondition(_Answer):
    fact: str
    op: Literal["eq", "ne", "in", "not_in", "lt", "lte", "gt", "gte", "between", "present", "absent"]
    value: str  # JSON text of the value


class ProposedOutcome(_Answer):
    outcome: str
    value: str  # JSON text of the value


class ProposedRow(_Answer):
    when: list[ProposedCondition]
    then: list[ProposedOutcome]


class ProposedRule(_Answer):
    title: str
    kind: Literal["eligibility", "exclusion", "requirement", "sublimit", "deductible", "premium_factor", "valuation",
                  "obligation"]
    level: str
    modules: list[str]
    facts: list[str]
    hit: Literal["first", "collect"]
    rows: list[ProposedRow]
    page: int
    clause: str
    quote: str


class ProposedRules(_Answer):
    # D-h: required, as every field of the answer is, so the provider holds the model to this form strictly (a default
    # made the form not strict, and the first paid answer named its fields as it liked)
    rules: list[ProposedRule]


@dataclass(frozen=True)
class Request:
    document_ref: str
    pages: tuple[int, ...]
    prompt: str


Proposer = Callable[[Request], ProposedRules]
Verifier = Callable[[Rule, DocumentPages], rule_support.Support]


@dataclass(frozen=True)
class Proposal:
    record: ProposedRule
    rule: Rule | None
    problem: Said | None  # why the record is no rule of the registry's form
    check: rule_checks.RuleCheck | None
    pages: tuple[int, ...]  # the pages it was proposed from
    support: rule_support.Support | None = None  # D-c7d: JEV's mark (None: not asked for, or code found it blocking)


def _site() -> dict[str, Any]:
    return cfg.load(f"gpt_{SITE}")


def _value(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text.strip()  # a bare code


_MONEY_TEXT = re.compile(r"^\s*(\d[\d ., ]*?)\s*(HUF|Ft|EUR|€|USD)?\s*$")
_CURRENCY = {"Ft": "HUF", "€": "EUR"}


def _typed(kind: str | None, currency: str | None, value: Any) -> Any:
    """231 (U-A0; the D-h measurement): an amount written as text ("10000000 HUF", "10 000 000 Ft") for a money fact or
    outcome, as the registry's amount with its currency (Ft is HUF; none named: the catalogue's); a list's or a
    range's amounts each so; anything else as given."""
    if kind != "money":
        return value
    if isinstance(value, list):
        return [_typed(kind, currency, v) for v in value]
    if not isinstance(value, str) or not (m := _MONEY_TEXT.match(value)):
        return value
    amount = numbers.read_number(m.group(1)).value
    if amount is None:
        return value
    return {"amount": str(amount), "currency": _CURRENCY.get(m.group(2) or "", m.group(2)) or currency or "HUF"}


def to_rule(record: ProposedRule, catalogue_id: str, document_ref: str, *,
            modules: Collection[str] = ()) -> tuple[Rule | None, Said | None]:
    """The registry's rule a record stands for, or why it is none. 231 (U-A0): a record naming every one of the
    product's `modules` applies to every module (none named, so a module added later is covered too), and an amount
    written as text is read as money."""
    cat = facts.catalogue(catalogue_id)
    fact_kind = {name: (d.type, d.currency) for name, d in cat.facts.items()}
    outcome_kind = {name: (o.type, o.currency) for name, o in cat.outcomes.items()}
    rows = []
    for row in record.rows:
        when: dict[str, dict[str, Any]] = {}
        for c in row.when:
            when.setdefault(c.fact, {})[c.op] = _typed(*fact_kind.get(c.fact, (None, None)), _value(c.value))
        rows.append({"when": when, "then": {o.outcome: _typed(*outcome_kind.get(o.outcome, (None, None)), _value(o.value))
                                            for o in row.then}})
    named = [] if modules and set(modules) <= set(record.modules) else list(record.modules)
    data = {"catalogue": catalogue_id, "kind": record.kind, "title": record.title, "level": record.level,
            "modules": named, "facts": list(record.facts), "table": {"hit": record.hit, "rows": rows},
            # D-h: a clause as printed ("3.1.") is the clause the registry names without its closing dot ("3.1")
            "source": {"document": document_ref, "page": record.page, "clause": record.clause.strip().rstrip(".").strip() or None,
                       "quote": record.quote.strip() or None},
            "origin": {"kind": "proposal"}}
    try:
        return Rule.model_validate(data), None
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        return None, said("its record is no rule: {{where}}: {{reason}}", where=where or "–", reason=first["msg"])


def record_of(rule: Rule) -> ProposedRule:
    """A rule as a proposer's record (the stand-in answers with these)."""
    def text(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    rows = [ProposedRow(when=[ProposedCondition(fact=f, op=op, value=text(v)) for f, cond in r["when"].items() for op, v in cond.items()],
                        then=[ProposedOutcome(outcome=o, value=text(v)) for o, v in r["then"].items()])
            for r in rule.model_dump(mode="json")["table"]["rows"]]
    return ProposedRule(title=rule.title, kind=rule.kind, level=rule.level, modules=list(rule.modules), facts=list(rule.facts),
                        hit=rule.table.hit, rows=rows, page=rule.source.page or 0, clause=rule.source.clause or "",
                        quote=rule.source.quote or "")


def _prompt(cat: facts.Catalogue, modules: dict[str, str], pages: dict[int, str]) -> str:
    known = {
        "levels": [{"code": level, "title": cat.labels.get(level, level)} for level in cat.levels],
        "facts": [{"name": name, "title": d.title, "type": d.type, "level": d.level, "unit": d.unit, "currency": d.currency,
                   "options": list(d.options) if d.options else None} for name, d in cat.facts.items()],
        "outcomes": [{"name": name, "title": o.title, "type": o.type, "options": list(o.options) if o.options else None,
                      "currency": o.currency} for name, o in cat.outcomes.items()],
        "kinds": list(KINDS), "comparisons": list(OPS),
        "cover_modules": [{"code": code, "name": name} for code, name in modules.items()],
    }
    text = "\n\n".join(f"=== page {n} ===\n{pages[n]}" for n in sorted(pages))
    return f"CATALOGUE (JSON):\n{json.dumps(known, ensure_ascii=False)}\n\nPAGES (data):\n{text}"


def gpt_proposer(run_id: str) -> Proposer:
    """GPT's proposals, through the call log under the caller's OpenAI budget (`gpt_answer.NoBudget` without one)."""
    def answer(request: Request) -> ProposedRules:
        site = _site()
        return gpt_answer.ask(SITE, request.prompt, ProposedRules, instructions=site["instructions"],
                              max_output_tokens=int(site["max_output_tokens"]), run_id=run_id,
                              config_hash=cfg.config_hash(f"gpt_{SITE}"))
    return answer


def set_proposer(product_set: Any) -> Proposer:
    """A stand-in proposer: a product set's rules read from the document and the pages asked (free; a stand-in)."""
    def answer(request: Request) -> ProposedRules:
        ident = versions.split(request.document_ref)[0]
        return ProposedRules(rules=[record_of(rule) for rule in product_set.rules.values()
                                    if versions.split(rule.source.document)[0] == ident and rule.source.page in request.pages])
    return answer


def propose(document_ref: str, pages: DocumentPages, catalogue_id: str, *, proposer: Proposer,
            modules: dict[str, str] | None = None, document: ConditionDocument | None = None,
            verifier: Verifier | None = None) -> list[Proposal]:
    """The rules `proposer` reads from the document's pages, a few pages at a time, each turned into a rule and
    checked by code, then judged by `verifier` when code found nothing blocking. A page its marking kept out is never
    asked about."""
    cat = facts.catalogue(catalogue_id)
    per = max(1, int(_site()["pages_per_request"]))
    numbers = sorted(pages.pages)
    out: list[Proposal] = []
    for start in range(0, len(numbers), per):
        chunk = tuple(numbers[start:start + per])
        request = Request(document_ref, chunk, _prompt(cat, modules or {}, {n: pages.pages[n] for n in chunk}))
        for record in proposer(request).rules:
            rule, problem = to_rule(record, catalogue_id, document_ref, modules=tuple(modules or {}))
            check = rule_checks.check(rule, pages, document_ref=document_ref, document=document) if rule is not None else None
            judged = verifier(rule, pages) if verifier is not None and rule is not None and check and not check.blocking else None
            out.append(Proposal(record, rule, problem, check, chunk, judged))
    return out
