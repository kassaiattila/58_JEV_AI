"""Shared views of the command line and the local service (040 K2): the same request gets the same data.

Layer: UI/CLI → **this** (application operation: read-only assemblies) → `jav.app.work`, `jav.app.corrections`,
`jav.runtime` (business rules). There are no rules here, only assembly and JSON shape: money goes out as a `Decimal`
rendered as text (not as a float), dates as ISO text.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jav.app import item_kinds, logic_packs, work, work_readiness, work_recipes, work_runs
from jav.ai import typepack
from jav.core import cfg, display, store
from jav.core import calls


def jsonable(value: Any) -> Any:
    """Shared JSON shape for both interfaces: `Decimal` and dates as text, accents preserved."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def recipe_catalog(*, every_status: bool = False) -> list[dict[str, Any]]:
    """The recipes the UI offers (080: only the active processing; internal and retired recipes are not offered;
    `every_status`: all of them, for the command line): the choices taken from the type packs (`allowed_from`)
    expanded into an `allowed` list. 160-D: the engine's default is the application's, as for a package without saved
    settings (`work_recipes.default_params`)."""
    out = []
    for r in work_recipes.recipes() if every_status else work_recipes.active_recipes():
        params = {k: ({**spec, "allowed": sorted(typepack.extractable_keys())} if spec.get("allowed_from") == "typepacks" else spec)
                  for k, spec in r["params"].items()}
        if engine := work_recipes.engine_params(r):
            params["jev"] = {**params["jev"], "default": engine["jev"]}
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
    """The folder a package was read from (a folder or a watched folder), for the subfolder titles (081). 177: the
    source kind says whether its reference is that folder (`jav/app/item_kinds.py`)."""
    kind = wp.get("source_kind")
    return wp.get("source_ref") if kind in item_kinds.source_names() and item_kinds.source(kind).folder else None


def item_titles(items: list[dict[str, Any]], root: str | None = None) -> dict[str, str]:
    """Readable item title for the UI (048 T2): for an email, the subject and the sender (the file name is always
    `message.json`). 081: a document in a subfolder of the package's folder (`root`) is titled with its path below
    that folder, so files with the same name in different subfolders stay apart."""
    out = {}
    base = Path(root) if root else None
    for i in items:
        p = Path(i["source_path"])
        if base and item_kinds.of(i).record and not i.get("parent_item_id") and p.parent != base and p.is_relative_to(base):
            out[i["item_id"]] = p.relative_to(base).as_posix()
    for own in item_kinds.handlers():  # 185: an email's subject and sender, an attachment's email (`mailbox.item_titles`)
        out.update(own.titles(items))
    return out


ACTIVE = ("queued", "running")


def next_step(wp: dict[str, Any], last_run: dict[str, Any] | None, ready: bool | None = None) -> dict[str, Any]:
    """The package's next step (057, after the V4 `sessionAction.ts` pattern): computed in one place, shown both by the
    list column and by the button in the package header. `stage`: the package stage (process / review / result) the
    step leads to. `ready` is needed only for a package without runs (the readiness check is expensive: it computes the
    files' fingerprints)."""
    def step(code: str, label: str, stage: str, **params: Any) -> dict[str, Any]:
        # the UI translates from the code and the parameters (057 language switch); `label` is the English caption (231,
        # D4: the interface's source; `step_text` shows it in the request's language)
        return {"code": code, "label": label, "stage": stage, "params": params}

    items = wp["items"] if isinstance(wp.get("items"), list) else None
    n_items = len(items) if items is not None else wp.get("items", 0)
    if not n_items:
        return step("empty", "Empty document batch", "process")
    if last_run is None:  # 080: without an assignment the default processing settings apply
        return step("start", "Start trial run", "process") if ready is not False else step("blocked", "Cannot start", "process")
    status = last_run["status"]
    if status in ACTIVE:
        done, total = last_run.get("items_done", 0), last_run.get("items", 0)
        return step("running", f"Running: {done}/{total}", "process", done=done, total=total)
    if status in ("failed", "cancelled"):
        return step("rerun", "Failed or stopped run: rerun", "process")
    # 160-C S2: items added after the run come first: their processing may raise further to-dos (`work_runs.pending_items`)
    if wp.get("id") and (pending := len(work_runs.pending_items(wp["id"], last_run["mode"]))):
        return step("pending", f"{pending} new item(s) to process", "process", n=pending)
    if last_run.get("open_reasons"):
        if last_run["mode"] == "shadow":  # 150: a trial cannot be approved; its to-dos are information, the step is going live
            return step("go_live", f"Trial finished: live run ({last_run['open_reasons']} to-dos in the trial)", "process",
                        trial_reasons=last_run["open_reasons"])
        return step("review", f"Review: {last_run['open_reasons']} to-dos", "review", n=last_run["open_reasons"])
    if last_run["mode"] == "apply":
        # 172 (plan 170 L1): the step is the package's Approve and release; an approval without a released version
        # (the way before v1.20.0, or a release stopped after its approvals) still needs it
        if last_run.get("approval") and not (wp.get("id") and _unreleased_approval(wp["id"])):
            return step("done", "Released: download result", "result")
        return step("release", "Approve and release", "result")
    return step("go_live", "Trial OK: live run", "process")


