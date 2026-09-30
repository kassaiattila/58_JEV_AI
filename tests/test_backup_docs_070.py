"""070 D-mentés (döntés 2026-09-30): a belső munkaanyag verziókövetés nélkül helyben él, ezért a napi mentés viszi.

A belső dokumentumok egy tömörített fájlba kerülnek a mentés mappájában (`internal-docs.zip`, projektgyökérhez
viszonyított nevekkel); a fájl ellenőrzött, és a második helyre (NAS) készült másolat tartalomhash-e is lefedi.
"""

import zipfile
from pathlib import Path

import pytest

from jav import backup, store, work


@pytest.fixture()
def db(tmp_path: Path):
    with store.use_store(tmp_path / "s.sqlite"):
        work.create_workpackage(name="Mentendő", source_kind="manual", source_ref=None)
        yield tmp_path


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "projekt"
    for rel in ("docs/handoffs/069-2026-09-29-handoff.md", "docs/plans/070/PLAN.md", "docs/DECISIONS.md",
                "docs/ARCHITECTURE.md", "docs/guides/SETUP.md", "README.md"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(f"mesterséges tartalom: {rel}", encoding="utf-8")
    return root


def _docs_entry(manifest: dict) -> dict:
    return next(f for f in manifest["files"] if f["file"] == backup.DOCS_ARCHIVE)


def test_backup_carries_only_the_internal_docs_and_the_copy_verifies_them(db, project):
    local, nas = db / "helyi", db / "nas"
    m = backup.backup(out_root=local, keep=2, copy_to=nas, with_docs=True, docs_root=project)
    assert m["ok"] and m["copy"]["ok"] and m["copy"]["verified"]
    entry = _docs_entry(m)
    assert entry["entries"] == 3 and entry["integrity"] == "ok" and entry["bytes"] > 0
    with zipfile.ZipFile(Path(m["dir"]) / backup.DOCS_ARCHIVE) as z:
        assert sorted(z.namelist()) == ["docs/DECISIONS.md", "docs/handoffs/069-2026-09-29-handoff.md", "docs/plans/070/PLAN.md"]
        assert z.read("docs/DECISIONS.md").decode("utf-8") == "mesterséges tartalom: docs/DECISIONS.md"
    copied = Path(m["copy"]["dir"]) / backup.DOCS_ARCHIVE
    assert copied.read_bytes() == (Path(m["dir"]) / backup.DOCS_ARCHIVE).read_bytes()


def test_without_the_setting_no_docs_are_saved(db, project):
    m = backup.backup(out_root=db / "helyi", keep=2, docs_root=project)
    assert m["ok"] and [f["file"] for f in m["files"]] == ["s.sqlite"]
    assert not (Path(m["dir"]) / backup.DOCS_ARCHIVE).exists()


def test_no_internal_docs_on_a_fresh_clone_is_not_an_error(db, tmp_path):
    empty = tmp_path / "friss-klon"
    (empty / "docs" / "guides").mkdir(parents=True)
    m = backup.backup(out_root=db / "helyi", keep=2, with_docs=True, docs_root=empty)
    assert m["ok"] and [f["file"] for f in m["files"]] == ["s.sqlite"]


def test_a_broken_docs_archive_fails_the_backup_like_a_broken_store(db, project, monkeypatch):
    monkeypatch.setattr(backup, "_zip_integrity", lambda path: "bad member: docs/DECISIONS.md")
    m = backup.backup(out_root=db / "helyi", keep=2, copy_to=db / "nas", with_docs=True, docs_root=project)
    assert m["ok"] is False and _docs_entry(m)["integrity"] == "bad member: docs/DECISIONS.md"
    assert m["copy"]["ok"] is False and m["copy"].get("skipped")


def test_scheduled_backup_passes_the_docs_setting(db, monkeypatch):
    seen = {}
    monkeypatch.setattr(backup, "backup", lambda **kw: seen.update(kw) or {"ok": True, "copy": None, "files": [], "dir": "x"})
    backup.scheduled(config={"keep": 14, "copy_to": None, "with_burr": False, "with_docs": True})
    assert seen["with_docs"] is True
