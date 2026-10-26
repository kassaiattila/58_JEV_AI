"""A person's decision on another step's result, one capability for every decision a case makes (231, stage D, D-d4).

Plain-language summary: a case may ask a person to decide on what an earlier step made: first on the risk (the rules'
verdict), then on the premium (the owner's decision of 2026-10-26). Both are this one step, each named by the pack with
the step it decides on and its choices (their titles; the values of the result a choice needs, so a refused risk is
not accepted; the outcome a choice ends the case with, such as declined). The decision is the step's own approved
version: who decided, when, on which result version, with the note. A page that shows an older result is refused;
when the result decided on changes, the decision goes out of date and is made again; a person may return it with a
reason instead (`case_views.return_step`). Above a limit of a versioned rule file the case kept as it started
(`configs/case_decisions.json`), the decision is made by another person than the one who made an earlier decision the
pack names: whether a second person is needed is a row of the decision trace, and the task goes to anyone but them.

- `CAPABILITY` (`decision@1`): params `about` (the step decided on), `choices`, `other_than` and `limit` (both or
  neither), `amount_field` (the result's amount compared with the limit); result: the version, the choice and the
  result version decided on.
- `view(case_id, step)`, `decide(case_id, step, choice=, note=, expected_basis=, actor=)`, `needs_second(amount, above)`.
  A return goes through `case_views.return_step`. D-f2: the step's action `decide` (`DecideForm`), with the result
  versions the page showed (an older page is refused).

Layer: application; it names no process and no business (the choices, their wording and the limits are data).
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jav.app import capabilities, human_tasks, package_release
from jav.core import activity_kinds, cfg, decisions, identity, store, trace
from jav.core.measures import Money
from jav.core.process import cases, kinds
from jav.core.user_messages import explained

__all__ = ["CAPABILITY", "POINT", "AnotherDeciderNeeded", "CaseDecisionError", "Choice", "Decision", "DecisionResult", "decide",
           "needs_second", "register", "view"]

POINT = "decision.second_person"
RULE_FILE = "case_decisions"
POLL_S = 5.0

activity_kinds.register_events("package", ("decision_approve", "decision_reopen"), __name__)


class CaseDecisionError(ValueError):
    """A decision that cannot be made: nothing to decide yet, a choice the step does not offer or the result does not
    allow, a decline without a reason, a limit in another currency."""


class AnotherDeciderNeeded(CaseDecisionError):
    """Above the limit, the decision is another person's than the one who made the earlier decision."""


class Choice(BaseModel):
    """A choice the decision offers: its title, the values of the decided result's fields it needs (none: any), and the
    outcome it ends the case with (none: the case goes on)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    title: str = Field(min_length=1, max_length=120)
    allowed_when: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    closes: str | None = Field(None, pattern=r"^[a-z][a-z0-9_]*$")


class Decision(BaseModel):
    """The step decided on, the choices, and - both or neither - the earlier decision whose maker may not make this
    one above the limit, and the limit."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    about: str = capabilities.step_ref(min_length=1)
    choices: dict[str, Choice] = Field(min_length=1)
    other_than: str | None = capabilities.step_ref(None, of="decision", optional=True)
    limit: str | None = Field(None, min_length=1, title="Limit for a second person")
    amount_field: str = Field("total", min_length=1, title="The amount compared with the limit")

    @model_validator(mode="after")
    def _paired(self) -> Decision:
        if (self.other_than is None) != (self.limit is None):
            raise ValueError("a second person needs both the earlier decision (other_than) and the limit")
        return self


class DecisionResult(capabilities.OwnVersionResult):
    """The decision: its version, the choice and the result version of the step decided on."""

    choice: str
    about_version: int


def needs_second(amount: Money, above: Money) -> bool:
    """Whether the amount is above the limit (`CurrencyMismatch` for another currency: never converted)."""
    return amount > above


def _replay(inputs: Any) -> Any:
    return {"needed": needs_second(Money.model_validate(inputs["amount"]), Money.model_validate(inputs["above"]))}


trace.register(trace.Point(
    POINT, owner=__name__, files=(f"{RULE_FILE}.json",), rule=_replay,
    what="whether a case's decision is another person's than an earlier decision's maker: the decided result's amount "
         "above the limit the pack names",
    not_for="the decision itself or the rules and premium it decides on"))


