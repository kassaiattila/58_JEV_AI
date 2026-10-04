"""Snapshot-bound native artifacts survive backup, copy and isolated restoration."""
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from jav import backup, corrections, native_results, source_instances, store
from tests.test_native_review_api_109 import published_run


def test_native_backup_restores_source_view_and_correction(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    with store.use_store(live / "native.sqlite"):
        rid, item, publication, _cite = published_run(live)
        fact = native_results.machine_facts(publication)[0]
        corrections.save_native(rid, item["item_id"], values={fact.fact_id: "00456"}, native_sources={},
            expected_revision=0, expected_result_version=publication.result_version, actor="reviewer")
        before = corrections.item_result(rid, item["item_id"])
        report = backup.backup(out_root=tmp_path / "backups", copy_to=tmp_path / "second", keep=2)
        assert report["ok"], report
        saved = next((tmp_path / "backups").glob("*/manifest.json")).parent
        manifest = json.loads((saved / "manifest.json").read_text(encoding="utf-8"))
        native = next(entry for entry in manifest["files"] if entry["file"] == backup.NATIVE_ARCHIVE)
        assert native["integrity"] == "ok" and native["entries"] > 0
        with zipfile.ZipFile(saved / backup.NATIVE_ARCHIVE) as archive:
            assert set(archive.namelist()) == {ref["relative_path"] for ref in native["artifacts"]}
            restored = tmp_path / "restored"
            restored.mkdir()
            archive.extractall(restored)
        shutil.copy2(saved / "native.sqlite", restored / "native.sqlite")
        shutil.copytree(tmp_path / "backups" / "sources", restored / "sources")
    with store.use_store(restored / "native.sqlite"):
        after = corrections.item_result(rid, item["item_id"])
        assert after == before
        assert native_results.source_elements(native_results.get_publication(rid, item["item_id"])).total > 0


def test_source_release_preserves_frozen_run_reference(tmp_path):
    with store.use_store(tmp_path / "run.sqlite"):
        _rid, item, _publication, _cite = published_run(tmp_path)
        with store.connect() as c:
            c.execute("DELETE FROM workpackage_items")
        assert source_instances.release([item["instance"]]) == []
        assert source_instances.path_of(item["instance"]).is_file()


def test_tampered_native_artifact_blocks_approval_and_cached_result(tmp_path):
    from jav import datasets, work
    from jav.tablequery import Query

    with store.use_store(tmp_path / "damaged.sqlite"):
        rid, item, publication, _cite = published_run(tmp_path)
        datasets.query("native_facts", {"run_id": rid}, Query())
        version = corrections.review_version(rid)
        with store.connect() as c:
            refs = native_results.referenced_artifacts(c)
        artifact = tmp_path / refs[0].relative_path
        artifact.write_bytes(b"damaged synthetic evidence")
        report = backup.backup(out_root=tmp_path / "damaged-backups", keep=1)
        assert not report["ok"] and report["store_ok"] and report["removed"] == []
        assert (Path(report["dir"]) / "damaged.sqlite").is_file()
        with pytest.raises(ValueError):
            work.approve_run(rid, actor="reviewer", review_version=version)
        assert work.get_run(rid)["approval"] is None
        with pytest.raises(ValueError):
            datasets.query("native_facts", {"run_id": rid}, Query())
