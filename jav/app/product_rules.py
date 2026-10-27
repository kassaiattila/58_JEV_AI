"""Products, their condition documents and rules, kept as versions (231, stage D, D-c1).

Plain-language summary: a product (its cover modules, the condition documents and the rules it is offered under), each
condition document (its kind, the days it applies, its clauses and pages) and each rule is a versioned thing: a draft,
then active, then superseded or retired (the shared versions, `jav/core/versions.py`). A rule is a decision table over
the facts of a catalogue (`jav/app/facts.py`) on one level, giving outcomes the catalogue knows, with its source: the
document version, page and clause it was read from. A product version is the release manifest: it names exact rule and
document versions, and it becomes active only by another person than its maker, and only when every rule it names is
no draft, reads facts of its level or above, compares them with values of the right type, unit and currency, gives
known outcomes, and cites a document of the product and a clause that document has (`ManifestRefused` with every
problem). A retired or superseded version stays readable by its reference (`<id>@<n>`), so a case keeps the product
version of its start (`kept`, `named`).

- `add(kind, ident, content, actor)`: a draft (the thing's next version); `activate`, `retire`; `get`, `resolve`,
  `latest`, `listing`; `product_at(ref)`: a product version with its rules and documents.
- D-c3: a tariff (`Tariff`, kind `tariff`, the owner's decision of 2026-10-26: a tariff store of its own, beside the
  products): the currency, the days it is in force, the roundings, each module's basis, rate per thousand, minimum
  and factors, the factors (each read from a fact or an outcome, through a table of values), the total factors and
  the policy minimum (`jav/app/rating.py` computes with it).

Layer: application; it names no process and no business (the products, documents and rules are data).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from jav.app import capabilities, facts
from jav.core import identity, store, versions
from jav.core.measures import Money, PerMille, Rounding, Validity
from jav.core.clock import utc_stamp as _now
from jav.core.user_messages import Said, explained, inside, said, said_fields, said_from

__all__ = ["KINDS", "Citation", "ConditionDocument", "Factor", "ManifestRefused", "Product", "ProductAt", "Rule",
           "SecondPersonNeeded", "Tariff", "TariffModule", "activate", "add", "add_in", "choices", "get", "keeper", "kept", "latest",
           "listing", "made_by_ids_in", "named", "overview", "problems_of", "product_at", "remove_in", "resolve", "retire",
           "rule_problems"]

KINDS = ("document", "rule", "product", "tariff")
_TABLES = {"document": "condition_documents", "rule": "product_rules", "product": "products", "tariff": "tariffs"}
OPS = ("eq", "ne", "in", "not_in", "lt", "lte", "gt", "gte", "between", "present", "absent")

for _kind, _table in _TABLES.items():
    store.register_schema(_table, f"""