def _params(c: Any, case_id: str, step: str) -> Decision:
    case = cases.find_case_in(c, case_id)
    if case is None:
        raise KeyError(case_id)
    return Decision.model_validate({k: v for k, v in cases.definition_of(case).step(step).params.items() if not k.startswith("_")})


def _limit(case_id: str, name: str) -> Money:
    with capabilities.case_rules(case_id):
        limits = cfg.load(RULE_FILE).get("limits") or {}
    if name not in limits:
        raise explained(CaseDecisionError, "the rule file names no limit {{limit}}", limit=name)
    return Money.model_validate(limits[name]["above"])


def _second(c: Any, case_id: str, params: Decision, result: dict[str, Any]) -> dict[str, Any] | None:
    """Whether a second person is needed for this result, with what it is decided from (None: the pack names no limit)."""
    if params.limit is None:
        return None
    above = _limit(case_id, params.limit)
    raw = result.get(params.amount_field)
    if raw is None:
        raise explained(CaseDecisionError, "the result decided on has no {{field}} to compare with the limit",
                        field=params.amount_field)
    amount = Money.model_validate(raw)
    if amount.currency != above.currency:
        raise explained(CaseDecisionError, "the limit is in {{limit}} and the amount in {{amount}}; nothing is converted",
                        limit=above.currency, amount=amount.currency)
    earlier = package_release.own_approval(case_id, c, step=params.other_than)["active"]
    return {"limit": params.limit, "amount": amount.model_dump(mode="json"), "above": above.model_dump(mode="json"),
            "needed": needs_second(amount, above), "other_than": params.other_than,
            "earlier_by": earlier["approved_by"] if earlier else None,
            "earlier_by_id": earlier.get("approved_by_id") if earlier else None}


# --- the step ------------------------------------------------------------------------------------------------------------


def _run(ctx: Any, params: Decision) -> kinds.StepOutcome:
    from jav.app import process_runtime

    case_id = str(ctx.data["container"])
    if (why := process_runtime.outdated(case_id, ctx.step.id)) is not None:
        with store.connect() as c:  # the result decided on changed: decided again
            store.begin_immediate(c)
            package_release.reopen_logged(c, case_id, event="decision", note=why, actor=ctx.actor, step=ctx.step.id)
    approval = package_release.own_approval(case_id, step=ctx.step.id)
    if approval["active"] is None:
        if not approval["versions"]:  # its first round; a reopened version opened its task again
            _version, result = ctx.result_of(params.about)
            with ctx.transaction() as c:
                try:
                    second = _second(c, case_id, params, result or {})
                except CaseDecisionError:  # the limit cannot be applied: the task goes to anyone, and the decision says why
                    second = {"needed": True}
                human_tasks.own_approval_waits(c, case_id, ctx.step.id,
                                               **({"assignee": None} if second and second["needed"] else {}))
        return ctx.wait("decision", timer=("check", time.time() + POLL_S))
    version = approval["active"]["version"]
    content = package_release.own_version(case_id, version, step=ctx.step.id)["content"]
    choice = params.choices.get(content["choice"])
    if choice is not None and choice.closes:
        return kinds.Close(choice.closes)
    return kinds.Done({"version": version, "choice": content["choice"], "about_version": content["about_version"]})


def view(case_id: str, step: str) -> dict[str, Any]:
    """What a person decides on: the step decided on and its result now (with the result versions to send back with
    the decision), the choices with whether the result allows each, whether a second person is needed and the
    approval (missing, approved, out of date, returned)."""
    from jav.app import process_runtime

    with store.connect() as c:
        params = _params(c, case_id, step)
        row = cases.step_row(c, case_id, params.about)
        done = row["state"] == cases.DONE
        result = row["result"] if done else None
        try:
            second = _second(c, case_id, params, result) if done else None
            problem = None
        except CaseDecisionError as exc:
            second, problem = None, exc
        basis = process_runtime.basis_of(case_id, step, c)
    choices = [{"code": code, "title": ch.title, "closes": ch.closes,
                "allowed": done and _allows(ch, result or {})} for code, ch in params.choices.items()]
    return {"about": params.about, "result": result, "basis": basis, "choices": choices, "second_person": second,
            "problem": str(problem) if problem else None,
            "approval": package_release.approval_state(case_id, step=step)}


