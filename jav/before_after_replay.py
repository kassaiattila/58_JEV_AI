"""Running before/after snapshot (plan 170, E0b): the processing itself, replayed from earlier answers.

Plain-language summary: the static snapshot (`jav.before_after`) shows that a refactoring step left every list, page
and download the same, but it only reads results that are already stored. This one processes documents again: about
150 items, chosen so that every way the processing can go is represented, run once more on a fresh copy of the
backed-up store, from earlier answers only. Nothing can reach a provider: the keys are replaced by a placeholder, the
network goes to a closed local port and the replayed runs have no budget, so a question without an earlier answer
becomes a to-do instead of a call. Afterwards the call log has to show that no live call happened. The results are
written in the static snapshot's format, so `before-after-diff` compares two replays.

- `sample` chooses the items. Every finished item of a run that was not stopped falls into a stratum: its flow, item
  kind, package kind, trial or live run, engine, the path its data points took, native facts, its end state, email
  tasks and the cross-document to-dos it got. Each stratum gets one unit, its newest, the rest is shared out by
  stratum size. An email goes together with its attachments, because they affect each other (a suspicious email marks
  its attachments).
- `running_snapshot` replays in two rounds: first the newest unit of every stratum, then the rest of the sample, shared
  out only among the strata whose first unit had every earlier answer. Each unit goes through the worker's own
  processing (`jav.runtime.worker.process`), one after the other in the order of the original runs. It records each
  item's end state, its stored rows (data points,
  documents, to-dos, email result, native facts, ledger and call log) and its views, and each replayed run's views.
- `live_calls` is the gate: every call of a replayed run that was not an earlier answer.
- Random identifiers made while processing (a new native reading's intake, a temporary instance) come from a fixed
  sequence per item during the replay (`_FixedIds`): a native document whose reading the backup lacks is read anew,
  and its random intake identifier would otherwise change the reading's digest from one replay to the next.

Two replays are comparable when they start from the same backup, the same JEV answer cache and the same work folder
(stored paths name it), on the same day (a few checks compare dates with today).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import urllib.error
import urllib.request
import uuid
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from jav import before_after
from jav.before_after import SnapshotError

SAMPLE_SIZE = 150
WORKER = "before.after.replay"
PLACEHOLDER_KEY = "replay-without-a-key"
CLOSED_PROXY = "http://127.0.0.1:9"  # the discard port: nothing listens there, so a request fails before it leaves
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
_NO_PROXY_VARS = ("NO_PROXY", "no_proxy")
_OPENAI_BASE_URL = "OPENAI_BASE_URL"
_NETWORK_PROBE = "https://api.openai.com/"

# The producers of to-dos that look at other documents than the one being processed (the duplicate check, the party
# roles and their history, the reconciliation, the suspicious email of an attachment, the rule of a package's kind).
_CROSS_PRODUCERS = frozenset({"duplicates", "parties", "reconcile", "email_source", "package_rule:detection",
                              "package_rule:item"})
# Keys whose values say when or by which process something happened, not what it is; dropped from every replay view.
_VOLATILE = frozenset({"created_at", "updated_at", "finished_at", "started_at", "claimed_at", "claimed_by",
                       "closed_at", "decided_at", "stopped_at", "approved_at", "fetched_at", "first_seen", "seconds",
                       "holder", "refreshing"})
# The run tables of a replayed run, read as the interface reads them
_REPLAY_DATASETS = ("run_items", "emails", "email_tasks", "documents", "datapoints", "native_facts", "line_items")


@dataclass(frozen=True)
class Unit:
    """One item of a run, or an email with its attachments, replayed together; `stratum` is the head item's."""
    run_id: str
    item_ids: tuple[str, ...]
    stratum: tuple[str, ...]


# --- the sample ---------------------------------------------------------------------------------------------------

def _owner(flow_id: str, flow_ids: set[str]) -> str | None:
    """The item flow identifier a stored flow identifier belongs to: itself, or a stage of it (`<flow id>-<flow>`)."""
    candidate = flow_id
    while candidate not in flow_ids:
        if "-" not in candidate:
            return None
        candidate = candidate.rsplit("-", 1)[0]
    return candidate