CREATE TABLE IF NOT EXISTS {_table} (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ident           TEXT NOT NULL,      -- the thing's identifier, the same for all its versions
    version         INTEGER NOT NULL,
    state           TEXT NOT NULL,      -- draft, active, superseded, retired
    name            TEXT NOT NULL,
    content         TEXT NOT NULL,      -- JSON: the {_kind}
    fingerprint     TEXT NOT NULL,      -- sha256 of the content
    made_by         TEXT NOT NULL,
    made_by_id      TEXT,
    made_at         TEXT NOT NULL,
    activated_by    TEXT,
    activated_by_id TEXT,
    activated_at    TEXT,
    retired_by      TEXT,
    retired_by_id   TEXT,
    retired_at      TEXT,
    UNIQUE (ident, version)
);
""")


class SecondPersonNeeded(versions.VersionStateError):
    """A product version is made active by another person than the one who made it."""


class ManifestRefused(ValueError):
    """A product version whose manifest does not hold (`problems`: every one)."""

    def __init__(self, problems: list[Said]) -> None:
        super().__init__("the product cannot be made active: " + "; ".join(problems))
        self.problems = problems


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


_REF = rf"^[^{versions.AT}\s]+{versions.AT}[1-9][0-9]*$"


class Section(_Model):
    clause: str
    page: int | None = None
    title: str | None = None


class ConditionDocument(_Model):
    kind: Literal["general", "special", "supplementary", "clause"]
    title: str
    valid_from: date
    valid_to: date | None = None
    sections: tuple[Section, ...] = ()
    references: tuple[str, ...] = ()


class Citation(_Model):
    document: str = Field(pattern=_REF)
    page: int | None = None
    clause: str | None = None
    quote: str | None = None


class Row(_Model):
    when: dict[str, dict[str, Any]] = Field(default_factory=dict)
    then: dict[str, Any]


class Table(_Model):
    hit: Literal["first", "collect"] = "first"
    rows: tuple[Row, ...] = Field(min_length=1)


class Rule(_Model):
    catalogue: str
    kind: Literal["eligibility", "exclusion", "requirement", "sublimit", "deductible", "premium_factor", "valuation",
                  "obligation"]
    title: str
    level: str
    modules: tuple[str, ...] = ()  # empty: every module of the product
    facts: tuple[str, ...]
    table: Table
    source: Citation
    applies_at: tuple[Literal["quote", "binding", "claim"], ...] = ("quote",)
    origin: dict[str, Any] = Field(default_factory=lambda: {"kind": "manual"})


class Module(_Model):
    code: str
    name: str
    kind: Literal["base", "extension"]
    requires: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()


class Product(_Model):
    name: str
    catalogue: str
    modules: tuple[Module, ...] = Field(min_length=1)
    documents: tuple[str, ...] = ()
    rules: tuple[str, ...] = ()
    tariff: str | None = None


class FactorRow(_Model):
    when: dict[str, Any] = Field(default_factory=dict)  # {op: value}; empty: every value
    factor: Decimal


class Factor(_Model):
    """A multiplier read from a fact the unit sees or an outcome of the rules; through `table` (the first row whose
    comparison holds), or, for an outcome without one, the outcome's value itself."""

    title: str
    fact: str | None = None
    outcome: str | None = None
    table: tuple[FactorRow, ...] = ()

    @model_validator(mode="after")
    def _one_source(self) -> Factor:
        if (self.fact is None) == (self.outcome is None):
            raise ValueError("a factor reads a fact or an outcome, one of them")
        if self.fact is not None and not self.table:
            raise ValueError("a factor read from a fact maps it through a table")
        return self


class TariffModule(_Model):
    level: str
    basis: str  # the money fact the rate applies to (a sum insured)
    rate: PerMille
    minimum: Money | None = None
    factors: tuple[str, ...] = ()
    # D-c5: the units it prices, by the facts they see ({fact: {op: value}}, the rules' comparisons); empty: every unit
    # of its level with the basis
    only: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _known_comparisons(self) -> TariffModule:
        if unknown := sorted({op for condition in self.only.values() for op in condition
                              if op not in OPS or op in ("present", "absent")}):
            raise ValueError(f"a module prices its units by comparisons, not by {', '.join(unknown)}")
        return self


class Tariff(_Model):
    title: str | None = None  # D-c6: how it reads to a person
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    valid: Validity
    line_rounding: Rounding
    total_rounding: Rounding
    modules: dict[str, TariffModule]
    factors: dict[str, Factor] = Field(default_factory=dict)
    total_factors: tuple[str, ...] = ()
    policy_minimum: Money | None = None

    @model_validator(mode="after")
    def _known_factors(self) -> Tariff:
        named = [f for m in self.modules.values() for f in m.factors] + list(self.total_factors)
        if unknown := sorted({f for f in named if f not in self.factors}):
            raise ValueError(f"the tariff names factors it does not define: {', '.join(unknown)}")
        return self


_MODELS: dict[str, type[_Model]] = {"document": ConditionDocument, "rule": Rule, "product": Product, "tariff": Tariff}
_VERSIONS = {kind: versions.VersionTable(table, "ident") for kind, table in _TABLES.items()}


def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"no kind {kind!r}: one of {', '.join(KINDS)}")
    return kind


def _content_name(kind: str, content: _Model) -> str:
    return str(getattr(content, "name", None) or getattr(content, "title", ""))


def add(kind: str, ident: str, content: dict[str, Any], *, actor: identity.Who) -> dict[str, Any]:
    """A draft: the thing's next version (the first one for a new identifier). A content that does not fit its form is
    a `ValidationError`."""
    with store.connect() as c:
        store.begin_immediate(c)
        version = add_in(c, kind, ident, content, actor=actor)
    return get(kind, ident, version)


