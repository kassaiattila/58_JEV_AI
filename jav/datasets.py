"""Adatkészletek (056 U1): a felület minden listája és eredménytáblája egy megnevezett, oszlopleírással ellátott
sorhalmaz, amelyet a szolgáltatás egységes lekérdezéssel (`jav/tablequery.py`) ad.

Egy adatkészlet: név, felirat, kötelező hatókör (pl. `run_id`), sor-előállító és — ha drága — ujjlenyomat. A felület
csak az oszlopleírásból rajzol, ezért új kimenethez nem kell felületi kód (döntés 2026-09-28: általános adatnézegető,
nem kimenetenkénti egyedi felület).

Gyorsítótár: a futás eredménytábláinak előállítása drága (a javított mezők forráshelyét újraszámolja; 49 iratnál kb.
10 s), a lapozás és a szűrés viszont minden lépésnél új kérés. Ezért a sorok a futás adatának ujjlenyomatáig
(javítások, teendők, tételállapot) megmaradnak; javítás vagy teendő-zárás után a következő kérés újraszámol.

Oszlop-`extra` a felületnek: `link` = hivatkozás-cél (`run`, `workpackage`, `reviews`, `review`, `item`); a hivatkozás
a sor `_wp`, `_run`, `_stage` és `item_id` mezőjéből épül (`next`: a csomag következő lépésének szakasza).
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from jav import cfg, store, work, work_views
from jav.runtime import calls
from jav.tablequery import Column, Query, run_query, select, shown

Rows = tuple[list[Column], list[dict[str, Any]]]


class UnknownDataset(KeyError):
    """Nincs ilyen nevű adatkészlet."""


class MissingScope(ValueError):
    """Az adatkészlethez hatókör (pl. futás-azonosító) kell."""


@dataclass(frozen=True)
class Dataset:
    name: str
    label: str
    scope: tuple[str, ...]                         # kötelező hatókör-kulcsok
    build: Callable[[dict[str, str]], Rows]
    fingerprint: Callable[[dict[str, str]], str] | None = None  # None: nincs gyorsítótár (olcsó lista)
    optional_scope: tuple[str, ...] = ()
    natural_sort: tuple[tuple[str, bool], ...] = ()  # 062: (oszlop, csökkenő) — kért rendezés nélkül ebben a sorrendben jönnek a sorok

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "label": self.label, "scope": list(self.scope), "optional_scope": list(self.optional_scope),
                "natural_sort": [{"col": c, "desc": d} for c, d in self.natural_sort]}


def _labels(name: str) -> dict[str, str]:
    if name == "field":
        return cfg.load("field_labels")["fields"]
    if name == "doc_type":
        return cfg.load("field_labels")["doc_types"]
    if name == "recipe":
        return {r["id"]: r["title"] for r in work.recipes()}
    if name == "intent":  # 058 K5.1: a levél-szándékok neve a regiszterből
        from jav import intents

        return {k: v.display_name for k, v in intents.BY_KEY.items()}
    if name == "task_action":  # 058 K5.3: a feladat-akciók magyar neve
        return dict(cfg.load("email_tasks")["actions"])
    if name == "next_flow":
        from jav import mailbox

        return mailbox.next_flow_labels()
    return cfg.load("datasets")["labels"][name]


def _field_label(f: str) -> str:
    return cfg.load("field_labels")["fields"].get(f, f)


def _column_label(c: str) -> str:
    return cfg.load("field_labels")["columns"].get(c, c)


def _col(key: str, label: str, kind: str = "text", *, labels: str | None = None, hidden: bool = False, **extra: Any) -> Column:
    return Column(key, label, kind, hidden=hidden, labels=_labels(labels) if labels else None, extra=extra)  # type: ignore[arg-type]


# --- ujjlenyomat -----------------------------------------------------------------------------------------------


def _run_fingerprint(scope: dict[str, str]) -> str:
    """A futás eredményét érintő változások: javítás, a futás alanyainak teendői (a korábbi futásból jöttek is, a
    „korábbi” jelölés miatt), feladatjavaslat-döntés, tétel-eredmény, futás-állapot. 062: a teendők a futás alanyaira
    szűkítve — addig bármely futás teendő-változása minden futás tárolt eredményét érvénytelenítette."""
    run_id = scope["run_id"]
    with store.connect() as c:
        row = c.execute("SELECT status, approval, input FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        corr = c.execute("SELECT COUNT(*), MAX(created_at) FROM run_item_corrections WHERE run_id=?", (run_id,)).fetchone()
        rsn: list[Any] = []
        subjects = [work.review_subject(i) for i in json.loads(row["input"])["items"]]
        for kind in sorted({k for k, _ in subjects}):
            ids = sorted({i for k, i in subjects if k == kind})
            for start in range(0, len(ids), 500):  # az SQLite paraméterkorlátja alatt
                chunk = ids[start:start + 500]
                rsn += c.execute(
                    "SELECT COUNT(*), SUM(r.status='open'), MAX(r.id), MAX(r.closed_at) FROM review_reasons r"
                    f" JOIN review_queue q ON q.id = r.review_id WHERE q.subject_kind=? AND q.subject_id IN ({','.join('?' * len(chunk))})",
                    (kind, *chunk)).fetchone()
        # a levél folyamat-azonosítója `<futás>:<tétel>`; tartomány-feltétel, hogy a kulcs indexe használható legyen
        dec = c.execute("SELECT COUNT(*), GROUP_CONCAT(k) FROM (SELECT run_id || '#' || task_index || '=' || decision || '@' || decided_at AS k"
                        " FROM email_task_decisions WHERE run_id >= ? AND run_id < ? ORDER BY k)", (run_id + ":", run_id + ";")).fetchone()
        items = c.execute("SELECT COUNT(*), MAX(updated_at) FROM run_items WHERE run_id=?", (run_id,)).fetchone()
    digest = hashlib.sha256(str(dec[1]).encode("utf-8")).hexdigest()[:16]
    return "|".join(str(x) for x in (*corr, *rsn, dec[0], digest, *items, row["status"], row["approval"]))


def _calls_fingerprint(scope: dict[str, str]) -> str:
    with store.connect() as c:
        row = c.execute("SELECT COUNT(*), MAX(id) FROM invocations WHERE budget_scope=?", (scope["run_id"],)).fetchone()
    return "|".join(str(x) for x in row)


# --- sor-előállítók --------------------------------------------------------------------------------------------


def _runs(scope: dict[str, str]) -> Rows:
    wp_id = scope.get("workpackage_id")
    if wp_id:
        work.get(wp_id)  # ismeretlen csomag: 404
    cols = [
        _col("created_at", "Indítva", "datetime", link="run"),
        _col("workpackage_name", "Munkacsomag", link="workpackage"),
        _col("recipe_id", "Recept", "enum", labels="recipe"),
        _col("mode", "Mód", "enum", labels="mode"),
        _col("status", "Állapot", "enum", labels="run_status", badge=True),
        _col("approval", "Jóváhagyás", "enum", labels="approval"),
        _col("approved_by", "Jóváhagyta", hidden=True),
        _col("items_done", "Lefutott tétel", "number"),
        _col("items", "Tétel", "number"),
        _col("open_reasons", "Nyitott teendő", "number", alert=True),
        _col("actor", "Indította", hidden=True),
        _col("finished_at", "Befejeződött", "datetime", hidden=True),
        _col("run_id", "Futás-azonosító", "id", hidden=True, link="run"),
    ]
    titles = _labels("recipe")  # 058: a recept címe (a felület fordítja), nem a kódneve
    rows = [{**r, "_key": r["run_id"], "_run": r["run_id"], "_wp": r["workpackage_id"],
             "recipe": titles.get(r["recipe_id"], r["recipe_id"])} for r in work.run_rows(wp_id)]
    return cols, rows


def _workpackages(scope: dict[str, str]) -> Rows:
    archived = scope.get("include_archived") == "1"  # 058: az elrejtett csomagok csak kérésre
    cols = [
        _col("name", "Név", link="workpackage"),
        *([_col("status", "Csomag", "enum", labels="wp_status", badge=True)] if archived else []),
        _col("next_label", "Következő lépés", link="next"),
        _col("last_status", "Utolsó futás", "enum", labels="run_status", badge=True),
        _col("items", "Tétel", "number"),  # 058: irat vagy levél
        _col("open_reasons", "Nyitott teendő", "number", link="reviews", alert=True),
        _col("open_reasons_all", "Nyitott teendő a korábbi futásokkal", "number", hidden=True),
        _col("source_kind", "Forrás", "enum", labels="source_kind"),
        _col("recipe_id", "Recept", "enum", labels="recipe"),
        _col("owner", "Felelős"),  # 061
        _col("last_activity", "Utolsó tevékenység", "datetime"),
        _col("created_at", "Létrehozva", "datetime"),  # 062: látható, mert ez a lista alapsorrendje
        _col("source_ref", "Forrás helye", hidden=True),
        _col("next_code", "Lépés kódja", "enum", hidden=True),
        _col("id", "Azonosító", "id", hidden=True),
    ]
    rows = [{**r, "_key": r["id"], "_wp": r["id"], "_run": r["last_run_id"], "_stage": r["next"]["stage"],
             "next_label": r["next"]["label"], "next_code": r["next"]["code"], "_next_params": r["next"]["params"]}
            for r in work_views.workpackage_list(include_archived=archived)]
    for r in rows:
        r.pop("next", None)
    if scope.get("owner"):  # 061: „Saját csomagjaim” — a felelős neve kis-nagybetűtől függetlenül
        who = " ".join(scope["owner"].split()).casefold()
        rows = [r for r in rows if (r.get("owner") or "").casefold() == who]
    return cols, rows


def _activity(scope: dict[str, str]) -> Rows:
    """061: a személy napi műveletei („Mai munkám”); a nap üresen a mai (helyi) nap."""
    from jav import activity

    cols = [
        _col("at", "Időpont", "datetime"),
        _col("action", "Művelet", "enum", labels="activity_action"),
        _col("workpackage_name", "Munkacsomag", link="workpackage"),
        _col("detail", "Részlet"),
        _col("run_id", "Futás", "id", link="run"),
    ]
    titles = _labels("recipe")  # 062: a recept címe (a felület fordítja), nem a kódneve
    rows = [{**e, "detail": titles.get(e["detail"], e["detail"]) if e["action"] == "recipe" else e["detail"],
             "_key": f"{e['at']}|{e['action']}|{n}", "_wp": e["workpackage_id"], "_run": e["run_id"]}
            for n, e in enumerate(activity.entries(scope["actor"], scope.get("day") or None))]
    return cols, rows


def _item_name(item: dict[str, Any], titles: dict[str, str]) -> str:
    return titles.get(item["item_id"]) or Path(item["source_path"]).name


def _workpackage_items(scope: dict[str, str]) -> Rows:
    wp = work.get(scope["workpackage_id"])
    titles = work_views.item_titles(wp["items"])
    cols = [
        _col("name", "Tétel", link="review"),
        _col("kind", "Fajta", "enum", labels="kind"),
        _col("open_reasons", "Nyitott teendő", "number", link="review", alert=True),
        _col("added_revision", "Felvéve (verzió)", "number", hidden=True),
        _col("source_path", "Útvonal", hidden=True),
        _col("sha256", "Ujjlenyomat", "id", hidden=True),
        _col("item_id", "Tétel-azonosító", "id", hidden=True),
    ]
    open_by_subject = store.review_open_reasons_many([work.review_subject(i) for i in wp["items"]])
    rows = [{"_key": i["item_id"], "_wp": wp["id"], "item_id": i["item_id"], "name": _item_name(i, titles),
             "kind": i.get("kind") or "document", "source_path": i["source_path"], "sha256": i.get("sha256"),
             "added_revision": i.get("added_revision"),
             "open_reasons": len(open_by_subject[work.review_subject(i)])} for i in wp["items"]]
    return cols, rows


def _run_items(scope: dict[str, str]) -> Rows:
    run = work.get_run(scope["run_id"])
    titles = work_views.item_titles(run["input"]["items"])
    results = {r["item_id"]: r for r in run["items"]}
    cols = [
        _col("name", "Tétel", link="review"),
        _col("kind", "Fajta", "enum", labels="kind", hidden=True),
        _col("status", "Futás", "enum", labels="item_status", badge=True),
        _col("final_status", "Eredmény", "enum", labels="final_status"),
        _col("open_reasons", "Teendő", "number", link="review", alert=True),
        _col("earlier_reasons", "Korábbi teendő", "number", hidden=True),
        _col("error", "Hiba", hidden=True),
        _col("updated_at", "Frissítve", "datetime", hidden=True),
        _col("item_id", "Tétel-azonosító", "id", hidden=True),
    ]
    rows = []
    splits = work.items_reasons(run["run_id"], run["input"]["items"])
    for i in run["input"]["items"]:
        r = results.get(i["item_id"]) or {}
        split = splits[i["item_id"]]
        rows.append({"_key": i["item_id"], "_wp": run["workpackage_id"], "_run": run["run_id"], "item_id": i["item_id"],
                     "name": _item_name(i, titles), "kind": i.get("kind") or "document", "status": r.get("status"),
                     "final_status": r.get("final_status"), "error": r.get("error"), "updated_at": r.get("updated_at"),
                     "open_reasons": len(split["run"]), "earlier_reasons": len(split["earlier"])})
    return cols, rows


def _emails(scope: dict[str, str]) -> Rows:
    """058 K5.1: a futás levelei — szándék (a kézi javítással), javasolt következő lépés, csatolmányok, és hogy a levél
    szövegéből mennyit látott a felismerés."""
    from jav import export

    run = work.get_run(scope["run_id"])
    doc_types = _labels("doc_type")
    records = export.email_records(run["run_id"])
    cols = [
        _col("subject", "Tárgy", link="item"),
        _col("sender", "Feladó"),
        _col("received_at", "Érkezett", "datetime"),
        _col("mailbox", "Postafiók", hidden=True),
        _col("intent", "Szándék", "enum", labels="intent"),
        _col("confidence", "Valószínűség", "number", percent=True),
        _col("corrected", "Javítva", "enum", labels="yes"),
        _col("machine_intent", "Gépi szándék", "enum", labels="intent", hidden=True),
        _col("next_flow", "Javasolt következő lépés", "enum", labels="next_flow"),
        _col("attachments", "Csatolmány", "number"),
        _col("attachment_types", "Csatolmányok típusa"),
        _col("body_status", "Levél szövege", "enum", labels="body_status"),
        _col("body_chars", "Levél hossza (karakter)", "number", hidden=True),
        _col("tasks", "Feladatjavaslat", "number", hidden=not any(r.get("tasks") for r in records)),
        _col("open_reasons", "Nyitott teendő", "number", link="item", alert=True),
        _col("message_id", "Levél-azonosító", "id", hidden=True),
        _col("item_id", "Tétel-azonosító", "id", hidden=True),
    ]
    rows = []
    for r in records:
        types = sorted({doc_types.get(a.get("doc_type"), a.get("doc_type")) for a in r["attachments"] if a.get("doc_type")})
        rows.append({"_key": r["item_id"], "_wp": run["workpackage_id"], "_run": run["run_id"], "item_id": r["item_id"],
                     "message_id": r["message_id"], "subject": r["subject"] or "(tárgy nélkül)", "sender": r["sender"],
                     "received_at": r["received_at"], "mailbox": r["mailbox"], "intent": r["intent"],
                     "machine_intent": r["machine_intent"], "confidence": r["confidence"],
                     "corrected": "igen" if r["corrected"] else None, "next_flow": r["next_flow"],
                     "attachments": len(r["attachments"]), "attachment_types": ", ".join(types) or None,
                     "body_status": r["body"]["status"], "body_chars": r["body"]["chars"], "open_reasons": len(r["open_reasons"]),
                     "tasks": len((r.get("tasks") or {}).get("tasks") or []) or None})
    return cols, rows


def _email_tasks(scope: dict[str, str]) -> Rows:
    """058 K5.3: a feladatjavaslatok soronként, a bizonyítékkal és az emberi döntéssel (elfogadni csak ember tud)."""
    from jav import export

    run = work.get_run(scope["run_id"])
    cols = [
        _col("subject", "Levél", link="item"),
        _col("action", "Akció", "enum", labels="task_action"),
        _col("title", "Feladat"),
        _col("due_date", "Határidő", "date"),
        _col("assignee_hint", "Felelős"),
        _col("evidence", "Bizonyíték"),
        _col("decision", "Döntés", "enum", labels="task_decision"),
        _col("decided_by", "Döntött", hidden=True),
        _col("decided_at", "Döntés ideje", "datetime", hidden=True),
        _col("done_at", "Elvégezve", "datetime"),  # 062: kézi „elvégezve” az elfogadott feladaton
        _col("done_by", "Elvégezte", hidden=True),
        _col("item_id", "Tétel-azonosító", "id", hidden=True),
    ]
    rows = [{**t, "_key": f"{t['item_id']}:{t['index']}", "_wp": run["workpackage_id"], "_run": run["run_id"]}
            for t in export.task_rows(export.email_records(run["run_id"]))]
    return cols, rows


# az export táblái (jav/export.py) oszlopkulccsal: a fejléc sorrendje szerint
_DOC_KEYS = [("file", "Irat", "text"), ("item_id", "Tétel-azonosító", "id"), ("doc_type", "Típus", "enum"), ("arm", "Út", "enum"),
             ("final_status", "Állapot", "enum"), ("open_reasons", "Nyitott teendők", "text"),
             ("source_email", "Forrás-levél", "text")]  # 058 K5.2: a levél csatolmányánál a levél tárgya
_DP_KEYS = _DOC_KEYS[:3] + [("field", "Mező", "enum"), ("value", "Érték", "text"), ("page", "Oldal", "number"),
                            ("quote", "Forrásszöveg", "text"), ("place", "Hely", "enum"), ("corrected", "Javítva", "enum"),
                            ("field_reason", "Teendő a mezőn", "enum")]
_LI_KEYS = _DOC_KEYS[:3] + [("list", "Lista", "enum"), ("row", "Sor", "number"), ("page", "Oldal", "number")]
_HIDDEN = {"item_id"}
_LABELS = {"final_status": "final_status", "place": "provenance", "field": "field", "list": "field", "doc_type": "doc_type"}


def _fixed(keys: list[tuple[str, str, str]]) -> list[Column]:
    """Az export rögzített oszlopai; az irat neve a tétel ellenőrző nézetére hivatkozik."""
    return [_col(k, label, kind, hidden=k in _HIDDEN, labels=_LABELS.get(k), **({"link": "review"} if k == "file" else {}))
            for k, label, kind in keys]


def _zip_rows(keys: list[str], rows: list[list[Any]], run: dict[str, Any], key_of: Callable[[dict[str, Any]], str]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        d = dict(zip(keys, row, strict=False))
        d.update({"_run": run["run_id"], "_wp": run["workpackage_id"], "_key": key_of(d)})
        out.append(d)
    return out


def _records(scope: dict[str, str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return work.get_run(scope["run_id"]), run_records(scope["run_id"])


def run_records(run_id: str) -> list[dict[str, Any]]:
    """A futás érvényes adata (`export.run_records`) gyorsítótárból: az összes eredménytábla, a közmű-riport és a teljes
    export ugyanazt a — drága — számítást használja, és csak a futás adatának változása után számol újra."""
    from jav import export

    scope = {"run_id": run_id}
    key = (str(store.active_path()), "_records", run_id)
    fp = _run_fingerprint(scope)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == fp:
            _cache.move_to_end(key)
            return hit[1]  # type: ignore[return-value]
    built = export.run_records(run_id)
    _remember(key, fp, built)
    return built


def _field_kind(kind: str | None) -> str:
    return {"money": "money", "number": "number", "date": "date"}.get(kind or "", "text")


def _documents(scope: dict[str, str]) -> Rows:
    from jav import export

    run, records = _records(scope)
    head, rows = export.documents_table(records)
    kinds: dict[str, str] = {}
    for r in records:
        for f, k in r["kinds"].items():
            kinds.setdefault(f, k)
    fields = head[len(export.DOC_HEAD):]
    cols = _fixed(_DOC_KEYS) + [_col(f"f:{f}", _field_label(f), _field_kind(kinds.get(f)), field=f) for f in fields]
    if not any(r.get("source_email") for r in records):  # csak levélcsomagban van értelme: máskor rejtett
        cols = [replace(c, hidden=True) if c.key == "source_email" else c for c in cols]
    return cols, _zip_rows([c.key for c in cols], rows, run, lambda d: d["item_id"])


def _datapoints(scope: dict[str, str]) -> Rows:
    from jav import export

    run, records = _records(scope)
    _head, rows = export.datapoints_table(records)
    cols = _fixed(_DP_KEYS)
    return cols, _zip_rows([c.key for c in cols], rows, run, lambda d: f"{d['item_id']}:{d['field']}")


def _line_items(scope: dict[str, str]) -> Rows:
    from jav import export

    run, records = _records(scope)
    head, rows = export.line_items_table(records)
    extra = head[len(_LI_KEYS):]
    list_kinds: dict[str, str] = {}
    from jav import typepack

    for r in records:
        for lf in typepack.get(r["doc_type"]).list_fields.values():
            for c, k in lf.items():
                list_kinds.setdefault(c, k)
    cols = _fixed(_LI_KEYS) + [_col(f"c:{c}", _column_label(c), _field_kind(list_kinds.get(c)), field=c) for c in extra]
    return cols, _zip_rows([c.key for c in cols], rows, run, lambda d: f"{d['item_id']}:{d['list']}:{d['row']}")


def _calls(scope: dict[str, str]) -> Rows:
    work.get_run(scope["run_id"])
    cols = [
        _col("created_at", "Időpont", "datetime"),
        _col("step", "Lépés"),
        _col("provider", "Szolgáltató", "enum"),
        _col("model_actual", "Modell", "enum"),
        _col("status", "Állapot", "enum"),
        _col("cost_usd", "Költség (USD)", "number"),
        _col("max_cost_usd", "Lefoglalt (USD)", "number", hidden=True),
        _col("input_tokens", "Bemeneti token", "number", hidden=True),
        _col("error", "Hiba", hidden=True),
        _col("step_id", "Lépés (teljes)", "id", hidden=True),
    ]
    rows = [{**{k: c.get(k) for k in ("created_at", "provider", "model_actual", "status", "cost_usd", "max_cost_usd",
                                      "input_tokens", "error", "step_id")},
             "_key": str(c["id"]), "_run": scope["run_id"], "step": ":".join(str(c["step_id"]).split(":")[:2])}
            for c in calls.scope_journal(scope["run_id"])]
    return cols, rows


def _utility_report(scope: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    from jav import report_utility

    run, records = _records(scope)
    return run, report_utility.build(records)


def _utility_cost(scope: dict[str, str]) -> Rows:
    """A közmű-költség havi rácsa hosszú formában: fogyasztási hely × közmű × hónap soronként (Excelben kimutatható)."""
    run, rep = _utility_report(scope)
    cols = [
        _col("address", "Fogyasztási hely"),
        _col("utility", "Közmű", "enum"),
        _col("month", "Hónap", "date"),
        _col("status", "Állapot", "enum", labels="utility_status"),
        _col("amount", "Összeg (bruttó, a hónapra jutó)", "money"),
        _col("consumption", "Fogyasztás", "number"),
        _col("unit", "Egység", "enum", hidden=True),
        _col("settlement", "Elszámoló számla", "enum", labels="yes", hidden=True),
        _col("summary_only", "Csak tájékoztató", "enum", labels="yes"),
        _col("bills", "Forrásszámla", "number"),
        _col("suppliers", "Szolgáltató", hidden=True),
    ]
    rows = []
    for s_ in rep["series"]:
        for m, c in s_["cells"].items():
            rows.append({"_key": f"{s_['address']}|{s_['utility']}|{m}", "_run": run["run_id"], "_wp": run["workpackage_id"],
                         "address": s_["address"], "utility": s_["utility"], "month": m, "status": c["status"], "amount": c["amount"],
                         "consumption": c["consumption"], "unit": s_["consumption_unit"], "settlement": "igen" if c["settlement"] else None,
                         "summary_only": "igen" if s_["summary_only"] else None, "bills": len(c["sources"]),
                         "suppliers": ", ".join(s_["suppliers"])})
    return cols, rows


def _utility_sources(scope: dict[str, str]) -> Rows:
    """A közmű-költség minden cellájának forrásszámlái (a riport „Közmű-források” lapja): cella → irat, oldal, összeg."""
    run, rep = _utility_report(scope)
    cols = [
        _col("address", "Fogyasztási hely"),
        _col("utility", "Közmű", "enum"),
        _col("month", "Hónap", "date"),
        _col("status", "Állapot", "enum", labels="utility_status"),
        _col("amount", "Összeg (a hónapra jutó)", "money"),
        _col("file", "Irat", link="review"),
        _col("page", "Oldal", "number"),
        _col("field", "Mező", "enum", labels="field"),
        _col("corrected", "Javítva", "enum", labels="yes"),
        _col("open_reasons", "Nyitott teendő", "number", alert=True),
        _col("item_id", "Tétel-azonosító", "id", hidden=True),
    ]
    rows = []
    for s_ in rep["series"]:
        for m, c in s_["cells"].items():
            for i, x in enumerate(c["sources"]):
                rows.append({"_key": f"{s_['address']}|{s_['utility']}|{m}|{i}", "_run": run["run_id"], "_wp": run["workpackage_id"],
                             "address": s_["address"], "utility": s_["utility"], "month": m,
                             "status": "settlement" if x.get("settlement") else c["status"], "amount": x["amount"], "file": x["file"],
                             "page": x["page"], "field": x["field"], "corrected": "igen" if x["corrected"] else None,
                             "open_reasons": x["open_reasons"], "item_id": x["item_id"]})
    for u in rep["unplaced"]:
        rows.append({"_key": f"unplaced|{u['item_id']}", "_run": run["run_id"], "_wp": run["workpackage_id"], "status": u["reason"],
                     "file": u["file"], "item_id": u["item_id"]})
    for d in rep.get("duplicates", []):
        rows.append({"_key": f"duplicate|{d['item_id']}", "_run": run["run_id"], "_wp": run["workpackage_id"], "status": "duplicate",
                     "file": d["file"], "item_id": d["item_id"]})
    return cols, rows


def _mailbox_pulls(_scope: dict[str, str]) -> Rows:
    from jav import mailbox

    cols = [
        _col("created_at", "Indítva", "datetime"),
        _col("label", "Postafiók / időszak"),
        _col("status", "Állapot", "enum", labels="pull_status", badge=True),
        _col("new", "Új levél", "number"),
        _col("changed", "Változott", "number", hidden=True),
        _col("duplicate", "Már megvolt", "number", hidden=True),
        _col("workpackage", "Munkacsomag", "id", link="workpackage"),
        _col("actor", "Indította"),
        _col("error", "Hiba"),
        _col("finished_at", "Befejeződött", "datetime", hidden=True),
    ]
    rows = []
    for p in mailbox.pulls(limit=cfg.load("datasets")["export_max_rows"]):
        res = p.get("result") or {}
        rows.append({"_key": p["id"], "_wp": res.get("workpackage"), "created_at": p["created_at"], "label": p["label"],
                     "status": p["status"], "new": res.get("new"), "changed": res.get("changed"), "duplicate": res.get("duplicate"),
                     "workpackage": res.get("workpackage"), "actor": p["actor"], "error": res.get("error"),
                     "finished_at": p.get("finished_at")})
    return cols, rows


REGISTRY: dict[str, Dataset] = {d.name: d for d in [
    Dataset("runs", "Futások", (), _runs, optional_scope=("workpackage_id",)),
    Dataset("workpackages", "Munkacsomagok", (), _workpackages, optional_scope=("include_archived", "owner"),
            natural_sort=(("created_at", True),)),
    Dataset("workpackage_items", "Csomag tételei", ("workpackage_id",), _workpackage_items),
    Dataset("run_items", "Futás tételei", ("run_id",), _run_items, _run_fingerprint),
    Dataset("emails", "Levelek", ("run_id",), _emails, _run_fingerprint),
    Dataset("email_tasks", "Feladatjavaslatok", ("run_id",), _email_tasks, _run_fingerprint),
    Dataset("documents", "Iratok", ("run_id",), _documents, _run_fingerprint),
    Dataset("datapoints", "Adatpontok", ("run_id",), _datapoints, _run_fingerprint),
    Dataset("line_items", "Tételsorok", ("run_id",), _line_items, _run_fingerprint),
    Dataset("utility_cost", "Közmű-költség havonta", ("run_id",), _utility_cost, _run_fingerprint),
    Dataset("utility_sources", "Közmű-költség forrásai", ("run_id",), _utility_sources, _run_fingerprint),
    Dataset("calls", "Hívásnapló", ("run_id",), _calls, _calls_fingerprint),
    Dataset("mailbox_pulls", "Postafiók-letöltések", (), _mailbox_pulls),
    Dataset("activity", "Tevékenységnapló", ("actor",), _activity, optional_scope=("day",)),
]}


# --- gyorsítótár és lekérdezés ---------------------------------------------------------------------------------

_cache: OrderedDict[tuple, tuple[str, Any]] = OrderedDict()
_lock = threading.Lock()


def get(name: str) -> Dataset:
    if name not in REGISTRY:
        raise UnknownDataset(name)
    return REGISTRY[name]


def _scope_of(ds: Dataset, scope: dict[str, str] | None) -> dict[str, str]:
    scope = {k: v for k, v in (scope or {}).items() if v}
    missing = [k for k in ds.scope if k not in scope]
    if missing:
        raise MissingScope(f"dataset {ds.name} needs scope: {', '.join(missing)}")
    return {k: scope[k] for k in (*ds.scope, *ds.optional_scope) if k in scope}


def rows(name: str, scope: dict[str, str] | None = None) -> Rows:
    """Az adatkészlet oszlopai és összes sora (a hatókörre), gyorsítótárból, ha az ujjlenyomat nem változott."""
    ds = get(name)
    sc = _scope_of(ds, scope)
    key = (str(store.active_path()), name, tuple(sorted(sc.items())))
    if ds.fingerprint is None:
        with store.session():  # 061: egy kapcsolat a sorok összes lekérdezésére
            return ds.build(sc)
    fp = ds.fingerprint(sc)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == fp:
            _cache.move_to_end(key)
            return hit[1]
    with store.session():
        built = ds.build(sc)
    _remember(key, fp, built)
    return built


def _remember(key: tuple, fp: str, value: Any) -> None:
    with _lock:
        _cache[key] = (fp, value)
        _cache.move_to_end(key)
        while len(_cache) > cfg.load("datasets")["cache_entries"]:
            _cache.popitem(last=False)


def query(name: str, scope: dict[str, str] | None, q: Query) -> dict[str, Any]:
    cols, all_rows = rows(name, scope)
    ds = get(name)
    return work_views.jsonable({"dataset": ds.spec(), **run_query(cols, all_rows, q)})


# --- letöltés ---------------------------------------------------------------------------------------------------

MEDIA = {"csv": "text/csv; charset=utf-8", "json": "application/json",
         "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


def export_rows(name: str, scope: dict[str, str] | None, q: Query, rows_mode: str,
                columns: list[str] | None = None) -> tuple[list[Column], list[dict[str, Any]]]:
    """A letöltendő oszlopok és sorok. `rows_mode`: `all` (minden sor, a rendezés marad), `filtered` (a keresés és a
    szűrők szerint), `selected` (csak a kijelölt `keys`). A lapozás a letöltésre nem vonatkozik."""
    cols, all_rows = rows(name, scope)
    if rows_mode == "all":
        q = Query(sort=q.sort)
    elif rows_mode == "selected":
        if not q.keys:
            raise ValueError("selected export needs keys")
        q = Query(sort=q.sort, keys=q.keys)
    elif rows_mode != "filtered":
        raise ValueError(f"unknown rows mode: {rows_mode}")
    by_key = {c.key: c for c in cols}
    if columns:
        unknown = [c for c in columns if c not in by_key]
        if unknown:
            raise ValueError(f"unknown column: {', '.join(unknown)}")
        out_cols = [by_key[c] for c in columns]
    else:
        out_cols = [c for c in cols if not c.hidden]
    picked = select(cols, all_rows, q)
    limit = cfg.load("datasets")["export_max_rows"]
    if len(picked) > limit:
        raise ValueError(f"export too large: {len(picked)} rows (limit {limit})")
    return out_cols, picked


def _stamp() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d-%H%M")


def export_file(name: str, scope: dict[str, str] | None, q: Query, rows_mode: str, fmt: str,
                columns: list[str] | None = None) -> tuple[bytes, str, str, int]:
    """(tartalom, médiatípus, fájlnév, sorok száma). A CSV és az Excel a megjelenő feliratot írja (a felsorolt kód
    helyett), a JSON a nyers értéket az oszlopleírással. A képlet-védelem és a magyar CSV-formátum a `jav/export.py`-é."""
    import io
    import json

    from jav import export

    if fmt not in MEDIA:
        raise ValueError(f"unknown export format: {fmt}")
    ds = get(name)
    cols, picked = export_rows(name, scope, q, rows_mode, columns)
    sc = _scope_of(ds, scope)
    fname = "-".join([name, *[v[:24] for v in sc.values()], rows_mode, _stamp()]) + f".{fmt}"
    head = [c.label for c in cols]
    table = [[shown(c, r.get(c.key)) for c in cols] for r in picked]
    if fmt == "csv":
        data = export.csv_bytes(head, table)
    elif fmt == "xlsx":
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = export._safe_sheet(ds.label, set())
        export._write_sheet(ws, head, table, [c.kind if c.kind in ("money", "number") else None for c in cols])
        buf = io.BytesIO()
        wb.save(buf)
        data = buf.getvalue()
    else:
        body = {"dataset": ds.spec(), "scope": sc, "rows_mode": rows_mode, "query": q.model_dump(exclude={"offset", "limit"}),
                "exported_at": _stamp(), "columns": [c.spec() for c in cols],
                "rows": [{c.key: r.get(c.key) for c in cols} for r in picked]}
        data = json.dumps(work_views.jsonable(body), ensure_ascii=False, indent=1).encode("utf-8")
    return data, MEDIA[fmt], fname, len(picked)


def catalog() -> list[dict[str, Any]]:
    return [d.spec() for d in REGISTRY.values()]


def clear_cache() -> None:
    with _lock:
        _cache.clear()


__all__ = ["REGISTRY", "Dataset", "MissingScope", "UnknownDataset", "catalog", "clear_cache", "export_file", "export_rows",
           "get", "query", "rows", "run_records"]