def step_text(step: dict[str, Any]) -> str:
    """231 (D4): a next step's caption in the request's language, as the interface's `stepLabel` makes it
    (`ui/src/labels.ts`), for what the service writes itself (a download of the package list): a step with a number
    from its parameters, any other by its caption, which is the interface's source text (each kind's `next_step`)."""
    code, p = step["code"], step.get("params") or {}
    text = display.text
    if code == "running":
        return text("Running: {{done}}/{{total}}", done=p.get("done", 0), total=p.get("total", 0))
    if code == "go_live" and p.get("trial_reasons"):
        return text("Trial finished: live run ({{n}} to-dos in the trial)", n=p["trial_reasons"])
    if code == "decision_make" and isinstance(p.get("title"), str):
        return text("Decide: {{what}}", what=text(p["title"]))
    counted = {"review": "Review: {{n}} to-dos", "pending": "{{n}} new item(s) to process",
               "reconcile_pair": "Pairing: {{n}} open lines", "routing_decide": "Route the documents: {{n}} to decide",
               "quote_request_check": "Check the request: {{n}} gap(s)", "missing_facts": "Get the missing facts: {{n}}"}
    if code in counted:
        return text(counted[code], n=p.get("n", 0))
    if code in ("reconcile_approved", "quote_approved"):
        return text("Approved: version {{n}}", n=p.get("version", ""))
    if code == "quote_compose" and p.get("n"):
        return text("Compose the quote: {{n}} to settle", n=p["n"])
    if code == "facts_check" and p.get("n"):
        return text("Check the facts: {{n}} to settle", n=p["n"])
    return text(step["label"])


def _unreleased_approval(wp_id: str) -> bool:
    from jav.app import package_release

    with store.connect() as c:
        return package_release.unreleased_approval(wp_id, c)


def current_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """153: the run the package's next step is about — the newest run, passing over runs a person stopped after it, so
    a later stopped run does not hide the to-dos or the approval of an earlier finished run (2026-10-13: a package with
    169 open to-dos on its live run offered "rerun" because two later runs had been stopped). A package whose runs were
    all stopped still offers a rerun. `runs`: newest first (`work_runs.run_rows`).

    160-C S3: a queued or running run comes first (its progress); otherwise the OLDEST open live run
    (`work_runs.open_live_runs`), so a later run over the pending items, or a later trial, does not hide the to-dos or the
    approval of an earlier live run."""
    if not runs:
        return None
    if active := next((r for r in runs if r["status"] in ACTIVE), None):
        return active
    if any(r.get("mode") == "apply" and not r.get("approval") and r["status"] in work_runs.SUPERSEDABLE for r in runs):
        if open_ids := work_runs.open_live_runs(runs[0]["workpackage_id"]):
            return next(r for r in runs if r["run_id"] == open_ids[0])
    return next((r for r in runs if r["status"] != "cancelled"), runs[0])


def open_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """160-C S3: the package's open live runs (`work_runs.open_live_runs`) as list rows, oldest first: the review shows
    the other open runs' to-dos next to the current run's."""
    if not runs:
        return []
    by_id = {r["run_id"]: r for r in runs}
    return [by_id[i] for i in work_runs.open_live_runs(runs[0]["workpackage_id"]) if i in by_id]


def workpackage_view(wp_id: str) -> dict[str, Any]:
    from jav.app import intake

    with store.session():  # 153 (review B1): one connection for the package's page
        view = {**_workpackage_view(wp_id), **_owner_case(wp_id)}
        # 231 (C1c): the processes whose case may read this package (an email package's email routing)
        offers = intake.package_offers(view["workpackage"])
        return {**view, "intake": offers} if offers else view


