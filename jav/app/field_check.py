"""A person's check of the assessed units, frozen as the step's own version (231, stage D, D-d2).

Plain-language summary: an assessment's units (a policyholder, its sites, their asset groups) carry facts with the
source each came from: a document read, an outside register's answer, a person's entry. This step is where a person
checks them. The steps it waits for may offer claims (a lookup's answers, a reading's facts), each naming its unit by the
offering step's own key and level (and its parent's key): a claim creates a unit the step does not have yet, fills a
fact still missing, or agrees with the fact there; a claim that differs from a fact already there is never chosen: it is
shown to the person as a conflict. Each claim is placed once, and its placement is a row of the decision trace. The
person corrects what needs it (`assessed_units`) and freezes the units with the day cover starts: the checked input -
the units typed by the catalogue, the product version the case kept at its start and that day - becomes the step's
own approved version (the owner's decision of 2026-10-26: the field check freezes the input), with the result versions
of the steps it built on. A later correction does not change it; when the person reopens it, or a step it built on
changes, it is frozen again and the steps after it run again.

- `CAPABILITY` (`field_check@1`): params `catalogue` (a fact catalogue, kept as the case started) and `product` (kept at
  its version at the start); its result: the version, product, catalogue, cover start and the units' reference.
- `view(case_id, step)`, `freeze(case_id, step, cover_start=, expected_state=, actor=)`, `reopen(case_id, step, note=,
  actor=)`. D-f2: the step's actions (`ACTIONS`): freeze, reopen, and a unit added, saved or removed, each with the state
  of the page it was made on (an older one is refused).
- U1 (the walkthrough of 2026-10-28): `keep(case_id, step, claim_key, actor=)`: a person keeps the value shown in a
  disagreement instead of the one another source offers; it is settled in their name (`KEPT`, journaled), so the units
  can be frozen with it.

Layer: application; it names no process and no business (the catalogue and the claims are data).
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from jav.app import assessed_units, capabilities, facts, human_tasks, package_release, product_rules
from jav.core import activity_kinds, decisions, identity, store, trace
from jav.core.clock import utc_stamp as _now
from jav.core.process import kinds
from jav.core.user_messages import explained

__all__ = ["CAPABILITY", "KEPT", "POINT", "CheckedResult", "Claim", "FieldCheck", "FieldCheckError", "freeze", "keep", "placement",
           "register", "reopen", "view"]

POINT = "claims.offered"
KEPT = "field_check_claim"  # U1: a person's decision on a disagreement (the value shown kept)
EVENT = "field_check"
POLL_S = 5.0
Placement = Literal["new_unit", "filled", "agrees", "conflict", "unplaced"]

activity_kinds.register_events("package", (f"{EVENT}_approve", f"{EVENT}_reopen"), __name__)

store.register_schema("field_check", """
-- 231 (stage D, D-d2): the units a field check made from claims, by the offering step's key, and each claim's placement
CREATE TABLE IF NOT EXISTS field_check_units (
    case_id   TEXT NOT NULL,
    step_id   TEXT NOT NULL,
    unit_key  TEXT NOT NULL,   -- the offering step's name of the unit ("holder", "site:1")
    unit_id   TEXT NOT NULL,
    PRIMARY KEY (case_id, step_id, unit_key)
);
CREATE TABLE IF NOT EXISTS field_check_claims (
    case_id    TEXT NOT NULL,
    step_id    TEXT NOT NULL,
    claim_key  TEXT NOT NULL,  -- the claim's fingerprint: placed once
    from_step  TEXT NOT NULL,
    unit_key   TEXT NOT NULL,
    fact       TEXT NOT NULL,
    value      TEXT NOT NULL,  -- JSON
    placement  TEXT NOT NULL,
    unit_id    TEXT,
    placed_at  TEXT NOT NULL,
    PRIMARY KEY (case_id, step_id, claim_key)
);
""")
store.register_migration("field_check_claims_kept", lambda conn: (store.add_columns(conn, "field_check_claims", {
    "kept_by": "TEXT", "kept_at": "TEXT"}), store.add_actor_ids(conn, "field_check_claims", ("kept_by",))))
# U1: a disagreement settled by keeping the value shown, with who kept it (its name and its stable id)
decisions.register(decisions.Kind(KEPT, ("keep",), __name__))


class FieldCheckError(ValueError):
    """A freeze that cannot be: nothing to freeze, no such step."""


class Claim(BaseModel):
    """A fact a step offers: its unit by the offering step's key and level (and its parent's key), the value and where
    it came from."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    unit: str = Field(min_length=1, max_length=120)
    level: str
    parent: str | None = None
    fact: str
    value: Any
    original: str | None = None
    source: facts.SourceRef
    reading: str  # the reading or the lookup (and its version) that made the value


