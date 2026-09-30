"""063: stability review — pinning down the bugs, confirmed in the code, that threatened normal operation.

Synthetic data, a fake JEV and a fake Outlook script, no paid call. Every test rules out a previously confirmed bug:
the worker does not stop on a faulty job (nor at the same place on restart), a stop requested during shutdown does
not get stuck, a half-finished run start is repaired and cannot be approved, the emails of an interrupted mail
download are not lost, and a failed scan of a watched folder does not skip a file.
"""

import os
import subprocess
from pathlib import Path

import pytest

from jav import app_settings, emails, ingest_server, mailbox, store, work
from jav.adapters import jev as jev_mod
from jav.runtime import queue, worker
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_mailbox import MAILS, REQ, FakeBridge
from tests.test_runtime_worker import FakeClient


@pytest.fixture()
def db(tmp_path: Path):
    with store.use_store(tmp_path / "s.sqlite"):
        yield tmp_path


@pytest.fixture()
def wp_env(tmp_path: Path):
    adapter = jev_mod.JevAdapter(client=FakeClient(), cache_dir=tmp_path / "cache", model="jev-1.13.0")
    folder = tmp_path / "bejovo"
    folder.mkdir()
    write_text_pdf(folder / "szamla_1.pdf", INVOICE_LINES)
    write_text_pdf(folder / "szamla_2.pdf", [line.replace("MINTA-2026-001", "MINTA-2026-002") for line in INVOICE_LINES])
    with store.use_store(tmp_path / "w.sqlite"), jev_mod.use_adapter(adapter):
        wp = work.create_from_folder(folder, name="Mesterséges számlák")
        work.assign_recipe(wp["id"], "invoice-extraction", params={"arm": "S", "doc_type": "invoice_hu"}, expected_revision=0, actor="t")
        yield {"wp": wp, "tmp": tmp_path}


