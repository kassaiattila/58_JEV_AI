"""Running before/after snapshot (plan 170, E0b): the processing replayed from earlier answers, without any provider.

Guarantees tested: a replay taken twice is the same and leaves the backup, the environment and the default store as
they were; a missing earlier answer becomes a to-do, never a call; the gate names every call that was not an earlier
answer; the sample takes every stratum once, then shares the rest out by size, keeps an email with its attachments and
leaves stopped runs out; the queue hands over one given job.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from typesafe_sdk import Choice, SystemOneResponse

from jav import before_after, before_after_replay, store, work, work_readiness, work_recipes, work_runs
from jav.adapters import jev as jev_mod
from jav.runtime import queue, worker
from tests.pdfgen import INVOICE_LINES, write_text_pdf


class FakeClient:
    def __init__(self) -> None:
        self.calls = 0

    def system_one(self, *, state, questions, model):
        self.calls += 1
        answers = {}
        for qid, q in questions.items():
            if isinstance(q, Choice):
                first = next(iter(q.criteria))
                answers[qid] = {"type": "choice", "choice": first, "confidence": 0.97,
                                "probabilities": {k: (0.97 if k == first else 0.03 / max(len(q.criteria) - 1, 1)) for k in q.criteria}}
            else:
                answers[qid] = {"type": "noul", "noul": 0.95}
        return SystemOneResponse.model_validate({"model": model, "usage": {"input_tokens": 500, "output_tokens": 0}, "answers": answers})


def _versions(cache: Path) -> None:
    """The alias resolution as the work cache keeps it; long expired, so the replay must use it without a probe (200: with
    the configured model pinned the replay needs no resolution; the file stays for an alias configuration)."""
    cache.mkdir(parents=True, exist_ok=True)
    (cache / jev_mod.MODEL_VERSIONS_FILE).write_text(json.dumps(
        {"jev-latest": {"model": "jev-1.13.0", "resolved_at": "2026-01-01T00:00:00+00:00"}}), encoding="utf-8")


@pytest.fixture()
def processed(tmp_path: Path, monkeypatch):
    """A backup of a store with one trial run over two synthetic invoices, answered by a fake JEV into a cache."""
    monkeypatch.setattr(before_after_replay, "_network_closed", lambda: None)  # no connection attempt in the tests
    client = FakeClient()
    cache = tmp_path / "jev-cache"
    _versions(cache)
    folder = tmp_path / "incoming"
    folder.mkdir()
    write_text_pdf(folder / "invoice_1.pdf", INVOICE_LINES)
    write_text_pdf(folder / "invoice_2.pdf", [line.replace("MINTA-2026-001", "MINTA-2026-002") for line in INVOICE_LINES])
    live = tmp_path / "live" / "jav.sqlite"
    # 200: the answers under the configured model's key, which the replay reads (a pinned version since then)
    adapter = jev_mod.JevAdapter(client=client, cache_dir=cache)
    with store.use_store(live), jev_mod.use_adapter(adapter):
        wp = work.create_from_folder(folder, name="Synthetic invoices")
        work_recipes.assign_recipe(wp["id"], "invoice-extraction", params={"arm": "S", "doc_type": "invoice_hu"},
                           expected_revision=0, actor="t")
        ready = work_readiness.readiness(wp["id"])
        run_id = work_runs.start_run(wp["id"], mode="shadow", expected_assignment_revision=1, input_hash=ready["input_hash"],
                                actor="t")["run_id"]
        assert worker.run_worker(once=True)["processed"] == 2
        original = {i["item_id"]: i["final_status"] for i in work_runs.get_run(run_id)["items"]}
    backup = tmp_path / "backup" / "20261018-120000"
    backup.mkdir(parents=True)
    shutil.copyfile(live, backup / "jav.sqlite")
    if (live.parent / "sources").is_dir():
        shutil.copytree(live.parent / "sources", backup.parent / "sources")
    return {"backup": backup, "cache": cache, "client": client, "run_id": run_id, "original": original, "tmp": tmp_path}


def test_a_replay_taken_twice_is_the_same_and_asks_no_one(processed) -> None:
    tmp, backup = processed["tmp"], processed["backup"]
    stored = (backup / "jav.sqlite").read_bytes()
    default, environment, asked = store.STORE_PATH, dict(os.environ), processed["client"].calls
    first, second = tmp / "first.jsonl", tmp / "second.jsonl"
    summary = before_after_replay.running_snapshot(backup, tmp / "work", first, jev_cache=processed["cache"])
    before_after_replay.running_snapshot(backup, tmp / "work", second, jev_cache=processed["cache"])
    assert before_after.diff(first, second) == []
    assert summary["live_calls"] == 0 and summary["passed"] is True
    assert summary["units"] == 2 and summary["items"] == 2 and summary["missing_answers"] == 0
    assert summary["answered_strata"] == 1  # the first round's unit had its answers: the second added the other
    assert summary["same_as_original"] == 2
    assert summary["unregistered_todos"] == {}  # 177: every replayed to-do is of a registered kind
    assert processed["client"].calls == asked
    assert (backup / "jav.sqlite").read_bytes() == stored
    assert store.STORE_PATH == default and dict(os.environ) == environment
    meta, views = before_after.load(first)
    assert meta["kind"] == "replay" and meta["gate"] == {"live_calls": 0, "passed": True}
    run_id = processed["run_id"]
    for item_id, final in processed["original"].items():
        assert views[f"replay/{run_id}/{item_id}/result"]["body"]["final_status"] == final
        assert views[f"replay/{run_id}/{item_id}/view"]["status"] == 200
        rows = views[f"replay/{run_id}/{item_id}/rows"]["body"]
        assert rows["datapoints"] and all(r["arm"] == "S" for r in rows["datapoints"])
        assert rows["ledger"] and all(r["cached"] == 1 for r in rows["ledger"])
    assert views[f"replay/{run_id}/run"]["status"] == 200
    with pytest.raises(before_after.SnapshotError, match="already exists"):
        before_after_replay.running_snapshot(backup, tmp / "work", first, jev_cache=processed["cache"])


def test_a_missing_earlier_answer_becomes_a_to_do_not_a_call(processed) -> None:
    tmp = processed["tmp"]
    empty = tmp / "empty-cache"
    _versions(empty)
    out = tmp / "missing.jsonl"
    summary = before_after_replay.running_snapshot(processed["backup"], tmp / "work", out, jev_cache=empty)
    assert summary["live_calls"] == 0 and summary["passed"] is True
    assert summary["missing_answers"] > 0 and summary["same_as_original"] == 0
    # the stratum's first unit lacked an answer, so the second round gives it no more
    assert summary["units"] == 1 and summary["answered_strata"] == 0
    _, views = before_after.load(out)
    run_id = processed["run_id"]
    rows = [v for k, v in views.items() if k.startswith(f"replay/{run_id}/") and k.endswith("/rows")]
    assert len(rows) == 1
    assert "jev_unavailable:budget_exceeded" in [r["reason"] for r in rows[0]["body"]["reasons"]]
    assert processed["client"].calls > 0  # the fixture's own run; the replay added nothing (no client to call)


def test_the_gate_names_every_call_that_was_not_an_earlier_answer(tmp_path) -> None:
    rid = "run-aaaaaaaaaaaa"
    with store.use_store(tmp_path / "s.sqlite"):
        from jav.runtime import calls  # noqa: F401 - registers the call log's tables

        with store.connect() as c:
            insert = ("INSERT INTO invocations(run_id, step_id, attempt, provider, request_hash, budget_scope, status,"
                      " max_cost_usd, note, created_at) VALUES (?,?,1,?,?,?,?,?,?,?)")
            c.execute(insert, (f"{rid}:item-1", "jev:a", "jev", "h1", rid, "succeeded", "0", "reused_answer:5", "t"))
            c.execute(insert, (f"{rid}:item-1", "gpt:b", "openai", "h2", rid, "succeeded", "0.01", None, "t"))
            c.execute(insert, (f"{rid}:item-2-doc_detect", "jev:c", "jev", "h3", rid, "failed", "0.01", None, "t"))
            c.execute(insert, ("run-bbbbbbbbbbbb:item-1", "jev:d", "jev", "h4", "run-bbbbbbbbbbbb", "succeeded", "0.01", None, "t"))
        for flow_id, cached in ((f"{rid}:item-1", 1), (f"{rid}:item-1", 0), ("run-bbbbbbbbbbbb:item-1", 0)):
            store.ledger_add(run_id=flow_id, step="s", provider="jev", model="jev-1.13.0", input_tokens=1,
                             output_tokens=0, cost_usd=0.0, seconds=0.0, cached=bool(cached), cache_key="k",
                             config_hash=None)
        with store.connect() as c:
            found = before_after_replay.live_calls(c, [rid])
    assert [(f["source"], f["step"]) for f in found] == [("invocations", "gpt:b"), ("invocations", "jev:c"), ("ledger", "s")]


def _seed(path: Path) -> dict[str, str]:
    """Runs written straight into a store: a trial invoice run with ten documents, a live email run with an email and
    its two attachments plus a loose document, and a stopped run."""
    invoice = {"flow": "invoice"}
    email = {"flow": "document", "flows": {"email": "email"}}
    with store.use_store(path):
        a = work.create_workpackage(name="A", source_kind="folder", source_ref=None)
        b = work.create_workpackage(name="B", source_kind="mailbox", source_ref=None)
        with store.connect() as c:
            def run(run_id, wp, mode, status, recipe, items, created):
                c.execute("INSERT INTO runs(run_id, workpackage_id, dedup_key, mode, assignment_revision, recipe_id,"
                          " recipe_version, recipe_hash, recipe, params, input, input_hash, status, actor, created_at)"
                          " VALUES (?,?,?,?,1,'r','1','h',?,?,?,'i',?,'t',?)",
                          (run_id, wp, run_id, mode, json.dumps(recipe), json.dumps({"arm": "auto"}),
                           json.dumps({"items": items}), status, created))
                for item in items:
                    c.execute("INSERT INTO run_items(run_id, item_id, status, final_status, flow_run_id, updated_at)"
                              " VALUES (?,?,?,?,?,?)", (run_id, item["item_id"], "done", "done",
                                                        work_runs.flow_run_id(run_id, item["item_id"]), created))

            run("run-000000000001", a["id"], "shadow", "done", invoice,
                [{"item_id": f"doc-{n:02d}", "kind": "document", "source_path": f"C:/x/{n}.pdf", "sha256": "s"}
                 for n in range(10)], "2026-10-01T10:00:00+00:00")
            run("run-000000000002", b["id"], "apply", "done", email,
                [{"item_id": "mail-1", "kind": "email", "source_path": "C:/x/m/message.json", "sha256": "s"},
                 {"item_id": "att-1", "kind": "document", "source_path": "C:/x/m/a.pdf", "sha256": "s", "parent_item_id": "mail-1"},
                 {"item_id": "att-2", "kind": "document", "source_path": "C:/x/m/b.pdf", "sha256": "s", "parent_item_id": "mail-1"},
                 {"item_id": "loose-1", "kind": "document", "source_path": "C:/x/c.pdf", "sha256": "s"}],
                "2026-09-01T10:00:00+00:00")
            run("run-000000000003", a["id"], "apply", "cancelled", invoice,
                [{"item_id": f"stop-{n}", "kind": "document", "source_path": f"C:/x/s{n}.pdf", "sha256": "s"}
                 for n in range(3)], "2026-10-02T10:00:00+00:00")
    return {"a": a["id"], "b": b["id"]}


def test_the_sample_takes_every_stratum_once_then_shares_the_rest_by_size(tmp_path) -> None:
    path = tmp_path / "s.sqlite"
    _seed(path)
    with store.use_store(path), store.connect() as c:
        units = before_after_replay.sample(c, size=4)
        again = before_after_replay.sample(c, size=4)
        everything = before_after_replay.sample(c, size=100)
        documents = next(u for u in everything if u.run_id == "run-000000000001").stratum
        loose = next(u for u in everything if u.item_ids[0] == "loose-1").stratum
        to_documents = before_after_replay.sample(c, size=6, answered={documents})
        to_loose = before_after_replay.sample(c, size=6, answered={loose})
    assert units == again
    assert all(u.run_id != "run-000000000003" for u in everything)  # a stopped run is left out
    assert len(everything) == 10 + 2  # ten documents; the email with its attachments; the loose document
    assert sum(len(u.item_ids) for u in everything) == 14
    strata = {u.stratum for u in units}
    assert strata == {u.stratum for u in everything}  # every stratum is in the small sample too
    assert len(units) == 4
    mail = next(u for u in everything if u.item_ids[0] == "mail-1")
    assert mail.item_ids == ("mail-1", "att-1", "att-2")
    # the second round: beyond its first unit, only an answered stratum gets more (the loose one has no more)
    assert [u.run_id for u in to_documents].count("run-000000000001") == 4 and len(to_documents) == 6
    assert [u.run_id for u in to_loose].count("run-000000000001") == 1 and len(to_loose) == 3
    # three strata, one each and the fourth to the largest; in the order the runs were made, then the items' order
    assert [(u.run_id, u.item_ids[0]) for u in units][:2] == [("run-000000000002", "mail-1"), ("run-000000000002", "loose-1")]
    assert [u.run_id for u in units][2:] == ["run-000000000001"] * 2


def test_inside_offline_no_request_leaves_and_everything_is_put_back(tmp_path) -> None:
    from jav import ocr
    from jav.config import API_KEY_ENV_VARS, OPENAI_KEY_ENV_VAR

    environment, cache = dict(os.environ), ocr.CACHE_DIR
    with before_after_replay.offline(tmp_path):  # the real check: a request to a provider fails at the closed port
        assert os.environ[OPENAI_KEY_ENV_VAR] == before_after_replay.PLACEHOLDER_KEY
        assert all(os.environ[name] == before_after_replay.PLACEHOLDER_KEY for name in API_KEY_ENV_VARS)
        assert os.environ["HTTPS_PROXY"] == before_after_replay.CLOSED_PROXY
        assert ocr.CACHE_DIR == tmp_path / "ocr-cache"
    assert dict(os.environ) == environment and ocr.CACHE_DIR == cache


def test_random_identifiers_repeat_per_item_inside_a_replay_only() -> None:
    import uuid

    from jav import native_results
    from jav.readers import pipeline

    real = uuid.uuid4
    with before_after_replay._fixed_ids() as ids:
        ids.item("run-a:item-1")
        first = [uuid.uuid4(), native_results.uuid4(), pipeline.uuid4()]
        ids.item("run-a:item-2")
        other = uuid.uuid4()
        ids.item("run-a:item-1")
        again = [uuid.uuid4(), native_results.uuid4(), pipeline.uuid4()]
    assert first == again and len(set(first)) == 3 and other not in first
    assert all(u.version == 4 for u in first)
    assert uuid.uuid4 is real and native_results.uuid4 is real and pipeline.uuid4 is real
    assert uuid.uuid4() != uuid.uuid4()


def test_the_queue_hands_over_one_given_job(tmp_path) -> None:
    with store.use_store(tmp_path / "q.sqlite"):
        first = queue.enqueue("run_item", run_id="r", payload={"n": 1}, dedup_key="a")
        later = queue.enqueue("run_item", run_id="r", payload={"n": 2}, dedup_key="b", delay_s=3600)
        claimed = queue.claim_job(later.id, "w")  # not yet available to the worker; a replay takes it anyway
        assert claimed is not None and claimed.id == later.id and claimed.status == "claimed"
        assert queue.claim_job(later.id, "w") is None  # already claimed
        assert queue.claim("w").id == first.id
