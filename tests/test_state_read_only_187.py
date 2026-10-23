"""187 (backlog: the live-store check): the state snapshot and the backup leave the real store as it is.

The start-up check writes the state snapshot from the real store with the code of the checked-out branch, while the
service may still run the released code. Before this, opening the store ran the branch's schema and migrations, so a
branch's data migration (186: the shared package scopes) already ran on the real store at the first check. A store
whose structure is older than the code (here: a registered migration that has not run on it) must come out of the
snapshot and the backup unchanged, and a store that does not exist yet must not be created.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from jav.devtools import admin
from jav.runtime import backup
from jav.core import store


def _older_store(path: Path) -> None:
    with store.use_store(path):
        store.review_enqueue(subject_kind="document", subject_id="d" * 64, run_id="cli-x", reasons=["needs:look"])


def _structure(path: Path) -> tuple[bytes, list[tuple], int]:
    with sqlite3.connect(str(path)) as c:
        tables = c.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall()
        version = c.execute("PRAGMA schema_version").fetchone()[0]
    return hashlib.sha256(path.read_bytes()).digest(), tables, version


@pytest.fixture()
def pending(monkeypatch):
    """Registers a migration of the checked-out code after the store was made, so it has not run on it; the returned
    list records every run."""
    ran: list[str] = []

    def migrate(conn: sqlite3.Connection) -> None:
        ran.append("probe")
        conn.execute("CREATE TABLE IF NOT EXISTS probe_187 (k TEXT)")
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('probe_187', 'copied')")

    def register() -> list[str]:
        monkeypatch.setitem(store._EXTRA_MIGRATIONS, "probe_187", migrate)
        return ran

    return register


def test_the_state_snapshot_leaves_an_older_store_as_it_is(tmp_path, pending) -> None:
    path = tmp_path / "jav.sqlite"
    _older_store(path)
    ran = pending()
    before = _structure(path)
    with store.use_store(path):
        out = admin.write_state(tmp_path / "STATE.md")
    assert ran == []
    assert _structure(path) == before
    text = out.read_text(encoding="utf-8")
    assert "**1**" in text and "without a run 1" in text  # the open review queue, read from the store


def test_the_state_snapshot_of_a_missing_store_creates_none(tmp_path, pending) -> None:
    path = tmp_path / "none" / "jav.sqlite"
    ran = pending()
    with store.use_store(path):
        out = admin.write_state(tmp_path / "STATE.md")
    assert not path.parent.exists()
    text = out.read_text(encoding="utf-8")
    assert text.count("no store yet") == 2  # the store's block and the open review queue's
    assert ran == []


def test_a_backup_leaves_an_older_store_as_it_is(tmp_path, pending) -> None:
    path = tmp_path / "jav.sqlite"
    _older_store(path)
    ran = pending()
    before = _structure(path)
    with store.use_store(path):
        manifest = backup.backup(out_root=tmp_path / "backups", keep=3)
    assert manifest["ok"] and ran == []
    assert _structure(path) == before


def test_a_read_only_store_refuses_writes_and_only_inside_the_block(tmp_path) -> None:
    path = tmp_path / "jav.sqlite"
    _older_store(path)
    with store.use_store(path):
        with store.read_only(), store.connect() as c:
            assert c.execute("SELECT COUNT(*) FROM review_queue").fetchone()[0] == 1
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                c.execute("INSERT INTO meta(key, value) VALUES ('x', 'y')")
        with store.connect() as c:
            c.execute("INSERT INTO meta(key, value) VALUES ('x', 'y')")


def test_a_read_only_look_at_a_missing_store_names_it(tmp_path) -> None:
    path = tmp_path / "none.sqlite"
    with store.use_store(path), store.read_only(), pytest.raises(store.StoreMissing):
        with store.connect():
            pass
    assert not path.exists()
