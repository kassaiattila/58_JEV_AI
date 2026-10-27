"""A product set kept as data (231, stage D, D-c5).

Plain-language summary: a product set is what the issuer of a product publishes for an offer: its condition documents
with each clause's text, the rules a careful person reads from them, its products and tariffs, kept as one data file
(the invented insurer's: `configs/golden_products.json`). This module reads a set and checks that it holds together:
every rule against its catalogue and the documents, the page and clause it cites, its quote found in that clause's
text, every clause with its text, every reference naming a thing of the set. It installs a set into a store: each
thing a draft by one person and, when asked, made active by another (the four eyes a product needs), in the order the
references need (documents, rules, tariffs, products). A thing already there with the same content is kept; one with
another content refuses the whole set, before anything is written. A set's reference cases are checked inputs with
their expected outcome, worked by hand; `case_differences` compares them with the rule evaluation and the rating.

- `load(name)`: the set (`ProductSet`); `problems(product_set)`: what does not hold together.
- `install(product_set, maker=, approver=None)`: the references installed or found (`SetRefused`: why none).
- `run_case(product_set, case)`, `case_differences(product_set, case)`: a reference case evaluated and priced, and
  how that differs from what it expects.
- D-c7a: `document_pages(product_set, ident)`, `write_documents(product_set, folder)`: each condition document as the
  pages of a PDF, every clause (its number, title and text) on the page it says, so a rule proposal reads the invented
  documents as it will read a real file.

Layer: application (a config read; the registry writes); it names no process and no business (a set is data).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from jav.app import facts, product_rules, rating, rule_evaluation
from jav.app.product_rules import ConditionDocument, Product, Resolved, Rule, Tariff
from jav.core import cfg, identity, versions
from jav.core.measures import Money
from jav.documents.synthetic_pdf import write_unicode_pdf_pages
from jav.core.user_messages import explained

__all__ = ["SETS", "Case", "DocumentEntry", "Expected", "ProductSet", "SetRefused", "case_differences", "document_pages", "install",
           "load", "problems", "run_case", "write_documents"]

FIRST = 1  # a set names the first version of each of its things
SETS = ("golden_products",)  # D-c7g: the product sets kept as data (`configs/<name>.json`), a stand-in proposer's answers


class SetRefused(ValueError):
    """A set that does not hold together, or that a store holds another content of: nothing is written."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DocumentEntry(_Model):
    content: ConditionDocument
    text: dict[str, str]  # each clause's text as printed


class Expected(_Model):
    verdict: str | None = None
    missing: tuple[tuple[str, str], ...] = ()  # (unit, fact)
    units: dict[str, dict[str, Any]] = Field(default_factory=dict)  # a unit's combined outcomes, in full
    lines: tuple[tuple[str, str, str], ...] = ()  # (unit, module, amount in the tariff's currency)
    total: str | None = None
    policy_minimum_applied: bool = False
    blockers: tuple[str, ...] = ()


class Case(_Model):
    id: str
    title: str
    modules: tuple[str, ...]
    input: dict[str, Any]  # a checked input (`facts.checked_input`)
    expected: Expected


class ProductSet(_Model):
    issuer: str
    documents: dict[str, DocumentEntry]
    rules: dict[str, Rule]
    tariffs: dict[str, Tariff] = Field(default_factory=dict)
    products: dict[str, Product]
    cases: tuple[Case, ...] = ()


def load(name: str = "golden_products") -> ProductSet:
    """A set from its data file (`configs/<name>.json`)."""
    return ProductSet.model_validate({k: v for k, v in cfg.load(name).items() if k != "meta"})


