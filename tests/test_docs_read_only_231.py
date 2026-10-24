"""231 (backlog R-docs-live-store): the generated call-site pages leave the real store as it is.

The call-site pages read their run statistics from the ledger. Before this, they opened the store with an ordinary
connection, so the schema and the migrations of the checked-out branch ran on the real store while the service was
still running the released code (230, at the v1.41.0 release). Like the state snapshot (187), the pages now only read
the store: an older store comes out unchanged, and a store that does not exist yet is not created.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from jav.core import store
from jav.devtools import docsgen


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
        conn.execute("CREATE TABLE IF NOT EXISTS probe_231 (k TEXT)")

    def register() -> list[str]:
        monkeypatch.setitem(store._EXTRA_MIGRATIONS, "probe_231", migrate)
        return ran

    return register


def test_the_call_site_pages_leave_an_older_store_as_it_is(tmp_path, pending) -> None:
    path = tmp_path / "jav.sqlite"
    _older_store(path)
    ran = pending()
    before = _structure(path)
    with store.use_store(path):
        pages = docsgen.write_callsite_docs(tmp_path / "callsites")
    assert ran == []
    assert _structure(path) == before
    assert len(pages) == len(docsgen.all_callsites()) + 1  # every call site and the index


def test_the_call_site_pages_of_a_missing_store_create_none(tmp_path, pending) -> None:
    path = tmp_path / "none" / "jav.sqlite"
    ran = pending()
    with store.use_store(path):
        pages = docsgen.write_callsite_docs(tmp_path / "callsites")
    assert not path.parent.exists()
    assert ran == []
    assert len(pages) == len(docsgen.all_callsites()) + 1
