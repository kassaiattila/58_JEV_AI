"""A frozen input's rules evaluated, and its premium computed, as steps of a case (231, stage D, D-d3).

Plain-language summary: once a person froze the checked input (`field_check@1`), the case evaluates the rules of the
product version the input names on it (`rule_evaluation@1`): each rule's outcome on each unit is a row of the decision
trace, and the evaluation - its verdict, the facts it missed, its blockers and every unit's outcomes - is kept as a
record that never changes. Then, usually after a person accepted the risk, the case computes the premium from the tariff
it kept at its start (`rating@1`): every line itemised, a trace row, and a record. Each record belongs to the input
version it was made from, so a rerun with the same input makes nothing new, and a new freeze (the check reopened)
makes a new record that the steps after it read. A premium a blocker stops is kept with its blockers and stops the step
with them: never a default. The cover modules evaluated and priced are the ones the input asks for (a fact of its top
unit, `requested_modules` by default); an input that does not say them has the rules of every module evaluated, names
the missing fact and is not priced.

- `EVALUATION` (`rule_evaluation@1`): params `from_step` (a field check), `modules_fact`; result: the record's version,
  the input version, the verdict, the missing facts, the blockers, the product and the modules.
- `RATING` (`rating@1`): params `from_step` (a rule evaluation), `tariff` (kept at its version at the start); result: the
  record's version, the total, the tariff.
- `record(case_id, step, version)`: a step's record as kept; `records(case_id, step)`: all of them, the newest first.
- D-f5: the elements `evaluation` and `calculation` (the latest record in full, every version in a line).

Layer: application; it names no process and no business (the product, its rules and its tariff are data).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from jav.app import capabilities, facts, package_release, product_rules, rating, rule_evaluation
from jav.core import store, versions
from jav.core.clock import utc_stamp as _now
from jav.core.measures import Money
from jav.core.process import kinds

__all__ = ["EVALUATION", "RATING", "EvaluationResult", "RatingResult", "record", "records", "register", "unit_names"]

EVALUATION_KIND, RATING_KIND = "evaluation", "rating"

store.register_schema("evaluation_records", """
-- 231 (stage D, D-d3): a case step's evaluation of the rules, or its premium, kept as it was made
CREATE TABLE IF NOT EXISTS evaluation_records (
    case_id       TEXT NOT NULL,
    step_id       TEXT NOT NULL,
    version       INTEGER NOT NULL,   -- the record's number within its step
    kind          TEXT NOT NULL,      -- evaluation | rating
    input_step    TEXT NOT NULL,      -- the step it was made from
    input_version INTEGER NOT NULL,   -- that step's result version it was made from
    content       TEXT NOT NULL,      -- JSON
    fingerprint   TEXT NOT NULL,
    trace_ids     TEXT NOT NULL,      -- JSON: its decision trace rows
    made_at       TEXT NOT NULL,
    PRIMARY KEY (case_id, step_id, version)
);
""")


class _Frozen(capabilities.Result):
    """What the evaluation expects of the step it reads: the frozen input's version."""

    version: int


class _Evaluated(capabilities.Result):
    """What the rating expects of the step it reads: the evaluation record's version."""

    version: int


class RuleEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    from_step: str = capabilities.step_ref(min_length=1, of="field_check", expects=_Frozen)
    modules_fact: str = Field("requested_modules", min_length=1, title="The fact naming the cover modules asked for")


