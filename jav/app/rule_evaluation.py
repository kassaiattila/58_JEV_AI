"""A product's rules evaluated on a case's checked input (231, stage D, D-c2).

Plain-language summary: each rule of the product (`jav/app/product_rules.py`) that applies at quoting, to a requested
module, is evaluated on every unit of its level; a unit sees its own facts and its ancestors' (an asset group sees its
site's flood zone). A decision table gives the first matching row's outcomes (`hit: first`) or every matching row's
(`collect`). A comparison with a missing fact is not a guess: a row that cannot be decided makes the rule's outcome
unknown and names the fact (a row that is false whatever the missing fact is skipped). The outcomes of the rules on a
unit combine by the catalogue's rule (`jav/app/facts.py`): the worst verdict, the largest or smallest value, the union
of codes, and exactly one value where the catalogue says `one` (two different ones are a blocker). The assessment's
verdict is the worst of its units'. Every rule's evaluation is a row of the decision trace (point `rules.outcome`):
its inputs are the rule's table and the facts it read, typed, and its replay gives the same outcome.

- `evaluate(rules, checked, modules)`: the `Evaluation` (per unit: each rule's outcome and the combined outcomes; the
  verdict, the missing facts, the blockers).
- `trace_in(c, case_id, evaluation)`: its trace rows, in the caller's write transaction.

Layer: application; pure apart from `trace_in`; it names no process and no business.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from jav.app import facts
from jav.app.product_rules import Resolved, Rule
from jav.core import trace
from jav.core.measures import Money, Quantity, Rate

__all__ = ["POINT", "UNKNOWN", "Evaluation", "RuleOutcome", "UnitOutcome", "evaluate", "evaluate_rule", "from_json", "holds",
           "plain", "to_json", "trace_in"]

POINT = "rules.outcome"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class RuleOutcome:
    rule: str
    matched: tuple[int, ...] = ()  # the rows that matched (1-based)
    outcomes: dict[str, Any] = field(default_factory=dict)
    missing: tuple[str, ...] = ()  # the facts that kept it undecided


@dataclass(frozen=True)
class UnitOutcome:
    unit_id: str
    level: str
    rules: dict[str, RuleOutcome]
    combined: dict[str, Any]
    seen: dict[str, Any]  # the facts the unit sees: its own and its ancestors'


@dataclass(frozen=True)
class Evaluation:
    catalogue: str
    product: str
    units: dict[str, UnitOutcome]
    verdict: str | None
    missing: tuple[tuple[str, str], ...]
    blockers: tuple[str, ...]
    rules: dict[str, Rule] = field(default_factory=dict)  # the rules evaluated, by reference


def _number(value: Any) -> Any:
    """What a comparison compares: an amount, a quantity's value, a rate's value, a number, a day."""
    if isinstance(value, Money):
        return value.amount
    if isinstance(value, Quantity):
        return value.value
    if isinstance(value, Rate):
        return value.value
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return value


def holds(op: str, have: Any, want: Any) -> bool:
    """Whether a comparison holds between a typed value and the typed value(s) it is compared with."""
    if op == "eq":
        return have == want
    if op == "ne":
        return have != want
    if op == "in":
        return have in want
    if op == "not_in":
        return have not in want
    a = _number(have)
    if op == "between":
        lo, hi = (_number(w) for w in want)
        return lo <= a <= hi
    b = _number(want)
    return {"lt": a < b, "lte": a <= b, "gt": a > b, "gte": a >= b}[op]


def _typed_values(cat: facts.Catalogue, name: str, op: str, value: Any) -> Any:
    d = cat.facts[name]
    if op in ("in", "not_in"):
        return [facts.typed_value(name, d, v) for v in value]
    if op == "between":
        return [facts.typed_value(name, d, v) for v in value]
    return facts.typed_value(name, d, value)


def evaluate_rule(rule: Rule, ref: str, seen: dict[str, Any], cat: facts.Catalogue) -> RuleOutcome:
    """One rule on the facts a unit sees: its matched rows and outcomes, or the facts that keep it undecided."""
    matched: list[int] = []
    outcomes: dict[str, Any] = {}
    for n, row in enumerate(rule.table.rows, 1):
        undecided: list[str] = []
        fits = True
        for name, condition in row.when.items():
            for op, value in condition.items():
                if op in ("present", "absent"):
                    wanted = (op == "present") == bool(value)  # {"present": true} or {"absent": false}: it is there
                    if (name in seen) != wanted:
                        fits = False
                    continue
                if name not in seen:
                    undecided.append(name)
                    continue
                if not holds(op, seen[name], _typed_values(cat, name, op, value)):
                    fits = False
        if not fits:
            continue  # false whatever the missing facts are
        if undecided:
            return RuleOutcome(ref, tuple(matched), outcomes, tuple(dict.fromkeys(undecided)))
        matched.append(n)
        for name, value in row.then.items():
            got = facts.typed_value(name, cat.outcomes[name], value)
            if rule.table.hit == "collect":
                outcomes.setdefault(name, []).append(got)
            else:
                outcomes.setdefault(name, got)
        if rule.table.hit == "first":
            break
    if rule.table.hit == "collect":  # several rows' values of one outcome combine as the catalogue says
        outcomes = {name: _combine(cat.outcomes[name], [(ref, v) for v in values], [])[0] for name, values in outcomes.items()}
    return RuleOutcome(ref, tuple(matched), outcomes)


def _combine(o: facts.OutcomeDef, given: list[tuple[str, Any]], clashes: list[str]) -> tuple[Any, bool]:
    """The combined value of an outcome given by several rules (`given`: (rule, value)); a clash of `one` is noted."""
    values = [v for _, v in given]
    if o.combine == "worst":
        order = list(o.options or ())
        return max(values, key=order.index), True
    if o.combine == "max":
        return max(values, key=_number), True
    if o.combine == "min":
        return min(values, key=_number), True
    if o.combine == "union":
        out: list[str] = []
        for v in values:
            out += [c for c in v if c not in out]
        return tuple(out), True
    distinct = list(dict.fromkeys(json.dumps(plain(v), sort_keys=True) for v in values))
    if len(distinct) > 1:
        clashes.append(", ".join(f"{_shown(v)} ({r})" for r, v in given))
        return None, False
    return values[0], True


def plain(value: Any) -> Any:
    """A typed value as JSON (an amount as text, a day as ISO text)."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    return value