def _facts(c: sqlite3.Connection, flow_ids: set[str]) -> dict[str, dict[str, set[str]]]:
    """Per item flow identifier: the paths of its data points, its cross-document to-do producers, email tasks and
    native facts."""
    from jav import work

    facts: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for run_id, arm in c.execute("SELECT run_id, arm FROM datapoints"):
        if (own := _owner(str(run_id), flow_ids)) is not None:
            facts[own]["arms"].add(str(arm or "-"))
    for run_id, producer in c.execute("SELECT run_id, producer FROM review_reasons"):
        if producer in _CROSS_PRODUCERS and (own := _owner(str(run_id), flow_ids)) is not None:
            facts[own]["cross"].add(producer)
    for run_id, tasks in c.execute("SELECT run_id, tasks FROM email_results"):
        if (own := _owner(str(run_id), flow_ids)) is not None and json.loads(tasks or "[]"):
            facts[own]["tasks"].add("tasks")
    if c.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'native_outcomes'").fetchone():
        for run_id, item_id in c.execute("SELECT run_id, item_id FROM native_outcomes"):
            if (own := work.flow_run_id(str(run_id), str(item_id))) in flow_ids:
                facts[own]["native"].add("native")
    return facts


def _units(items: list[dict[str, Any]]) -> list[tuple[int, list[dict[str, Any]]]]:
    """A run's input as units in input order: an email with its attachments, every other item alone."""
    emails = {i["item_id"] for i in items if i.get("kind") == "email"}
    units = []
    for n, item in enumerate(items):
        if item.get("parent_item_id") in emails:
            continue
        attached = [i for i in items if i.get("parent_item_id") == item["item_id"]] if item["item_id"] in emails else []
        units.append((n, [item, *attached]))
    return units


def _allocate(groups: dict[tuple[str, ...], list[Unit]], size: int,
              answered: set[tuple[str, ...]] | None = None) -> list[Unit]:
    """One unit of every stratum (even past `size`), then the rest by stratum size (largest remainder), only among the
    `answered` strata when given."""
    strata = sorted(groups)
    take = dict.fromkeys(strata, 1)
    left = size - len(strata)
    rest = {s: len(groups[s]) - 1 if answered is None or s in answered else 0 for s in strata}
    pool = sum(rest.values())
    if left >= pool:  # everything there is to take fits
        take = {s: 1 + rest[s] for s in strata}
    elif left > 0:
        shares = {s: left * rest[s] / pool for s in strata}
        for s in strata:
            take[s] += int(shares[s])
        by_remainder = sorted(strata, key=lambda s: (int(shares[s]) - shares[s], s))
        for s in by_remainder[: size - sum(take.values())]:
            take[s] = min(take[s] + 1, len(groups[s]))
    return [u for s in strata for u in groups[s][: take[s]]]


def sample(c: sqlite3.Connection, size: int = SAMPLE_SIZE, *, answered: set[tuple[str, ...]] | None = None) -> list[Unit]:
    """The units to replay, in the order of their runs (oldest first) and of their items in the run; deterministic.
    Within a stratum the newest runs' units are taken first (a run's position by creation, then a hash of its head
    item): an older run's questions were asked in an earlier wording, and a changed question has a new key in the
    answer cache, so its earlier answers no longer count (173: of the 128 replayed items of runs before 2026-10-10, 106
    had an answer missing; of the 24 later ones, 1). `answered`: only these strata get units beyond their first."""
    from jav import work

    runs = c.execute("SELECT r.run_id, r.mode, r.recipe, r.params, r.input, w.source_kind FROM runs r"
                     " LEFT JOIN workpackages w ON w.id = r.workpackage_id"
                     " WHERE r.status NOT IN ('cancelled', 'queued', 'running') ORDER BY r.created_at, r.run_id").fetchall()
    ended: dict[tuple[str, str], str] = {}
    for run_id, item_id, status, final in c.execute("SELECT run_id, item_id, status, final_status FROM run_items"):
        if status in ("done", "failed"):
            ended[(run_id, item_id)] = final or status
    candidates: list[tuple[dict[str, Any], int, list[dict[str, Any]]]] = []
    for run in runs:
        for n, unit in _units(json.loads(run["input"])["items"]):
            if (run["run_id"], unit[0]["item_id"]) in ended:
                candidates.append((dict(run), n, unit))
    flow_ids = {work.flow_run_id(run["run_id"], unit[0]["item_id"]) for run, _, unit in candidates}
    facts = _facts(c, flow_ids)
    groups: dict[tuple[str, ...], list[Unit]] = defaultdict(list)
    position: dict[Unit, tuple[int, int]] = {}
    for order, (run, n, unit) in enumerate(candidates):
        head = unit[0]
        recipe, params = json.loads(run["recipe"]), json.loads(run["params"] or "{}")
        fact = facts.get(work.flow_run_id(run["run_id"], head["item_id"]), {})
        stratum = (work.flow_for(recipe, head), str(head.get("kind") or "-"), str(run["source_kind"] or "-"), run["mode"],
                   "gpt" if params.get("jev") == "off" else "jev", "+".join(sorted(fact.get("arms", ()))) or "-",
                   "native" if fact.get("native") else "-", ended[(run["run_id"], head["item_id"])],
                   "tasks" if fact.get("tasks") else "-", "+".join(sorted(fact.get("cross", ()))) or "-")
        u = Unit(run["run_id"], tuple(i["item_id"] for i in unit), stratum)
        groups[stratum].append(u)
        position[u] = (order, n)
    for units in groups.values():  # the newest runs first; within a run by a hash of the head item
        units.sort(key=lambda u: (-position[u][0], hashlib.sha256(f"{u.run_id}:{u.item_ids[0]}".encode()).hexdigest()))
    return sorted(_allocate(groups, size, answered), key=lambda u: position[u])