class FieldCheck(BaseModel):
    """The fact catalogue the units are of, and the product version the input is frozen for."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    catalogue: str = Field(min_length=1, title="Fact catalogue")
    product: str = Field(min_length=1, title="Product")

    @field_validator("catalogue")
    @classmethod
    def _known(cls, value: str) -> str:
        try:
            facts.catalogue(value)
        except FileNotFoundError:
            raise ValueError(f"no fact catalogue {value!r}") from None
        return value


class CheckedResult(capabilities.OwnVersionResult):
    """The frozen checked input: its version, the product version and catalogue it is for, the day cover starts, and
    the units' reference (their rows stay in the step's units)."""

    product: str
    catalogue: str
    cover_start: date
    units: capabilities.DatasetRef


# --- placing the claims --------------------------------------------------------------------------------------------------


def placement(cat: facts.Catalogue, *, fact: str, value: Any, unit_found: bool, parent_found: bool, top: bool,
              has_current: bool, current: Any) -> Placement:
    """Where a claim goes: a new unit (its parent there, or the top level), a fact filled, one it agrees with, one it
    conflicts with (never chosen: a person decides), or nowhere (its unit's parent is not there)."""
    if not unit_found:
        return "new_unit" if top or parent_found else "unplaced"
    if not has_current:
        return "filled"
    d = cat.facts[fact]
    return "agrees" if facts.typed_value(fact, d, current) == facts.typed_value(fact, d, value) else "conflict"


def _replay(inputs: Any) -> Any:
    cat = facts.catalogue(inputs["catalogue"])
    return placement(cat, fact=inputs["fact"], value=inputs["value"], unit_found=inputs["unit_found"],
                     parent_found=inputs["parent_found"], top=inputs["top"], has_current=inputs["has_current"],
                     current=inputs["current"])


trace.register(trace.Point(
    POINT, owner=__name__, files=("facts_*.json",), rule=_replay,
    what="where a fact another step offers goes in a field check: a new unit, a fact still missing filled, one it agrees "
         "with, one it conflicts with (left to a person), or nowhere (its unit's parent is not there)",
    not_for="the person's own corrections or the freezing of the checked input"))


def _claim_key(from_step: str, claim: Claim) -> str:
    text = json.dumps({"from": from_step, **claim.model_dump(mode="json")}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _offered(ctx: Any) -> list[tuple[str, Claim]]:
    """The claims the steps this one waits for offer, in the pack's order of those steps."""
    out: list[tuple[str, Claim]] = []
    needs = set(ctx.definition.step(ctx.step.id).needs())
    for step in ctx.definition.steps:
        if step.id not in needs:
            continue
        try:
            _version, result = ctx.result_of(step.id)
        except (KeyError, ValueError):
            continue
        for raw in (result or {}).get("claims") or []:
            try:
                out.append((step.id, Claim.model_validate(raw)))
            except ValidationError:
                continue  # a claim not of the form is the offering step's error, shown there
    return out


def _place(ctx: Any, case_id: str, params: FieldCheck) -> None:
    cat = facts.catalogue(params.catalogue)
    step = ctx.step.id
    for from_step, claim in _offered(ctx):
        key = _claim_key(from_step, claim)
        with store.connect() as c:
            if c.execute("SELECT 1 FROM field_check_claims WHERE case_id=? AND step_id=? AND claim_key=?",
                         (case_id, step, key)).fetchone():
                continue
            keys = {r["unit_key"]: r["unit_id"] for r in c.execute(
                "SELECT unit_key, unit_id FROM field_check_units WHERE case_id=? AND step_id=?", (case_id, step))}
        unit_id = keys.get(claim.unit)
        current_unit = assessed_units.unit(case_id, step, unit_id) if unit_id else None
        has_current = bool(current_unit) and claim.fact in current_unit["facts"]
        top = claim.level == cat.levels[0]
        inputs = {"catalogue": cat.id, "fact": claim.fact, "value": claim.value, "unit_found": unit_id is not None,
                  "parent_found": claim.parent in keys if claim.parent else False, "top": top, "has_current": has_current,
                  "current": current_unit["facts"].get(claim.fact) if current_unit else None, "unit": claim.unit,
                  "level": claim.level, "from_step": from_step}
        try:
            where = placement(cat, fact=claim.fact, value=claim.value, unit_found=inputs["unit_found"],
                              parent_found=inputs["parent_found"], top=top, has_current=has_current, current=inputs["current"])
        except (facts.FactError, KeyError):
            where = "unplaced"  # a fact the catalogue does not have, or a value not of its type: nothing is guessed
        source = {claim.fact: {"value": claim.value, "original": claim.original, "source": claim.source.model_dump(mode="json"),
                               "interpretation": {"reading": claim.reading}}}
        try:
            if where == "new_unit":
                unit_id = assessed_units.add(case_id, step, cat.id, level=claim.level, parent_id=keys.get(claim.parent or ""),
                                             facts={claim.fact: claim.value}, sources=source, actor=ctx.actor)
            elif where == "filled":
                assert current_unit is not None
                assessed_units.save(case_id, step, cat.id, unit_id, facts={**current_unit["facts"], claim.fact: claim.value},
                                    sources=source, actor=ctx.actor, expected_state=current_unit["state"],
                                    note=f"offered by {from_step}")
        except (facts.FactError, ValueError, decisions.RevisionConflict):
            where = "unplaced"
        with store.connect() as c:
            store.begin_immediate(c)
            if where == "new_unit":
                c.execute("INSERT INTO field_check_units(case_id, step_id, unit_key, unit_id) VALUES (?,?,?,?) ON CONFLICT DO NOTHING",
                          (case_id, step, claim.unit, unit_id))
            c.execute("INSERT INTO field_check_claims(case_id, step_id, claim_key, from_step, unit_key, fact, value,"
                      " placement, unit_id, placed_at) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                      (case_id, step, key, from_step, claim.unit, claim.fact, json.dumps(claim.value, ensure_ascii=False),
                       where, unit_id, _now()))
            trace.record_in(c, POINT, subject=("field_check", f"{case_id}:{step}"), inputs=inputs, outcome=where,
                            keys={f"facts_{cat.id}.json": [claim.fact]}, case_id=case_id)


# --- the step ------------------------------------------------------------------------------------------------------------


def _run(ctx: Any, params: FieldCheck) -> kinds.StepOutcome:
    from jav.app import process_runtime

    case_id = str(ctx.data["container"])
    _place(ctx, case_id, params)
    if (why := process_runtime.outdated(case_id, ctx.step.id)) is not None:
        reopen(case_id, ctx.step.id, note=why, actor=ctx.actor)  # a step it built on changed: frozen again
    approval = package_release.own_approval(case_id, step=ctx.step.id)
    if approval["active"] is None:
        if not approval["versions"]:  # its first round; a reopened version opened its task again
            with ctx.transaction() as c:
                human_tasks.own_approval_waits(c, case_id, ctx.step.id)
        return ctx.wait("freeze", timer=("check", time.time() + POLL_S))
    version = approval["active"]["version"]
    content = package_release.own_version(case_id, version, step=ctx.step.id)["content"]
    return kinds.Done({"version": version, "product": content["product"], "catalogue": content["catalogue"],
                       "cover_start": content["cover_start"],
                       "units": assessed_units.reference(case_id, ctx.step.id).model_dump(mode="json")})


def _params(case_id: str, step: str, c: Any) -> FieldCheck:
    from jav.core.process import cases

    case = cases.find_case_in(c, case_id)
    if case is None:
        raise KeyError(case_id)
    return FieldCheck.model_validate({k: v for k, v in cases.definition_of(case).step(step).params.items() if not k.startswith("_")})


def view(case_id: str, step: str) -> dict[str, Any]:
    """What a person checks: the units with their sources, the claims and where each went (the conflicts still open:
    the unit's value differs from the claim's), the approval and the state to send back with a freeze."""
    units = assessed_units.units(case_id, step, include_removed=True)
    by_id = {u["unit_id"]: u for u in units}
    with store.connect() as c:
        claims = [dict(r) for r in c.execute("SELECT claim_key, from_step, unit_key, fact, value, placement, unit_id, placed_at,"
                                             " kept_by, kept_at FROM field_check_claims WHERE case_id=? AND step_id=?"
                                             " ORDER BY placed_at", (case_id, step))]
        state = assessed_units.state_in(c, case_id, step)
    for claim in claims:
        claim["value"] = json.loads(claim["value"])
        unit = by_id.get(claim["unit_id"] or "")
        kept_by, kept_at = claim.pop("kept_by"), claim.pop("kept_at")
        claim["kept"] = {"by": kept_by, "at": kept_at} if kept_by else None  # U1: settled by keeping the value shown
        claim["open"] = (claim["placement"] == "conflict" and bool(unit) and unit["facts"].get(claim["fact"]) != claim["value"]
                         and not kept_by)
    return {"units": units, "claims": claims, "approval": package_release.approval_state(case_id, step=step), "state": state}


def keep(case_id: str, step: str, claim_key: str, *, actor: identity.Who) -> None:
    """U1: a person keeps the value shown instead of the one the claim offers (an open disagreement): settled in their
    name and journaled. A claim that is no open disagreement is refused."""
    if not any(c["claim_key"] == claim_key and c["open"] for c in view(case_id, step)["claims"]):
        raise explained(FieldCheckError, "there is no open disagreement to settle here")
    who = identity.who(actor)
    with store.connect() as c:
        store.begin_immediate(c)
        c.execute("UPDATE field_check_claims SET kept_by=?, kept_by_id=?, kept_at=? WHERE case_id=? AND step_id=?"
                  " AND claim_key=?", (who.name, who.id, _now(), case_id, step, claim_key))
        decisions.record(c, KEPT, f"{case_id}:{step}:{claim_key}", "keep", actor=actor, workpackage_id=case_id)


def freeze(case_id: str, step: str, *, cover_start: str | date, expected_state: int | None, actor: identity.Who) -> dict[str, Any]:
    """The units as they are now, frozen as the step's next own version: the checked input for the product version the
    case kept and the day cover starts. A page that shows another state of the units is refused (`RevisionConflict`);
    a fact that does not fit its catalogue is refused with what is wrong (`facts.FactError`)."""
    from jav.app import process_runtime

    with store.connect() as c:
        store.begin_immediate(c)
        params = _params(case_id, step, c)
        if expected_state is not None and assessed_units.state_in(c, case_id, step) != expected_state:
            raise explained(decisions.RevisionConflict, "the units changed meanwhile; reload them")
        if not assessed_units.units_in(c, case_id, step):
            raise explained(FieldCheckError, "there is no unit to freeze")
        checked = assessed_units.checked_input_in(c, case_id, step, params.catalogue, product=params.product,
                                                  cover_start=cover_start)
        content = checked.model_dump(mode="json")
        fingerprint = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        n = package_release.approve_own(c, case_id, event="field_check", content=content, fingerprint=fingerprint, locks=[], actor=actor,
                                        files=lambda _c, _n: None, details={"units": len(checked.units),
                                                                             "cover_start": str(checked.cover_start)},
                                        step=step, basis=process_runtime.basis_of(case_id, step, c))
    return {"version": n, "fingerprint": fingerprint}


def reopen(case_id: str, step: str, *, note: str, actor: identity.Who) -> int | None:
    """The frozen version that holds reopened with the reason; the steps after it run again once it is frozen anew."""
    with store.connect() as c:
        store.begin_immediate(c)
        return package_release.reopen_logged(c, case_id, event="field_check", note=note, actor=actor, step=step)


# --- the person's actions (D-f2) ----------------------------------------------------------------------------------------


class _Form(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FreezeForm(_Form):
    cover_start: date = Field(title="Cover starts")  # 261 (B1g): a field the shared form shows
    expected_state: int  # the state of the units the page showed


class UnitAddForm(_Form):
    level: str
    parent_id: str | None = None
    facts: dict[str, Any]
    note: str | None = None


class UnitSaveForm(_Form):
    unit_id: str
    facts: dict[str, Any]
    expected_state: int  # the unit's state the page showed
    note: str | None = None


class KeepForm(_Form):
    claim_key: str = Field(min_length=1)  # U1: the disagreement whose value shown is kept


class UnitRemoveForm(_Form):
    unit_id: str
    reason: str = Field(min_length=1)
    expected_state: int


def _catalogue(case_id: str, step: str) -> str:
    with store.connect() as c:
        return _params(case_id, step, c).catalogue


def _open(case_id: str, step: str) -> bool:
    """The check waits for its freeze: its units may change."""
    from jav.core.process import cases

    with store.connect() as c:
        row = cases.find_step_in(c, case_id, step)
    return bool(row) and row["state"] == cases.RUNNING and package_release.own_approval(case_id, step=step)["active"] is None


def _frozen(case_id: str, step: str) -> bool:
    return package_release.own_approval(case_id, step=step)["active"] is not None


def _freeze_start(case_id: str, step: str) -> dict[str, Any]:
    """261 (B1g): the freeze's form as the shared form starts it: the day cover starts the units give (or the last
    freeze's), the units' state the page shows (which the freeze checks), and why it cannot be sent while a
    disagreement is open."""
    shown = view(case_id, step)
    open_claims = sum(1 for c in shown["claims"] if c["open"])
    return {"values": {"cover_start": _cover_start_hint(case_id, step, shown), "expected_state": shown["state"]},
            "blocked": "Settle the disagreements first." if open_claims else None}


def _reopen_action(case_id: str, step: str, actor: identity.Who, note: str | None) -> None:
    if not note:
        raise explained(FieldCheckError, "reopening needs a reason")
    reopen(case_id, step, note=note, actor=actor)


ACTIONS = (
    capabilities.form_action("freeze", "Freeze the facts", _open, FreezeForm,
                             lambda case_id, step, actor, v: freeze(case_id, step, cover_start=v.cover_start,
                                                                     expected_state=v.expected_state, actor=actor),
                             prefill=_freeze_start),
    capabilities.Action("reopen", "Reopen the check", _frozen, _reopen_action, on_done=True),
    capabilities.form_action("unit_add", "Add a unit", _open, UnitAddForm,
                             lambda case_id, step, actor, v: assessed_units.add(
                                 case_id, step, _catalogue(case_id, step), level=v.level, parent_id=v.parent_id, facts=v.facts,
                                 actor=actor)),
    capabilities.form_action("unit_save", "Save the unit", _open, UnitSaveForm,
                             lambda case_id, step, actor, v: assessed_units.save(
                                 case_id, step, _catalogue(case_id, step), v.unit_id, facts=v.facts, actor=actor,
                                 expected_state=v.expected_state, note=v.note)),
    capabilities.form_action("keep_value", "Keep the value shown", _open, KeepForm,
                             lambda case_id, step, actor, v: keep(case_id, step, v.claim_key, actor=actor)),
    capabilities.form_action("unit_remove", "Remove the unit", _open, UnitRemoveForm,
                             lambda case_id, step, actor, v: assessed_units.remove(
                                 case_id, step, v.unit_id, reason=v.reason, actor=actor, expected_state=v.expected_state)),
)


CAPABILITY = capabilities.Capability(
    name="field_check", version=1, module=__name__, run=_run, kind="human", params=FieldCheck, state="step",
    output=CheckedResult, own_version=True, reads=lambda p: (f"facts_{p['catalogue']}",), actions=ACTIONS,
    at_start={"product": product_rules.keeper("product")}, choices={"product": product_rules.choices("product")},
    approval_what="Check and freeze the facts",
    summary="A person checks the assessed units and their sources, with the facts other steps offer, and freezes them as "
            "the checked input.")


def _review(case_id: str, step: str | None, _shared: dict[str, Any]) -> dict[str, Any]:
    """D-f4: the shared field review element's data for a field check: the units with their sources, the claims (the
    conflicts still open, those not placed), the catalogue (to show and edit the facts), the frozen version, and the
    page's next step while the check waits for its freeze."""
    from jav.core.process import cases

    step_id = str(step)
    shown = view(case_id, step_id)
    with store.connect() as c:
        params = _params(case_id, step_id, c)
        row = cases.find_step_in(c, case_id, step_id)
    active = shown["approval"]["active"]
    frozen = None
    if active is not None:
        content = package_release.own_version(case_id, active["version"], step=step_id)["content"]
        frozen = {"version": active["version"], "cover_start": content["cover_start"], "by": active["approved_by"],
                  "at": active["approved_at"]}
    conflicts = sum(1 for c in shown["claims"] if c["open"])
    waits = bool(row) and row["state"] == cases.RUNNING and active is None
    nxt = {"code": "facts_check", "label": "Check and freeze the facts", "stage": "review", "element": "field_review",
           "params": {"n": conflicts}} if waits else None
    return {**shown, "catalogue": facts.catalogue(params.catalogue).model_dump(mode="json"), "frozen": frozen,
            "conflicts": conflicts, "waits": waits, "next": nxt, "cover_start_hint": _cover_start_hint(case_id, step_id, shown)}


def _cover_start_hint(case_id: str, step: str, shown: dict[str, Any]) -> str | None:
    """U1 (the walkthrough of 2026-10-28): the day cover starts the freeze offers to begin with: the one a unit's facts
    give (a document read it), else the one the check was last frozen with (it was reopened); a person changes it."""
    for unit in shown["units"]:
        if not unit.get("removed") and isinstance(unit["facts"].get("cover_start"), str):
            return str(unit["facts"]["cover_start"])
    versions = shown["approval"].get("versions") or []
    if not versions:
        return None
    latest = max(int(v["version"]) for v in versions)
    return str(package_release.own_version(case_id, latest, step=step)["content"].get("cover_start") or "") or None


def register() -> None:
    from jav.app import case_views

    capabilities.register(CAPABILITY)
    case_views.register(case_views.ElementData("field_review", None, __name__, _review, applies=lambda cap: cap == "field_check"))
