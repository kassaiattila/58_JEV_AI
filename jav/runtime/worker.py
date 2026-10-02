"""Worker (040 K1): runs the job queue's `run_item` jobs, with resumable Burr state and a budget.

One worker runs at a time (the queue's orphaned-claim handling relies on this; guarded by a lock since 040 K2). At
start-up: `queue.recover_orphans()` (interrupted claims go back to the queue) and `calls.recover_uncertain()` (unsettled
paid attempts become uncertain and are not retried automatically).

Processing one item:
1. check the frozen input: whether the source's content hash matches (otherwise `source_changed`, no retry); a document
   over an input or PDF-reader limit (`DocumentTooLarge`, `PdfReaderLimit`, 077) fails without a retry too;
2. the recipe's flow (`flow`) is built with the same identifier (`<run_id>:<item_id[:16]>`) and a durable state
   persister, so after a restart it resumes from the next step;
3. after every step, check for a cancellation request (`queue.check_cancellation`);
4. provider calls stay within the run's budget (`calls.use_run(budget_scope=run_id)`).
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

from jav import app_settings, isolated_pdf, mailbox, pdf, store, work
from jav.runtime import applog, calls, lock, persistence, queue
from jav.runtime.persistence import ClosingSQLitePersister

log = logging.getLogger("jav.worker")

burr_pydantic.set_allowlist(["jav"])  # only the project's own models when state is loaded back

BACKOFF_S = 30.0


def error_text(exc: BaseException, *, limit: int | None = None) -> str:
    """The stored form of an item or job error: type and message, with secrets masked (075, S04)."""
    text = applog.redact(f"{type(exc).__name__}: {exc}")
    return text if limit is None else text[:limit]


class SourceChanged(RuntimeError):
    """The item's source has changed or disappeared since the start; content that differs from the frozen input is not
    processed."""

    code = "source_changed"


class InstanceDamaged(SourceChanged):
    """The copy kept when the document was added (its source instance) is missing or no longer matches its
    fingerprint."""

    code = "instance_damaged"


# 064: of a finished item's saved flow states only the last one is kept (otherwise the store grows by ~0.7 MB per item)
PRUNE_FINISHED_STATE = True


def persister_path() -> Path:
    return store.current_path().with_name("burr_state.sqlite")


def _json_default(value: Any) -> Any:
    """Burr's pydantic serialiser dumps in Python mode (date and Decimal stay as they are); we convert these to JSON
    form. When loaded back, the typed fields (e.g. `date`, `Decimal`) are restored by pydantic validation."""
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
    """Burr's SQLite state persister with JSON-safe value handling (dates, money) and safe closing."""

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


def _attachment_reads(items: list[dict[str, Any]], email_item_id: str) -> dict[str, str]:
    """The email's attachments that are items of the run with an intact source instance: resolved original path ->
    instance. A damaged instance is left out (its own document item fails with `instance_damaged`)."""
    from jav import source_instances

    out = {}
    for i in items:
        if i.get("parent_item_id") == email_item_id and i.get("instance"):
            instance = work.source_file(i)
            if source_instances.intact(instance, i["sha256"]):
                out[str(Path(i["source_path"]).resolve())] = str(instance)
    return out


def _flow_module(name: str):
    from jav import flow, flow_detect, flow_email  # deferred import: the flows pull in heavy dependencies
    return {"invoice": flow, "doc_detect": flow_detect, "email": flow_email}[name]


def arm_for(doc_type: str, preferred: str) -> str:
    """The effective path (arm) for the type (the rule is in `typepack.resolve_arm`; 065: the budget reservation uses it
    too)."""
    from jav import typepack

    return typepack.resolve_arm(doc_type, preferred)