def _start(wp_id: str, mode: str = "shadow") -> str:
    r = work.readiness(wp_id)
    return work.start_run(wp_id, mode=mode, expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")["run_id"]


# --- work queue: orphaned claims on restart -----------------------------------------------------------------------


def test_orphan_with_cancel_request_is_cancelled_on_restart(db):
    job = queue.enqueue("run_item", run_id="r1", payload={}, dedup_key="a")
    queue.claim("halott")
    assert queue.cancel(job.id) == "cancel_requested"  # cancel was requested while the worker was shutting down
    rec = queue.recover_orphans()
    assert [j.id for j in rec.cancelled] == [job.id] and rec.requeued == 0
    assert queue.get(job.id).status == "cancelled" and queue.claim("w2") is None


def test_orphan_over_the_attempt_limit_goes_dead(db):
    job = queue.enqueue("run_item", run_id="r1", payload={}, dedup_key="a")
    for n in range(1, queue.ORPHAN_MAX_ATTEMPTS):  # the job "kills" the worker on every attempt
        assert queue.claim("w").id == job.id
        assert queue.recover_orphans().requeued == 1
    queue.claim("w")
    rec = queue.recover_orphans()
    assert [j.id for j in rec.dead] == [job.id]
    dead = queue.get(job.id)
    assert dead.status == "dead" and dead.attempts == queue.ORPHAN_MAX_ATTEMPTS


def test_requeued_orphan_yields_to_fresh_jobs(db):
    crashy = queue.enqueue("run_item", run_id="r1", payload={"n": 1}, dedup_key="a")
    fresh = queue.enqueue("run_item", run_id="r1", payload={"n": 2}, dedup_key="b")
    queue.claim("w")
    queue.recover_orphans()
    assert queue.claim("w2").id == fresh.id  # after a restart the fresh job runs first, not the suspect one
    assert queue.claim("w2").id == crashy.id


# --- the worker loop does not stop on an unexpected error ----------------------------------------------------------


def test_worker_survives_unexpected_errors_in_ticks_and_pull_jobs(wp_env, monkeypatch):
    run_id = _start(wp_env["wp"]["id"])

    def boom(*_a, **_k):
        raise RuntimeError("váratlan hiba")

    monkeypatch.setattr(mailbox, "tick", boom)
    monkeypatch.setattr(app_settings, "tick", boom)
    monkeypatch.setattr(worker, "process_pull", boom)
    pull_job = queue.enqueue(mailbox.PULL_JOB_KIND, run_id=None, payload={"pull_id": "pull-x"}, dedup_key="p")
    info = worker.run_worker(once=True)
    assert info["results"].get("done") == 2  # both document items ran
    assert info["errors"] >= 3  # the two scheduler errors and the download error were logged and did not stop it
    assert queue.get(pull_job.id).status == "dead"  # the faulty job is not retried forever
    assert work.get_run(run_id)["status"] in ("done", "needs_review")


def test_dead_orphan_item_is_recorded_as_failed(wp_env):
    run_id = _start(wp_env["wp"]["id"])
    job = queue.claim("w")
    with store.connect() as c:  # the item has already "killed" the worker several times; now again
        c.execute("UPDATE jobs SET attempts=? WHERE id=?", (queue.ORPHAN_MAX_ATTEMPTS - 1, job.id))
    info = worker.startup()
    assert info["orphans_dead"] == 1 and info["orphans_requeued"] == 0
    item = next(i for i in work.get_run(run_id)["items"] if i["item_id"] == job.payload["item_id"])
    assert item["status"] == "failed" and "orphaned" in item["error"]
    worker.run_worker(once=True)  # the other item runs; the run closes as failed (the dead item is visible)
    assert work.get_run(run_id)["status"] == "failed"


# --- starting and approving runs ------------------------------------------------------------------------------------


def test_half_started_run_is_repaired_by_retry_and_cannot_be_approved_meanwhile(wp_env):
    wp_id = wp_env["wp"]["id"]
    run_id = _start(wp_id, mode="apply")
    with store.connect() as c:  # the start was interrupted after the run row was written: no jobs
        c.execute("DELETE FROM jobs WHERE run_id=?", (run_id,))
    assert work.refresh_run_status(run_id) == "queued"  # not "done": the items have not run yet
    with pytest.raises(work.NotReady):
        work.approve_run(run_id, actor="t")
    again = work.start_run(wp_id, mode="apply", expected_assignment_revision=1, input_hash=work.readiness(wp_id)["input_hash"], actor="t")
    assert again == {"run_id": run_id, "deduped": True}
    assert queue.counts(run_id=run_id).get("queued") == 2  # the repeated start filled in the missing jobs
    worker.run_worker(once=True)
    assert work.get_run(run_id)["status"] in ("done", "needs_review")


# --- mailbox download -----------------------------------------------------------------------------------------------


@pytest.fixture()
def mail_env(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ingest_server, "BRIDGE_DATA_ROOT", tmp_path / "bridge" / "data")
    monkeypatch.setattr(emails, "BRIDGE_DATA_ROOT", tmp_path / "bridge" / "data")
    with store.use_store(tmp_path / "m.sqlite"):
        yield {"inbox": tmp_path / "inbox"}


class TimeoutBridge(FakeBridge):
    """The emails arrive, then the script exceeds its time limit (or the worker is stopped)."""

    def __call__(self, argv: list[str], timeout: int) -> tuple[int, str, str]:
        super().__call__(argv, timeout)
        raise subprocess.TimeoutExpired(argv, timeout)


def test_interrupted_download_still_packages_the_stored_mail(mail_env):
    res = mailbox.fetch(REQ, actor="t", runner=TimeoutBridge(MAILS), inbox_root=mail_env["inbox"])
    assert res["new"] == 2 and res["workpackage"] and res["error"]
    assert len(work.get(res["workpackage"])["items"]) == 2


def test_stored_mail_without_a_package_is_packaged_on_the_next_download(mail_env, monkeypatch):
    real = mailbox._workpackage
    monkeypatch.setattr(mailbox, "_workpackage", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("adattár-hiba")))
    with pytest.raises(RuntimeError):
        mailbox.fetch(REQ, actor="t", runner=FakeBridge(MAILS), inbox_root=mail_env["inbox"])
    monkeypatch.setattr(mailbox, "_workpackage", real)
    again = mailbox.fetch(REQ, actor="t", runner=FakeBridge(MAILS), inbox_root=mail_env["inbox"])
    assert again["duplicate"] == 2 and again["workpackage"]  # the emails already downloaded but not yet packaged
    assert len(work.get(again["workpackage"])["items"]) == 2
    third = mailbox.fetch(REQ, actor="t", runner=FakeBridge(MAILS), inbox_root=mail_env["inbox"])
    assert third["workpackage"] is None  # what is already in a package is not packaged again


