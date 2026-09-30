"""066 Á31: the state store (Burr) opens set up for concurrent reading and with a 30-second wait, like the main store.
With the defaults (5 s, rollback-journal mode) the worker's save and a concurrent thinning could fail with a
"database is locked" error."""

from __future__ import annotations

from jav.runtime.persistence import ClosingSQLitePersister


def test_state_store_uses_wal_and_a_long_busy_timeout(tmp_path):
    p = ClosingSQLitePersister(str(tmp_path / "burr_state.sqlite"))
    try:
        assert p.connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert p.connection.execute("PRAGMA busy_timeout").fetchone()[0] >= 30_000
    finally:
        p.cleanup()


def test_an_explicit_connection_is_left_as_given(tmp_path):
    import sqlite3

    conn = sqlite3.connect(str(tmp_path / "sajat.sqlite"), timeout=1)
    p = ClosingSQLitePersister(str(tmp_path / "sajat.sqlite"), connection=conn)
    try:
        assert p.connection is conn
        assert p.connection.execute("PRAGMA busy_timeout").fetchone()[0] == 1000
    finally:
        p.cleanup()
