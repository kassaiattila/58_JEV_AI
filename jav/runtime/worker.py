"""Feldolgozó (040 K1): a munkasor `run_item` feladatait futtatja, folytatható Burr-állapottal és kerettel.

Egy feldolgozó fut egyszerre (a munkasor árvafoglalás-kezelése erre épül; 040 K2 óta zár őrzi). Indításkor:
`queue.recover_orphans()` (félbemaradt foglalások vissza a sorba) és `calls.recover_uncertain()` (lezáratlan fizetős
kísérletek bizonytalanná válnak, nem hívódnak újra automatikusan).

Egy tétel feldolgozása:
1. a rögzített bemenet ellenőrzése: a forrás tartalomhash-e egyezik-e (különben `source_changed`, nincs újrapróbálás);
2. a recept folyamata (`flow`) ugyanazzal az azonosítóval (`<run_id>:<item_id[:16]>`) és tartós állapotmentővel épül,
   így újraindítás után a következő lépéstől folytatódik;
3. minden lépés után leállítási kérés ellenőrzése (`queue.check_cancellation`);
4. a szolgáltatói hívások a futás keretén belül (`calls.use_run(budget_scope=run_id)`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import socket
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from burr.integrations.serde import pydantic as burr_pydantic

from jav import app_settings, mailbox, store, work
from jav.runtime import calls, lock, persistence, queue
from jav.runtime.persistence import ClosingSQLitePersister

log = logging.getLogger("jav.worker")

burr_pydantic.set_allowlist(["jav"])  # állapot-visszatöltéskor csak a projekt saját modelljei

BACKOFF_S = 30.0


class SourceChanged(RuntimeError):
    """A tétel forrása az indítás óta megváltozott vagy eltűnt; a rögzített bemenettől eltérő tartalmat nem dolgozunk fel."""


# 064: a lezárt tétel mentett folyamat-állapotaiból csak az utolsó marad (a tár különben tételenként ~0,7 MB-tal nő)
PRUNE_FINISHED_STATE = True


def persister_path() -> Path:
    return store.current_path().with_name("burr_state.sqlite")


def _json_default(value: Any) -> Any:
    """A Burr pydantic-szerializálója Python-módban dumpol (date, Decimal marad); ezeket JSON-alakra hozzuk.
    Visszatöltéskor a típusos mezők (pl. `date`, `Decimal`) a pydantic-validációval visszaalakulnak."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class StatePersister(ClosingSQLitePersister):
    """A Burr SQLite-állapotmentője JSON-biztos értékkezeléssel (dátum, pénz) és biztonságos lezárással."""

    def save(self, partition_key, app_id, sequence_id, position, state, status, **kwargs):
        partition_key = partition_key if partition_key is not None else ClosingSQLitePersister.PARTITION_KEY_DEFAULT
        json_state = json.dumps(state.serialize(**self.serde_kwargs), default=_json_default)
        self.connection.execute(
            f"INSERT INTO {self.table_name} (partition_key, app_id, sequence_id, position, state, status) VALUES (?, ?, ?, ?, ?, ?)",
            (partition_key, app_id, sequence_id, position, json_state, status))
        self.connection.commit()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _flow_module(name: str):
    from jav import flow, flow_detect, flow_email  # késleltetett import: a folyamatok nehéz függőségeket húznak
    return {"invoice": flow, "doc_detect": flow_detect, "email": flow_email}[name]


def arm_for(doc_type: str, preferred: str) -> str:
    """A típus tényleges útja (a szabály a `typepack.resolve_arm`-ban; 065: a keretfoglalás is ezt használja)."""
    from jav import typepack

    return typepack.resolve_arm(doc_type, preferred)


