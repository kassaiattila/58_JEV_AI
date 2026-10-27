"""A premium from a versioned tariff, step by step (231, stage D, D-c3; the reassessment after D0 of 2026-10-26, T14).

Plain-language summary: a tariff (`product_rules.Tariff`, a versioned thing kept by a case as it started) prices each
requested module on the units of its level (D-c5: only those whose facts fit the module's `only`, so a burglary cover
does not price a building), in a fixed order: the basis (a sum insured) times the module's rate per
thousand; its factors in their order, each read from a fact the unit sees or an outcome of the rules on it or its
ancestors, through the factor's table; rounded once per line; the module's minimum; the modules summed in the tariff's
one currency; the total factors (the payment frequency, read from the top unit); rounded once more; the policy's
minimum. Every step is itemised. A missing factor, a value no row of a factor's table takes, a cover start the tariff is
not in force on, or an amount of another currency gives no total but a blocker: never a default. The calculation is a
row of the decision trace (point `rating.premium`, the tariff inline), and its replay gives the same outcome.

- `calculate(tariff, tariff_ref, checked, evaluation, modules)`: the `Calculation`.
- `trace_in(c, case_id, calculation)`: its trace row, in the caller's write transaction.

Layer: application; pure apart from `trace_in`; it names no process and no business.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from jav.app import facts, rule_evaluation
from jav.app.product_rules import Factor, Tariff
from jav.core import trace
from jav.core.measures import Money

__all__ = ["POINT", "Calculation", "Line", "Step", "calculate", "trace_in"]

POINT = "rating.premium"


@dataclass(frozen=True)
class Step:
    name: str
    factor: Decimal
    after: Money


@dataclass(frozen=True)
class Line:
    unit_id: str
    module: str
    basis: Money
    base: Money
    steps: tuple[Step, ...]
    amount: Money


@dataclass(frozen=True)
class Calculation:
    tariff: str
    catalogue: str
    product: str
    cover_start: date
    modules_asked: tuple[str, ...]
    lines: tuple[Line, ...]
    modules: dict[str, dict[str, Any]]
    subtotal: Money | None
    total_steps: tuple[Step, ...]
    total: Money | None
    policy_minimum_applied: bool
    blockers: tuple[str, ...]
    inputs: dict[str, Any] = field(default_factory=dict, compare=False)  # what it was computed from (the trace's inputs)


@dataclass(frozen=True)
class _Unit:
    unit_id: str
    level: str
    seen: dict[str, Any]  # facts: its own and its ancestors'
    outcomes: dict[str, Any]  # combined outcomes: its own and its ancestors'


def _factor(cat: facts.Catalogue, name: str, f: Factor, unit: _Unit) -> tuple[Decimal | None, str | None]:
    """A factor's value for a unit, or why there is none."""
    if f.fact is not None:
        if f.fact not in unit.seen:
            return None, f"{unit.unit_id}: no {name} factor: the fact {f.fact} is missing"
        value, d = unit.seen[f.fact], cat.facts[f.fact]
    else:
        if f.outcome not in unit.outcomes:
            return None, f"{unit.unit_id}: no {name} factor: the outcome {f.outcome} is missing"
        value, d = unit.outcomes[f.outcome], cat.outcomes[f.outcome]  # type: ignore[index]
        if not f.table:
            return Decimal(str(value)), None
    for row in f.table:
        fits = True
        for op, want in row.when.items():
            if not rule_evaluation.holds(op, value, _typed(cat, name, d, op, want)):  # the same comparisons as the rules
                fits = False
        if fits:
            return row.factor, None
    return None, f"{unit.unit_id}: no row of the {name} factor takes {value}"


def _typed(cat: facts.Catalogue, name: str, d: Any, op: str, want: Any) -> Any:
    return facts.compared_value(name, d, op, want)


def _priced(cat: facts.Catalogue, code: str, only: dict[str, dict[str, Any]], unit: _Unit) -> tuple[bool, str | None]:
    """Whether a module prices a unit (its `only`), or why that cannot be told."""
    for name, condition in only.items():
        if name not in unit.seen:
            return False, f"{unit.unit_id}: the module {code} prices by {name}, which is missing"
        for op, want in condition.items():
            if not rule_evaluation.holds(op, unit.seen[name], _typed(cat, name, cat.facts[name], op, want)):
                return False, None
    return True, None