def _shown(value: Any) -> str:
    shown = plain(value)
    return json.dumps(shown) if isinstance(shown, (dict, list)) else str(shown)


def evaluate(rules: list[Resolved], checked: facts.CheckedInput, *, modules: tuple[str, ...],
             at: str = "quote") -> Evaluation:
    """The rules that apply at `at` to a requested module, on every unit of their level, combined."""
    cat = facts.catalogue(checked.catalogue)
    by_id = {u.unit_id: u for u in checked.units}
    units: dict[str, UnitOutcome] = {}
    missing: list[tuple[str, str]] = []
    blockers: list[str] = []
    verdicts: list[str] = []
    for unit in checked.units:
        seen: dict[str, Any] = {}
        node = unit
        while node is not None:  # its own facts win over an ancestor's of the same name
            seen = {**node.facts, **seen}
            node = by_id.get(node.parent_id) if node.parent_id else None
        outcomes: dict[str, RuleOutcome] = {}
        for item in rules:
            rule = item.content
            if rule.level != unit.level or at not in rule.applies_at or (rule.modules and not set(rule.modules) & set(modules)):
                continue
            outcomes[item.ref] = evaluate_rule(rule, item.ref, seen, cat)
        given: dict[str, list[tuple[str, Any]]] = {}
        for ref, result in outcomes.items():
            for name, value in result.outcomes.items():
                given.setdefault(name, []).append((ref, value))
            if result.missing:
                if "verdict" in cat.outcomes:
                    given.setdefault("verdict", []).append((ref, UNKNOWN))
                missing += [(unit.unit_id, f) for f in result.missing]
        combined: dict[str, Any] = {}
        for name, values in given.items():
            clashes: list[str] = []
            value, ok = _combine(cat.outcomes[name], values, clashes)
            if ok:
                combined[name] = value
            blockers += [f"{unit.unit_id}: {name} given twice: {c}" for c in clashes]
        if "verdict" in combined:
            verdicts.append(combined["verdict"])
        units[unit.unit_id] = UnitOutcome(unit.unit_id, unit.level, outcomes, combined, seen)
    verdict_def = cat.outcomes.get("verdict")
    verdict = max(verdicts, key=list(verdict_def.options or ()).index) if verdicts and verdict_def else None
    return Evaluation(cat.id, checked.product, units, verdict, tuple(dict.fromkeys(missing)), tuple(blockers),
                      {item.ref: item.content for item in rules})


