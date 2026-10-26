"""The units a case's step assesses (231, stage D, D-b4; the reassessment after D0 of 2026-10-26, P06, P10).

Plain-language summary: a step that assesses something (a policyholder, its sites, their asset groups) keeps its units
with durable ids. A correction keeps the id; every change is a row of the decision journal with the facts and their
sources, so an earlier value and where it came from stay visible. A change made on an older state is refused (the page
reloads), a removed unit stays visible and takes no correction, and a fact that does not fit the catalogue
(`jav/app/facts.py`) writes nothing. The units list page by page (the dataset `assessed_units`); a case's summary
carries a reference to the list (`reference`), never its rows. The checked input a person accepts is frozen from the
units (`checked_input`), and a later correction does not change it.

- `add`, `save`, `remove`: the changes (`expected_state`: the unit's journal state the page read).
- `unit`, `units`, `history`, `state`, `reference`, `checked_input`: the reads.

Layer: application; it names no process and no business.
"""

from __future__ import annotations

import json
import secrets
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from jav.app import capabilities, datasets, facts
from jav.app.tablequery import Column
from jav.core import decisions, identity, store
from jav.core.clock import utc_stamp as _now
from jav.core.user_messages import explained

__all__ = ["KIND", "UnitRemoved", "UnknownUnit", "add", "checked_input", "history", "reference", "register", "remove",
           "save", "state", "unit", "units"]

KIND = "assessed_unit"
DATASET = "assessed_units"
decisions.register(decisions.Kind(KIND, ("add", "save", "remove"), __name__))

store.register_schema("assessed_units", """
CREATE TABLE IF NOT EXISTS assessed_units (
    case_id    TEXT NOT NULL,
    step_id    TEXT NOT NULL,
    unit_id    TEXT NOT NULL,            -- durable: a correction keeps it
    catalogue  TEXT NOT NULL,            -- the fact catalogue its facts are typed by (configs/facts_<id>.json)
    level      TEXT NOT NULL,
    parent_id  TEXT,
    facts      TEXT NOT NULL,            -- JSON {fact: value}, as the catalogue types it
    sources    TEXT NOT NULL,            -- JSON {fact: source claim}
    removed    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (case_id, step_id, unit_id)
);
""")


class UnknownUnit(KeyError):
    """No such unit in the case's step."""


class UnitRemoved(ValueError):
    """The unit was removed: it stays visible and takes no correction."""


def _key(case_id: str, step_id: str, unit_id: str) -> str:
    return f"{case_id}:{step_id}:{unit_id}"


def _plain(value: Any) -> Any:
    """A typed value as JSON."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    return value


def _checked(c: Any, case_id: str, step_id: str, catalogue_id: str, level: str, parent_id: str | None,
             values: dict[str, Any], sources: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The facts typed and the sources read, with the parent of the level above (`FactError` otherwise)."""
    cat = facts.catalogue(catalogue_id)
    if level not in cat.levels:
        raise facts.FactError(f"no level {level!r} in the catalogue {cat.id}")
    rank = cat.levels.index(level)
    if parent_id is None and rank:
        raise facts.FactError(f"a {level} has a parent, a {cat.levels[rank - 1]}")
    if parent_id is not None:
        parent = _row(c, case_id, step_id, parent_id)
        if parent is None or parent["removed"]:
            raise facts.FactError(f"no unit {parent_id} to be the parent")
        if not rank or parent["level"] != cat.levels[rank - 1]:
            raise facts.FactError(f"a {level}'s parent is a {cat.levels[rank - 1] if rank else 'none'}, not a {parent['level']}")
    typed = {name: _plain(facts.typed_fact(cat, name, level, value)) for name, value in values.items()}
    claims = {name: facts.SourceClaim.model_validate(claim).model_dump(mode="json") for name, claim in sources.items()
              if name in typed}
    return typed, claims


def _row(c: Any, case_id: str, step_id: str, unit_id: str) -> Any:
    return c.execute("SELECT * FROM assessed_units WHERE case_id=? AND step_id=? AND unit_id=?",
                     (case_id, step_id, unit_id)).fetchone()


def add(case_id: str, step_id: str, catalogue_id: str, *, level: str, parent_id: str | None, facts: dict[str, Any],
        actor: identity.Who, sources: dict[str, Any] | None = None) -> str:
    """A new unit of the step; its id."""
    values = facts
    unit_id = "u-" + secrets.token_hex(5)
    with store.connect() as c:
        store.begin_immediate(c)
        typed, claims = _checked(c, case_id, step_id, catalogue_id, level, parent_id, values, sources or {})
        now = _now()
        c.execute("INSERT INTO assessed_units(case_id, step_id, unit_id, catalogue, level, parent_id, facts, sources, created_at,"
                  " updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (case_id, step_id, unit_id, catalogue_id, level, parent_id, json.dumps(typed, ensure_ascii=False),
                   json.dumps(claims, ensure_ascii=False), now, now))
        decisions.record(c, KIND, _key(case_id, step_id, unit_id), "add", actor=actor, workpackage_id=case_id,
                         value={"level": level, "parent_id": parent_id, "facts": typed, "sources": claims})
    return unit_id