def _stages(recipe: dict[str, Any], params: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """A recept lépcsői: (folyamat, paraméterek). Az `document` recept (047 T1.3) két lépcső: felismerés, majd a
    felismert részletes típus kinyerése; a második lépcső paramétereit az első eredménye adja (`_next_params`)."""
    if recipe["flow"] == "document":
        return [("doc_detect", {}), ("invoice", dict(params))]
    if recipe["flow"] == "invoice" and "doc_type" in params:  # a kar a típus csomagja szerint (automatikus vagy nem támogatott kérés)
        return [("invoice", {**params, "arm": arm_for(params["doc_type"], params.get("arm", "auto"))})]
    return [(recipe["flow"], dict(params))]


def _build(recipe: dict[str, Any], params: dict[str, Any], source_path: str, app_id: str, persister):
    mod = _flow_module(recipe["flow"])
    if recipe["flow"] == "invoice":
        # `jev_cache=live`: a JEV-gyorsítótár olvasása nélkül, hogy minden hívás a naplón és a kereten át menjen (élő próba)
        app = mod.build_app(source_path, app_id, params["arm"], tracker=False, doc_type=params["doc_type"], run_id=app_id,
                            persister=persister, use_cache=params.get("jev_cache", "reuse") != "live")
    elif recipe["flow"] == "email":  # 048 T2: a tétel a levél `message.json`-ja, a folyamat a mappáját olvassa
        app = mod.build_app(source_dir=str(Path(source_path).parent), tracker=False, run_id=app_id, persister=persister,
                            use_cache=params.get("jev_cache", "reuse") != "live", propose_tasks=params.get("tasks") == "propose")
    else:
        app = mod.build_app(source_path, tracker=False, run_id=app_id, persister=persister,
                            use_cache=params.get("jev_cache", "reuse") != "live")
    return app, mod.TERMINALS


def _run_stage(recipe: dict[str, Any], params: dict[str, Any], source_path: str, app_id: str, persister, *, run_id: str,
               job_id: int, after_step: Callable[[str], None] | None):
    """Egy lépcső futtatása mentéssel: a már végállapotba jutott lépcső nem fut újra (összeomlás utáni folytatás).
    A mentett állapotot a folyamat saját partíciója alatt keressük (066 Á08: a levélfolyamat `email_intent` alatt ment,
    a keresés eddig a recept `email` nevével történt, ezért a lezárt levél újrafutott, és a feladat elhalt)."""
    mod = _flow_module(recipe["flow"])
    saved = persister.load(mod.PARTITION, app_id)
    if saved and saved["position"] in mod.TERMINALS:
        return saved["state"]
    app, terminals = _build(recipe, params, source_path, app_id, persister)
    state = None
    with calls.use_run(budget_scope=run_id):
        for action, _result, state in app.iterate(halt_after=terminals):
            if after_step is not None:
                after_step(action.name)
            queue.check_cancellation(job_id)
    return state


def _next_params(params: dict[str, Any], detect_state) -> dict[str, Any] | None:
    """A felismerés után: a részletes típus csomagja és a kar (a kért, ha a csomag támogatja). Nincs részletes típus
    vagy az irat szöveg nélküli → None."""
    detail = detect_state.get("detail")
    key = (detail.get("key") if isinstance(detail, dict) else getattr(detail, "key", None)) if detail else None
    if not key or detect_state.get("final_status") != "done":
        return None
    return {**params, "doc_type": key, "arm": arm_for(key, params.get("arm", "auto"))}


def process(job: queue.Job, *, after_step: Callable[[str], None] | None = None) -> str:
    """Egy lefoglalt feladat; visszaadja a feladat végállapotát. `after_step`: teszthorog (hibainjektálás)."""
    run_id, item_id = job.payload["run_id"], job.payload["item_id"]
    run = work.get_run(run_id)
    item = next(i for i in run["input"]["items"] if i["item_id"] == item_id)
    app_id = work.flow_run_id(run_id, item_id)
    try:
        src = Path(item["source_path"])
        if not src.exists() or _sha256_file(src) != item["sha256"]:
            raise SourceChanged(f"{src.name} differs from the frozen input")
        persister = StatePersister(str(persister_path()))
        persister.initialize()
        try:
            # 058 K5.2: a több tétel-fajtát kezelő recept (levél + csatolmány) fajtánként választ folyamatot
            stages = _stages({**run["recipe"], "flow": work.flow_for(run["recipe"], item.get("kind"))}, run["params"])
            final, state = None, None
            for n, (flow_name, params) in enumerate(stages):
                stage_id = app_id if n == len(stages) - 1 else f"{app_id}-{flow_name}"
                if n > 0:
                    params = _next_params(params, state)
                    if params is None:  # a részletes típus nyitva maradt: nincs mit kinyerni, a teendő a felismerésé
                        final = "needs_review"
                        break
                state = _run_stage({**run["recipe"], "flow": flow_name}, params, item["source_path"], stage_id, persister,
                                   run_id=run_id, job_id=job.id, after_step=after_step)
                final = state.get("final_status")
        finally:
            persister.cleanup()
    except queue.JobCancelled:
        work.record_item_result(run_id, item_id, status="cancelled", flow_run_id=app_id)
        result = queue.finish_cancelled(job.id)
    except SourceChanged as exc:
        work.record_item_result(run_id, item_id, status="failed", flow_run_id=app_id, error=f"source_changed: {exc}")
        result = queue.fail(job.id, f"source_changed: {exc}", max_attempts=1, backoff_s=0)
    except Exception as exc:  # noqa: BLE001 - minden más hiba tételszintű; a munkasor próbálkozáskerete dönt
        log.exception("item %s of %s failed", item_id, run_id)  # 063: a teljes hibanyom a naplóban (a tételen 300 karakter)
        work.record_item_result(run_id, item_id, status="failed", flow_run_id=app_id, error=f"{type(exc).__name__}: {exc}"[:300])
        result = queue.fail(job.id, f"{type(exc).__name__}: {exc}", max_attempts=int(run["recipe"].get("max_attempts", 2)),
                            backoff_s=BACKOFF_S)
    else:
        work.record_item_result(run_id, item_id, status="done", final_status=final, flow_run_id=app_id)
        result = queue.complete(job.id)
    if result in queue.TERMINAL and PRUNE_FINISHED_STATE:
        _prune_state(app_id)
    work.refresh_run_status(run_id)
    return result


def _prune_state(app_id: str) -> None:
    """064: a lezárt tétel folyamat-állapotaiból csak az utolsó marad (visszaolvasni csak azt kell). A ritkítás hibája
    nem érinti a tétel eredményét; naplózva."""
    try:
        persistence.prune_to_last(persister_path(), app_id=app_id)
    except Exception:  # noqa: BLE001 - a tár ritkítása nem lehet a feldolgozás akadálya
        log.exception("could not prune the saved state of %s", app_id)


def process_pull(job: queue.Job) -> str:
    """Ütemezett postafiók-letöltés (048 T2): az eredmény / hiba az ütemezésen látszik, a feladat mindig lezárul."""
    mailbox.run_pull_job(job.payload)
    return queue.complete(job.id)


def startup() -> dict[str, int]:
    """Indulás: a félbemaradt foglalások rendezése és a lezáratlan fizetős hívások jelölése. A halottá vagy leállítottá
    vált tétel eredménye a futáson is látszik (063: különben a futás tétele eredmény nélkül maradna)."""
    rec = queue.recover_orphans()
    for job in [*rec.dead, *rec.cancelled]:
        status = "failed" if job in rec.dead else "cancelled"
        log.warning("orphaned job %s (%s) -> %s: %s", job.id, job.kind, job.status, job.error)
        _settle_abandoned(job, status, job.error or "orphaned")
    return {"orphans_requeued": rec.requeued, "orphans_dead": len(rec.dead), "orphans_cancelled": len(rec.cancelled),
            "uncertain_marked": calls.recover_uncertain()}


def _settle_abandoned(job: queue.Job, status: str, error: str) -> None:
    """A feladat gazdájának lezárása, ha a feladat rendes feldolgozás nélkül ért véget: a futás tételéé vagy a letöltésé."""
    if job.kind == work.JOB_KIND:
        run_id, item_id = job.payload["run_id"], job.payload["item_id"]
        work.record_item_result(run_id, item_id, status=status, flow_run_id=work.flow_run_id(run_id, item_id), error=error[:300])
        if PRUNE_FINISHED_STATE:
            _prune_state(work.flow_run_id(run_id, item_id))
        work.refresh_run_status(run_id)
    elif job.kind == mailbox.PULL_JOB_KIND:
        mailbox.abandon_pull(job.payload["pull_id"], error)


def _fail_unexpected(job: queue.Job, exc: Exception) -> str:
    """063: a feldolgozó hurok védőhálója — a váratlan hiba a feladatot lezárja (nem ismétlődik), a hurok fut tovább."""
    error = f"unexpected: {type(exc).__name__}: {exc}"
    result = queue.fail(job.id, error, max_attempts=1, backoff_s=0)
    try:
        _settle_abandoned(job, "failed", error)
    except Exception:  # noqa: BLE001 - a lezárás hibája sem állíthatja le a feldolgozót; naplózva
        log.exception("could not settle job %s after an unexpected error", job.id)
    return result


def lock_path() -> Path:
    return store.current_path().with_name("worker.lock")


def stop_path() -> Path:
    return store.current_path().with_name("worker.stop")


def request_stop() -> None:
    """Szabályos leállítás kérése: a feldolgozó a folyamatban lévő tétel után kilép (040 K2, indító/leállító szkript)."""
    stop_path().parent.mkdir(parents=True, exist_ok=True)
    stop_path().write_text("stop", encoding="utf-8")


def status() -> dict[str, Any]:
    """Fut-e feldolgozó (a zár foglalt), kért-e valaki leállítást, és mennyi feladat vár."""
    return {"running": lock.is_held(lock_path()), "stop_requested": stop_path().exists(), "jobs": queue.counts()}


def run_worker(*, once: bool = False, idle_sleep_s: float = 2.0, max_jobs: int | None = None,
               name: str | None = None) -> dict[str, Any]:
    """Feldolgozó hurok. `once=True`: a sor kiürüléséig fut, utána kilép (parancssori és tesztcélra).

    Egyszerre egy példány futhat (`lock.single_instance`; foglalt zárnál `lock.AlreadyRunning`). Leállítási kérésnél
    (`request_stop`) a folyamatban lévő tétel befejezése után kilép; a kérés indításkor törlődik."""
    worker = name or f"{socket.gethostname()}:{int(time.time())}"
    with lock.single_instance(lock_path()):
        stop_path().unlink(missing_ok=True)
        info: dict[str, Any] = {"startup": startup(), "processed": 0, "results": {}, "stopped": False, "errors": 0}
        log.info("worker %s started: %s", worker, info["startup"])
        while max_jobs is None or info["processed"] < max_jobs:
            if stop_path().exists():
                stop_path().unlink(missing_ok=True)
                info["stopped"] = True
                break
            # 048 T2: az esedékes postafiók-ütemezésekhez letöltési feladat; 057: az esedékes figyelt munkamappák átnézése.
            # 063: egy ütemező hibája nem állítja le a feldolgozót (a hiba naplózva, a következő körben újra próbálja).
            for name, tick in (("mailbox.tick", mailbox.tick), ("folders.tick", app_settings.tick)):
                try:
                    tick()
                except Exception:  # noqa: BLE001 - üzemi védőháló, naplózva
                    log.exception("%s failed", name)
                    info["errors"] += 1
            try:
                job = queue.claim(worker, kinds=(work.JOB_KIND, mailbox.PULL_JOB_KIND))
            except Exception:  # noqa: BLE001 - pl. tartósan zárolt adattár: várakozás, utána újra
                log.exception("claim failed")
                info["errors"] += 1
                if once:
                    break
                time.sleep(idle_sleep_s)
                continue
            if job is None:
                if once:
                    break
                time.sleep(idle_sleep_s)
                continue
            try:
                res = process_pull(job) if job.kind == mailbox.PULL_JOB_KIND else process(job)
            except Exception as exc:  # noqa: BLE001 - üzemi védőháló: a feladat lezárul, a hurok fut tovább
                log.exception("job %s (%s) failed unexpectedly", job.id, job.kind)
                info["errors"] += 1
                res = _fail_unexpected(job, exc)
            info["processed"] += 1
            info["results"][res] = info["results"].get(res, 0) + 1
        log.info("worker %s stopped: processed=%s results=%s errors=%s", worker, info["processed"], info["results"], info["errors"])
    return info