def _owner_case(wp_id: str) -> dict[str, Any]:
    """231 (U2a; the owner's decision of 2026-10-28: one work list, the cases): the case and the step a case step's
    package belongs to, with the case's tab that shows the step, so the package's page leads back to its case. 261 (B1c):
    `parent`, the case that case is a sub-case of (its tab that shows the step), so the page leads back to it too."""
    from jav.app import document_processing, process_runtime

    owner = document_processing.owner_of(wp_id)
    if owner is None:
        return {}
    case_id, step_id = owner
    pack = process_runtime.pack_for(case_id)
    step = next((s for s in pack.steps if s.id == step_id), None) if pack else None
    tab = next((tab.id for tab in pack.screens.tabs for e in tab.elements if e.step == step_id), None) if pack else None
    parent = process_runtime.parent_of(case_id)
    return {"owner_case": {"id": case_id, "name": work.get(case_id)["name"], "step": step_id,
                           "step_title": step.title if step else None, "tab": tab,
                           "parent": {k: parent[k] for k in ("id", "name", "step_title", "tab")} if parent else None}}


def _workpackage_view(wp_id: str) -> dict[str, Any]:
    wp = work.get(wp_id)
    pack = logic_packs.of(wp["source_kind"])  # 176: the logic pack the pack runs, if any
    if pack is not None and not pack.has_runs:  # 131: a reconciliation pack has a scope, no files and no runs
        return jsonable({"workpackage": wp, "titles": {}, "last_run": None, "runs": 0, **pack.page(wp_id),
                         "workflow": _workflow_of(wp_id), **_scope_of(wp)})
    ready = work_readiness.readiness(wp_id)
    runs = work_runs.run_rows(wp_id)
    extra = {}
    if pack is None:  # 177: the source kind's part (058 K5.2: a mailbox package's missing PDF attachments)
        extra.update(item_kinds.page(wp))
    if pack is not None and pack.page is not None:  # 140: a statement pack's party, period and statements
        extra.update(pack.page(wp_id))
    elif (rule := work.package_rule(wp_id)) is not None and (rule.page is not None or rule.adds != "documents"):
        # 231 (C3b5a): its named rule's part, and what the interface needs to show it and to add to the package (the
        # page part's keys, by which the interface finds its panel, and how it adds), with no kind of its own to ask
        part = rule.page(wp_id) if rule.page is not None else {}
        extra.update(part)
        extra["rule"] = {"name": work.rule_name(wp_id), "adds": rule.adds, "parts": sorted(part)}
    current = current_run(runs)
    extra["item_counts"] = item_counts(wp)  # 168: the item list's tally
    return jsonable({"workpackage": wp, "readiness": ready, "titles": item_titles(wp["items"], package_root(wp)), **extra,
                     "last_run": runs[0] if runs else None, "current_run": current, "runs": len(runs),
                     "open_runs": open_runs(runs),  # 160-C S3: every open live run, the current one too
                     "next": next_step(wp, current, ready["ready"]), "workflow": _workflow_of(wp_id),
                     "supersedable": work_runs.supersedable_runs(wp_id),  # 152: older live runs a person can supersede
                     **_scope_of(wp), **_release_of(wp_id)})


def item_counts(wp: dict[str, Any]) -> dict[str, int]:
    """168 (plan F-item-list-and-adding): how many of the package's items are in each state (`work_runs.item_states`), and
    how many were removed; a state without items is left out."""
    states = Counter(s["state"] for s in work_runs.item_states(wp["id"], wp["items"]).values())
    with store.connect() as c:
        removed = c.execute("SELECT COUNT(*) FROM workpackage_items WHERE workpackage_id=? AND removed_revision IS NOT NULL",
                            (wp["id"],)).fetchone()[0]
    return {**dict(states), **({"removed": removed} if removed else {})}


def _release_of(wp_id: str) -> dict[str, Any]:
    """181: a released package's release state and latest version (the stage bar's result), only when it has one."""
    from jav.app import package_release

    summary = package_release.release_summary(wp_id)
    return {"release": summary} if summary else {}


def _scope_of(wp: dict[str, Any]) -> dict[str, Any]:
    """181: the package's scope (its party, period and role, `jav/app/package_scope.py`), only when it has one."""
    from jav.app import package_scope

    scope = package_scope.scope_of(wp["id"], kind=wp["source_kind"])
    return {"scope": scope} if scope else {}


def _workflow_of(wp_id: str) -> dict[str, Any] | None:
    """146: the workflow the package is a step of (the package header links to its control view)."""
    from jav.app import workflows

    return workflows.workflow_of(wp_id)