def save(case_id: str, step_id: str, catalogue_id: str, unit_id: str, *, facts: dict[str, Any], actor: identity.Who,
         expected_state: int | None, sources: dict[str, Any] | None = None, note: str | None = None) -> dict[str, Any]:
    """The unit's facts as given (its sources: the earlier ones, with these over them); the unit as it is now."""
    values = facts
    with store.connect() as c:
        store.begin_immediate(c)
        row = _row(c, case_id, step_id, unit_id)
        if row is None:
            raise UnknownUnit(unit_id)
        if row["removed"]:
            raise explained(UnitRemoved, "the unit was removed; it takes no correction")
        decisions.check(c, KIND, _key(case_id, step_id, unit_id), expected_state)
        merged = {**json.loads(row["sources"]), **(sources or {})}
        typed, claims = _checked(c, case_id, step_id, catalogue_id, row["level"], row["parent_id"], values, merged)
        c.execute("UPDATE assessed_units SET facts=?, sources=?, updated_at=? WHERE case_id=? AND step_id=? AND unit_id=?",
                  (json.dumps(typed, ensure_ascii=False), json.dumps(claims, ensure_ascii=False), _now(), case_id, step_id,
                   unit_id))
        decisions.record(c, KIND, _key(case_id, step_id, unit_id), "save", actor=actor, workpackage_id=case_id, note=note,
                         value={"facts": typed, "sources": claims})
    return unit(case_id, step_id, unit_id)


def remove(case_id: str, step_id: str, unit_id: str, *, reason: str, actor: identity.Who, expected_state: int | None) -> None:
    """The unit removed with a reason; it stays visible."""
    if not reason.strip():
        raise ValueError("removing a unit needs a reason")
    with store.connect() as c:
        store.begin_immediate(c)
        if _row(c, case_id, step_id, unit_id) is None:
            raise UnknownUnit(unit_id)
        decisions.check(c, KIND, _key(case_id, step_id, unit_id), expected_state)
        c.execute("UPDATE assessed_units SET removed=1, updated_at=? WHERE case_id=? AND step_id=? AND unit_id=?",
                  (_now(), case_id, step_id, unit_id))
        decisions.record(c, KIND, _key(case_id, step_id, unit_id), "remove", actor=actor, workpackage_id=case_id, note=reason)


def _view(c: Any, row: Any) -> dict[str, Any]:
    return {"unit_id": row["unit_id"], "catalogue": row["catalogue"], "level": row["level"], "parent_id": row["parent_id"],
            "facts": json.loads(row["facts"]), "sources": json.loads(row["sources"]), "removed": bool(row["removed"]),
            "state": decisions.state(c, KIND, _key(row["case_id"], row["step_id"], row["unit_id"]))}


def unit(case_id: str, step_id: str, unit_id: str) -> dict[str, Any]:
    with store.connect() as c:
        row = _row(c, case_id, step_id, unit_id)
        if row is None:
            raise UnknownUnit(unit_id)
        return _view(c, row)


def units(case_id: str, step_id: str, *, include_removed: bool = False) -> list[dict[str, Any]]:
    """The step's units in the order they were added."""
    with store.connect() as c:
        rows = c.execute("SELECT * FROM assessed_units WHERE case_id=? AND step_id=? ORDER BY rowid", (case_id, step_id)).fetchall()
        return [_view(c, r) for r in rows if include_removed or not r["removed"]]


def history(case_id: str, step_id: str, unit_id: str) -> list[dict[str, Any]]:
    """Every change of the unit, oldest first: what, who, when, why, with the facts and sources it recorded."""
    return decisions.history(KIND, _key(case_id, step_id, unit_id))


def state(case_id: str, step_id: str) -> int:
    """A mark that changes with any change of the case's units."""
    with store.connect() as c:
        return decisions.package_state(c, case_id, (KIND,))


def reference(case_id: str, step_id: str) -> capabilities.DatasetRef:
    """How a result names the step's units: the dataset, its scope and the state it lists, not the rows."""
    return capabilities.DatasetRef(dataset=DATASET, scope={"case_id": case_id, "step_id": step_id},
                                   version=str(state(case_id, step_id)))


def checked_input(case_id: str, step_id: str, catalogue_id: str, *, product: str, cover_start: str | date) -> facts.CheckedInput:
    """The units as they are now, frozen as a checked input (a later correction does not change it)."""
    rows = units(case_id, step_id)
    return facts.checked_input({"catalogue": catalogue_id, "product": product, "cover_start": str(cover_start),
                                "units": [{k: u[k] for k in ("unit_id", "level", "parent_id", "facts", "sources")} for u in rows]})


def _summary(values: dict[str, Any]) -> str:
    def shown(v: Any) -> str:
        if isinstance(v, dict) and "amount" in v:
            return f"{v['amount']} {v['currency']}"
        if isinstance(v, dict) and "unit" in v:
            return f"{v['value']} {v['unit']}"
        if isinstance(v, dict) and "per" in v:
            return f"{v['value']}/{v['per']}"
        return ", ".join(v) if isinstance(v, list) else str(v)

    return "; ".join(f"{k}: {shown(v)}" for k, v in values.items())


def _rows(scope: dict[str, str]) -> datasets.Rows:
    cols: list[Column] = [datasets.col("unit_id", "Unit", "code"), datasets.col("level", "Level"),
                          datasets.col("parent_id", "Parent", "code"), datasets.col("facts", "Facts"),
                          datasets.col("removed", "Removed", "bool")]
    rows = [{"unit_id": u["unit_id"], "level": u["level"], "parent_id": u["parent_id"], "facts": _summary(u["facts"]),
             "removed": u["removed"], "_key": u["unit_id"]}
            for u in units(scope["case_id"], scope["step_id"], include_removed=True)]
    return cols, rows


def _fingerprint(scope: dict[str, str]) -> str:
    return str(state(scope["case_id"], scope["step_id"]))


# made once, so a repeated registration gives the same dataset
_DATASET = datasets.Dataset(DATASET, "Assessed units", ("case_id", "step_id"), _rows, fingerprint=_fingerprint)


def register() -> None:
    datasets.register(_DATASET, after="cases", module=__name__)
