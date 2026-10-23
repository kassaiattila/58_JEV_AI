"""Recipes and their assignment to a work package (202, plan G-core-generalisation M3b; until then part of
`jav/work.py`): the versioned recipes of `configs/recipes.json`, their parameters and engine, and the assignment
history with `expected_revision`.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from jav import typepack
from jav.core import cfg, store
from jav.core.user_messages import explained
from jav.core.clock import utc_stamp as _now
from jav import work


def recipes() -> list[dict[str, Any]]:
    """Every recipe, whatever its status (080): `active` is offered in the UI, `internal` (a given document type
    without recognition) only on the command line and in tests, `retired` stays readable for old runs and
    assignments but cannot be assigned again."""
    return list(cfg.load("recipes")["recipes"])


def recipe_status(r: dict[str, Any]) -> str:
    return r.get("status", "active")


def active_recipes() -> list[dict[str, Any]]:
    return [r for r in recipes() if recipe_status(r) == "active"]


def default_recipe() -> dict[str, Any]:
    """080: the processing every package gets unless it says otherwise (the first active recipe)."""
    return active_recipes()[0]


def recipe(recipe_id: str) -> dict[str, Any]:
    for r in recipes():
        if r["id"] == recipe_id:
            return r
    raise explained(ValueError, "unknown recipe {{recipe_id}}", recipe_id=repr(recipe_id))


def carried_params(r: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """080: the settings of an old assignment that the recipe `r` also has (path, JEV reuse, Azure, task proposal),
    the rest with `r`'s defaults. A given document type is dropped: the processing recognises it."""
    return _validated_params(r, {k: v for k, v in params.items() if k in r["params"]})


ENGINE_JEV = {"jev": "on", "gpt": "off"}  # 160-D: the AI engine as the recipes' `jev` setting


def engine_params(r: dict[str, Any], engine: str | None = None) -> dict[str, str]:
    """160-D (plan F-csak-gpt Sz4): the engine setting a new processing setting gets when it does not name one:
    `engine`, or the application's (`app_settings.engine_default`). Empty for a recipe without the setting."""
    if "jev" not in r["params"]:
        return {}
    if engine is None:
        from jav import app_settings  # it imports this module

        engine = app_settings.engine_default()
    return {"jev": ENGINE_JEV[engine]}


def default_params(r: dict[str, Any], engine: str | None = None) -> dict[str, Any]:
    """The settings of a package without saved ones: the recipe's defaults with the application's engine (or
    `engine`, a workflow step's own)."""
    return _validated_params(r, engine_params(r, engine))


def recipe_hash(r: dict[str, Any]) -> str:
    return hashlib.sha256(work._canon(r).encode("utf-8")).hexdigest()[:16]


def _validated_params(r: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    unknown = set(params) - set(r["params"])
    if unknown:
        raise explained(ValueError, "unknown params: {{unknown}}", unknown=sorted(unknown))
    for name, spec in r["params"].items():
        value = params.get(name, spec.get("default"))
        allowed = spec.get("allowed") or (typepack.extractable_keys() if spec.get("allowed_from") == "typepacks" else None)
        if allowed is not None and value not in allowed:
            raise explained(ValueError, "param {{name}}={{value}} not in {{allowed}}",
                            name=name, value=repr(value), allowed=sorted(allowed))
        out[name] = value
    return out


def current_assignment(wp_id: str, c: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """`c`: an open connection (inside a write transaction, so the new row is visible)."""
    if c is None:
        with store.connect() as c:
            return current_assignment(wp_id, c)
    row = c.execute("SELECT * FROM recipe_assignments WHERE workpackage_id=? ORDER BY revision DESC LIMIT 1", (wp_id,)).fetchone()
    return {**dict(row), "params": json.loads(row["params"])} if row else None


def assignment_history(wp_id: str) -> list[dict[str, Any]]:
    with store.connect() as c:
        rows = c.execute("SELECT * FROM recipe_assignments WHERE workpackage_id=? ORDER BY revision", (wp_id,)).fetchall()
    return [{**dict(r), "params": json.loads(r["params"])} for r in rows]


def assign_recipe(wp_id: str, recipe_id: str, *, params: dict[str, Any], expected_revision: int, actor: str,
                  note: str | None = None) -> dict[str, Any]:
    """The assignment gets its own revision (the V4 `expected_revision` pattern); earlier ones stay as history. A
    retired recipe (080) cannot be assigned again. 160-D: a setting that does not name the engine takes the
    application's."""
    r = recipe(recipe_id)
    if recipe_status(r) == "retired":
        raise explained(work.RetiredRecipe, "recipe {{recipe_id}} is retired; assign {{id}} instead",
                        recipe_id=repr(recipe_id), id=repr(default_recipe()["id"]))
    clean = _validated_params(r, {**engine_params(r), **params})
    with store.connect() as c:
        work._begin(c)
        if c.execute("SELECT 1 FROM workpackages WHERE id=?", (wp_id,)).fetchone() is None:
            raise KeyError(wp_id)
        _insert_assignment(c, wp_id, r, clean, expected_revision=expected_revision, actor=actor, note=note)
    return current_assignment(wp_id)


def _insert_assignment(c, wp_id: str, r: dict[str, Any], params: dict[str, Any], *, expected_revision: int, actor: str,
                       note: str | None) -> int:
    cur = c.execute("SELECT MAX(revision) m FROM recipe_assignments WHERE workpackage_id=?", (wp_id,)).fetchone()["m"] or 0
    if cur != expected_revision:
        raise explained(work.RevisionConflict, "assignment of {{wp_id}} is at revision {{cur}}, not {{expected_revision}}",
                        wp_id=wp_id, cur=cur, expected_revision=expected_revision)
    c.execute("INSERT INTO recipe_assignments VALUES (?,?,?,?,?,?,?,?,?)",
              (wp_id, cur + 1, r["id"], r["version"], recipe_hash(r), work._canon(params), actor, note, _now()))
    return cur + 1


MIGRATION_ACTOR = "rendszer"  # data: the actor of the 080 migration in the assignment history (shown in the UI)


def migrate_assignments(*, write: bool) -> list[dict[str, Any]]:
    """080 (owner's decision of 2026-10-01: automatic migration): every package whose current assignment is not an
    active recipe moves onto the default processing, keeping its settings (`carried_params`); hidden packages too.
    Without `write` it only lists what it would do. Repeatable: a package already on the active recipe is left alone.
    Old runs keep their own recipe snapshot."""
    target = default_recipe()
    with store.connect() as c:
        rows = c.execute("SELECT a.* FROM recipe_assignments a WHERE a.revision = (SELECT MAX(revision) FROM recipe_assignments b"
                         " WHERE b.workpackage_id = a.workpackage_id) ORDER BY a.workpackage_id").fetchall()
    out = []
    for row in rows:
        old = recipe(row["recipe_id"])
        if recipe_status(old) == "active":
            continue
        params = json.loads(row["params"])
        new = carried_params(target, params)
        doc_type = f", típus: {params['doc_type']}" if params.get("doc_type") else ""
        # data (the assignment history, shown in the UI as written), not a label
        note = f"080: átállítás az egységes feldolgozásra (előtte: {old['title']}, {old['version']}. változat{doc_type})"
        out.append({"workpackage_id": row["workpackage_id"], "from": row["recipe_id"], "from_params": params, "params": new,
                    "revision": row["revision"] + 1, "note": note})
        if write:
            with store.connect() as c:
                work._begin(c)
                _insert_assignment(c, row["workpackage_id"], target, new, expected_revision=row["revision"],
                                   actor=MIGRATION_ACTOR, note=note)
    return out
