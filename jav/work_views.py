"""Shared views of the command line and the local service (040 K2): the same request gets the same data.

Layer: UI/CLI → **this** (application operation: read-only assemblies) → `jav.work`, `jav.corrections`,
`jav.runtime` (business rules). There are no rules here, only assembly and JSON shape: money goes out as a `Decimal`
rendered as text (not as a float), dates as ISO text.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jav import cfg, store, typepack, work
from jav.runtime import calls, worker


def jsonable(value: Any) -> Any:
    """Shared JSON shape for both interfaces: `Decimal` and dates as text, accents preserved."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def recipe_catalog(*, every_status: bool = False) -> list[dict[str, Any]]:
    """The recipes the UI offers (080: only the active processing; internal and retired recipes are not offered;
    `every_status`: all of them, for the command line): the choices taken from the type packs (`allowed_from`)
    expanded into an `allowed` list."""
    out = []
    for r in work.recipes() if every_status else work.active_recipes():
        params = {k: ({**spec, "allowed": sorted(typepack.keys())} if spec.get("allowed_from") == "typepacks" else spec)
                  for k, spec in r["params"].items()}
        out.append({**r, "params": params})
    return jsonable(out)


def recipe_help() -> dict[str, Any]:
    """063: the recipe explanations for the UI (`configs/recipe_help.json`): per recipe, when it is suitable; per
    setting and selectable value, what it means. Kept apart from the recipe so that the recipe's fingerprint does not
    change."""
    data = cfg.load("recipe_help")
    # 080: also the general introduction, the item kinds and the comparison of the paths (Settings › Processing)
    return jsonable({k: data[k] for k in ("intro", "kinds", "recipes", "paths", "params")})


def package_root(wp: dict[str, Any]) -> str | None:
    """The folder a package was read from (a folder or a watched folder), for the subfolder titles (081)."""
    return wp.get("source_ref") if wp.get("source_kind") in ("folder", "watch") else None