# --- offline ------------------------------------------------------------------------------------------------------

def _network_closed() -> None:
    """Refuses to replay unless a request through both HTTP libraries the providers use fails before it leaves (the
    JEV and OpenAI clients use `httpx2`, the Azure and exchange rate requests `urllib`)."""
    import httpx2

    try:
        with httpx2.Client(timeout=5) as client:
            client.get(_NETWORK_PROBE)
    except httpx2.HTTPError:
        pass
    else:
        raise SnapshotError("the network is open for httpx2: the replay could reach a provider")
    try:
        urllib.request.urlopen(_NETWORK_PROBE, timeout=5)  # noqa: S310 - a fixed https address
    except urllib.error.HTTPError as exc:  # an answer: the request left
        raise SnapshotError("the network is open for urllib: the replay could reach a provider") from exc
    except OSError:  # URLError is one: the connection to the closed port was refused
        pass
    else:
        raise SnapshotError("the network is open for urllib: the replay could reach a provider")


def _no_rates(url: str, body: bytes, headers: dict[str, str], timeout: float) -> bytes:
    raise OSError("the before/after replay does not ask the exchange rate service")


class _FixedIds:
    """Random identifiers made while an item is processed (a new native reading's intake and folder, a temporary
    instance) from a fixed sequence per item instead: two replays then make the same ones. `item` starts an item's
    sequence, so that a change in one item does not shift another's."""

    def __init__(self) -> None:
        self.seed, self.count = "", 0

    def item(self, seed: str) -> None:
        self.seed, self.count = seed, 0

    def __call__(self) -> uuid.UUID:
        self.count += 1
        return uuid.UUID(bytes=hashlib.sha256(f"replay:{self.seed}:{self.count}".encode()).digest()[:16], version=4)


@contextmanager
def _fixed_ids() -> Iterator[_FixedIds]:
    """`uuid.uuid4` and the modules that imported it by name answer from `_FixedIds` inside; put back afterwards."""
    from jav import native_results
    from jav.readers import pipeline

    ids = _FixedIds()
    targets = [(uuid, "uuid4"), (native_results, "uuid4"), (pipeline, "uuid4")]
    saved = [getattr(module, name) for module, name in targets]
    try:
        for module, name in targets:
            setattr(module, name, ids)
        yield ids
    finally:
        for (module, name), value in zip(targets, saved, strict=True):
            setattr(module, name, value)


