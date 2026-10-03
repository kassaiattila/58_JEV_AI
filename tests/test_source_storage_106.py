"""Synthetic source storage failures; no production files or provider calls."""

from __future__ import annotations

import errno
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from jav import api, source_instances, store, work
from jav.runtime import lock


@pytest.fixture()
def source(tmp_path):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"synthetic source bytes")
    with store.use_store(tmp_path / "store" / "jav.sqlite"):
        yield path


def test_insufficient_space_rejects_before_creating_a_copy(source, monkeypatch):
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(ValueError, match="Insufficient disk space"):
        source_instances.freeze(source)
    assert source_instances.files() == []
    assert not list(source_instances.root().glob(".incoming-*"))


def test_space_is_rechecked_while_copying(source, monkeypatch):
    monkeypatch.setattr(source_instances, "CHUNK", 4)
    checks = []

    def space(_):
        checks.append(1)
        return SimpleNamespace(free=10**12 if len(checks) == 1 else 0)

    monkeypatch.setattr(shutil, "disk_usage", space)
    with pytest.raises(ValueError, match="Insufficient disk space"):
        source_instances.freeze(source)
    assert len(checks) >= 2
    assert source_instances.files() == []
    assert not list(source_instances.root().glob(".incoming-*"))


@pytest.mark.parametrize("operation", ["mkstemp", "fsync", "replace"])
def test_disk_full_has_a_named_error_and_keeps_no_partial_copy(source, monkeypatch, operation):
    def full(*args, **kwargs):
        raise OSError(errno.ENOSPC, "synthetic disk full")

    owner = source_instances.tempfile if operation == "mkstemp" else source_instances.os
    monkeypatch.setattr(owner, operation, full)
    with pytest.raises(ValueError, match="Insufficient disk space"):
        source_instances.freeze(source)
    assert source_instances.files() == []
    assert not list(source_instances.root().glob(".incoming-*"))


def test_api_rejects_disk_full_without_recording_a_successful_item(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"synthetic source")
    db = tmp_path / "store" / "jav.sqlite"
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    client = TestClient(api.create_app(store_path=db), base_url="http://127.0.0.1:8930")
    response = client.post("/api/workpackages", headers={"X-Actor": "test"},
                           json={"paths": [str(path)], "name": "Synthetic storage failure"})
    assert response.status_code == 422, response.text
    assert response.json().get("error") == "invalid", response.text
    assert "Insufficient disk space" in response.json()["message"]
    with store.use_store(db), store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM workpackage_items").fetchone()[0] == 0
        assert source_instances.files() == []


def _partial(source, *, age=120):
    base = source_instances.root()
    base.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    path = base / f".incoming-{token}-synthetic.part"
    path.write_bytes(b"synthetic partial")
    lease = base / f".incoming-{token}.lock"
    lease.write_bytes(b"synthetic owner")
    old = time.time() - age
    os.utime(path, (old, old))
    candidate = next(c for c in source_instances.partial_copies() if c.name == path.name)
    return path, lease, candidate


@pytest.mark.parametrize("operation", ["write", "flush"])
def test_storage_failure_during_output_leaves_no_instance(source, monkeypatch, operation):
    original = os.fdopen

    class FailingOutput:
        def __init__(self, file):
            self.file = file

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.file.close()

        def write(self, data):
            if operation == "write":
                self.file.write(data[:2])
                raise OSError(errno.ENOSPC, "synthetic partial write")
            return self.file.write(data)

        def flush(self):
            raise OSError(errno.ENOSPC, "synthetic failed flush")

    monkeypatch.setattr(os, "fdopen", lambda *a, **kw: FailingOutput(original(*a, **kw)))
    with pytest.raises(source_instances.InstanceStorageFull):
        source_instances.freeze(source)
    assert source_instances.files() == []
    assert not list(source_instances.root().glob(".incoming-*"))


def test_batch_storage_failure_preserves_existing_references_and_revision(source, monkeypatch):
    wp = work.create_from_files([source], name="Existing synthetic reference")
    instance = source_instances.path_of(wp["items"][0]["instance"])
    before = instance.read_bytes()
    second = source.parent / "second.pdf"
    second.write_bytes(b"different synthetic source")
    real_freeze = source_instances.freeze

    def freeze(path, **kwargs):
        if path == second:
            raise source_instances.InstanceStorageFull("Insufficient disk space")
        return real_freeze(path, **kwargs)

    monkeypatch.setattr(source_instances, "freeze", freeze)
    with pytest.raises(source_instances.InstanceStorageFull):
        work.add_documents(wp["id"], [source, second], expected_revision=wp["revision"])
    current = work.get(wp["id"])
    assert current["revision"] == wp["revision"] and len(current["items"]) == 1
    assert instance.read_bytes() == before