def add_in(c: Any, kind: str, ident: str, content: dict[str, Any], *, actor: identity.Who) -> int:
    """D-c7e: `add` inside the caller's write transaction (a draft made with the decision that made it); its version."""
    model = _MODELS[_kind(kind)].model_validate(content)
    text = json.dumps(model.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    table = _TABLES[kind]
    latest = c.execute(f"SELECT MAX(version) FROM {table} WHERE ident=?", (ident,)).fetchone()[0]  # noqa: S608 - own table name
    version = int(latest or 0) + 1
    c.execute(f"INSERT INTO {table}(ident, version, state, name, content, fingerprint, made_by, made_by_id, made_at)"  # noqa: S608
              " VALUES (?,?,?,?,?,?,?,?,?)",
              (ident, version, versions.DRAFT, _content_name(kind, model), text,
               hashlib.sha256(text.encode("utf-8")).hexdigest(), identity.name_of(actor), identity.id_of(actor), _now()))
    return version


def _view(row: Any) -> dict[str, Any]:
    return {"ident": row["ident"], "version": row["version"], "state": row["state"], "name": row["name"],
            "content": json.loads(row["content"]), "fingerprint": row["fingerprint"], "made_by": row["made_by"],
            "made_by_id": row["made_by_id"], "made_at": row["made_at"], "activated_by": row["activated_by"],
            "activated_at": row["activated_at"], "retired_by": row["retired_by"], "retired_at": row["retired_at"],
            "ref": versions.ref(row["ident"], row["version"])}


def get(kind: str, ident: str, version: int) -> dict[str, Any]:
    with store.connect() as c:
        return _view(_VERSIONS[_kind(kind)].row(c, ident, version))


def latest(kind: str, ident: str) -> dict[str, Any] | None:
    """D-c5: a thing's newest version, whatever its state; None when it has none."""
    with store.connect() as c:
        row = c.execute(f"SELECT * FROM {_TABLES[_kind(kind)]} WHERE ident=? ORDER BY version DESC LIMIT 1",  # noqa: S608
                        (ident,)).fetchone()
    return _view(row) if row is not None else None


def resolve(kind: str, reference: str) -> dict[str, Any]:
    """The version a reference names (`<id>@<n>`, whatever its state now; `<id>`: the active one)."""
    with store.connect() as c:
        row = _VERSIONS[_kind(kind)].at(c, reference)
    if row is None:
        raise versions.VersionNotFound(f"{kind} {reference}: no active version")
    return _view(row)


def listing(kind: str) -> list[dict[str, Any]]:
    """Every thing of the kind, newest first, each with its versions and its active one."""
    with store.connect() as c:
        rows = c.execute(f"SELECT * FROM {_TABLES[_kind(kind)]} ORDER BY id DESC").fetchall()  # noqa: S608
    return _VERSIONS[kind].grouped(rows, lambda r: {"ident": r["ident"], "name": r["name"]}, _view)


def activate(kind: str, ident: str, version: int, *, actor: identity.Who) -> dict[str, Any]:
    """The version made active (the active one before it is superseded). A rule's own checks against its catalogue run
    first; a product's manifest too, and it is made active only by another person than its maker."""
    with store.connect() as c:
        store.begin_immediate(c)
        row = _VERSIONS[_kind(kind)].row(c, ident, version)
        if kind == "rule" and (problems := rule_problems(Rule.model_validate(json.loads(row["content"])))):
            raise ManifestRefused(problems)
        if kind == "product":
            if (row["made_by_id"] or row["made_by"]) == (identity.id_of(actor) or identity.name_of(actor)):
                raise explained(SecondPersonNeeded, "a product version is made active by another person than its maker")
            if problems := _manifest_problems(c, Product.model_validate(json.loads(row["content"]))):
                raise ManifestRefused(problems)
        _VERSIONS[kind].activate(c, ident, version, actor=actor)
    return get(kind, ident, version)


def overview() -> dict[str, Any]:
    """D-c6: every product, condition document, rule and tariff with its versions (a draft with what keeps it from
    being made active, `problems`: sentences in the service's form), and the fact catalogues their rules read."""
    from jav.app import examples

    found: dict[str, list[dict[str, Any]]] = {}
    for kind in KINDS:
        things = listing(kind)
        for thing in things:
            # 231 (U0): a thing the examples' machine made every version of is a process's example material
            thing["example"] = all(examples.is_example(v["made_by_id"]) for v in thing["versions"])
            for v in thing["versions"]:
                if v["state"] == versions.DRAFT:
                    v["problems"] = [said_fields(p) for p in problems_of(kind, v["content"])]
        found[kind] = things
    catalogues: dict[str, Any] = {}
    for cid in sorted({v["content"]["catalogue"] for kind in ("rule", "product") for t in found[kind] for v in t["versions"]}):
        try:
            catalogues[cid] = facts.catalogue(cid).model_dump(mode="json")
        except FileNotFoundError:
            continue  # a draft naming a catalogue that is not there says so in its problems
    return {"products": found["product"], "documents": found["document"], "rules": found["rule"],
            "tariffs": found["tariff"], "catalogues": catalogues}


def made_by_ids_in(c: Any, kind: str, ident: str) -> set[str | None]:
    """231 (stage U, U0): who made each version of a thing (their stable ids)."""
    return {r[0] for r in c.execute(f"SELECT made_by_id FROM {_TABLES[_kind(kind)]} WHERE ident=?", (ident,))}  # noqa: S608


def remove_in(c: Any, kind: str, ident: str) -> int:
    """231 (U0): every version of a thing taken out of the store, inside the caller's write transaction; only for a
    process's example material that nothing keeps (`jav/app/examples.py` checks); the versions removed."""
    return c.execute(f"DELETE FROM {_TABLES[_kind(kind)]} WHERE ident=?", (ident,)).rowcount  # noqa: S608 - own table name


def retire(kind: str, ident: str, *, actor: identity.Who) -> dict[str, Any]:
    with store.connect() as c:
        store.begin_immediate(c)
        n = _VERSIONS[_kind(kind)].retire(c, ident, actor=actor)
    return get(kind, ident, n)


def _thing(kind: str, ref: str) -> Said:
    """A thing a problem is about, as a person reads it before the problem (D-c6)."""
    if kind == "rule":
        return said("rule {{ref}}", ref=ref)
    if kind == "document":
        return said("document {{ref}}", ref=ref)
    if kind == "tariff":
        return said("tariff {{ref}}", ref=ref)
    return said("product {{ref}}", ref=ref)


def rule_problems(rule: Rule, documents: dict[str, ConditionDocument] | None = None) -> list[Said]:
    """What is wrong with a rule against its catalogue (and, with `documents`, against the product's documents); each a
    sentence in the interface's language (D-c6)."""
    try:
        cat = facts.catalogue(rule.catalogue)
    except FileNotFoundError:
        return [said("no fact catalogue {{catalogue}}", catalogue=rule.catalogue)]
    problems: list[Said] = []
    if rule.level not in cat.levels:
        return [said("no level {{level}} in the catalogue {{catalogue}}", level=rule.level, catalogue=cat.id)]
    rank = cat.levels.index(rule.level)
    for name in rule.facts:
        d = cat.facts.get(name)
        if d is None:
            problems.append(said("reads {{fact}}, which the catalogue {{catalogue}} does not have", fact=name, catalogue=cat.id))
        elif cat.levels.index(d.level) > rank:
            problems.append(said("reads {{fact}} of the level {{fact_level}}, below its level {{level}}", fact=name,
                                 fact_level=d.level, level=rule.level))
    for n, row in enumerate(rule.table.rows, 1):
        at = said("row {{row}}", row=n)
        for name, condition in row.when.items():
            if name not in rule.facts:
                problems.append(said("compares {{fact}}, which it does not read", within=at, fact=name))
                continue
            d = cat.facts.get(name)
            for op, value in condition.items():
                if op not in OPS:
                    problems.append(said("no comparison {{op}}", within=at, op=op))
                elif d is not None and op not in ("present", "absent"):
                    values = value if op in ("in", "not_in", "between") else [value]
                    if op == "between" and (not isinstance(values, list) or len(values) != 2):
                        problems.append(said("{{op}} takes two values", within=at, op=op))
                        continue
                    if not isinstance(values, list):
                        problems.append(said("{{op}} takes a list", within=at, op=op))
                        continue
                    for v in values:
                        try:
                            facts.typed_value(name, d, v)
                        except facts.FactError as exc:
                            problems.append(said_from(exc, within=at))
        for name, value in row.then.items():
            o = cat.outcomes.get(name)
            if o is None:
                problems.append(said("gives {{outcome}}, which the catalogue {{catalogue}} does not have", within=at,
                                     outcome=name, catalogue=cat.id))
                continue
            try:
                facts.typed_value(name, o, value)
            except facts.FactError as exc:
                problems.append(said_from(exc, within=at))
    if documents is not None:
        doc = documents.get(rule.source.document)
        if doc is None:
            problems.append(said("cites {{document}}, which the product does not name", document=rule.source.document))
        elif rule.source.clause is not None and rule.source.clause not in {s.clause for s in doc.sections}:
            problems.append(said("cites clause {{clause}}, which {{document}} does not have", clause=rule.source.clause,
                                 document=rule.source.document))
    return problems


def _manifest_problems(c: Any, product: Product) -> list[Said]:
    problems: list[Said] = []
    documents: dict[str, ConditionDocument] = {}
    for ref in product.documents:
        found = _referenced(c, "document", ref, problems)
        if found is not None:
            documents[ref] = ConditionDocument.model_validate(json.loads(found["content"]))
    codes = {m.code for m in product.modules}
    if product.tariff is not None:  # D-c3: the tariff it is priced by is there (a case keeps its version at start)
        with_versions = c.execute("SELECT COUNT(*) FROM tariffs WHERE ident=? AND state != ?", (product.tariff, versions.DRAFT)).fetchone()[0]
        if not with_versions:
            problems.append(said("no version that is not a draft", within=_thing("tariff", product.tariff)))
    for m in product.modules:
        problems += [said("module {{module}} requires {{required}}, which the product does not have", module=m.code, required=r)
                     for r in m.requires if r not in codes]
    for ref in product.rules:
        found = _referenced(c, "rule", ref, problems)
        if found is None:
            continue
        rule = Rule.model_validate(json.loads(found["content"]))
        at = _thing("rule", ref)
        if rule.catalogue != product.catalogue:
            problems.append(said("reads the catalogue {{catalogue}}, not the product's {{product_catalogue}}", within=at,
                                 catalogue=rule.catalogue, product_catalogue=product.catalogue))
        problems += [said("module {{module}} is not the product's", within=at, module=m) for m in rule.modules if m not in codes]
        problems += [inside(at, p) for p in rule_problems(rule, documents)]
    return problems


def _referenced(c: Any, kind: str, ref: str, problems: list[Said]) -> Any:
    """The version a manifest names; a problem when it is not there or still a draft."""
    ident, n = versions.split(ref)
    if n is None:
        problems.append(said("a manifest names an exact version", within=_thing(kind, ref)))
        return None
    try:
        row = _VERSIONS[kind].row(c, ident, n)
    except versions.VersionNotFound:
        problems.append(said("no such version", within=_thing(kind, ref)))
        return None
    if row["state"] == versions.DRAFT:
        problems.append(said("still a draft", within=_thing(kind, ref)))
        return None
    return row


def problems_of(kind: str, content: dict[str, Any]) -> list[Said]:
    """D-c6: what keeps a draft from being made active now: a rule's own checks, a product's manifest; none for a
    document or a tariff (its form is checked when it is added)."""
    if kind == "rule":
        return rule_problems(Rule.model_validate(content))
    if kind == "product":
        with store.connect() as c:
            return _manifest_problems(c, Product.model_validate(content))
    return []


@dataclass(frozen=True)
class Resolved:
    ref: str
    content: Any


@dataclass(frozen=True)
class ProductAt:
    """A product version with its documents and rules as the manifest names them."""

    ref: str
    product: Product
    documents: tuple[Resolved, ...]
    rules: tuple[Resolved, ...]


def product_at(reference: str) -> ProductAt:
    found = resolve("product", reference)
    product = Product.model_validate(found["content"])
    return ProductAt(found["ref"], product,
                     tuple(Resolved(r, ConditionDocument.model_validate(resolve("document", r)["content"])) for r in product.documents),
                     tuple(Resolved(r, Rule.model_validate(resolve("rule", r)["content"])) for r in product.rules))


def kept(value: str, kind: str = "product") -> str:
    """A case keeps the version of a product (or a tariff, ...) active at its start (`<id>@<version>`)."""
    with store.connect() as c:
        return _VERSIONS[_kind(kind)].kept(c, value)


def named(value: str, kind: str = "product") -> dict[str, Any]:
    """How a product (or a tariff, ...) a case keeps reads to a person."""
    try:
        found = resolve(kind, value)
    except (versions.VersionNotFound, ValidationError):
        return {"name": value, "version": None}
    return {"name": found["name"] or value, "version": versions.split(value)[1]}


def keeper(kind: str) -> capabilities.AtStart:
    """D-c4: how a capability's parameter naming a product, a tariff, ... keeps the version of a case's start
    (`Capability.at_start`)."""
    _kind(kind)
    return capabilities.AtStart(lambda value: kept(value, kind), lambda value: named(value, kind))


def choices(kind: str) -> Callable[[], list[tuple[str, str]]]:
    """231 (stage U, U0): the values a parameter naming a product, a tariff, ... may take (`Capability.choices`): the
    things of the kind with an active version, each with its name, so a process's own value is picked, not typed."""
    _kind(kind)
    return lambda: [(t["ident"], t["name"] or t["ident"]) for t in listing(kind) if t["active"] is not None]