def item_titles(items: list[dict[str, Any]], root: str | None = None) -> dict[str, str]:
    """Readable item title for the UI (048 T2): for an email, the subject and the sender (the file name is always
    `message.json`). 081: a document in a subfolder of the package's folder (`root`) is titled with its path below
    that folder, so files with the same name in different subfolders stay apart."""
    out, subjects = {}, {}
    base = Path(root) if root else None
    for i in items:
        p = Path(i["source_path"])
        if base and i.get("kind") != "email" and not i.get("parent_item_id") and p.parent != base and p.is_relative_to(base):
            out[i["item_id"]] = p.relative_to(base).as_posix()
    for i in items:
        if i.get("kind") != "email":
            continue
        try:
            m = json.loads(Path(i["source_path"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        subjects[i["item_id"]] = (m.get("subject") or "(tárgy nélkül)")[:100]
        out[i["item_id"]] = f"{subjects[i['item_id']]} — {m.get('sender_name') or m.get('sender') or '?'}"
    for i in items:  # 058 K5.2: the attachment's origin in its name (which email it came from)
        if i.get("parent_item_id") in subjects:
            out[i["item_id"]] = f"{Path(i['source_path']).name} (a levél csatolmánya: {subjects[i['parent_item_id']]})"
    return out


ACTIVE = ("queued", "running")


def next_step(wp: dict[str, Any], last_run: dict[str, Any] | None, ready: bool | None = None) -> dict[str, Any]:
    """The package's next step (057, after the V4 `sessionAction.ts` pattern): computed in one place, shown both by the
    list column and by the button in the package header. `stage`: the package stage (process / review / result) the
    step leads to. `ready` is needed only for a package without runs (the readiness check is expensive: it computes the
    files' fingerprints)."""
    def step(code: str, label: str, stage: str, **params: Any) -> dict[str, Any]:
        # the UI translates from the code and the parameters (057 language switch); `label` is the Hungarian caption
        return {"code": code, "label": label, "stage": stage, "params": params}

    items = wp["items"] if isinstance(wp.get("items"), list) else None
    n_items = len(items) if items is not None else wp.get("items", 0)
    if not n_items:
        return step("empty", "Üres csomag", "process")
    if last_run is None:  # 080: without an assignment the default processing settings apply
        return step("start", "Próbafutás indítása", "process") if ready is not False else step("blocked", "Nem indítható", "process")
    status = last_run["status"]
    if status in ACTIVE:
        done, total = last_run.get("items_done", 0), last_run.get("items", 0)
        return step("running", f"Fut: {done}/{total}", "process", done=done, total=total)
    if status in ("failed", "cancelled"):
        return step("rerun", "Hibás vagy leállított futás: újrafuttatás", "process")
    if last_run.get("open_reasons"):
        return step("review", f"Ellenőrzés: {last_run['open_reasons']} teendő", "review", n=last_run["open_reasons"])
    if last_run["mode"] == "apply":
        if last_run.get("approval"):
            return step("done", "Kiadva: eredmény letöltése", "result")
        return step("approve", "Jóváhagyás", "result")
    return step("go_live", "Próba rendben: éles futás", "process")


def workpackage_view(wp_id: str) -> dict[str, Any]:
    wp = work.get(wp_id)
    ready = work.readiness(wp_id)
    runs = work.run_rows(wp_id)
    extra = {}
    if wp["source_kind"] == "mailbox":  # 058 K5.2: PDF attachments can be added later to a pre-058 email package
        from jav import mailbox

        extra["attachments_missing"] = len(mailbox.missing_attachments(wp))
    return jsonable({"workpackage": wp, "readiness": ready, "titles": item_titles(wp["items"], package_root(wp)), **extra,
                     "last_run": runs[0] if runs else None, "runs": len(runs),
                     "next": next_step(wp, runs[0] if runs else None, ready["ready"])})


def workpackage_list(*, include_archived: bool = False) -> list[dict[str, Any]]:
    """List: name, source, item count, recipe, last run and the number of the items' open to-do reasons."""
    with store.session():  # 061: one connection for the per-package queries
        return _workpackage_list(include_archived=include_archived)


def _workpackage_list(*, include_archived: bool) -> list[dict[str, Any]]:
    rows = work.list_workpackages(include_archived=include_archived)
    packages = {r["id"]: work.get(r["id"]) for r in rows}
    # all to-dos open on the documents (including earlier runs') — for information; the list shows the latest run's;
    # one query for all items of all packages (061: instead of a connection per item)
    open_by_subject = store.review_open_reasons_many(
        [work.review_subject(i) for wp in packages.values() for i in wp["items"]])
    for r in rows:
        wp = packages[r["id"]]
        r["open_reasons_all"] = sum(len(open_by_subject[work.review_subject(i)]) for i in wp["items"])
        runs = work.run_rows(r["id"])
        last = runs[0] if runs else None
        r["open_reasons"] = last["open_reasons"] if last else 0
        r["last_status"] = last["status"] if last else None
        r["last_activity"] = (last["finished_at"] or last["created_at"]) if last else r["created_at"]
        # without a run we do not check readiness (expensive); the step is then "start"
        r["next"] = next_step(wp, last)
    return jsonable(rows)


def workpackage_reviews(wp_id: str) -> dict[str, Any]:
    """The open to-do reasons of the package's items, per item (the UI's To-dos tab)."""
    wp = work.get(wp_id)
    open_by_subject = store.review_open_reasons_many([work.review_subject(i) for i in wp["items"]])
    items = [{"item_id": i["item_id"], "source_path": i["source_path"],
              "open_reasons": open_by_subject[work.review_subject(i)]} for i in wp["items"]]
    return jsonable({"workpackage_id": wp_id, "items": items,
                     "open_reasons": sum(len(i["open_reasons"]) for i in items)})


def assignment_view(wp_id: str) -> dict[str, Any]:
    work.get(wp_id)  # KeyError for an unknown package
    return jsonable({"workpackage_id": wp_id, "assignment": work.current_assignment(wp_id),
                     "history": work.assignment_history(wp_id)})


def result_tables(run_id: str) -> list[str]:
    """The meaningful views of the run's result (058): an empty view does not appear in the UI. Documents and data
    points if there is an extracted document; line items if there is an itemised list; utility cost if there is a
    utility bill."""
    from jav import datasets, report_utility

    records = datasets.run_records(run_id)
    items = work.get_run(run_id)["input"]["items"]
    out = ["emails"] if any(i.get("kind") == "email" for i in items) else []  # 058 K5.1
    if out:  # 058 K5.3: task-proposal view if the run asked for proposals
        from jav import export

        if export.task_rows(export.email_records(run_id)):
            out.append("tasks")
    out += ["documents", "datapoints"] if records else []
    if any(any(r.get("lists", {}).values()) for r in records):
        out.append("line_items")
    if report_utility.has_utility(records):
        out.append("utility")
    if any(i.get("kind") != "email" for i in items):  # 078: content-based names of the documents (also detection only)
        out.append("file_names")
    return out


def run_view(run_id: str, *, names: bool = False) -> dict[str, Any]:
    """One run: items, queue, budget; the items' own open to-do reasons (`open_reasons`) and the earlier reasons left
    open on the documents (`earlier_open_reasons`, for information only, they do not block approval). `names` (082):
    also the items' unified names in this run (`jav/naming.py` `run_item_names`) — only on request, because the
    run's page polls this view while the run is going. `review_version` (085): the version of the result shown, which
    the approval sends back (`work.approve_run`)."""
    run = work.get_run(run_id)
    split = work.items_reasons(run_id, run["input"]["items"])
    titles = item_titles(run["input"]["items"], package_root(work.get(run["workpackage_id"])))
    from jav import corrections, costs

    extra: dict[str, Any] = {"costs": costs.plan_vs_actual(run_id),  # 082: planned and actual cost per provider
                             "review_version": corrections.review_version(run_id)}
    if names:
        from jav import naming

        extra["names"] = {k: asdict(v) for k, v in naming.run_item_names(run_id).items()}
    return jsonable({"run": run, "budget": calls.budget_usage(run_id), "titles": titles,
                     "tables": result_tables(run_id),
                     "open_reasons": {k: v["run"] for k, v in split.items()},
                     "earlier_open_reasons": {k: v["earlier"] for k, v in split.items() if v["earlier"]}, **extra})


def run_list(wp_id: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
    if wp_id is not None:
        work.get(wp_id)
        return jsonable(work.runs(wp_id))
    with store.connect() as c:
        ids = [r["run_id"] for r in c.execute("SELECT run_id FROM runs ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,))]
    return jsonable([work.get_run(i) for i in ids])


def run_journal(run_id: str) -> dict[str, Any]:
    """The run's call log (physical model calls, cost) — in the UI it is visible only when expanded."""
    work.get_run(run_id)
    return jsonable({"run_id": run_id, "calls": calls.scope_journal(run_id), "budget": calls.budget_usage(run_id)})


def worker_status() -> dict[str, Any]:
    return jsonable(worker.status())