class Rating(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    from_step: str = capabilities.step_ref(min_length=1, of="rule_evaluation", expects=_Evaluated)
    tariff: str = Field(min_length=1, title="Tariff")


class EvaluationResult(capabilities.Result):
    """The evaluation: its record's version, the frozen input's version, the verdict, what it missed, what blocks it."""

    version: int
    input_version: int
    verdict: str | None = None
    missing: list[dict[str, str]]
    blockers: list[str]
    product: str
    modules: list[str]


class RatingResult(capabilities.Result):
    """The premium: its record's version, the total and the tariff it was computed from."""

    version: int
    total: Money
    tariff: str


def _fingerprint(content: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _row(c: Any, case_id: str, step: str, *, input_version: int | None = None, version: int | None = None) -> Any:
    if version is not None:
        return c.execute("SELECT * FROM evaluation_records WHERE case_id=? AND step_id=? AND version=?",
                         (case_id, step, version)).fetchone()
    return c.execute("SELECT * FROM evaluation_records WHERE case_id=? AND step_id=? AND input_version=? ORDER BY version DESC",
                     (case_id, step, input_version)).fetchone()


def _keep(c: Any, case_id: str, step: str, kind: str, input_step: str, input_version: int, content: dict[str, Any],
          trace_ids: list[int]) -> int:
    n = (c.execute("SELECT MAX(version) FROM evaluation_records WHERE case_id=? AND step_id=?", (case_id, step)).fetchone()[0] or 0) + 1
    c.execute("INSERT INTO evaluation_records(case_id, step_id, version, kind, input_step, input_version, content, fingerprint,"
              " trace_ids, made_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
              (case_id, step, n, kind, input_step, input_version, json.dumps(content, ensure_ascii=False, default=str),
               _fingerprint(content), json.dumps(trace_ids), _now()))
    return n


def record(case_id: str, step: str, version: int) -> dict[str, Any]:
    """A step's record as kept: its kind, the step and version it was made from, its content (KeyError: none)."""
    with store.connect() as c:
        row = _row(c, case_id, step, version=version)
    if row is None:
        raise KeyError(f"{case_id} {step} record {version}")
    return {"version": row["version"], "kind": row["kind"], "input_step": row["input_step"], "input_version": row["input_version"],
            "content": json.loads(row["content"]), "fingerprint": row["fingerprint"], "made_at": row["made_at"]}


def records(case_id: str, step: str) -> list[dict[str, Any]]:
    """D-f5: every record of the step, the newest first."""
    with store.connect() as c:
        rows = c.execute("SELECT * FROM evaluation_records WHERE case_id=? AND step_id=? ORDER BY version DESC",
                         (case_id, step)).fetchall()
    return [{"version": r["version"], "kind": r["kind"], "input_step": r["input_step"], "input_version": r["input_version"],
             "content": json.loads(r["content"]), "made_at": r["made_at"]} for r in rows]


_NAMED = ("company_name", "site_address", "asset_group")  # the facts a person tells a unit by


def _units_of(content: dict[str, Any]) -> list[dict[str, Any]]:
    """An evaluation's units in their order, each with the facts a person tells it by: its own level's (a unit sees its
    ancestors' facts too, so a site would otherwise be named by its policyholder)."""
    cat = facts.catalogue(content["catalogue"])
    own = {k for k in _NAMED if k in cat.facts}
    return [{"unit_id": uid, "level": u["level"],
             "named": {k: u["seen"][k] for k in own if k in u["seen"] and cat.facts[k].level == u["level"]},
             "combined": u["combined"], "rules": u["rules"]} for uid, u in content["units"].items()]


def unit_names(case_id: str, step: str) -> dict[str, dict[str, Any]]:
    """D-f5: the latest evaluation's units by id, each with its level, the facts a person tells it by, and a coded one's
    catalogue label (`label`, English: the interface translates it)."""
    found = records(case_id, step)
    if not found:
        return {}
    labels = facts.catalogue(found[0]["content"]["catalogue"]).labels
    out = {}
    for u in _units_of(found[0]["content"]):
        code = next((v for v in u["named"].values() if isinstance(v, str) and v in labels), None)
        out[u["unit_id"]] = {"level": u["level"], "named": u["named"], **({"label": labels[code]} if code else {})}
    return out


def _evaluation_view(case_id: str, step: str | None, _shared: dict[str, Any]) -> dict[str, Any]:
    """D-f5: the evaluation element's data: the latest evaluation in full (the verdict, the modules, the missing facts,
    the blockers, each unit's outcomes and the rules that gave them), the catalogue and the rules' titles and citations,
    and every version (the checked input it was made from)."""
    found = records(case_id, str(step))
    versions = [{"version": r["version"], "input_version": r["input_version"], "made_at": r["made_at"],
                 "verdict": r["content"]["verdict"], "missing": len(r["content"]["missing_named"]),
                 "blockers": len(r["content"]["blockers"])} for r in found]
    if not found:
        return {"versions": [], "latest": None, "catalogue": None, "rules": {}}
    content = found[0]["content"]
    rules = {ref: {"title": r["title"], "kind": r["kind"], "source": r["source"]} for ref, r in content["rules"].items()}
    latest = {"version": found[0]["version"], "input_version": found[0]["input_version"], "verdict": content["verdict"],
              "modules": content["modules"], "modules_said": content.get("modules_said", True),
              "missing": content["missing_named"], "blockers": content["blockers"], "product": content["product"],
              "units": _units_of(content)}
    return {"versions": versions, "latest": latest, "catalogue": facts.catalogue(content["catalogue"]).model_dump(mode="json"),
            "rules": rules}


def _calculation_view(case_id: str, step: str | None, _shared: dict[str, Any]) -> dict[str, Any]:
    """D-f5: the calculation element's data: the latest premium in full (each line with its basis, base and factors,
    the modules' totals and minimums, the total's factors, the total, the policy minimum, the blockers), the tariff's
    title and its factors' titles, the product's module names, the units' names, and every version."""
    found = records(case_id, str(step))
    versions = [{"version": r["version"], "input_version": r["input_version"], "made_at": r["made_at"],
                 "total": r["content"]["total"], "blockers": len(r["content"]["blockers"])} for r in found]
    if not found:
        return {"versions": [], "latest": None}
    content = found[0]["content"]
    tariff = product_rules.resolve("tariff", content["tariff_ref"])["content"]
    evaluation = record(case_id, found[0]["input_step"], found[0]["input_version"])["content"]
    product = product_rules.product_at(evaluation["product"]).product
    return {"versions": versions,
            "latest": {"version": found[0]["version"], "evaluation_version": found[0]["input_version"], **content},
            "tariff": {"ref": content["tariff_ref"], "title": tariff.get("title"), "currency": tariff["currency"],
                       "factors": {name: f.get("title") for name, f in (tariff.get("factors") or {}).items()}},
            "modules": {m.code: m.name for m in product.modules},
            "units": {u["unit_id"]: {"level": u["level"], "named": u["named"]} for u in _units_of(evaluation)},
            "catalogue": facts.catalogue(evaluation["catalogue"]).model_dump(mode="json")}


def _checked(case_id: str, field_step: str, version: int) -> facts.CheckedInput:
    return facts.checked_input(package_release.own_version(case_id, version, step=field_step)["content"])


def _modules(checked: facts.CheckedInput, fact: str) -> tuple[tuple[str, ...], bool]:
    """The cover modules the input asks for (from its top unit's fact), and whether it says them."""
    top = next((u for u in checked.units if u.parent_id is None), None)
    if top is None or fact not in top.facts:
        return (), False
    value = top.facts[fact]
    return (tuple(value) if isinstance(value, (list, tuple)) else (str(value),)), True


def _unsaid(cat: facts.Catalogue, verdict: str | None) -> str | None:
    """The verdict of an input that does not say the modules it asks for: no better than unknown."""
    d = cat.outcomes.get("verdict")
    order = list(d.options or ()) if d is not None else []
    if rule_evaluation.UNKNOWN not in order:
        return verdict
    return max((v for v in (verdict, rule_evaluation.UNKNOWN) if v is not None), key=order.index)


def _summary(n: int, input_version: int, content: dict[str, Any]) -> dict[str, Any]:
    return {"version": n, "input_version": input_version, "verdict": content["verdict"], "missing": content["missing_named"],
            "blockers": content["blockers"], "product": content["product"], "modules": content["modules"]}


def _evaluate(ctx: Any, params: RuleEvaluation) -> kinds.StepOutcome:
    case_id = str(ctx.data["container"])
    frozen = capabilities.read_result(ctx, params, "from_step")
    input_version = int(frozen["version"])
    with store.connect() as c:
        kept = _row(c, case_id, ctx.step.id, input_version=input_version)
    if kept is not None:  # made from this input already: nothing new
        return kinds.Done(_summary(kept["version"], input_version, json.loads(kept["content"])))
    try:
        checked = _checked(case_id, params.from_step, input_version)
        at = product_rules.product_at(checked.product)
    except (KeyError, versions.VersionNotFound, facts.FactError) as exc:
        return kinds.Fail(str(exc))
    modules, said = _modules(checked, params.modules_fact)
    evaluation = rule_evaluation.evaluate(list(at.rules), checked, modules=modules or tuple(m.code for m in at.product.modules))
    cat = facts.catalogue(checked.catalogue)
    missing = [(u, f) for u, f in evaluation.missing]
    if not said:
        top = next(u.unit_id for u in checked.units if u.parent_id is None)
        missing = [(top, params.modules_fact), *missing]
    content = rule_evaluation.to_json(evaluation) | {
        "modules": list(modules), "modules_said": said, "input_step": params.from_step,
        "verdict": evaluation.verdict if said else _unsaid(cat, evaluation.verdict),
        "missing_named": [{"unit_id": u, "fact": f, "title": cat.facts[f].title if f in cat.facts else f} for u, f in missing]}
    with ctx.transaction() as c:
        trace_ids = rule_evaluation.trace_in(c, case_id, evaluation)
        n = _keep(c, case_id, ctx.step.id, EVALUATION_KIND, params.from_step, input_version, content, trace_ids)
    return kinds.Done(_summary(n, input_version, content))


def _rate(ctx: Any, params: Rating) -> kinds.StepOutcome:
    case_id = str(ctx.data["container"])
    evaluated = capabilities.read_result(ctx, params, "from_step")
    ev_version = int(evaluated["version"])
    with store.connect() as c:
        kept = _row(c, case_id, ctx.step.id, input_version=ev_version)
        ev_row = _row(c, case_id, params.from_step, version=ev_version)
    if kept is not None:
        content = json.loads(kept["content"])
        if content["blockers"]:
            return kinds.Fail("blocked: " + "; ".join(content["blockers"]))
        return kinds.Done({"version": kept["version"], "total": content["total"], "tariff": content["tariff_ref"]})
    if ev_row is None:
        return kinds.Fail(f"no evaluation record {ev_version} of step {params.from_step}")
    ev_content = json.loads(ev_row["content"])
    if not ev_content["modules_said"]:  # nothing is priced for modules nobody asked for
        return kinds.Fail(f"blocked: the input does not say the cover modules it asks for ({ev_content['missing_named'][0]['fact']})")
    evaluation = rule_evaluation.from_json(ev_content)
    try:
        checked = _checked(case_id, ev_content["input_step"], int(ev_row["input_version"]))
        found = product_rules.resolve("tariff", params.tariff)
        product = product_rules.product_at(checked.product).product
    except (KeyError, versions.VersionNotFound, facts.FactError) as exc:
        return kinds.Fail(str(exc))
    if product.tariff != versions.split(found["ref"])[0]:
        return kinds.Fail(f"the tariff {found['ref']} is not the one the product {checked.product} is priced by ({product.tariff})")
    modules = tuple(ev_content["modules"])
    calc = rating.calculate(product_rules.Tariff.model_validate(found["content"]), found["ref"], checked, evaluation, modules=modules)
    content = {"tariff_ref": found["ref"], "modules": list(modules), "total": rule_evaluation.plain(calc.total) if calc.total else None,
               "subtotal": rule_evaluation.plain(calc.subtotal) if calc.subtotal else None,
               "policy_minimum_applied": calc.policy_minimum_applied, "blockers": [*evaluation.blockers, *calc.blockers],
               "lines": [{"unit_id": line.unit_id, "module": line.module, "basis": rule_evaluation.plain(line.basis),
                          "base": rule_evaluation.plain(line.base),
                          "steps": [{"name": s.name, "factor": str(s.factor), "after": rule_evaluation.plain(s.after)} for s in line.steps],
                          "amount": rule_evaluation.plain(line.amount)} for line in calc.lines],
               "module_totals": {k: {"lines": rule_evaluation.plain(v["lines"]), "minimum_applied": v["minimum_applied"],
                                     "total": rule_evaluation.plain(v["total"])} for k, v in calc.modules.items()},
               "total_steps": [{"name": s.name, "factor": str(s.factor), "after": rule_evaluation.plain(s.after)} for s in calc.total_steps]}
    with ctx.transaction() as c:
        trace_id = rating.trace_in(c, case_id, calc)
        n = _keep(c, case_id, ctx.step.id, RATING_KIND, params.from_step, ev_version, content, [trace_id])
    if content["blockers"]:  # kept with its blockers (the rules' and the tariff's), so the reason shows; never a default
        return kinds.Fail("blocked: " + "; ".join(content["blockers"]))
    return kinds.Done({"version": n, "total": content["total"], "tariff": found["ref"]})


EVALUATION = capabilities.Capability(
    name="rule_evaluation", version=1, module=__name__, run=_evaluate, kind="machine", params=RuleEvaluation, state="step",
    output=EvaluationResult, effects="store",
    summary="Evaluates the rules of the product version a frozen input names on its units, and keeps the evaluation.")
RATING = capabilities.Capability(
    name="rating", version=1, module=__name__, run=_rate, kind="machine", params=Rating, state="step", output=RatingResult,
    effects="store", at_start={"tariff": product_rules.keeper("tariff")},
    summary="Computes the premium from the tariff the case kept, itemised, and keeps it; a blocker stops it.")


def register() -> None:
    from jav.app import case_views

    capabilities.register(EVALUATION)
    capabilities.register(RATING)
    case_views.register(case_views.ElementData("evaluation", "rule_evaluation", __name__, _evaluation_view))
    case_views.register(case_views.ElementData("calculation", "rating", __name__, _calculation_view))