def _allows(choice: Choice, result: dict[str, Any]) -> bool:
    return all(str(result.get(field)) in values for field, values in choice.allowed_when.items())


def decide(case_id: str, step: str, *, choice: str, note: str | None, expected_basis: dict[str, int] | None,
           actor: identity.Who) -> dict[str, Any]:
    """The person's decision as the step's next own version. Refused: a page showing older results
    (`RevisionConflict`), nothing to decide yet, a choice not offered or the result does not allow, a choice ending the
    case without a reason (`CaseDecisionError`), and above the limit, the earlier decision's maker (`AnotherDeciderNeeded`)."""
    from jav.app import process_runtime

    with store.connect() as c:
        store.begin_immediate(c)
        params = _params(c, case_id, step)
        row = cases.step_row(c, case_id, params.about)
        if row["state"] != cases.DONE:
            raise explained(CaseDecisionError, "there is nothing to decide yet")
        basis = process_runtime.basis_of(case_id, step, c)
        if expected_basis is not None and basis != expected_basis:
            raise explained(decisions.RevisionConflict, "the result decided on changed meanwhile; reload it")
        offered = params.choices.get(choice)
        if offered is None:
            raise explained(CaseDecisionError, "the decision offers no choice {{choice}}", choice=choice)
        result = row["result"] or {}
        if not _allows(offered, result):
            raise explained(CaseDecisionError, "the result decided on does not allow {{choice}}", choice=offered.title)
        if offered.closes and not (note or "").strip():
            raise explained(CaseDecisionError, "a decision that ends the case needs a reason")
        second = _second(c, case_id, params, result)
        if second is not None and second["needed"]:
            if second["earlier_by_id"] is None:
                raise explained(CaseDecisionError, "the decision {{step}} is not made yet", step=params.other_than)
            if second["earlier_by_id"] == identity.id_of(actor):
                raise explained(AnotherDeciderNeeded, "above the limit, another person than the one who decided {{step}} decides",
                                step=params.other_than)
        content = {"choice": choice, "title": offered.title, "note": (note or "").strip() or None, "about": params.about,
                   "about_version": int(row["result_version"]), "result": result, "second_person": second}
        fingerprint = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
        n = package_release.approve_own(c, case_id, event="decision", content=content, fingerprint=fingerprint, locks=[],
                                        actor=actor, files=lambda _c, _n: None,
                                        details={"step": step, "choice": choice, "about_version": content["about_version"]},
                                        step=step, basis=basis)
        if second is not None:
            trace.record_in(c, POINT, subject=("decision", f"{case_id}:{step}"),
                            inputs={"amount": second["amount"], "above": second["above"], "limit": second["limit"]},
                            outcome={"needed": second["needed"]},
                            keys={f"{RULE_FILE}.json": [f"limits.{second['limit']}"]}, case_id=case_id)
    return {"version": n, "fingerprint": fingerprint}


class DecideForm(BaseModel):
    """D-f2: a person's decision as the page sends it: the choice, the note, and the result versions it showed."""

    model_config = ConfigDict(extra="forbid")
    choice: str = Field(min_length=1)
    note: str | None = None
    expected_basis: dict[str, int]


def _waits(case_id: str, step: str) -> bool:
    """The decision waits: what it decides on is done, and no decision of it holds."""
    with store.connect() as c:
        row = cases.find_step_in(c, case_id, step)
        if not row or row["state"] != cases.RUNNING:
            return False
        about = _params(c, case_id, step).about
        if cases.step_row(c, case_id, about)["state"] != cases.DONE:
            return False
    return package_release.own_approval(case_id, step=step)["active"] is None


ACTIONS = (capabilities.form_action("decide", "Decide", _waits, DecideForm,
                                    lambda case_id, step, actor, v: decide(case_id, step, choice=v.choice, note=v.note,
                                                                           expected_basis=v.expected_basis, actor=actor)),)


CAPABILITY = capabilities.Capability(
    name="decision", version=1, module=__name__, run=_run, kind="human", params=Decision, state="step",
    output=DecisionResult, own_version=True, reads=lambda p: (RULE_FILE,) if p.get("limit") else (), actions=ACTIONS,
    approval_what="Make the decision",
    summary="A person decides on another step's result with the choices the pack names; above a limit, another person "
            "than an earlier decision's maker.")


def register() -> None:
    capabilities.register(CAPABILITY)