def own_reasons(reasons: list[dict[str, Any]], wp_id: str, run_packages: dict[str, str]) -> list[dict[str, Any]]:
    """153 (review): the to-do reasons on a package's documents, without those another package's runs raised. A to-do
    belongs to the document's content, so the same file in another package carried that package's to-dos into this one
    (a package never run showed 720). A reason of a run that belongs to no package (a measurement or the command line)
    still shows (K3: an old measurement's to-do stays on the document). `run_packages`: run id -> package
    (`run_packages()`)."""
    return [r for r in reasons if run_packages.get(str(r.get("run_id") or "").split(":", 1)[0], wp_id) == wp_id]


def run_packages() -> dict[str, str]:
    """Every run's package, by run id (one query)."""
    with store.connect() as c:
        return {r["run_id"]: r["workpackage_id"] for r in c.execute("SELECT run_id, workpackage_id FROM runs")}


def workpackage_list(*, include_archived: bool = False, batches_only: bool = False) -> list[dict[str, Any]]:
    """List: name, source, item count, recipe, last run and the number of the items' open to-do reasons. 231 (U2a; the
    owner's decision of 2026-10-28: one work list, the cases): `batches_only`, the document batches that are no case's,
    a case's container and its steps' packages left out before anything is read of them (the list of every batch builds
    no reconciliation's workspace)."""
    with store.session():  # 061: one connection for the per-package queries
        return _workpackage_list(include_archived=include_archived, batches_only=batches_only)


def _workpackage_list(*, include_archived: bool, batches_only: bool = False) -> list[dict[str, Any]]:
    rows = work.list_workpackages(include_archived=include_archived)
    if batches_only:
        from jav.app import document_processing, process_runtime  # lazy: they build on these views

        owned = document_processing.owned_packages()
        rows = [r for r in rows if r["id"] not in owned and r["source_kind"] != process_runtime.CONTAINER]
    packages = {r["id"]: work.get(r["id"]) for r in rows}
    # all to-dos open on the documents (including earlier runs') — for information; the list shows the latest run's;
    # one query for all items of all packages (061: instead of a connection per item)
    open_by_subject = store.review_open_reasons_many(
        [work_runs.review_subject(i) for wp in packages.values() for i in wp["items"]])
    owners = run_packages()  # 153: not another package's runs' to-dos
    for r in rows:
        wp = packages[r["id"]]
        runs = work_runs.run_rows(r["id"])
        r["open_reasons_all"] = sum(len(own_reasons(open_by_subject[work_runs.review_subject(i)], r["id"], owners)) for i in wp["items"])
        last = runs[0] if runs else None
        current = current_run(runs)  # 153: the to-dos and the next step of the run a later stopped run does not hide
        r["open_reasons"] = current["open_reasons"] if current else 0
        r["last_status"] = last["status"] if last else None
        r["last_activity"] = (last["finished_at"] or last["created_at"]) if last else r["created_at"]
        r["older_runs"] = 0
        pack = logic_packs.of(wp["source_kind"])
        if pack is not None and not pack.has_runs:  # 131: its own next step (pairing / result); 176: its logic pack's
            r["next"] = pack.list_next(r["id"])
            continue
        # 153: the owner could not tell from the list which packages had older live runs to supersede (152 shows them
        # on the package's page only)
        r["older_runs"] = len(work_runs.supersedable_runs(r["id"]))
        # without a run we do not check readiness (expensive); the step is then "start"
        r["next"] = next_step(wp, current)
    return jsonable(rows)


def workpackage_reviews(wp_id: str) -> dict[str, Any]:
    """The open to-do reasons of the package's items, per item (the UI's To-dos tab)."""
    wp = work.get(wp_id)
    open_by_subject = store.review_open_reasons_many([work_runs.review_subject(i) for i in wp["items"]])
    owners = run_packages()  # 153: not another package's runs' to-dos
    items = [{"item_id": i["item_id"], "source_path": i["source_path"],
              "open_reasons": own_reasons(open_by_subject[work_runs.review_subject(i)], wp_id, owners)} for i in wp["items"]]
    return jsonable({"workpackage_id": wp_id, "items": items,
                     "open_reasons": sum(len(i["open_reasons"]) for i in items)})


def assignment_view(wp_id: str) -> dict[str, Any]:
    work.get(wp_id)  # KeyError for an unknown package
    return jsonable({"workpackage_id": wp_id, "assignment": work_recipes.current_assignment(wp_id),
                     "history": work_recipes.assignment_history(wp_id)})