def test_pull_job_records_unexpected_errors_instead_of_raising(mail_env, monkeypatch):
    p = mailbox.request_pull(REQ, actor="t")
    monkeypatch.setattr(mailbox, "fetch", lambda *a, **k: (_ for _ in ()).throw(ValueError("hibás message.json")))
    out = mailbox.run_pull_job({"pull_id": p["id"]})
    assert out["status"] == "error" and "hibás message.json" in out["error"]
    assert mailbox.pull(p["id"])["status"] == "error"


def test_pull_row_exists_before_the_job_can_be_claimed(mail_env, monkeypatch):
    seen = {}
    real_enqueue = queue.enqueue

    def enqueue_and_peek(kind, **kw):
        job = real_enqueue(kind, **kw)
        seen["row"] = mailbox.pull(kw["payload"]["pull_id"])  # the worker could already claim it at this point
        return job

    monkeypatch.setattr(queue, "enqueue", enqueue_and_peek)
    mailbox.request_pull(REQ, actor="t")
    assert seen["row"]["status"] == "queued"


def _dir(p: str) -> Path:
    return Path(p).resolve()


# --- watched folder -------------------------------------------------------------------------------------------------


def test_failed_folder_scan_does_not_lose_files(db, monkeypatch):
    folder = db / "figyelt"
    folder.mkdir()
    for n in range(3):
        write_text_pdf(folder / f"szamla_{n}.pdf", [line.replace("MINTA-2026-001", f"MINTA-2026-10{n}") for line in INVOICE_LINES])
        old = (folder / f"szamla_{n}.pdf").stat().st_mtime - 3600
        os.utime(folder / f"szamla_{n}.pdf", (old, old))
    saved = app_settings.save_folders([app_settings.WatchedFolder(name="Figyelt", path=str(folder))], check_dir=_dir)
    fid = saved[0]["id"]
    real_hash = work.sha256_file

    def locked_second(p):
        if Path(p).name == "szamla_1.pdf":
            raise PermissionError("a fájlt egy másik folyamat zárolja")
        return real_hash(p)

    monkeypatch.setattr(work, "sha256_file", locked_second)
    first = app_settings.scan(fid)
    assert first["status"] == "ok" and first["new"] == 2 and first["unreadable"] == 1  # locked file skipped, others not
    monkeypatch.setattr(work, "sha256_file", real_hash)
    second = app_settings.scan(fid)
    assert second["new"] == 1  # the locked file is added on the next scan
    names = sorted(Path(i["source_path"]).name for i in work.get(second["workpackage"])["items"])
    assert names == ["szamla_0.pdf", "szamla_1.pdf", "szamla_2.pdf"]


def test_folder_scan_that_fails_to_add_keeps_files_for_the_next_scan(db, monkeypatch):
    folder = db / "figyelt"
    folder.mkdir()
    write_text_pdf(folder / "szamla_0.pdf", INVOICE_LINES)
    old = (folder / "szamla_0.pdf").stat().st_mtime - 3600
    os.utime(folder / "szamla_0.pdf", (old, old))
    fid = app_settings.save_folders([app_settings.WatchedFolder(name="Figyelt", path=str(folder))], check_dir=_dir)[0]["id"]
    real_add = work.add_documents
    monkeypatch.setattr(work, "add_documents", lambda *a, **k: (_ for _ in ()).throw(work.RevisionConflict("közben változott")))
    assert app_settings.scan(fid)["status"] == "error"  # does not raise: the error shows on the folder
    monkeypatch.setattr(work, "add_documents", real_add)
    assert app_settings.scan(fid)["new"] == 1