def to_json(evaluation: Evaluation) -> dict[str, Any]:
    """D-d3: an evaluation as JSON (a step's record), every value in its plain form; `from_json` types it again."""
    def outcome(r: RuleOutcome) -> dict[str, Any]:
        return {"matched": list(r.matched), "outcomes": {k: plain(v) for k, v in r.outcomes.items()}, "missing": list(r.missing)}

    return {"catalogue": evaluation.catalogue, "product": evaluation.product, "verdict": evaluation.verdict,
            "missing": [list(m) for m in evaluation.missing], "blockers": list(evaluation.blockers),
            "rules": {ref: rule.model_dump(mode="json") for ref, rule in evaluation.rules.items()},
            "units": {uid: {"level": u.level, "rules": {ref: outcome(r) for ref, r in u.rules.items()},
                            "combined": {k: plain(v) for k, v in u.combined.items()},
                            "seen": {k: plain(v) for k, v in u.seen.items()}} for uid, u in evaluation.units.items()}}


def from_json(data: dict[str, Any]) -> Evaluation:
    """D-d3: an evaluation from its JSON (`to_json`), its values typed again by its catalogue."""
    cat = facts.catalogue(data["catalogue"])

    def outcomes(values: dict[str, Any]) -> dict[str, Any]:
        return {k: facts.typed_value(k, cat.outcomes[k], v) for k, v in values.items()}

    units = {uid: UnitOutcome(uid, u["level"],
                              {ref: RuleOutcome(ref, tuple(r["matched"]), outcomes(r["outcomes"]), tuple(r["missing"]))
                               for ref, r in u["rules"].items()},
                              outcomes(u["combined"]), {k: facts.typed_value(k, cat.facts[k], v) for k, v in u["seen"].items()})
             for uid, u in data["units"].items()}
    return Evaluation(data["catalogue"], data["product"], units, data["verdict"], tuple(tuple(m) for m in data["missing"]),
                      tuple(data["blockers"]), {ref: Rule.model_validate(r) for ref, r in data["rules"].items()})


def _replay(inputs: Any) -> Any:
    """The trace point's rule: the stored rule's table on the stored facts, again."""
    cat = facts.catalogue(inputs["catalogue"])
    seen = {name: facts.typed_value(name, cat.facts[name], value) for name, value in inputs["facts"].items()}
    result = evaluate_rule(Rule.model_validate(inputs["table_rule"]), inputs["rule"], seen, cat)
    return _outcome_json(result)


def _outcome_json(result: RuleOutcome) -> dict[str, Any]:
    return {"matched": list(result.matched), "outcomes": {k: plain(v) for k, v in result.outcomes.items()},
            "missing": list(result.missing)}


trace.register(trace.Point(
    POINT, owner=__name__, files=("facts_*.json",), rule=_replay,
    what="a product rule's outcome on one assessed unit: the matched rows of its decision table, the outcomes they give "
         "and the facts that kept it undecided",
    not_for="the combination of several rules' outcomes or a person's decision on them"))


def trace_in(c: Any, case_id: str, evaluation: Evaluation) -> list[int]:
    """One trace row per rule and unit, in the caller's write transaction; the row ids."""
    ids = []
    for unit in evaluation.units.values():
        for ref, result in unit.rules.items():
            rule = evaluation.rules[ref]
            read = rule.facts
            inputs = {"rule": ref, "catalogue": evaluation.catalogue, "product": evaluation.product,
                      "table_rule": rule.model_dump(mode="json"),
                      "facts": {name: plain(unit.seen[name]) for name in read if name in unit.seen}}
            ids.append(trace.record_in(c, POINT, subject=("assessed_unit", f"{case_id}:{unit.unit_id}"), inputs=inputs,
                                       outcome=_outcome_json(result),
                                       keys={f"facts_{evaluation.catalogue}.json": sorted(read)}, case_id=case_id))
    return ids
