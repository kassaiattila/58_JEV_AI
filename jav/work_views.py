"""A parancssor és a helyi szolgáltatás közös nézetei (040 K2): ugyanarra a kérésre ugyanaz az adat.

Réteg: felület/CLI → **ez** (alkalmazási művelet: olvasó összeállítások) → `jav.work`, `jav.corrections`,
`jav.runtime` (üzleti szabályok). Itt nincs szabály, csak összeállítás és JSON-alak: a pénz `Decimal`-ként szövegként
megy ki (nem lebegőpontosan), a dátum ISO-szövegként.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jav import cfg, store, typepack, work
from jav.runtime import calls, worker


def jsonable(value: Any) -> Any:
    """Közös JSON-alak mindkét felületnek: `Decimal` és dátum szövegként, ékezet megtartva."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def recipe_catalog() -> list[dict[str, Any]]:
    """A receptek a felületnek: a típuscsomagból vett választék (`allowed_from`) kibontva `allowed` listává."""
    out = []
    for r in work.recipes():
        params = {k: ({**spec, "allowed": sorted(typepack.keys())} if spec.get("allowed_from") == "typepacks" else spec)
                  for k, spec in r["params"].items()}
        out.append({**r, "params": params})
    return jsonable(out)


def recipe_help() -> dict[str, Any]:
    """063: a receptek magyarázata a felületnek (`configs/recipe_help.json`): receptenként mikor való, beállításonként
    és választható értékenként mit jelent. Külön a recepttől, hogy a recept ujjlenyomata ne változzon."""
    data = cfg.load("recipe_help")
    return jsonable({"recipes": data["recipes"], "params": data["params"]})