@contextmanager
def offline(work_dir: Path) -> Iterator[None]:
    """No provider can be reached inside: the keys are placeholders (a client can be built, so a question without an
    earlier answer reaches the budget check, which refuses it), Azure is not configured, every HTTP request goes to a
    closed local port, the exchange rate service is not asked; the OCR cache is a copy in `work_dir` and the
    operational log goes there too, so the real ones are not written. Everything is put back afterwards."""
    from jav import fx, ocr
    from jav.adapters import jev
    from jav.config import API_KEY_ENV_VARS, AZURE_DI_ENV_VARS, OPENAI_KEY_ENV_VAR
    from jav.runtime import applog

    values = {**dict.fromkeys((*API_KEY_ENV_VARS, OPENAI_KEY_ENV_VAR), PLACEHOLDER_KEY),
              **dict.fromkeys(_PROXY_VARS, CLOSED_PROXY), _OPENAI_BASE_URL: f"{CLOSED_PROXY}/v1"}
    removed = (*AZURE_DI_ENV_VARS, ocr.ENGINE_ENV, *_NO_PROXY_VARS)
    saved = {name: os.environ.get(name) for name in (*values, *removed)}
    ocr_cache, log_dir = ocr.CACHE_DIR, applog.LOG_DIR
    try:
        for name in removed:
            os.environ.pop(name, None)
        os.environ.update(values)
        urllib.request.install_opener(None)  # the shared opener reads the proxy settings once, when it is built
        jev.get_adapter.cache_clear()
        _network_closed()
        copy = work_dir / "ocr-cache"
        if Path(ocr_cache).is_dir():
            shutil.copytree(ocr_cache, copy)
        ocr.CACHE_DIR, applog.LOG_DIR = copy, work_dir / "logs"
        with fx.use_transport(_no_rates):
            yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        urllib.request.install_opener(None)
        ocr.CACHE_DIR, applog.LOG_DIR = ocr_cache, log_dir
        jev.get_adapter.cache_clear()


# --- the replay ---------------------------------------------------------------------------------------------------

def replay_run_id(run_id: str) -> str:
    """The replayed run's identifier: the same for every replay of a run, so that two replays can be compared."""
    return "run-" + hashlib.sha256(f"replay:{run_id}".encode()).hexdigest()[:12]


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _replay(units: list[Unit]) -> None:
    """A replayed run per original run (its recipe, settings with earlier answers, its whole input, no budget), and its
    chosen items processed one after the other with the worker's own processing; a retry runs at once."""
    from jav import store, work
    from jav.runtime import queue, worker

    runs = list(dict.fromkeys(u.run_id for u in units))
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with store.connect() as c:
        store.begin_immediate(c)
        for run_id in runs:
            r = c.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            params = {**json.loads(r["params"] or "{}"), "jev_cache": "reuse"}  # never "live": every answer is an earlier one
            # a run of the first round is replayed again in the second: its replayed run is there already
            c.execute("INSERT OR IGNORE INTO runs(run_id, workpackage_id, dedup_key, mode, assignment_revision, recipe_id, recipe_version,"
                      " recipe_hash, recipe, params, input, input_hash, status, actor, created_at, plan, scope)"
                      " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'queued',?,?,?,?)",
                      (replay_run_id(run_id), r["workpackage_id"], f"replay:{run_id}", r["mode"], r["assignment_revision"],
                       r["recipe_id"], r["recipe_version"], r["recipe_hash"], r["recipe"], _canon(params), r["input"],
                       r["input_hash"], before_after.ACTOR, now, r["plan"], r["scope"]))
    jobs = []
    for u in units:
        rid = replay_run_id(u.run_id)
        for item_id in u.item_ids:
            jobs.append((f"{rid}:{item_id}", queue.enqueue(work.JOB_KIND, run_id=rid, dedup_key=f"{rid}:{item_id}",
                                                           payload={"run_id": rid, "item_id": item_id}).id))
    with _fixed_ids() as ids:
        for seed, job_id in jobs:
            ids.item(seed)
            while (job := queue.claim_job(job_id, WORKER)) is not None:
                worker.process(job)


def live_calls(c: sqlite3.Connection, run_ids: list[str]) -> list[dict[str, Any]]:
    """The gate: every call of the replayed runs that was not an earlier answer, first in the call log (a call that
    was reserved, sent or failed), then in the ledger (an answer that was not cached)."""
    from jav.runtime import calls

    found: list[dict[str, Any]] = []
    for rid in run_ids:
        mine = "(budget_scope = ? OR substr(run_id, 1, ?) = ?)"
        for r in c.execute(f"SELECT run_id, step_id, provider, status, note FROM invocations WHERE {mine} ORDER BY id",  # noqa: S608 - fixed text
                           (rid, len(rid) + 1, f"{rid}:")):
            if not (r["status"] == "succeeded" and str(r["note"] or "").startswith(f"{calls.REUSED_NOTE}:")):
                found.append({"source": "invocations", "run_id": r["run_id"], "step": r["step_id"],
                              "provider": r["provider"], "status": r["status"]})
    for rid in run_ids:
        for r in c.execute("SELECT run_id, step, provider, error FROM ledger WHERE substr(run_id, 1, ?) = ? AND cached = 0"
                           " ORDER BY id", (len(rid) + 1, f"{rid}:")):
            found.append({"source": "ledger", "run_id": r["run_id"], "step": r["step"], "provider": r["provider"],
                          "status": "error" if r["error"] else "answered"})
    return found