@pytest.mark.parametrize("entry", ["part", "lease"])
def test_cleanup_refuses_a_candidate_replaced_by_a_directory(source, entry):
    path, lease, candidate = _partial(source)
    replaced = path if entry == "part" else lease
    replaced.unlink()
    replaced.mkdir()
    assert source_instances.cleanup_partials([candidate], dry_run=False, min_age_seconds=60) == {path.name: "not_regular"}
    assert path.exists()


def test_cleanup_defaults_to_listing_and_only_removes_the_selected_partial(source):
    path, lease, candidate = _partial(source)
    other, _, _ = _partial(source)
    digest, rel = source_instances.freeze(source)
    final = source_instances.path_of(rel)
    # Initialise the application's own schema, with no work package references.
    with store.connect():
        pass
    before = {p: p.read_bytes() for p in (path, lease, other, final)}
    assert source_instances.cleanup_partials([candidate], min_age_seconds=60) == {path.name: "eligible"}
    assert all(p.read_bytes() == data for p, data in before.items())
    assert source_instances.cleanup_partials([candidate], dry_run=False, min_age_seconds=60) == {path.name: "removed"}
    assert not path.exists() and not lease.exists()
    assert other.exists() and source_instances.intact(final, digest)


def test_cleanup_preserves_active_partial_even_when_its_timestamp_is_old(source):
    path, lease, candidate = _partial(source)
    with lock.single_instance(lease):
        assert source_instances.cleanup_partials([candidate], dry_run=False, min_age_seconds=60) == {path.name: "active"}
        assert path.exists()


def test_cleanup_preserves_referenced_and_removed_items(source):
    wp = work.create_from_files([source], name="Synthetic reference")
    path, _, candidate = _partial(source)
    with store.connect() as conn:
        conn.execute("UPDATE workpackage_items SET instance=?, removed_revision=2 WHERE workpackage_id=?",
                     (path.name, wp["id"]))
    assert source_instances.cleanup_partials([candidate], dry_run=False, min_age_seconds=60) == {path.name: "referenced"}
    assert path.exists()


@pytest.mark.parametrize("change, expected", [("fresh", "recent"), ("bytes", "changed"),
                                              ("missing_lease", "missing_file_or_lease"),
                                              ("outside", "unowned_or_outside_store"),
                                              ("traversal", "unowned_or_outside_store")])
def test_cleanup_rechecks_candidate_before_removal(source, change, expected):
    path, lease, candidate = _partial(source, age=0 if change == "fresh" else 120)
    if change == "bytes":
        path.write_bytes(b"different synthetic bytes")
    elif change == "missing_lease":
        lease.unlink()
    elif change == "outside":
        candidate = replace(candidate, source_root=str(source.parent))
    elif change == "traversal":
        candidate = replace(candidate, name="../" + candidate.name)
    assert source_instances.cleanup_partials([candidate], dry_run=False, min_age_seconds=60) == {candidate.name: expected}
    assert path.exists()


def test_cleanup_does_not_remove_legacy_unowned_partials(source):
    base = source_instances.root()
    base.mkdir(parents=True)
    path = base / ".incoming-legacy.part"
    path.write_bytes(b"synthetic old partial")
    candidates = source_instances.partial_copies()
    assert source_instances.cleanup_partials(candidates, dry_run=False, min_age_seconds=60) == {
        path.name: "unowned_or_outside_store"}
    assert path.exists()


def test_cleanup_after_a_real_process_exit_preserves_final_sources(source):
    _, rel = source_instances.freeze(source)
    final = source_instances.path_of(rel)
    data = final.read_bytes()
    script = """import os, sys
from pathlib import Path
from jav import source_instances, store
with store.use_store(Path(sys.argv[1])):
    source_instances.os.fsync = lambda fd: os._exit(17)
    source_instances.freeze(Path(sys.argv[2]))
"""
    result = subprocess.run([sys.executable, "-c", script, str(store.current_path()), str(source)],
                            timeout=30, capture_output=True, check=False)
    assert result.returncode == 17, result.stderr.decode(errors="replace")
    candidates = source_instances.partial_copies()
    assert len(candidates) == 1
    path = source_instances.root() / candidates[0].name
    old = time.time() - 120
    os.utime(path, (old, old))
    with store.connect():
        pass
    candidates = source_instances.partial_copies()
    assert source_instances.cleanup_partials(candidates, dry_run=False, min_age_seconds=60) == {path.name: "removed"}
    assert final.read_bytes() == data
