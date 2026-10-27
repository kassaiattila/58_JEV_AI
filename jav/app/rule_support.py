"""How far the page a rule was read from supports a proposed rule: a JEV check (231, stage D, D-c7d).

Plain-language summary: code checks a proposed rule's form, citation, quote and numbers (`jav/app/rule_checks.py`).
What code cannot tell is whether the page says what the rule says. One JEV request per proposal asks three things
together, with the cited page verbatim and the rule written out by code in plain English: which kind of rule the page
states there (a Choice over the kinds, or none: no rule decidable when making an offer); for each row of the decision
table, whether the page states that the row's conditions lead to its results; and whether the page names a further
condition, amount or exception the rule leaves out (`configs/callsites/rule_proposal.json`). The answer is a mark beside
the proposal: supported, to check, or contradicted. It never accepts anything: a person decides every proposal, and
JEV's support is no proof. Without JEV (switched off, unavailable, out of budget) the mark is "not asked" with the
reason, and the person decides on the code's checks alone.

- `support(rule, pages, run_id=)`: the `Support` (the mark, the raw probabilities and the bands they fall in).
- `rule_sentences(rule)`: the rule written out in English from its catalogue's titles.

Layer: application (every JEV question through `jav.ai.jev`); it names no process and no business.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from typesafe_sdk import Choice, Noul

from jav.ai import policy
from jav.ai.jev import JevUnavailableError, get_adapter
from jav.app import facts
from jav.app.product_rules import Rule
from jav.core import cfg
from jav.core.measures import Money, PerMille, Percentage, Quantity
from jav.documents.page_text import DocumentPages

__all__ = ["CALLSITE", "Support", "rule_sentences", "support"]

REQUEST_ID = "rule_proposal"
CALLSITE = "rules.proposal"  # the policy bands it is judged on (none of its own: the default set)
NONE = "none"
Mark = Literal["supported", "check", "contradicted", "not_asked"]
_SIGN = {"eq": "is", "ne": "is not", "lt": "is below", "lte": "is at most", "gt": "is above", "gte": "is at least"}


@dataclass(frozen=True)
class Support:
    mark: Mark
    reason: str | None = None  # why it is to check, contradicted or not asked
    kind: str | None = None  # the kind the page states, as JEV chose it
    kind_probability: float | None = None
    rows: tuple[float, ...] = ()  # P(the page states row n)
    left_out: float | None = None  # P(the page names something the rule leaves out)
    bands: dict[str, str] = field(default_factory=dict)
    model: str | None = None
    cost_usd: float | None = None


def _site() -> dict[str, Any]:
    return cfg.load(f"callsite:{REQUEST_ID}")


def config_hash() -> str:
    return cfg.config_hash(f"callsite:{REQUEST_ID}")


def _shown(cat: facts.Catalogue, value: Any) -> str:
    if isinstance(value, Money):
        return f"{value.amount} {value.currency}"
    if isinstance(value, Quantity):
        return f"{value.value} {value.unit}"
    if isinstance(value, Percentage):
        return f"{value.value} %"
    if isinstance(value, PerMille):
        return f"{value.value} per mille"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, tuple):
        return ", ".join(_shown(cat, v) for v in value)
    if isinstance(value, str):
        return cat.labels.get(value, value)
    return str(value)


def _condition(cat: facts.Catalogue, name: str, op: str, value: Any) -> str:
    d = cat.facts[name]
    title = d.title
    if op in ("present", "absent"):
        given = (op == "present") == bool(value)
        return f"{title} is {'given' if given else 'not given'}"
    typed = [facts.typed_value(name, d, v) for v in value] if op in ("in", "not_in", "between") else facts.typed_value(name, d, value)
    if op == "in":
        return f"{title} is one of {', '.join(_shown(cat, v) for v in typed)}"
    if op == "not_in":
        return f"{title} is none of {', '.join(_shown(cat, v) for v in typed)}"
    if op == "between":
        return f"{title} is from {_shown(cat, typed[0])} to {_shown(cat, typed[1])}"
    return f"{title} {_SIGN[op]} {_shown(cat, typed)}"


def rule_sentences(rule: Rule) -> dict[str, Any]:
    """The rule as the state shows it: its kind, level and modules, and each row in an English sentence."""
    cat = facts.catalogue(rule.catalogue)
    rows = []
    for n, row in enumerate(rule.table.rows, 1):
        conditions = [_condition(cat, name, op, value) for name, cond in row.when.items() for op, value in cond.items()]
        results = [f"{cat.outcomes[name].title}: {_shown(cat, facts.typed_value(name, cat.outcomes[name], value))}"
                   for name, value in row.then.items()]
        when = " and ".join(conditions) if conditions else "for every unit"
        rows.append(f"{n}. When {when}: {'; '.join(results)}." if conditions else f"{n}. Otherwise: {'; '.join(results)}.")
    return {"kind": rule.kind, "applies_to": cat.labels.get(rule.level, rule.level),
            "modules": list(rule.modules) or "every module",
            "decides": "the first row that fits" if rule.table.hit == "first" else "every row that fits", "rows": rows}


def _questions(rule: Rule) -> dict[str, Choice | Noul]:
    q = _site()["questions"]
    criteria: dict[str, Any] = dict(q["kind"]["options"])
    criteria[NONE] = q["kind"]["none"]
    out: dict[str, Choice | Noul] = {"kind": Choice(instructions=q["kind"]["instructions"], criteria=criteria)}
    for n in range(1, len(rule.table.rows) + 1):
        out[f"row_{n}"] = Noul(instructions=q["row"]["instructions"].replace("{n}", str(n)), criteria=q["row"]["criteria"])
    out["left_out"] = Noul(instructions=q["left_out"]["instructions"], criteria=q["left_out"]["criteria"])
    return out


def _state(rule: Rule, pages: DocumentPages) -> dict[str, Any]:
    page = pages.pages.get(rule.source.page or 0, "")
    return {"page": page[: int(_site()["state"]["max_page_chars"])], "quote": rule.source.quote or "",
            "rule": rule_sentences(rule)}


def _mark(rule: Rule, choice: str | None, confidence: float, dist: dict[str, float], rows: list[float],
          left_out: float) -> tuple[Mark, str | None, dict[str, str]]:
    bands = {"kind": policy.choice_band(confidence, dist, CALLSITE), "left_out": policy.noul_band(left_out, CALLSITE)}
    bands |= {f"row_{n}": policy.noul_band(p, CALLSITE) for n, p in enumerate(rows, 1)}
    sure_kind = bands["kind"] == "auto"
    if choice == NONE and sure_kind:
        return "contradicted", "the page states no such rule", bands
    if any(bands[f"row_{n}"] == "no" for n in range(1, len(rows) + 1)):
        return "contradicted", "the page does not state a row", bands
    if not all(bands[f"row_{n}"] == "yes" for n in range(1, len(rows) + 1)):
        return "check", "a row is not clearly stated", bands
    if bands["left_out"] != "no":
        return "check", "the page may name something the rule leaves out", bands
    if choice != rule.kind:
        return "check", "the page states another kind of rule", bands
    return "supported", None, bands


def support(rule: Rule, pages: DocumentPages, *, run_id: str, use_cache: bool = True) -> Support:
    """JEV's judgement of how far the cited page supports the rule; "not asked" without JEV."""
    try:
        r = get_adapter().ask(REQUEST_ID, _state(rule, pages), _questions(rule), run_id=run_id, use_cache=use_cache,
                              config_hash=config_hash())
    except JevUnavailableError as exc:
        return Support("not_asked", f"jev_unavailable:{exc.reason}")
    ch = r.response.choices["kind"]
    dist = {str(k): float(v) for k, v in dict(ch.probabilities).items()}
    rows = [float(r.response.nouls[f"row_{n}"].noul) for n in range(1, len(rule.table.rows) + 1)]
    left_out = float(r.response.nouls["left_out"].noul)
    mark, reason, bands = _mark(rule, ch.choice, float(ch.confidence), dist, rows, left_out)
    return Support(mark, reason, ch.choice, dist.get(ch.choice or ""), tuple(round(p, 4) for p in rows), round(left_out, 4),
                   bands, r.call.model, float(r.call.cost_usd))