def _stages(recipe: dict[str, Any], params: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """The recipe's stages: (flow, parameters). The `document` recipe (047 T1.3) has two stages: detection, then
    extraction of the detected detailed type; the second stage's parameters come from the first one's result
    (`_next_params`)."""
    if recipe["flow"] == "document":
        return [("doc_detect", {"jev": params["jev"]} if "jev" in params else {}), ("invoice", dict(params))]
    if recipe["flow"] == "invoice" and "doc_type" in params:  # path from the type pack (auto or unsupported request)
        return [("invoice", {**params, "arm": arm_for(params["doc_type"], _requested_arm(params))})]
    return [(recipe["flow"], dict(params))]


def _requested_arm(params: dict[str, Any]) -> str:
    """086: without JEV only the G path runs, whatever path was asked for."""
    return "G" if _jev_off(params) else params.get("arm", "auto")


def _jev_off(params: dict[str, Any]) -> bool:
    return params.get("jev") == "off"


def _build(recipe: dict[str, Any], params: dict[str, Any], source_path: str, app_id: str, persister,
           read_path: str | None = None, attachment_reads: dict[str, str] | None = None):
    """`read_path`: where a document's bytes are read from (its source instance); the file name, the year hint and
    the stored path stay those of `source_path`, the original. `attachment_reads`: for an email, the source instances
    of its attachments that are items of the package."""
    mod = _flow_module(recipe["flow"])
    if recipe["flow"] == "invoice":
        # `jev_cache=live`: skip reading the JEV cache so every call goes through the log and the budget (live test)
        app = mod.build_app(source_path, app_id, params["arm"], tracker=False, doc_type=params["doc_type"], run_id=app_id,
                            persister=persister, use_cache=reuse_answers(params), read_path=read_path,
                            jev=not _jev_off(params))
    elif recipe["flow"] == "email":  # 048 T2: the item is the email's `message.json`; the flow reads its folder
        app = mod.build_app(source_dir=str(Path(source_path).parent), tracker=False, run_id=app_id, persister=persister,
                            use_cache=reuse_answers(params), propose_tasks=params.get("tasks") == "propose",
                            attachment_reads=attachment_reads, jev=not _jev_off(params))
    else:
        app = mod.build_app(source_path, tracker=False, run_id=app_id, persister=persister,
                            use_cache=reuse_answers(params), read_path=read_path, jev=not _jev_off(params))
    return app, mod.TERMINALS


def _run_stage(recipe: dict[str, Any], params: dict[str, Any], source_path: str, app_id: str, persister, *, run_id: str,
               job_id: int, after_step: Callable[[str], None] | None, read_path: str | None = None,
               attachment_reads: dict[str, str] | None = None):
    """Runs one stage with persistence: a stage that already reached a terminal state does not run again (resume after
    a crash). The saved state is looked up under the flow's own partition (066 Á08: the email flow saves under
    `email_intent`, but the lookup used the recipe name `email`, so a finished email ran again and the job died)."""
    mod = _flow_module(recipe["flow"])
    saved = persister.load(mod.PARTITION, app_id)
    if saved and saved["position"] in mod.TERMINALS:
        return saved["state"]
    app, terminals = _build(recipe, params, source_path, app_id, persister, read_path, attachment_reads)
    state = None
    with calls.use_run(budget_scope=run_id, reuse=reuse_answers(params)):
        for action, _result, state in app.iterate(halt_after=terminals):
            if after_step is not None:
                after_step(action.name)
            queue.check_cancellation(job_id)
    return state


def reuse_answers(params: dict[str, Any]) -> bool:
    """090: the run's "earlier answers" setting (`jev_cache`, the saved key since 040): `reuse` (the default) lets JEV
    read its cache and GPT reuse an earlier answer to the same question; `live` asks every question again."""
    return params.get("jev_cache", "reuse") != "live"


def _next_params(params: dict[str, Any], detect_state) -> dict[str, Any] | None:
    """After detection: the detailed type's pack and the path (the requested one if the pack supports it). No detailed
    type, or a document without text → None."""
    detail = detect_state.get("detail")
    key = (detail.get("key") if isinstance(detail, dict) else getattr(detail, "key", None)) if detail else None
    if not key or detect_state.get("final_status") != "done":
        return None
    return {**params, "doc_type": key, "arm": arm_for(key, _requested_arm(params))}


def process(job: queue.Job, *, after_step: Callable[[str], None] | None = None) -> str:
    """Processes one claimed job and returns its resulting state. `after_step`: test hook (fault injection)."""
    run_id, item_id = job.payload["run_id"], job.payload["item_id"]
    run = work.get_run(run_id)
    item = next(i for i in run["input"]["items"] if i["item_id"] == item_id)
    app_id = work.flow_run_id(run_id, item_id)
    try:
        # an item with a source instance is read from it (a change to the original does not matter); without one, from
        # the original, which must still be the content that was added
        src = work.source_file(item)
        name = Path(item["source_path"]).name
        if not src.exists() or _sha256_file(src) != item["sha256"]:
            if item.get("instance"):
                raise InstanceDamaged(f"the copy of {name} kept when it was added is missing or damaged")
            raise SourceChanged(f"{name} differs from the frozen input")
        read_path = str(src) if item.get("instance") else None
        attachment_reads = _attachment_reads(run["input"]["items"], item_id) if item.get("kind") == "email" else None
        persister = StatePersister(str(persister_path()))
        persister.initialize()
        try:
            # 058 K5.2: a recipe handling several item kinds (email + attachment) chooses the flow per kind
            stages = _stages({**run["recipe"], "flow": work.flow_for(run["recipe"], item.get("kind"))}, run["params"])
            final, state = None, None
            for n, (flow_name, params) in enumerate(stages):
                stage_id = app_id if n == len(stages) - 1 else f"{app_id}-{flow_name}"
                if n > 0:
                    params = _next_params(params, state)
                    if params is None:  # detailed type left open: nothing to extract, the to-do belongs to detection
                        final = "needs_review"
                        break
                state = _run_stage({**run["recipe"], "flow": flow_name}, params, item["source_path"], stage_id, persister,
                                   run_id=run_id, job_id=job.id, after_step=after_step, read_path=read_path,
                                   attachment_reads=attachment_reads)
                final = state.get("final_status")
        finally:
            persister.cleanup()
    except queue.JobCancelled:
        work.record_item_result(run_id, item_id, status="cancelled", flow_run_id=app_id)
        result = queue.finish_cancelled(job.id)
    except SourceChanged as exc:
        work.record_item_result(run_id, item_id, status="failed", flow_run_id=app_id, error=f"{exc.code}: {applog.redact(str(exc))}")
        result = queue.fail(job.id, f"{exc.code}: {applog.redact(str(exc))}", max_attempts=1, backoff_s=0)
    except (pdf.DocumentTooLarge, isolated_pdf.PdfReaderLimit) as exc:
        # 077: a retry would hit the same limit (a timeout would hold the worker for as long again): final at once
        log.warning("item %s of %s is over a document limit: %s", item_id, run_id, exc)
        work.record_item_result(run_id, item_id, status="failed", flow_run_id=app_id, error=error_text(exc, limit=300))
        result = queue.fail(job.id, error_text(exc), max_attempts=1, backoff_s=0)
    except Exception as exc:  # noqa: BLE001 - every other error is item-level; the queue's attempt limit decides
        log.exception("item %s of %s failed", item_id, run_id)  # 063: full traceback to the log (item: 300 chars)
        work.record_item_result(run_id, item_id, status="failed", flow_run_id=app_id, error=error_text(exc, limit=300))
        result = queue.fail(job.id, error_text(exc), max_attempts=int(run["recipe"].get("max_attempts", 2)),
                            backoff_s=BACKOFF_S)
    else:
        work.record_item_result(run_id, item_id, status="done", final_status=final, flow_run_id=app_id)
        result = queue.complete(job.id)
    if result in queue.TERMINAL and PRUNE_FINISHED_STATE:
        _prune_state(app_id)
    work.refresh_run_status(run_id)
    return result


def _prune_state(app_id: str) -> None:
    """064: of a finished item's flow states only the last one is kept (that is the only one ever read back). A pruning
    error does not affect the item's result; it is logged."""
    try:
        persistence.prune_to_last(persister_path(), app_id=app_id)
    except Exception:  # noqa: BLE001 - store pruning must never block processing
        log.exception("could not prune the saved state of %s", app_id)


def process_pull(job: queue.Job) -> str:
    """Scheduled mailbox download (048 T2): the result / error shows on the schedule; the job is always completed."""
    mailbox.run_pull_job(job.payload)
    return queue.complete(job.id)


def startup() -> dict[str, int]:
    """Start-up: settles interrupted claims and marks unsettled paid calls. The result of an item that became dead or
    cancelled shows on the run too (063: otherwise the run's item would be left without a result)."""
    rec = queue.recover_orphans()
    for job in [*rec.dead, *rec.cancelled]:
        status = "failed" if job in rec.dead else "cancelled"
        log.warning("orphaned job %s (%s) -> %s: %s", job.id, job.kind, job.status, job.error)
        _settle_abandoned(job, status, job.error or "orphaned")
    return {"orphans_requeued": rec.requeued, "orphans_dead": len(rec.dead), "orphans_cancelled": len(rec.cancelled),
            "uncertain_marked": calls.recover_uncertain()}


def _settle_abandoned(job: queue.Job, status: str, error: str) -> None:
    """Settles the job's owner when the job ended without normal processing: the run's item or the download."""
    if job.kind == work.JOB_KIND:
        run_id, item_id = job.payload["run_id"], job.payload["item_id"]
        work.record_item_result(run_id, item_id, status=status, flow_run_id=work.flow_run_id(run_id, item_id), error=error[:300])
        if PRUNE_FINISHED_STATE:
            _prune_state(work.flow_run_id(run_id, item_id))
        work.refresh_run_status(run_id)
    elif job.kind == mailbox.PULL_JOB_KIND:
        mailbox.abandon_pull(job.payload["pull_id"], error)


def _fail_unexpected(job: queue.Job, exc: Exception) -> str:
    """063: the worker loop's safety net — an unexpected error closes the job (no retry), and the loop carries on."""
    error = f"unexpected: {error_text(exc)}"
    result = queue.fail(job.id, error, max_attempts=1, backoff_s=0)
    try:
        _settle_abandoned(job, "failed", error)
    except Exception:  # noqa: BLE001 - a settling error must not stop the worker either; logged
        log.exception("could not settle job %s after an unexpected error", job.id)
    return result


def lock_path() -> Path:
    return store.current_path().with_name("worker.lock")


def stop_path() -> Path:
    return store.current_path().with_name("worker.stop")


def request_stop() -> None:
    """Requests an orderly stop: the worker exits after the item in progress (040 K2, start/stop script)."""
    stop_path().parent.mkdir(parents=True, exist_ok=True)
    stop_path().write_text("stop", encoding="utf-8")


def status() -> dict[str, Any]:
    """Whether a worker is running (the lock is held), whether a stop was requested, and the job counts by state."""
    return {"running": lock.is_held(lock_path()), "stop_requested": stop_path().exists(), "jobs": queue.counts()}


def run_worker(*, once: bool = False, idle_sleep_s: float = 2.0, max_jobs: int | None = None,
               name: str | None = None) -> dict[str, Any]:
    """Worker loop. `once=True`: runs until the queue is empty, then exits (for the CLI and tests).

    Only one instance may run at a time (`lock.single_instance`; `lock.AlreadyRunning` if the lock is held). On a stop
    request (`request_stop`) it exits after finishing the item in progress; the request is cleared at start-up."""
    worker = name or f"{socket.gethostname()}:{int(time.time())}"
    with lock.single_instance(lock_path()):
        from jav.runtime import preload

        preload.preload()  # 091: all the code now, so later changes on disk cannot mix into this process
        stop_path().unlink(missing_ok=True)
        info: dict[str, Any] = {"startup": startup(), "processed": 0, "results": {}, "stopped": False, "errors": 0}
        log.info("worker %s started: %s", worker, info["startup"])
        while max_jobs is None or info["processed"] < max_jobs:
            if stop_path().exists():
                stop_path().unlink(missing_ok=True)
                info["stopped"] = True
                break
            # 048 T2: a download job for each due mailbox schedule; 057: scan the watched work folders that are due.
            # 063: a scheduler error does not stop the worker (the error is logged and retried in the next round).
            for name, tick in (("mailbox.tick", mailbox.tick), ("folders.tick", app_settings.tick)):
                try:
                    tick()
                except Exception:  # noqa: BLE001 - operational safety net, logged
                    log.exception("%s failed", name)
                    info["errors"] += 1
            try:
                job = queue.claim(worker, kinds=(work.JOB_KIND, mailbox.PULL_JOB_KIND))
            except Exception:  # noqa: BLE001 - e.g. a store locked for long: wait, then try again
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
            except Exception as exc:  # noqa: BLE001 - operational safety net: the job is closed, the loop carries on
                log.exception("job %s (%s) failed unexpectedly", job.id, job.kind)
                info["errors"] += 1
                res = _fail_unexpected(job, exc)
            info["processed"] += 1
            info["results"][res] = info["results"].get(res, 0) + 1
        log.info("worker %s stopped: processed=%s results=%s errors=%s", worker, info["processed"], info["results"], info["errors"])
    return info