def _missing_answer(reason: str) -> bool:
    """A to-do that says a question had no earlier answer and its call was refused for want of a budget."""
    return reason.endswith(":BudgetExceeded") or "budget_exceeded" in reason


def missing_answers(c: sqlite3.Connection, run_ids: list[str]) -> int:
    """The to-dos of the replayed runs that stand for a question without an earlier answer."""
    return sum(1 for rid in run_ids
               for (reason,) in c.execute("SELECT reason FROM review_reasons WHERE substr(run_id, 1, ?) = ?",
                                          (len(rid) + 1, f"{rid}:"))
               if _missing_answer(str(reason)))


def unregistered_todos(c: sqlite3.Connection, run_ids: list[str]) -> dict[str, str]:
    """177 (plan 170 E6): the to-dos of the replayed runs of a kind `configs/todo_kinds.json` does not register (kind
    code -> the first such reason); the replay names them, the store accepts them (the owner's decision)."""
    from jav import todo_kinds

    reasons = [str(reason) for rid in run_ids
               for (reason,) in c.execute("SELECT reason FROM review_reasons WHERE substr(run_id, 1, ?) = ?",
                                          (len(rid) + 1, f"{rid}:"))]
    return todo_kinds.unregistered(reasons)


def _answered(c: sqlite3.Connection, unit: Unit) -> bool:
    """Whether every question of the replayed unit had an earlier answer (no to-do stands for a missing one)."""
    from jav import work

    rid = replay_run_id(unit.run_id)
    for item_id in unit.item_ids:
        fid = work.flow_run_id(rid, item_id)
        for (reason,) in c.execute("SELECT reason FROM review_reasons WHERE run_id = ? OR substr(run_id, 1, ?) = ?",
                                   (fid, len(fid) + 1, f"{fid}-")):
            if _missing_answer(str(reason)):
                return False
    return True


# --- the records --------------------------------------------------------------------------------------------------