def item_titles(items: list[dict[str, Any]]) -> dict[str, str]:
    """Olvasható tételcím a felületnek (048 T2): levélnél a tárgy és a feladó (a fájlnév mindig `message.json`)."""
    out, subjects = {}, {}
    for i in items:
        if i.get("kind") != "email":
            continue
        try:
            m = json.loads(Path(i["source_path"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        subjects[i["item_id"]] = (m.get("subject") or "(tárgy nélkül)")[:100]
        out[i["item_id"]] = f"{subjects[i['item_id']]} — {m.get('sender_name') or m.get('sender') or '?'}"
    for i in items:  # 058 K5.2: a csatolmány eredete a nevében (melyik levélből jött)
        if i.get("parent_item_id") in subjects:
            out[i["item_id"]] = f"{Path(i['source_path']).name} (a levél csatolmánya: {subjects[i['parent_item_id']]})"
    return out


ACTIVE = ("queued", "running")


def next_step(wp: dict[str, Any], last_run: dict[str, Any] | None, ready: bool | None = None) -> dict[str, Any]:
    """A csomag következő lépése (057, a V4 `sessionAction.ts` mintájára): egy helyen számolva, ezt mutatja a lista
    oszlopa és a csomag fejlécének gombja is. `stage`: a csomag szakasza (process / review / result), ahová a lépés visz.
    A `ready` csak futás nélküli csomagnál kell (a készenlét-vizsgálat drága: a fájlok ujjlenyomatát számolja)."""
    def step(code: str, label: str, stage: str, **params: Any) -> dict[str, Any]:
        # a felület a kódból és a paraméterekből fordít (057 nyelvváltás); a `label` a magyar felirat
        return {"code": code, "label": label, "stage": stage, "params": params}

    items = wp["items"] if isinstance(wp.get("items"), list) else None
    n_items = len(items) if items is not None else wp.get("items", 0)
    if not n_items:
        return step("empty", "Üres csomag", "process")
    if wp.get("assignment") is None and not wp.get("recipe_id"):
        return step("configure", "Recept kiválasztása", "process")
    if last_run is None:
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
    if wp["source_kind"] == "mailbox":  # 058 K5.2: a 058 előtti levélcsomagba a PDF-csatolmányok utólag felvehetők
        from jav import mailbox

        extra["attachments_missing"] = len(mailbox.missing_attachments(wp))
    return jsonable({"workpackage": wp, "readiness": ready, "titles": item_titles(wp["items"]), **extra,
                     "last_run": runs[0] if runs else None, "runs": len(runs),
                     "next": next_step(wp, runs[0] if runs else None, ready["ready"])})


def workpackage_list(*, include_archived: bool = False) -> list[dict[str, Any]]:
    """Lista: név, forrás, tételszám, recept, utolsó futás és a tételek nyitott teendő-okainak száma."""
    with store.session():  # 061: egy kapcsolat a csomagonkénti lekérdezésekre
        return _workpackage_list(include_archived=include_archived)


def _workpackage_list(*, include_archived: bool) -> list[dict[str, Any]]:
    rows = work.list_workpackages(include_archived=include_archived)
    packages = {r["id"]: work.get(r["id"]) for r in rows}
    # az iratokon nyitott összes teendő (korábbi futásokéval együtt) — tájékoztató; a lista a legutóbbi futásét mutatja;
    # egy lekérdezéssel az összes csomag összes tételére (061: tételenkénti kapcsolódás helyett)
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
        # futás nélkül nem vizsgáljuk a készenlétet (drága); a lépés ekkor „indítás” vagy „recept”
        r["next"] = next_step(wp, last)
    return jsonable(rows)


def workpackage_reviews(wp_id: str) -> dict[str, Any]:
    """A csomag tételeinek nyitott teendő-okai tételenként (a felület Teendők füle)."""
    wp = work.get(wp_id)
    open_by_subject = store.review_open_reasons_many([work.review_subject(i) for i in wp["items"]])
    items = [{"item_id": i["item_id"], "source_path": i["source_path"],
              "open_reasons": open_by_subject[work.review_subject(i)]} for i in wp["items"]]
    return jsonable({"workpackage_id": wp_id, "items": items,
                     "open_reasons": sum(len(i["open_reasons"]) for i in items)})


def assignment_view(wp_id: str) -> dict[str, Any]:
    work.get(wp_id)  # ismeretlen csomagnál KeyError
    return jsonable({"workpackage_id": wp_id, "assignment": work.current_assignment(wp_id),
                     "history": work.assignment_history(wp_id)})


def result_tables(run_id: str) -> list[str]:
    """A futás eredményének értelmes nézetei (058): üres nézet nem jelenik meg a felületen. Iratok és adatpontok, ha
    van kinyert irat; tételsorok, ha van tételes lista; közmű-költség, ha van közmű-számla."""
    from jav import datasets, report_utility

    records = datasets.run_records(run_id)
    items = work.get_run(run_id)["input"]["items"]
    out = ["emails"] if any(i.get("kind") == "email" for i in items) else []  # 058 K5.1
    if out:  # 058 K5.3: feladatjavaslat-nézet, ha a futás kért javaslatot
        from jav import export

        if export.task_rows(export.email_records(run_id)):
            out.append("tasks")
    out += ["documents", "datapoints"] if records else []
    if any(any(r.get("lists", {}).values()) for r in records):
        out.append("line_items")
    if report_utility.has_utility(records):
        out.append("utility")
    return out


def run_view(run_id: str) -> dict[str, Any]:
    """Egy futás: tételek, munkasor, keret; a tételek saját nyitott teendő-okai (`open_reasons`) és az iratokon
    nyitva maradt korábbi okok (`earlier_open_reasons`, csak tájékoztató, a jóváhagyást nem akadályozza)."""
    run = work.get_run(run_id)
    split = work.items_reasons(run_id, run["input"]["items"])
    return jsonable({"run": run, "budget": calls.budget_usage(run_id), "titles": item_titles(run["input"]["items"]),
                     "tables": result_tables(run_id),
                     "open_reasons": {k: v["run"] for k, v in split.items()},
                     "earlier_open_reasons": {k: v["earlier"] for k, v in split.items() if v["earlier"]}})


def run_list(wp_id: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
    if wp_id is not None:
        work.get(wp_id)
        return jsonable(work.runs(wp_id))
    with store.connect() as c:
        ids = [r["run_id"] for r in c.execute("SELECT run_id FROM runs ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,))]
    return jsonable([work.get_run(i) for i in ids])


def run_journal(run_id: str) -> dict[str, Any]:
    """A futás hívásnaplója (fizikai modellhívások, költség) — a felületen csak kibontva látszik."""
    work.get_run(run_id)
    return jsonable({"run_id": run_id, "calls": calls.scope_journal(run_id), "budget": calls.budget_usage(run_id)})


def worker_status() -> dict[str, Any]:
    return jsonable(worker.status())
