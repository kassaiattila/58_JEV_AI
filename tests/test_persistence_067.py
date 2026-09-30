"""066 Á31: a folyamatállapot-tár (Burr) párhuzamos olvasásra állítva és 30 másodperces várakozással nyílik meg, mint a
fő adattár. Alapbeállítással (5 s, naplófájl-mód) a feldolgozó mentése és a közben futó ritkítás „zárolt adatbázis”
hibát adhatott."""

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