def _words(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _first(ident: str) -> str:
    return versions.ref(ident, FIRST)


def _in_set(kind: str, ref: str, things: dict[str, Any]) -> str | None:
    ident, n = versions.split(ref)
    if n != FIRST or ident not in things:
        return f"names {kind} {ref}, which is not a first version of the set"
    return None


def problems(product_set: ProductSet) -> list[str]:
    """What does not hold together in a set; empty when it does."""
    ps = product_set
    out: list[str] = []
    documents = {_first(ident): entry.content for ident, entry in ps.documents.items()}
    for ident, entry in ps.documents.items():
        clauses = {s.clause for s in entry.content.sections}
        out += [f"document {ident}: clause {c} has no text" for c in sorted(clauses - set(entry.text))]
        out += [f"document {ident}: a text for clause {c}, which it does not list" for c in sorted(set(entry.text) - clauses)]
    for ident, rule in ps.rules.items():
        out += [f"rule {ident}: {p}" for p in product_rules.rule_problems(rule, documents)]
        source = rule.source
        entry = ps.documents.get(versions.split(source.document)[0])
        if entry is None or source.clause is None:
            continue
        section = next((s for s in entry.content.sections if s.clause == source.clause), None)
        if section is not None and source.page is not None and section.page is not None and source.page != section.page:
            out.append(f"rule {ident} cites page {source.page}, but clause {source.clause} is on page {section.page}")
        if source.quote and _words(source.quote) not in _words(entry.text.get(source.clause, "")):
            out.append(f"rule {ident}: its quote is not in clause {source.clause} of {source.document}")
    for ident, product in ps.products.items():
        codes = {m.code for m in product.modules}
        out += [f"product {ident} {p}" for ref in product.documents if (p := _in_set("document", ref, ps.documents))]
        for ref in product.rules:
            if p := _in_set("rule", ref, ps.rules):
                out.append(f"product {ident} {p}")
                continue
            rule = ps.rules[versions.split(ref)[0]]
            if rule.source.document not in product.documents:
                out.append(f"product {ident}: rule {ref} cites {rule.source.document}, which the product does not name")
            out += [f"product {ident}: rule {ref} is for module {m}, which the product does not have"
                    for m in rule.modules if m not in codes]
        if product.tariff is not None and product.tariff not in ps.tariffs:
            out.append(f"product {ident} is priced by tariff {product.tariff}, which is not in the set")
    for case in ps.cases:
        ref = case.input.get("product", "")
        product = ps.products.get(versions.split(ref)[0]) if _in_set("product", ref, ps.products) is None else None
        if product is None:
            out.append(f"case {case.id} names product {ref}, which is not a first version of the set")
            continue
        out += [f"case {case.id} asks for module {m}, which the product does not have"
                for m in case.modules if m not in {x.code for x in product.modules}]
        try:
            facts.checked_input(case.input)
        except (facts.FactError, ValueError) as exc:
            out.append(f"case {case.id}: {exc}")
    return out


def _things(ps: ProductSet) -> list[tuple[str, str, Any]]:
    """Every thing of the set, in the order its references need."""
    return ([("document", i, e.content) for i, e in ps.documents.items()] + [("rule", i, r) for i, r in ps.rules.items()]
            + [("tariff", i, t) for i, t in ps.tariffs.items()] + [("product", i, p) for i, p in ps.products.items()])


def install(product_set: ProductSet, *, maker: identity.Who, approver: identity.Who | None = None) -> list[str]:
    """The set's things as first versions in the store, drafts by `maker`; with `approver`, made active by them. A thing
    already there with the same content is kept as it is. Its references (`<kind>:<id>@1`)."""
    if found := problems(product_set):
        raise SetRefused(found)
    if approver is not None and product_set.products and \
            (identity.id_of(approver) or identity.name_of(approver)) == (identity.id_of(maker) or identity.name_of(maker)):
        raise explained(product_rules.SecondPersonNeeded, "a product version is made active by another person than its maker")
    things = _things(product_set)
    clashes = []
    for kind, ident, content in things:
        latest = product_rules.latest(kind, ident)
        if latest is not None and (latest["version"] != FIRST or latest["content"] != content.model_dump(mode="json")):
            clashes.append(f"{kind} {ident}: the store holds another version of it ({latest['ref']})")
    if clashes:
        raise SetRefused(clashes)
    refs = []
    for kind, ident, content in things:
        found = product_rules.latest(kind, ident) or product_rules.add(kind, ident, content.model_dump(mode="json"), actor=maker)
        if approver is not None and found["state"] == versions.DRAFT:
            found = product_rules.activate(kind, ident, FIRST, actor=approver)
        refs.append(f"{kind}:{found['ref']}")
    return refs


def document_pages(product_set: ProductSet, ident: str) -> list[list[str]]:
    """A condition document's pages as rows: on each, the issuer and the title, then its clauses in their order (the
    number and title, then the text), and the page's number at its foot. A page no clause names stays with its head."""
    entry = product_set.documents[ident]
    doc = entry.content
    last = max((s.page or 1 for s in doc.sections), default=1)
    pages: list[list[str]] = [[product_set.issuer, doc.title, ""] for _ in range(last)]
    for s in doc.sections:
        rows = pages[(s.page or 1) - 1]
        rows += [f"{s.clause}. {s.title}" if s.title else f"{s.clause}.", entry.text.get(s.clause, ""), ""]
    for n, rows in enumerate(pages, 1):
        rows.append(f"– {n} –")
    return pages


def write_documents(product_set: ProductSet, folder: Path) -> dict[str, Path]:
    """Every condition document of the set as a PDF in `folder` (`<id>.pdf`); the paths by document."""
    folder.mkdir(parents=True, exist_ok=True)
    return {ident: write_unicode_pdf_pages(folder / f"{ident}.pdf", document_pages(product_set, ident))
            for ident in product_set.documents}


def run_case(product_set: ProductSet, case: Case) -> tuple[rule_evaluation.Evaluation, rating.Calculation | None]:
    """A reference case evaluated by its product's rules and priced by its tariff (none without one)."""
    checked = facts.checked_input(case.input)
    product = product_set.products[versions.split(checked.product)[0]]
    rules = [Resolved(ref, product_set.rules[versions.split(ref)[0]]) for ref in product.rules]
    evaluation = rule_evaluation.evaluate(rules, checked, modules=case.modules)
    if product.tariff is None:
        return evaluation, None
    tariff = product_set.tariffs[product.tariff]
    return evaluation, rating.calculate(tariff, _first(product.tariff), checked, evaluation, modules=case.modules)


def _shown(value: Any) -> Any:
    return rule_evaluation.plain(value)


def case_differences(product_set: ProductSet, case: Case) -> list[str]:
    """How a reference case's evaluation and premium differ from what it expects; empty when they do not."""
    evaluation, calc = run_case(product_set, case)
    want = case.expected
    cat = facts.catalogue(evaluation.catalogue)
    out: list[str] = []
    if evaluation.verdict != want.verdict:
        out.append(f"verdict {evaluation.verdict}, expected {want.verdict}")
    if evaluation.missing != want.missing:
        out.append(f"missing {list(evaluation.missing)}, expected {list(want.missing)}")
    for unit_id, outcomes in want.units.items():
        got = evaluation.units[unit_id].combined if unit_id in evaluation.units else {}
        typed = {name: facts.typed_value(name, cat.outcomes[name], value) for name, value in outcomes.items()}
        if got != typed:
            out.append(f"{unit_id}: {_shown(got)}, expected {outcomes}")
    if calc is None:
        return out
    currency = calc.inputs["tariff"]["currency"]
    lines = [(line.unit_id, line.module, line.amount) for line in calc.lines]
    expected_lines = [(u, m, Money(amount=a, currency=currency)) for u, m, a in want.lines]
    if lines != expected_lines:
        out.append(f"lines {[(u, m, str(a.amount)) for u, m, a in lines]}, expected {[list(x) for x in want.lines]}")
    total = Money(amount=want.total, currency=currency) if want.total is not None else None
    if calc.total != total:
        out.append(f"total {_shown(calc.total)}, expected {want.total}")
    if calc.policy_minimum_applied != want.policy_minimum_applied:
        out.append(f"policy minimum applied: {calc.policy_minimum_applied}, expected {want.policy_minimum_applied}")
    blockers = evaluation.blockers + calc.blockers
    if blockers != want.blockers:
        out.append(f"blockers {list(blockers)}, expected {list(want.blockers)}")
    return out
