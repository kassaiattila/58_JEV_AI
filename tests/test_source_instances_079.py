"""Source instances: when a document is added to a work package, the system keeps an unchanging copy of it under its
content fingerprint, and processing, viewing, the item view and the named copies read that copy. A later change to the
original file is reported, not an error; an item added before source instances existed follows the earlier rule.

Synthetic PDFs, a fake JEV client, no paid calls.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jav import api, backup, corrections, flow_detect, ocr, source_instances, store, work
from jav.adapters import jev as jev_mod
from jav.runtime import worker
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_runtime_worker import FakeClient


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture()
def env(tmp_path: Path):
    client = FakeClient()
    adapter = jev_mod.JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")
    folder = tmp_path / "bejovo"
    folder.mkdir()
    write_text_pdf(folder / "szamla_1.pdf", INVOICE_LINES)
    write_text_pdf(folder / "szamla_2.pdf", [line.replace("MINTA-2026-001", "MINTA-2026-002") for line in INVOICE_LINES])
    db = tmp_path / "w.sqlite"
    with store.use_store(db), jev_mod.use_adapter(adapter):
        wp = work.create_from_folder(folder, name="Synthetic invoices")
        work.assign_recipe(wp["id"], "invoice-extraction", params={"arm": "S", "doc_type": "invoice_hu"}, expected_revision=0, actor="t")
        yield {"wp": work.get(wp["id"]), "client": client, "tmp": tmp_path, "folder": folder, "db": db}


def _start(wp_id: str) -> str:
    r = work.readiness(wp_id)
    return work.start_run(wp_id, mode="shadow", expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")["run_id"]


def _swap_in_place(path: Path) -> bytes:
    """Same length, restored timestamps (the size + modification time memo cannot notice it); returns the old bytes."""
    before, st = path.read_bytes(), path.stat()
    changed = before.replace(b"MINTA", b"ALTER")
    assert changed != before and len(changed) == len(before)
    path.write_bytes(changed)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    return before


def _instance_files(tmp: Path) -> list[Path]:
    return sorted(p for p in (tmp / "sources").rglob("*") if p.is_file())


def _drop_instances(wp_id: str) -> None:
    """An item added before source instances existed: no instance recorded."""
    with store.connect() as c:
        c.execute("UPDATE workpackage_items SET instance=NULL WHERE workpackage_id=?", (wp_id,))


# --- intake ------------------------------------------------------------------------------------------------------


def test_adding_a_document_keeps_a_byte_identical_instance_next_to_the_store(env):
    for item in env["wp"]["items"]:
        original = Path(item["source_path"]).read_bytes()
        instance = work.source_file(item)
        assert item["instance"] and instance != Path(item["source_path"])
        assert instance.is_relative_to(env["tmp"] / "sources")
        assert instance.read_bytes() == original and item["sha256"] == _sha(original)
        assert instance.name == f"{item['sha256']}.pdf"


def test_the_same_content_in_two_packages_is_kept_once(env):
    work.create_from_files([env["folder"] / "szamla_1.pdf"], name="Second package")
    assert len(_instance_files(env["tmp"])) == 2


def test_the_fingerprint_is_taken_from_the_copied_bytes(env, monkeypatch):
    """The item's fingerprint comes from the bytes that were copied, so the instance and the recorded fingerprint
    always agree (before, the file was hashed first and could change before it was recorded)."""
    extra = env["tmp"] / "extra.pdf"
    write_text_pdf(extra, INVOICE_LINES[:3])
    calls_ = []
    monkeypatch.setattr(work, "sha256_file", lambda p: calls_.append(p) or "0" * 64)  # a separate hashing pass is not used
    wp = work.add_document(env["wp"]["id"], extra, expected_revision=env["wp"]["revision"])
    item = next(i for i in wp["items"] if Path(i["source_path"]).name == "extra.pdf")
    assert item["sha256"] == _sha(extra.read_bytes()) and not calls_


def test_a_failed_intake_leaves_no_orphan_instance(env):
    with pytest.raises(FileNotFoundError):
        work.create_from_files([env["tmp"] / "new.pdf"], name="Broken")  # nothing to copy
    good = env["tmp"] / "good.pdf"
    write_text_pdf(good, INVOICE_LINES[:2])
    with pytest.raises(FileNotFoundError):
        work.create_from_files([good, env["tmp"] / "missing.pdf"], name="Half broken")
    assert len(_instance_files(env["tmp"])) == 2  # only the two of the first package
    assert all(w["name"] != "Half broken" for w in work.list_workpackages(include_archived=True))


def test_deleting_a_package_without_runs_releases_only_its_unshared_instances(env):
    other = env["tmp"] / "other.pdf"
    write_text_pdf(other, INVOICE_LINES[:4])
    wp = work.create_from_files([env["folder"] / "szamla_1.pdf", other], name="To delete")
    assert len(_instance_files(env["tmp"])) == 3
    work.delete_workpackage(wp["id"], actor="t")
    names = [p.name for p in _instance_files(env["tmp"])]
    assert len(names) == 2 and f"{_sha(other.read_bytes())}.pdf" not in names


def test_an_email_item_gets_no_instance(env):
    msg = env["tmp"] / "inbox" / "box" / "m1" / "message.json"
    msg.parent.mkdir(parents=True)
    msg.write_text(json.dumps({"subject": "x"}), encoding="utf-8")
    wp = work.create_workpackage(name="Mail", source_kind="manual", source_ref=None)
    item = work.add_items(wp["id"], [msg], kind="email", expected_revision=0)["items"][0]
    assert item["instance"] is None and work.source_file(item) == msg.resolve()


# --- processing ----------------------------------------------------------------------------------------------------


def test_the_worker_processes_the_instance_when_the_original_changes_or_disappears(env):
    run_id = _start(env["wp"]["id"])
    first, second = (Path(i["source_path"]) for i in env["wp"]["items"])
    _swap_in_place(first)
    second.unlink()
    info = worker.run_worker(once=True)
    assert info["results"] == {"done": 2}
    with store.connect() as c:
        rows = {r["doc_id"]: r["source_path"] for r in c.execute("SELECT doc_id, source_path FROM documents")}
    assert rows == {i["item_id"]: i["source_path"] for i in env["wp"]["items"]}  # the original path is what is stored
    assert work.get_run(run_id)["status"] in ("done", "needs_review")


def test_the_model_request_is_the_same_as_from_the_original_path(env):
    """The file name is part of the type-recognition request (and so of its cache key): reading from the instance must
    not change it. The second run reads the instance with the original gone and makes no new model call."""
    item = env["wp"]["items"][0]
    original = item["source_path"]
    app = flow_detect.build_app(original, run_id="detect-original")
    app.run(halt_after=flow_detect.TERMINALS)
    calls_before = env["client"].calls
    assert calls_before > 0
    Path(original).unlink()
    app = flow_detect.build_app(original, read_path=str(work.source_file(item)), run_id="detect-instance")
    _, _, state = app.run(halt_after=flow_detect.TERMINALS)
    assert env["client"].calls == calls_before  # every request found in the cache: byte-identical requests
    assert state["doc_id"] == item["sha256"] and state["source_path"] == original


def test_an_item_without_instance_follows_the_old_rule(env):
    _drop_instances(env["wp"]["id"])
    run_id = _start(env["wp"]["id"])
    Path(env["wp"]["items"][0]["source_path"]).write_bytes(b"%PDF changed")
    info = worker.run_worker(once=True)
    assert info["results"] == {"dead": 1, "done": 1}
    failed = [i for i in work.get_run(run_id)["items"] if i["status"] == "failed"]
    assert len(failed) == 1 and failed[0]["error"].startswith("source_changed")


def test_a_damaged_instance_is_refused(env):
    run_id = _start(env["wp"]["id"])
    work.source_file(env["wp"]["items"][0]).write_bytes(b"%PDF damaged")
    info = worker.run_worker(once=True)
    assert info["results"] == {"dead": 1, "done": 1}
    failed = [i for i in work.get_run(run_id)["items"] if i["status"] == "failed"]
    assert len(failed) == 1 and failed[0]["error"].startswith("instance_damaged")


# --- readiness ----------------------------------------------------------------------------------------------------


def test_a_changed_or_missing_original_is_a_warning_not_a_blocker(env):
    first, second = (Path(i["source_path"]) for i in env["wp"]["items"])
    first.write_bytes(b"%PDF-1.4 changed, other size")
    second.unlink()
    r = work.readiness(env["wp"]["id"])
    assert r["ready"] and not r["blockers"]
    assert {w["code"] for w in r["warnings"]} >= {"original_changed", "original_missing"}


def test_a_damaged_or_missing_instance_blocks_the_start(env):
    first, second = env["wp"]["items"]
    work.source_file(first).write_bytes(b"%PDF-1.4 damaged, other size")
    work.source_file(second).unlink()
    r = work.readiness(env["wp"]["id"])
    assert not r["ready"] and [b["code"] for b in r["blockers"]] == ["instance_damaged", "instance_damaged"]


def test_readiness_without_instances_is_unchanged(env):
    _drop_instances(env["wp"]["id"])
    first, second = (Path(i["source_path"]) for i in env["wp"]["items"])
    first.write_bytes(b"%PDF changed")
    second.unlink()
    assert {b["code"] for b in work.readiness(env["wp"]["id"])["blockers"]} == {"source_changed", "source_missing"}


# --- viewing, the item view and the named copies --------------------------------------------------------------------


def test_the_source_and_its_pages_are_served_from_the_instance_after_the_original_is_swapped(env):
    item = env["wp"]["items"][0]
    before = _swap_in_place(Path(item["source_path"]))
    client = TestClient(api.create_app(store_path=env["db"]), base_url="http://127.0.0.1:8930")
    base = f"/api/workpackages/{env['wp']['id']}/items/{item['item_id']}"
    source = client.get(f"{base}/source")
    assert source.status_code == 200 and source.content == before
    assert source.headers["content-type"] == "application/pdf"
    page = client.get(f"{base}/pages/1.png")
    assert page.status_code == 200 and page.content.startswith(b"\x89PNG")


def test_the_item_view_tells_whether_the_original_changed(env):
    run_id = _start(env["wp"]["id"])
    worker.run_worker(once=True)
    first, second = env["wp"]["items"]
    assert corrections.item_result(run_id, first["item_id"])["source_file"] == {"copy": True, "original": "same"}
    _swap_in_place(Path(first["source_path"]))
    Path(second["source_path"]).unlink()
    view = corrections.item_result(run_id, first["item_id"])
    assert view["source_file"] == {"copy": True, "original": "changed"} and view["page_count"] == 1
    assert corrections.item_result(run_id, second["item_id"])["source_file"] == {"copy": True, "original": "missing"}


def test_the_named_copies_come_from_the_instance(env):
    run_id = _start(env["wp"]["id"])
    worker.run_worker(once=True)
    item = env["wp"]["items"][1]
    before = _swap_in_place(Path(item["source_path"]))
    client = TestClient(api.create_app(store_path=env["db"]), base_url="http://127.0.0.1:8930")
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/runs/{run_id}/named-copies.zip").content))
    pdfs = [z.read(n) for n in z.namelist() if n.endswith(".pdf")]
    assert len(pdfs) == 2 and before in pdfs


# --- Azure recognition keeps working where it worked before ---------------------------------------------------------


def test_azure_gets_the_unchanged_original_under_the_sidecar_folder(env, monkeypatch):
    data_root = env["tmp"] / "legacy_data"
    (data_root / "inbox").mkdir(parents=True)
    original = data_root / "inbox" / "scan.pdf"
    write_text_pdf(original, INVOICE_LINES[:2])
    digest, rel = source_instances.freeze(original)
    instance = source_instances.path_of(rel)
    monkeypatch.setitem(ocr._CFG["azure_di"], "data_root", str(data_root))
    sent = []

    def fake_urlopen(req, timeout):
        sent.append(json.loads(req.data)["path"])
        raise OSError("no sidecar in tests")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with ocr.azure_alias(str(original), digest), pytest.raises(ocr.OcrUnavailableError):
        ocr.azure_words(instance)
    assert sent == [f"{ocr._CFG['azure_di']['container_root']}/inbox/scan.pdf"]
    original.write_bytes(b"%PDF changed since it was added")
    with ocr.azure_alias(str(original), digest), pytest.raises(ocr.OcrUnavailableError, match="sidecar"):
        ocr.azure_words(instance)  # a changed original is never sent: refused as before, with no call
    assert len(sent) == 1


# --- backup -----------------------------------------------------------------------------------------------------------


def test_the_backup_keeps_every_instance_once_here_and_in_the_second_location(env):
    out, nas = env["tmp"] / "backups", env["tmp"] / "nas"
    first = backup.backup(out_root=out, keep=1, copy_to=nas)
    entry = next(f for f in first["files"] if f["file"] == "sources")
    assert first["ok"] and entry["integrity"] == "ok" and entry["added"] == 2 and entry["entries"] == 2
    assert first["copy"]["ok"] and first["copy"]["sources"]["added"] == 2
    for where in (out, nas):
        kept = sorted(p.name for p in (where / "sources").rglob("*.pdf"))
        assert kept == sorted(f"{i['sha256']}.pdf" for i in env["wp"]["items"])
    second = backup.backup(out_root=out, keep=1, copy_to=nas)  # prunes the first backup folder
    assert next(f for f in second["files"] if f["file"] == "sources")["added"] == 0
    assert second["removed"] and len(list((out / "sources").rglob("*.pdf"))) == 2  # pruning never touches it
    assert second["copy"]["sources"]["added"] == 0 and len(list((nas / "sources").rglob("*.pdf"))) == 2


def test_a_damaged_instance_is_not_backed_up_and_is_named(env):
    item = env["wp"]["items"][0]
    work.source_file(item).write_bytes(b"%PDF damaged")
    result = backup.backup(out_root=env["tmp"] / "backups", keep=1)
    entry = next(f for f in result["files"] if f["file"] == "sources")
    assert entry["added"] == 1 and entry["damaged"] == [f"{item['sha256']}.pdf"]
    assert result["ok"]  # the store backup itself is valid; the damaged copy is named, not hidden