def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k not in _VOLATILE}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _rows(c: sqlite3.Connection, run_id: str, item: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """The item's stored rows, by its flow identifier and its stages (explicit columns, without times and row ids)."""
    from jav import work

    fid = work.flow_run_id(run_id, item["item_id"])
    own = "({col} = ? OR substr({col}, 1, ?) = ?)"
    args = (fid, len(fid) + 1, f"{fid}-")

    def rows(sql: str, params: tuple = args) -> list[dict[str, Any]]:
        return [dict(r) for r in c.execute(sql, params)]

    item_args = (run_id, item["item_id"])
    return {
        "datapoints": rows("SELECT run_id, doc_id, doc_type, arm, datapoints, field_conf, validation, route, review_reasons,"
                           " final_status, config_hash, record_conf, evidence, provenance, source_layer_id FROM datapoints"
                           f" WHERE {own.format(col='run_id')} ORDER BY run_id, doc_id"),
        "documents": rows("SELECT doc_id, source_path, source_email, doc_type, type_conf, issuer_hu, has_text, page_count,"
                          " year, last_run_id, detail_type, detail_conf, detail_method FROM documents"
                          f" WHERE {own.format(col='last_run_id')} ORDER BY doc_id"),
        "reasons": rows("SELECT rq.subject_kind, rq.subject_id, rr.run_id, rr.reason, rr.producer, rr.status, rr.actor,"
                        " rr.resolution, rr.note FROM review_reasons rr JOIN review_queue rq ON rq.id = rr.review_id"
                        f" WHERE {own.format(col='rr.run_id')} ORDER BY rr.id"),
        "reviews": rows("SELECT subject_kind, subject_id, run_id, reasons, payload, status, decision FROM review_queue"
                        f" WHERE {own.format(col='run_id')} ORDER BY id"),
        "emails": rows("SELECT message_id, mailbox, sender, subject, received_at, body_excerpt, attachments, intent, intent_conf,"
                       f" signals, next_flow, run_id FROM emails WHERE {own.format(col='run_id')} ORDER BY message_id"),
        "email_results": rows("SELECT run_id, message_id, intent, intent_conf, signals, next_flow, attachments, body, tasks,"
                              f" folder FROM email_results WHERE {own.format(col='run_id')} ORDER BY run_id"),
        "native_outcomes": rows("SELECT graph_id, reading_id, payload_sha256 FROM native_outcomes WHERE run_id = ? AND item_id = ?"
                                " ORDER BY graph_id, reading_id", item_args),
        "native_publications": rows("SELECT publication_id, payload_sha256 FROM native_publications WHERE run_id = ?"
                                    " AND item_id = ? ORDER BY publication_id", item_args),
        "ledger": rows("SELECT run_id, step, provider, model, input_tokens, output_tokens, cost_usd, cached, cache_key,"
                       f" config_hash, error FROM ledger WHERE {own.format(col='run_id')} ORDER BY id"),
        "calls": rows("SELECT run_id, step_id, attempt, provider, model_requested, model_actual, request_hash, budget_scope,"
                      f" status, cost_usd, error, note FROM invocations WHERE {own.format(col='run_id')} ORDER BY id"),
    }


def _result(c: sqlite3.Connection, run_id: str, item_id: str) -> dict[str, Any] | None:
    row = c.execute("SELECT status, final_status, error FROM run_items WHERE run_id = ? AND item_id = ?",
                    (run_id, item_id)).fetchone()
    return dict(row) if row else None


def _values(rows: list[dict[str, Any]]) -> list[tuple[Any, Any]]:
    return [(r["doc_id"], r["datapoints"]) for r in rows]


def _records(reader: before_after._Reader, c: sqlite3.Connection, units: list[Unit]) -> Iterator[tuple[str, Any]]:
    """Per replayed run its views and tables, per item its end state, stored rows and view; keyed by the original."""
    for run_id in dict.fromkeys(u.run_id for u in units):
        rid = replay_run_id(run_id)
        for name, path in (("run", f"/runs/{rid}"), ("results", f"/runs/{rid}/results")):
            _, value = reader.get(f"replay/{name}", path)
            yield f"replay/{run_id}/{name}", value
        for name in _REPLAY_DATASETS:
            _, value = reader.dataset(name, {"run_id": rid})
            yield f"replay/{run_id}/dataset/{name}", value
    inputs: dict[str, dict[str, dict[str, Any]]] = {}
    for u in units:
        rid = replay_run_id(u.run_id)
        if u.run_id not in inputs:
            row = c.execute("SELECT input FROM runs WHERE run_id = ?", (rid,)).fetchone()
            inputs[u.run_id] = {i["item_id"]: i for i in json.loads(row["input"])["items"]}
        for item_id in u.item_ids:
            item = inputs[u.run_id][item_id]
            yield f"replay/{u.run_id}/{item_id}/result", {"status": 200, "body": _result(c, rid, item_id)}
            yield f"replay/{u.run_id}/{item_id}/rows", {"status": 200, "body": _rows(c, rid, item)}
            _, value = reader.get("replay/item", f"/runs/{rid}/items/{quote(item_id, safe='')}")
            yield f"replay/{u.run_id}/{item_id}/view", value


def _same_as_original(c: sqlite3.Connection, units: list[Unit]) -> int:
    """How many replayed items ended as their original did: the same end state and the same data points."""
    same = 0
    for u in units:
        rid = replay_run_id(u.run_id)
        inputs = {i["item_id"]: i for i in json.loads(c.execute("SELECT input FROM runs WHERE run_id = ?",
                                                                (u.run_id,)).fetchone()["input"])["items"]}
        for item_id in u.item_ids:
            original, replayed = _result(c, u.run_id, item_id), _result(c, rid, item_id)
            if original is None or replayed is None:
                continue
            if (original["status"], original["final_status"]) != (replayed["status"], replayed["final_status"]):
                continue
            item = inputs[item_id]
            if _values(_rows(c, u.run_id, item)["datapoints"]) == _values(_rows(c, rid, item)["datapoints"]):
                same += 1
    return same


def _cache_facts(cache: Path) -> dict[str, Any]:
    from jav.adapters import jev

    versions = cache / jev.MODEL_VERSIONS_FILE
    return {"path": str(cache), "files": sum(1 for _ in cache.glob("*.json")) if cache.is_dir() else 0,
            "versions": json.loads(versions.read_text(encoding="utf-8")) if versions.is_file() else {}}


def running_snapshot(baseline: Path, work_dir: Path, out: Path, *, size: int = SAMPLE_SIZE,
                     jev_cache: Path | None = None) -> dict[str, Any]:
    """Replay a sample of the backed-up store's items on a fresh copy, offline and from earlier answers only, and
    write the results to `out` (JSON lines, the static snapshot's format). `jev_cache`: the JEV answer cache read
    (default: the work one, `runs/cache`; it is only read, since no live answer can come).

    Returns the counts and the gate: `passed` is False when a replayed run made a call that was not an earlier answer
    (`live_calls`); the snapshot is written anyway, so that the call can be looked at."""
    from fastapi.testclient import TestClient

    from jav import datasets, registrations, store
    from jav.adapters import jev
    from jav.api import create_app
    from jav.config import CACHE_DIR
    from jav.runtime import calls

    registrations.load_all()  # 173 (plan 170 E2): the worker's registrations (a package kind's rule), as when it starts
    for path in (out, work_dir):
        before_after._outside_git(path)
    if out.exists():
        raise SnapshotError(f"the output already exists: {out}")
    cache = Path(jev_cache) if jev_cache is not None else CACHE_DIR
    copy = before_after.fresh_copy(baseline, work_dir)
    default = store.STORE_PATH
    store.STORE_PATH = copy
    datasets.clear_cache()  # a dataset cached from another copy at the same path would hide a difference
    try:
        with offline(copy.parent), jev.use_adapter(jev.JevAdapter(cache_dir=cache)):
            # two rounds: the newest unit of every stratum first; the rest of the sample then goes only to the strata
            # whose first unit had every earlier answer (an older unit of a stratum was asked in the same or an older
            # wording, so where the newest lacks an answer, the older ones lack it too)
            with store.connect() as c:
                first = sample(c, 0)
            _replay(first)
            with store.connect() as c:
                answered = {u.stratum for u in first if _answered(c, u)}
                units = sample(c, size, answered=answered)
            done = set(first)
            _replay([u for u in units if u not in done])
            datasets.wait_for_rebuilds()
            rids = [replay_run_id(r) for r in dict.fromkeys(u.run_id for u in units)]
            with store.connect() as c:
                found, missing, same = live_calls(c, rids), missing_answers(c, rids), _same_as_original(c, units)
                unregistered = unregistered_todos(c, rids)
            gate = {"live_calls": len(found), "passed": not found}
            out.parent.mkdir(parents=True, exist_ok=True)
            with TestClient(create_app(store_path=copy), base_url=before_after.BASE_URL,
                            headers={"X-Actor": before_after.ACTOR}) as client, \
                    store.connect() as c, out.open("w", encoding="utf-8", newline="\n") as f:
                meta = {"format": before_after.FORMAT_VERSION, "kind": "replay", "git": before_after._git_line(),
                        "baseline": str(before_after._store_of(baseline)),
                        "taken_at": datetime.now().astimezone().isoformat(timespec="seconds"), "size": size,
                        "units": len(units), "items": sum(len(u.item_ids) for u in units),
                        "strata": len({u.stratum for u in units}), "answered_strata": len(answered),
                        "jev_cache": _cache_facts(cache), "gate": gate,
                        "missing_answers": missing, "same_as_original": same, "live": found[:50]}
                f.write(json.dumps({"meta": meta}, ensure_ascii=False) + "\n")
                reader = before_after._Reader(client)
                views = 0
                for key, value in _records(reader, c, units):
                    f.write(json.dumps({"key": key, "value": _clean(value)}, ensure_ascii=False, sort_keys=True,
                                       default=str) + "\n")
                    views += 1
    finally:
        datasets.wait_for_rebuilds()
        datasets.clear_cache()
        calls.release_holder()  # the copy's holder lock (the call log's reservations): the next replay replaces the folder
        store.STORE_PATH = default
    return {"units": meta["units"], "items": meta["items"], "strata": meta["strata"],
            "answered_strata": meta["answered_strata"], "views": views,
            "live_calls": gate["live_calls"], "passed": gate["passed"], "missing_answers": missing,
            "same_as_original": same, "live": found[:20], "unregistered_todos": unregistered}
