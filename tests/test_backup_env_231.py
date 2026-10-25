"""231 (the owner's decision of 2026-10-25, after a deleted project folder): the backup carries the machine's local
settings too.

`.env` (the keys and the second backup location) and any other `.env.*` file at the project root go into one
compressed file in the backup folder (`local-env.zip`); the tracked template `.env.example` does not. The manifest
names the files, never a value; the file is verified, and the content hash of the copy in the second location covers
it. The daily backup takes them by default (`configs/service.json`). Invented values only.
"""

import json
import zipfile
from pathlib import Path

import pytest

from jav.app import work
from jav.core import cfg, store
from jav.runtime import backup

VALUE = "invented-value-for-the-test-0001"


@pytest.fixture()
def db(tmp_path: Path):
    with store.use_store(tmp_path / "s.sqlite"):
        work.create_workpackage(name="To back up", source_kind="manual", source_ref=None)
        yield tmp_path


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / ".env").write_text(f"TypeSafeJAV_API_KEY={VALUE}\nJAV_BACKUP_COPY_TO=D:\\nas\n", encoding="utf-8")
    (root / ".env.local").write_text("JAV_OCR_ENGINE=native\n", encoding="utf-8")
    (root / ".env.example").write_text("TypeSafeJAV_API_KEY=ts-...\n", encoding="utf-8")
    (root / ".envrc").write_text("not a settings file of ours\n", encoding="utf-8")
    return root


def _env_entry(manifest: dict) -> dict:
    return next(f for f in manifest["files"] if f["file"] == backup.ENV_ARCHIVE)


def test_the_local_settings_go_into_their_own_archive_and_the_copy_verifies_it(db, project):
    m = backup.backup(out_root=db / "local", keep=2, copy_to=db / "nas", with_env=True, env_root=project)
    assert m["ok"] and m["copy"]["ok"] and m["copy"]["verified"]
    entry = _env_entry(m)
    assert entry["entries"] == 2 and entry["integrity"] == "ok" and entry["bytes"] > 0
    with zipfile.ZipFile(Path(m["dir"]) / backup.ENV_ARCHIVE) as z:
        assert sorted(z.namelist()) == [".env", ".env.local"]
        assert z.read(".env") == (project / ".env").read_bytes()
    copied = Path(m["copy"]["dir"]) / backup.ENV_ARCHIVE
    assert copied.read_bytes() == (Path(m["dir"]) / backup.ENV_ARCHIVE).read_bytes()


def test_the_manifest_and_the_status_name_the_files_never_a_value(db, project):
    m = backup.backup(out_root=db / "local", keep=2, with_env=True, env_root=project)
    assert VALUE not in (Path(m["dir"]) / "manifest.json").read_text(encoding="utf-8")
    assert VALUE not in json.dumps(backup.status(db / "local"))
    assert ".env, .env.local" in _env_entry(m)["source"]


def test_without_the_setting_no_local_settings_are_saved(db, project):
    m = backup.backup(out_root=db / "local", keep=2, env_root=project)
    assert m["ok"] and backup.ENV_ARCHIVE not in [f["file"] for f in m["files"]]
    assert not (Path(m["dir"]) / backup.ENV_ARCHIVE).exists()


def test_no_local_settings_file_is_not_an_error(db, tmp_path):
    empty = tmp_path / "fresh-clone"
    empty.mkdir()
    (empty / ".env.example").write_text("OPENAI_API_KEY=sk-...\n", encoding="utf-8")
    m = backup.backup(out_root=db / "local", keep=2, with_env=True, env_root=empty)
    assert m["ok"] and [f["file"] for f in m["files"]] == ["s.sqlite"]


def test_a_broken_settings_archive_fails_the_backup(db, project, monkeypatch):
    monkeypatch.setattr(backup, "_zip_integrity", lambda path: "bad member: .env")
    m = backup.backup(out_root=db / "local", keep=2, copy_to=db / "nas", with_env=True, env_root=project)
    assert m["ok"] is False and _env_entry(m)["integrity"] == "bad member: .env"
    assert m["copy"]["ok"] is False and m["copy"].get("skipped")


def test_the_daily_backup_takes_the_local_settings(db, monkeypatch):
    seen = {}
    monkeypatch.setattr(backup, "backup", lambda **kw: seen.update(kw) or {"ok": True, "copy": None, "files": [], "dir": "x"})
    backup.scheduled(config={"keep": 14, "copy_to": None, "with_burr": False, "with_env": True})
    assert seen["with_env"] is True
    assert cfg.load("service")["backup"]["with_env"] is True  # on by default since service 1.10.0