def result_tables(run_id: str | None = None, *, workpackage_id: str | None = None) -> list[str]:
    """The meaningful views of the run's result (058): an empty view does not appear in the UI. Documents and data
    points if there is an extracted document; line items if there is an itemised list; utility cost if there is a
    utility bill. 172: also of the package's current result (`workpackage_id`), from each item's counted run; its file
    names only when one run gives them all (the named copies are made per run)."""
    from jav.app import datasets
    from jav.app.outputs import parts as output_parts

    scope = {"run_id": run_id} if run_id else {"workpackage_id": str(workpackage_id)}
    parts = datasets.result_parts(scope)
    records = datasets.result_records(scope)
    shown = [(run["run_id"], i) for run, keep in parts for i in run["input"]["items"] if keep is None or i["item_id"] in keep]
    items = [i for _run, i in shown]
    out = []
    for part in output_parts.item_parts():  # 058 K5.1, K5.3 (185: an item kind's part): the emails and their tasks
        if any(i.get("kind") == part.kind for i in items):
            out += part.views([m for run, keep in parts for m in part.read(run["run_id"]) if keep is None or m["item_id"] in keep])
    out += ["documents", "datapoints"] if records else []
    from jav.documents import native_results
    from jav.documents.native_contracts import NATIVE_SUFFIXES

    if any(native_results.native_item(r, i) for r, i in shown):  # 120: a continuing PDF too
        out.append("native_facts")
    if any(any(r.get("lists", {}).values()) for r in records):
        out.append("line_items")
    out += [part.view for part in output_parts.result_parts() if part.view and part.shown and part.shown(records)]  # the utility
    if len(parts) == 1 and any(item_kinds.of(i).record and Path(i["source_path"]).suffix.lower() not in NATIVE_SUFFIXES
                               for i in items):
        out.append("file_names")
    return out


def run_view(run_id: str, *, names: bool = False) -> dict[str, Any]:
    """One run: items, queue, budget; the items' own open to-do reasons (`open_reasons`) and the earlier reasons left
    open on the documents (`earlier_open_reasons`, for information only, they do not block approval). `names` (082):
    also the items' unified names in this run (`jav/app/naming.py` `run_item_names`) — only on request, because the
    run's page polls this view while the run is going. `review_version` (085): the version of the result shown, which
    the approval sends back (`work_runs.approve_run`). 153 (review B2): one connection for the whole view; a run of 468
    documents took 1.6 s on every poll, as each item's native check opened its own."""
    with store.session():
        return _run_view(run_id, names=names)


def _run_view(run_id: str, *, names: bool) -> dict[str, Any]:
    run = work_runs.get_run(run_id)
    split = work_runs.items_reasons(run_id, run["input"]["items"])
    titles = item_titles(run["input"]["items"], package_root(work.get(run["workpackage_id"])))
    from jav.app import corrections, costs

    extra: dict[str, Any] = {"costs": costs.plan_vs_actual(run_id),  # 082: planned and actual cost per provider
                             "review_version": corrections.review_version(run_id),
                             # 151: the offer to supersede an older live run, or who superseded it
                             "supersede": work_runs.supersede_info(run_id), "superseded": work_runs.superseded(run_id),
                             "engine": work_readiness.run_engine(run),  # 160-D: the approval and the review show it
                             # 160-C (decision 163 D7): items removed from the package, left out of the release
                             "removed_items": work_runs.excluded_items(run)}
    if changed := work_runs.rule_changes(run_id):  # 218: only when the rules or the code changed during the run
        extra["rule_changes"] = changed
    if names:
        from jav.app import naming

        extra["names"] = {k: asdict(v) for k, v in naming.run_item_names(run_id).items()}
    return jsonable({"run": run, "budget": calls.budget_usage(run_id), "titles": titles,
                     "tables": result_tables(run_id),
                     "open_reasons": {k: v["run"] for k, v in split.items()},
                     "earlier_open_reasons": {k: v["earlier"] for k, v in split.items() if v["earlier"]}, **extra})


def run_list(wp_id: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
    with store.session():  # 153 (review B4): one connection for the list, not one per run
        if wp_id is not None:
            work.get(wp_id)
            return jsonable(work_runs.runs(wp_id))
        with store.connect() as c:
            ids = [r["run_id"] for r in c.execute("SELECT run_id FROM runs ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,))]
        return jsonable([work_runs.get_run(i) for i in ids])


def run_journal(run_id: str) -> dict[str, Any]:
    """The run's call log (physical model calls, cost) — in the UI it is visible only when expanded."""
    work_runs.get_run(run_id)
    return jsonable({"run_id": run_id, "calls": calls.scope_journal(run_id), "budget": calls.budget_usage(run_id)})

