"""A question to an outside register, its answers offered as facts of the case (231, stage D, D-d5).

Plain-language summary: a case may check what it was told with an outside register: a company register asked with the
policyholder's tax number, a sanctions list asked with its name and tax number. This step asks one register through
its connector (the one way out, each question in the call log; nothing changes on the other side) with facts another
step offers (a document's reading), and offers what the answer says as facts of the same unit, each naming the
register it came from. It decides nothing: the field check places the facts, and a value that differs from the
document's is left to a person there. Two lookups of a case are independent branches: one register that does not
answer stops only its own step, which a person retries.

- `CAPABILITY` (`lookup@1`): params `connector` (a described lookup), `from_step` (the step whose facts it asks with),
  `asks` and `asks_if_known` (the question's fields by fact; a missing fact of `asks` means nothing is asked),
  `answers` (a field of the answer, dotted, by the fact it offers); result: whether it asked, the facts missing, the
  answer and the offered facts (`claims`, as the field check reads them).

Layer: application; it names no register and no business (the connector and the fields are the pack's data).
"""

from __future__ import annotations

import json
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jav.app import capabilities
from jav.core import calls, connectors
from jav.core.process import kinds

__all__ = ["CAPABILITY", "Lookup", "LookupResult", "register"]

BUSY_WAIT_S = 60.0


class Lookup(BaseModel):
    """The register's connector, the step whose facts it asks with, the question's fields and the answer's facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    connector: str = Field(min_length=1, title="Register")
    from_step: str = capabilities.step_ref(min_length=1)
    asks: dict[str, str] = Field(min_length=1)
    asks_if_known: dict[str, str] = Field(default_factory=dict)
    answers: dict[str, str] = Field(min_length=1)

    @field_validator("connector")
    @classmethod
    def _described(cls, value: str) -> str:
        if connectors.of(value).kind != "lookup":  # ConnectorError (a ValueError) when it is not described
            raise ValueError(f"the connector {value!r} is no lookup")
        return value


class LookupResult(capabilities.Result):
    """Whether it asked, and the facts it offers."""

    asked: bool
    claims: list[dict[str, Any]]


def _at(answer: Any, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(answer, dict) or part not in answer:
            return None
        answer = answer[part]
    return answer


def _known(result: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The facts the step offers on its top unit (the first value of each), and that unit's key and level."""
    facts: dict[str, Any] = {}
    unit = None
    for claim in result.get("claims") or []:
        if not isinstance(claim, dict) or claim.get("parent") is not None:
            continue
        unit = unit or {"unit": claim.get("unit"), "level": claim.get("level")}
        if claim.get("unit") == unit["unit"]:
            facts.setdefault(str(claim.get("fact")), claim.get("value"))
    return facts, unit


def _run(ctx: Any, params: Lookup) -> kinds.StepOutcome:
    _version, given = ctx.result_of(params.from_step)
    known, unit = _known(given or {})
    if missing := [fact for fact in params.asks.values() if fact not in known]:
        return kinds.Done({"asked": False, "missing": missing, "claims": []})
    assert unit is not None
    question = {key: known[fact] for key, fact in params.asks.items()}
    question |= {key: known[fact] for key, fact in params.asks_if_known.items() if fact in known}
    try:
        raw = connectors.ask(params.connector, json.dumps(question, ensure_ascii=False).encode("utf-8"),
                             purpose=f"lookup:{ctx.case_id}:{ctx.step.id}")
    except connectors.ConnectorUnavailable as exc:
        if exc.reason == "busy":  # nothing was sent: asked again in a minute
            return ctx.wait("lookup", timer=("retry", time.time() + BUSY_WAIT_S))
        return kinds.Fail(f"the register {params.connector} gave no usable answer ({exc.reason}); retry the step")
    except calls.BudgetExceeded as exc:
        return kinds.Fail(str(exc))
    try:
        answer = json.loads(raw)
    except ValueError:
        return kinds.Fail(f"the register {params.connector} answered something that is not JSON")
    claims = [{"unit": unit["unit"], "level": unit["level"], "parent": None, "fact": fact, "value": value,
               "source": {"item": f"lookup:{params.connector}"}, "reading": f"lookup:{params.connector}"}
              for path, fact in params.answers.items() if (value := _at(answer, path)) is not None]
    return kinds.Done({"asked": True, "missing": [], "question": question, "answer": answer, "claims": claims})


CAPABILITY = capabilities.Capability(
    name="lookup", version=1, module=__name__, run=_run, kind="machine", params=Lookup, state="step", output=LookupResult,
    effects="store",
    summary="Asks an outside register through its connector with facts another step offers, and offers its answer as "
            "facts.")


def _lookup_view(case_id: str, step: str | None, _shared: dict[str, Any]) -> dict[str, Any]:
    """D-f4: the lookup element's data: the register (its description), the step's state and note, and what it asked,
    what the register answered and the facts it offers."""
    from jav.core import store
    from jav.core.process import cases

    with store.connect() as c:
        case = cases.find_case_in(c, case_id)
        row = cases.find_step_in(c, case_id, str(step)) or {}
    name = str(cases.definition_of(case).step(str(step)).params.get("connector")) if case else ""
    try:
        what = connectors.of(name).what
    except connectors.ConnectorError:
        what = None
    result = row.get("result") or {}
    return {"state": row.get("state"), "note": row.get("note"), "connector": name, "what": what,
            "asked": result.get("asked"), "missing": result.get("missing") or [], "question": _by_fact(case, str(step), result),
            "claims": result.get("claims") or [], "catalogue": _catalogue_of(case, str(step))}


def _by_fact(case: Any, step: str, result: dict[str, Any]) -> dict[str, Any]:
    """What the register was asked with, by the fact each value is (the register's own field names are its business)."""
    from jav.core.process import cases

    if case is None:
        return {}
    params = cases.definition_of(case).step(step).params
    facts_of = {**(params.get("asks") or {}), **(params.get("asks_if_known") or {})}
    return {facts_of.get(key, key): value for key, value in (result.get("question") or {}).items()}


def _catalogue_of(case: Any, step: str) -> dict[str, Any] | None:
    """The fact catalogue of the field check the lookup offers its facts to (its titles and labels), if the pack has one."""
    from jav.app import facts
    from jav.core.process import cases

    if case is None:
        return None
    for s in cases.definition_of(case).steps:
        cap = capabilities.of_step_kind(s.kind)
        if step in s.needs() and cap is not None and cap.name == "field_check" and s.params.get("catalogue"):
            return facts.catalogue(str(s.params["catalogue"])).model_dump(mode="json")
    return None


def register() -> None:
    from jav.app import case_views

    capabilities.register(CAPABILITY)
    case_views.register(case_views.ElementData("lookup", "lookup", __name__, _lookup_view))