# --- operational basics: log, backup, unreadable file, schema extension ---------------------------------------------


def test_worker_log_is_a_persistent_rotating_file(tmp_path, monkeypatch):
    import logging

    from jav.runtime import applog

    monkeypatch.setattr(applog, "LOG_DIR", tmp_path / "logs")
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        path = applog.setup("proba")
        assert applog.setup("proba") == path and len(root.handlers) == len(before) + 1  # repeat call: no duplicate
        logging.getLogger("jav.worker").warning("próbasor")
        for h in root.handlers:
            h.flush()
        assert "WARNING jav.worker" in path.read_text(encoding="utf-8") and "próbasor" in path.read_text(encoding="utf-8")
    finally:
        for h in root.handlers[len(before):]:
            root.removeHandler(h)
            h.close()
    cfg = applog.uvicorn_config("api")
    assert "file" in cfg["loggers"]["uvicorn"]["handlers"] and cfg["root"]["handlers"] == ["file"]


def test_backup_is_a_verified_copy_and_keeps_the_latest(db):
    from jav import backup

    work.create_workpackage(name="Mentendő", source_kind="manual", source_ref=None)
    out = db / "mentesek"
    for n in range(3):
        (out / f"20260101-00000{n}").mkdir(parents=True)  # older backups
    (out / "kezi-mappa").mkdir()  # not one of our folders: not deleted
    m = backup.backup(out_root=out, keep=2)
    assert m["ok"] and m["files"][0]["integrity"] == "ok"
    import sqlite3
    with sqlite3.connect(Path(m["dir"]) / "s.sqlite") as c:
        assert c.execute("SELECT name FROM workpackages").fetchone()[0] == "Mentendő"
    assert sorted(m["removed"]) == ["20260101-000000", "20260101-000001"]
    assert (out / "kezi-mappa").is_dir() and (out / "20260101-000002").is_dir()


def test_unreadable_file_gives_a_clear_error_and_no_empty_package(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from jav import api

    folder = tmp_path / "gyoker" / "bejovo"
    folder.mkdir(parents=True)
    write_text_pdf(folder / "szamla_1.pdf", INVOICE_LINES)

    def locked(p):
        raise PermissionError(13, "a fájlt egy másik folyamat zárolja", str(p))

    from jav import source_instances

    monkeypatch.setattr(source_instances, "freeze", locked)  # a document is read once, when its copy is kept
    c = TestClient(api.create_app(store_path=tmp_path / "w.sqlite"), base_url="http://127.0.0.1:8930")
    r = c.post("/api/workpackages", headers={"X-Actor": "teszt.elek"}, json={"folder": str(folder), "name": "Zárolt"})
    assert r.status_code == 422 and r.json()["error"] == "unreadable" and "szamla_1.pdf" in r.json()["message"]
    with store.use_store(tmp_path / "w.sqlite"), store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM workpackages").fetchone()[0] == 0  # no empty package left behind


def test_concurrent_column_migration_is_tolerated(tmp_path):
    import sqlite3

    state = {"n": 0}

    def racing(conn):
        state["n"] += 1
        if state["n"] == 1:  # the other process has just added the same column
            raise sqlite3.OperationalError("duplicate column name: owner")

    store.register_migration("proba063", racing)
    try:
        with store.use_store(tmp_path / "x.sqlite"), store.connect() as c:
            assert c.execute("SELECT 1").fetchone()[0] == 1
        assert state["n"] == 2
    finally:
        store._EXTRA_MIGRATIONS.pop("proba063", None)
