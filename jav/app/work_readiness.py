"""A work package's readiness and a run's plan (202, plan G-core-generalisation M3b; until then part of
`jav/app/work.py`): the pinned input snapshot, the per-item budget and engine, the path and flow of each item, and the
blockers and warnings before a start.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path
from typing import Any

from jav.app import item_kinds
from jav.core import store
from jav.documents.native_contracts import NATIVE_SUFFIXES
from jav import flows
from jav.app import work, work_recipes, work_runs


def _input_snapshot(wp: dict[str, Any], items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The frozen input of a run: the package's items in use, or only `items` (160-C S3: the pending ones)."""
    frozen = [{"item_id": i["item_id"], "kind": i["kind"], "source_path": i["source_path"], "sha256": i["sha256"],
               **({"parent_item_id": i["parent_item_id"]} if i.get("parent_item_id") else {}),
               **({"instance": i["instance"]} if i.get("instance") else {})} for i in (wp["items"] if items is None else items)]
    return {"workpackage_id": wp["id"], "workpackage_revision": wp["revision"], "items": frozen}


def _snapshot_hash(snapshot: dict[str, Any]) -> str:
    """The identifier of the frozen input (the `input_hash` of readiness)."""
    return hashlib.sha256(work._canon(snapshot).encode("utf-8")).hexdigest()[:16]


def item_budget(r: dict[str, Any], params: dict[str, Any], kind: str | None = None, arm: str | None = None) -> dict[str, Decimal]:
    """The budget maximum of one item. A recipe handling several item kinds (058 K5.2) gives a budget per kind
    (`max_item_usd_by_kind`); where there is no path, the `*` row applies. `arm` (066 Á07): the item's actual path,
    known in advance; without it, the row of the requested path (a requested S path runs on G for a G-only type, which
    needs the G row)."""
    table = (r.get("max_item_usd_by_kind") or {}).get(kind or "") or r["max_item_usd"]
    per = table.get(arm or params.get("arm", "*"), table.get(params.get("arm", "*"), table.get("*", {})))
    out = {provider: Decimal(v) for provider, v in per.items()}
    drop: set[str] = set()
    for extra in r.get("param_item_usd") or []:  # 058 K5.3: parameter-bound extra (e.g. task proposal on the email)
        # 075: a parameter missing from an older assignment counts with the recipe's default (e.g. the Azure switch)
        value = params.get(extra["param"], (r.get("params", {}).get(extra["param"]) or {}).get("default"))
        if value == extra["value"] and extra.get("kind") in (None, kind):
            for provider, v in extra["usd"].items():
                out[provider] = out.get(provider, Decimal(0)) + Decimal(v)
            drop.update(extra.get("drop") or ())  # 086: e.g. without JEV the item has no JEV budget at all
    return {provider: v for provider, v in out.items() if provider not in drop}


def jev_off(r: dict[str, Any], params: dict[str, Any]) -> bool:
    """086: processing without JEV (the `jev` setting off): every document on the G path, the type recognised by GPT,
    no JEV budget."""
    return params.get("jev", (r.get("params", {}).get("jev") or {}).get("default", "on")) == "off"


def run_engine(run: dict[str, Any]) -> str:
    """160-D (plan F-csak-gpt L6, decision 160 D3): the AI engine a run ran with, from its frozen recipe and settings:
    `gpt` (GPT only) when its `jev` setting is off, `jev` (JEV and GPT) otherwise, a recipe without the setting
    included. The approval and the review show it with the results."""
    return "gpt" if jev_off(run["recipe"], run["params"]) else "jev"


def run_budget(r: dict[str, Any], params: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Decimal]:
    """The run's budget maximum: the sum of the items' budgets (per item kind, 058 K5.2).

    Decision 065: the reservation follows the actual path. Where the item's path is known in advance and is S
    (candidate finder + JEV), there is no OpenAI reservation: on the invoice recipe from the given type, in document
    processing from the detailed type already detected earlier. For a document of unknown type the worst case stays.
    If the path still turns out to be G (e.g. a different type is detected), the GPT call does not start because of
    the budget, and the item gets a to-do (`llm:failed:BudgetExceeded`)."""
    return _run_budget(r, params, items, _item_arms(r, params, items))