def _compute(tariff: Tariff, tariff_ref: str, cat: facts.Catalogue, product: str, cover_start: date,
             modules: tuple[str, ...], units: list[_Unit], inputs: dict[str, Any]) -> Calculation:
    blockers: list[str] = []
    if not tariff.valid.covers(cover_start):
        blockers.append(f"the tariff is not in force on {cover_start.isoformat()}")
    lines: list[Line] = []
    totals: dict[str, dict[str, Any]] = {}
    for code in modules:
        module = tariff.modules.get(code)
        if module is None:
            blockers.append(f"the tariff does not price the module {code}")
            continue
        module_lines: list[Line] = []
        for unit in units:
            if unit.level != module.level or module.basis not in unit.seen:
                continue
            priced, why = _priced(cat, code, module.only, unit)
            if why:
                blockers.append(why)
            if not priced:
                continue
            basis = unit.seen[module.basis]
            if not isinstance(basis, Money) or basis.currency != tariff.currency:
                currency = basis.currency if isinstance(basis, Money) else "no currency"
                blockers.append(f"the tariff is in {tariff.currency}, the {module.basis} of {unit.unit_id} in {currency}")
                continue
            amount = base = module.rate.of(basis)
            steps: list[Step] = []
            missing = False
            for name in module.factors:
                value, why = _factor(cat, name, tariff.factors[name], unit)
                if value is None:
                    blockers.append(why or name)
                    missing = True
                    break
                amount = amount.times(value)
                steps.append(Step(name, value, amount))
            if missing:
                continue
            module_lines.append(Line(unit.unit_id, code, basis, base, tuple(steps), amount.rounded(tariff.line_rounding)))
        lines += module_lines
        summed = sum((line.amount for line in module_lines), Money(amount="0", currency=tariff.currency))
        applied = module.minimum is not None and summed < module.minimum
        totals[code] = {"lines": summed, "minimum_applied": applied, "total": module.minimum if applied else summed}
    subtotal = total = None
    total_steps: list[Step] = []
    applied = False
    if not blockers:
        subtotal = sum((t["total"] for t in totals.values()), Money(amount="0", currency=tariff.currency))
        amount = subtotal
        top = next(u for u in units if u.level == cat.levels[0])
        for name in tariff.total_factors:
            value, why = _factor(cat, name, tariff.factors[name], top)
            if value is None:
                blockers.append(why or name)
                break
            amount = amount.times(value)
            total_steps.append(Step(name, value, amount))
        if not blockers:
            total = amount.rounded(tariff.total_rounding)
            if tariff.policy_minimum is not None and total < tariff.policy_minimum:
                total, applied = tariff.policy_minimum, True
    return Calculation(tariff_ref, cat.id, product, cover_start, modules, tuple(lines), totals, subtotal, tuple(total_steps),
                       total if not blockers else None, applied, tuple(blockers), inputs)


def _plain(value: Any) -> Any:
    return rule_evaluation.plain(value)  # one JSON form for the trace


def calculate(tariff: Tariff, tariff_ref: str, checked: facts.CheckedInput, evaluation: rule_evaluation.Evaluation, *,
              modules: tuple[str, ...]) -> Calculation:
    """The premium of the requested modules for the checked input, with the rules' outcomes."""
    cat = facts.catalogue(checked.catalogue)
    by_id = {u.unit_id: u for u in checked.units}
    units: list[_Unit] = []
    for unit in checked.units:
        outcomes: dict[str, Any] = {}
        node = unit
        while node is not None:  # its own outcome wins over an ancestor's
            found = evaluation.units.get(node.unit_id)
            outcomes = {**(found.combined if found else {}), **outcomes}
            node = by_id.get(node.parent_id) if node.parent_id else None
        seen = evaluation.units[unit.unit_id].seen if unit.unit_id in evaluation.units else dict(unit.facts)
        units.append(_Unit(unit.unit_id, unit.level, seen, outcomes))
    inputs = {"tariff_ref": tariff_ref, "tariff": tariff.model_dump(mode="json"), "catalogue": cat.id,
              "product": checked.product, "cover_start": checked.cover_start.isoformat(), "modules": list(modules),
              "units": [{"unit_id": u.unit_id, "level": u.level, "seen": {k: _plain(v) for k, v in u.seen.items()},
                         "outcomes": {k: _plain(v) for k, v in u.outcomes.items()}} for u in units]}
    return _compute(tariff, tariff_ref, cat, checked.product, checked.cover_start, modules, units, inputs)


def _outcome(calc: Calculation) -> dict[str, Any]:
    return {"lines": [{"unit_id": line.unit_id, "module": line.module, "amount": _plain(line.amount)} for line in calc.lines],
            "total": _plain(calc.total) if calc.total is not None else None, "blockers": list(calc.blockers)}


def _replay(inputs: Any) -> Any:
    """The trace point's rule: the stored tariff on the stored facts and outcomes, again."""
    cat = facts.catalogue(inputs["catalogue"])
    units = [_Unit(u["unit_id"], u["level"],
                   {k: facts.typed_value(k, cat.facts[k], v) for k, v in u["seen"].items()},
                   {k: facts.typed_value(k, cat.outcomes[k], v) for k, v in u["outcomes"].items()}) for u in inputs["units"]]
    calc = _compute(Tariff.model_validate(inputs["tariff"]), inputs["tariff_ref"], cat, inputs["product"],
                    date.fromisoformat(inputs["cover_start"]), tuple(inputs["modules"]), units, inputs)
    return _outcome(calc)


trace.register(trace.Point(
    POINT, owner=__name__, files=("facts_*.json",), rule=_replay,
    what="a premium computed from a tariff: each module's lines (the basis times the rate, the factors in their order, "
         "rounded), the module minimums, the total factors, the rounding and the policy minimum, or what blocks it",
    not_for="the rules' outcomes it reads or a person's decision on the premium"))


def trace_in(c: Any, case_id: str, calc: Calculation) -> int:
    """The calculation's trace row, in the caller's write transaction; its id."""
    read = sorted({k for u in calc.inputs["units"] for k in u["seen"]})
    return trace.record_in(c, POINT, subject=("calculation", f"{case_id}:{calc.tariff}"), inputs=calc.inputs,
                           outcome=_outcome(calc), keys={f"facts_{calc.catalogue}.json": read}, case_id=case_id)