def _item_extras(r: dict[str, Any], params: dict[str, Any], item: dict[str, Any]) -> list[tuple[Any, int]]:
    """192 (B6c): the budget extras the domains count on the item that the recipe's settings price now: (extra, its
    units on the item)."""
    return [(e, n) for e in item_kinds.item_extras(item.get("kind") or "")
            if _extras(r, params, e.extra) and (n := e.count(item))]


def _extra_counts(r: dict[str, Any], params: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        for e, n in _item_extras(r, params, i):
            out[e.plan_key] = out.get(e.plan_key, 0) + n
    return out


def _extras(r: dict[str, Any], params: dict[str, Any], kind: str) -> dict[str, Decimal]:
    """192: the parameter-bound extras of a kind that is no item (an email's table attachment), without a base budget."""
    out: dict[str, Decimal] = {}
    for extra in r.get("param_item_usd") or []:
        value = params.get(extra["param"], (r.get("params", {}).get(extra["param"]) or {}).get("default"))
        if value == extra["value"] and extra.get("kind") == kind:
            for provider, v in extra["usd"].items():
                out[provider] = out.get(provider, Decimal(0)) + Decimal(v)
    return out


def _run_budget(r: dict[str, Any], params: dict[str, Any], items: list[dict[str, Any]],
                arms: list[str | None]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for i, arm in zip(items, arms, strict=True):
        if native_flow(r, i):
            from jav.ai.native_processing import estimate_limits

            per = dict(estimate_limits(params).provider_limits_usd) if params.get("arm") != "S" else {}
        else:
            per = item_budget(r, params, i.get("kind"), arm=arm)
            # 192 (B6c): what the domains count on the item (an email's table attachments), each unit priced
            for extra, n in _item_extras(r, params, i):
                for provider, v in _extras(r, params, extra.extra).items():
                    per[provider] = per.get(provider, Decimal(0)) + v * n
        if arm == "S":
            per.pop("openai", None)
        for provider, v in per.items():
            out[provider] = out.get(provider, Decimal(0)) + v
    return out


def _item_arms(r: dict[str, Any], params: dict[str, Any], items: list[dict[str, Any]]) -> list[str | None]:
    from jav.ai import typepack

    packs, known = set(typepack.keys()), _known_detail_types(items)
    return [_item_arm(r, params, i, known, packs) for i in items]


def run_plan(r: dict[str, Any], params: dict[str, Any], items: list[dict[str, Any]],
             arms: list[str | None] | None = None) -> dict[str, Any]:
    """080 (the pre-start overview of F-külső-kapcsolók): what the run will do, for the UI to explain the budget per
    provider. Documents (attachments counted separately too) by their path known in advance (S / G / type not known
    yet), emails, emails that get a task proposal, whether Azure may be used and whether earlier JEV answers are
    reused. The budget itself is `run_budget`."""
    arms = _item_arms(r, params, items) if arms is None else arms

    def value(name: str) -> Any:
        return params.get(name, (r.get("params", {}).get(name) or {}).get("default"))

    docs = [(i, a) for i, a in zip(items, arms, strict=True) if item_kinds.of(i).detected]
    paths = {"S": 0, "G": 0, "unknown": 0}
    for _i, a in docs:
        paths[a if a in ("S", "G") else "unknown"] += 1
    # 177: each item kind under its own key, in the registry's order (a table statement, 136: code, free, only if any)
    counts = {k.plan_key: sum(1 for i in items if item_kinds.of(i) is k) for k in item_kinds.ITEM_KINDS}
    emails = counts[item_kinds.of(item_kinds.EMAIL).plan_key]
    plan = {**{k.plan_key: counts[k.plan_key] for k in item_kinds.ITEM_KINDS if k.plan_always or counts[k.plan_key]},
            "attachments": sum(1 for i, _a in docs if i.get("parent_item_id")), "paths": paths,
            "tasks_emails": emails if value("tasks") == "propose" else 0,
            "text_emails": emails if value("email_text") == "extract" else 0,  # 190: a quote request in the email
            # 192 (B6c): what the domains count on the items as a budget extra (an email's table attachments), while any
            **_extra_counts(r, params, items),
            "azure": value("azure_ocr") == "on" and any(not native_flow(r, i) for i, _a in docs),
            "jev_reuse": value("jev_cache") != "live",
            "arm": value("arm"),  # 082: with S chosen, a document on the G path has a type without a JEV path
            "jev": not jev_off(r, params)}  # 086: without JEV, GPT recognises the type and every document runs on G
    if r.get("flows_by_suffix"):
        plan.update(native_documents=sum(native_flow(r, i) for i, _a in docs),
                    item_flows={i["item_id"]: flow_for(r, i) for i in items})
    return plan


def _known_detail_types(items: list[dict[str, Any]]) -> dict[str, str]:
    """The detailed type of documents already detected (content hash → type), from the `documents` table (065)."""
    ids = [i["sha256"] for i in items if item_kinds.of(i).detected and i.get("sha256")]
    out: dict[str, str] = {}
    with store.connect() as c:
        for k in range(0, len(ids), 500):
            chunk = ids[k:k + 500]
            out.update({row["doc_id"]: row["detail_type"] for row in c.execute(
                f"SELECT doc_id, detail_type FROM documents WHERE detail_type IS NOT NULL AND doc_id IN ({','.join('?' * len(chunk))})", chunk)})
    return out


def _item_arm(r: dict[str, Any], params: dict[str, Any], item: dict[str, Any], known: dict[str, str], packs: set[str]) -> str | None:
    """The item's path known in advance (S / G), or None if the type is not known before the run (065)."""
    from jav.ai import typepack

    spec = flows.get(flow_for(r, item))
    if spec.native:
        return "S" if params.get("arm") == "S" else "G"
    # 173: where the document type is known before the run is the flow's registry entry
    doc_type = (params.get("doc_type") if spec.doc_type == "params"
                else known.get(item.get("sha256", "")) if spec.doc_type == "detected" else None)
    arm = "G" if jev_off(r, params) else params.get("arm", "auto")  # 086: without JEV only the G path runs
    return typepack.resolve_arm(doc_type, arm) if doc_type in packs else None


def native_flow(r: dict[str, Any], item: dict[str, Any]) -> bool:
    """173: whether the item's flow takes its budget and path from the native reader's estimate (the flow registry)."""
    return flows.get(flow_for(r, item)).native


def flow_for(r: dict[str, Any], item: dict[str, Any] | str | None) -> str:
    """Use the frozen source suffix for mixed documents (177: an item whose type is recognised from its content), then
    the recipe's item-kind routing."""
    kind = item.get("kind") if isinstance(item, dict) else item
    if isinstance(item, dict) and item_kinds.of(item).detected:
        suffix = Path(item["source_path"]).suffix.lower()
        routed = (r.get("flows_by_suffix") or {}).get(suffix)
        if routed:
            return routed
    return (r.get("flows") or {}).get(kind or "", r["flow"])


def readiness(wp_id: str, *, verify: bool = False) -> dict[str, Any]:
    """Pre-run check: blockers (cannot start) and warnings, with the hash of the input to be pinned.
    `verify=True` (at start): full re-check of the source files, without the remembered fingerprint.

    An item with a source instance is processed from the instance: only a missing or damaged instance blocks, and a
    changed or missing original is a warning. An item without one follows the original file, as before.

    080: a package without an assignment runs with the default processing and its default settings
    (`assignment_default`); starting the run saves them (`start_run`).

    153 (review B1): one connection for the whole check; a package of 468 documents opened in 4 s, as each item's
    instance and original check opened its own (944 connections)."""
    with store.session():
        return _readiness(wp_id, verify=verify)


def _readiness(wp_id: str, *, verify: bool) -> dict[str, Any]:
    wp = work.get(wp_id)
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    a = wp["assignment"]
    if not wp["items"]:
        blockers.append({"code": "no_items", "message": "Az iratkötegben nincs tétel."})
    r = work_recipes.recipe(a["recipe_id"]) if a else work_recipes.default_recipe()
    params = a["params"] if a else work_recipes.default_params(r)  # 160-D: with the application's engine
    if a is not None and work_recipes.recipe_status(r) == "retired":
        warnings.append({"code": "recipe_retired", "message": "The package uses a retired processing; switch it to the current processing settings."})
    elif a is not None and work_recipes.recipe_hash(r) != a["recipe_hash"]:
        warnings.append({"code": "recipe_changed", "message": "The processing changed since the settings were saved; save them again."})
    checks = _item_checks(r, params, wp["items"], verify=verify)
    snapshot = _input_snapshot(wp)
    arms = _item_arms(r, params, wp["items"])
    out = {"workpackage_id": wp_id, "ready": not blockers and not any(level == "blocker" for _i, level, _f in checks),
           "blockers": blockers + [f for _i, level, f in checks if level == "blocker"],
           "warnings": warnings + [f for _i, level, f in checks if level == "warning"],
           "counts": {"items": len(wp["items"])}, "budget": _run_budget(r, params, wp["items"], arms),
           "plan": run_plan(r, params, wp["items"], arms),
           "assignment_revision": a["revision"] if a else 0, "assignment_default": a is None,
           "input_hash": _snapshot_hash(snapshot)}
    if supplement := _supplements(wp, r, params, warnings, checks):
        out["supplement"] = supplement
    return out


def _item_checks(r: dict[str, Any], params: dict[str, Any], items: list[dict[str, Any]], *,
                 verify: bool) -> list[tuple[str, str, dict[str, str]]]:
    """The readiness findings of each item, in item order: (item id, "blocker" | "warning", finding)."""
    out: list[tuple[str, str, dict[str, str]]] = []
    for i in items:
        p = Path(i["source_path"])
        found: list[tuple[str, dict[str, str]]] = []
        if i["kind"] not in r["input_kinds"] or p.suffix.lower() not in r.get("file_suffixes", [p.suffix.lower()]):
            found.append(("blocker", {"code": "unsupported_item", "message": f"The processing does not handle: {p.name}"}))
        elif p.suffix.lower() in NATIVE_SUFFIXES and not native_flow(r, i):
            found.append(("blocker", {"code": "native_recipe_required", "message": f"Choose multi-format processing for: {p.name}"}))
        if native_flow(r, i) and params.get("arm") == "S":
            found.append(("blocker", {"code": "native_s_unsupported", "message": "Native documents require GPT extraction; the JEV-only path has no predefined field contract."}))
        if i.get("instance"):
            if not work._instance_ok(i, verify=verify):
                found.append(("blocker", {"code": "instance_damaged", "message": f"The copy kept when it was added is missing or damaged: {p.name}"}))
            elif (state := work.original_state(i)) != "same":
                found.append(("warning", {"code": f"original_{state}", "message": (
                    f"The original file has {'changed' if state == 'changed' else 'disappeared'} since it was added; "
                    f"the copy kept then is processed: {p.name}")}))
        elif not p.exists():
            found.append(("blocker", {"code": "source_missing", "message": f"Hiányzó forrás: {p.name}"}))
        elif work.fingerprint(p, verify=verify) != i["sha256"]:
            found.append(("blocker", {"code": "source_changed", "message": f"A forrás tartalma a felvétel óta változott: {p.name}"}))
        out += [(i["item_id"], level, finding) for level, finding in found]
    return out


def _supplements(wp: dict[str, Any], r: dict[str, Any], params: dict[str, Any], warnings: list[dict[str, str]],
                 checks: list[tuple[str, str, dict[str, str]]]) -> dict[str, dict[str, Any]]:
    """160-C S3: per mode (shadow / apply), the run over only the package's pending items, offered when a run of that
    mode has already finished some of the items in use and others are pending. Its blockers and warnings are the
    pending items' own (an earlier item's changed source does not hold it up), its budget, plan and input hash are
    theirs alone; `start_run(scope="pending")` starts it."""
    out: dict[str, dict[str, Any]] = {}
    for mode in ("shadow", "apply"):
        pending = set(work_runs.pending_items(wp["id"], mode, wp))
        if not 0 < len(pending) < len(wp["items"]):
            continue
        items = [i for i in wp["items"] if i["item_id"] in pending]
        found = [(level, f) for item_id, level, f in checks if item_id in pending]
        arms = _item_arms(r, params, items)
        out[mode] = {"items": len(items), "ready": not any(level == "blocker" for level, _f in found),
                     "blockers": [f for level, f in found if level == "blocker"],
                     "warnings": warnings + [f for level, f in found if level == "warning"],
                     "budget": _run_budget(r, params, items, arms), "plan": run_plan(r, params, items, arms),
                     "input_hash": _snapshot_hash(_input_snapshot(wp, items))}
    return out
