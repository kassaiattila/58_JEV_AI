"""061: az adattár szerkezet-ellenőrzése (séma + migrációk) kapcsolódásonként csak akkor fut, ha szükséges.

Előtte minden kapcsolódás lefuttatta a teljes sémát és a migrációkat; a munkacsomag-lista egy lekérése 380 kapcsolódással
~3 s volt. Most a séma-verzió (SQLite `schema_version`) és a regisztrált modul-sémák alapján dől el, kell-e újra futnia.
"""

from __future__ import annotations

import sqlite3

from jav import store


def _count_inits(monkeypatch) -> list[int]:
    calls: list[int] = []
    orig = store._initialize

    def spy(conn):
        calls.append(1)
        return orig(conn)

    monkeypatch.setattr(store, "_initialize", spy)
    return calls


def test_second_connect_skips_schema_work(tmp_path, monkeypatch):
    calls = _count_inits(monkeypatch)
    with store.use_store(tmp_path / "a.sqlite"):
        for _ in range(3):
            with store.connect() as c:
                c.execute("SELECT 1")
    assert len(calls) == 1


def test_external_schema_change_reinitializes(tmp_path, monkeypatch):
    db = tmp_path / "b.sqlite"
    with store.use_store(db):
        with store.connect():
            pass
    with sqlite3.connect(db) as c:
        c.execute("DROP TABLE review_reasons")
    calls = _count_inits(monkeypatch)
    with store.use_store(db):
        with store.connect() as c:
            assert c.execute("SELECT COUNT(*) FROM review_reasons").fetchone()[0] == 0
    assert len(calls) == 1


def test_new_registered_schema_reinitializes(tmp_path, monkeypatch):
    db = tmp_path / "c.sqlite"
    with store.use_store(db):
        with store.connect():
            pass
    monkeypatch.setitem(store._EXTRA_SCHEMAS, "test_061", "CREATE TABLE IF NOT EXISTS t061 (x INTEGER);")
    with store.use_store(db):
        with store.connect() as c:
            c.execute("INSERT INTO t061 VALUES (1)")


def test_session_reuses_one_connection_and_keeps_write_semantics(tmp_path):
    db = tmp_path / "s.sqlite"
    with store.use_store(db):
        with store.session():
            with store.connect() as a, store.connect() as b:
                assert a is b
            with store.connect() as c:
                c.execute("INSERT INTO meta(key, value) VALUES ('k1', 'v1')")
            try:
                with store.connect() as c:
                    c.execute("INSERT INTO meta(key, value) VALUES ('k2', 'v2')")
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
            # a véglegesített írás egy független kapcsolatból is látszik, a hibás blokké nem
            with sqlite3.connect(db) as other:
                keys = {r[0] for r in other.execute("SELECT key FROM meta")}
            assert "k1" in keys and "k2" not in keys
        with store.connect() as c:  # a blokk után ismét önálló kapcsolat
            assert c.execute("SELECT value FROM meta WHERE key='k1'").fetchone()[0] == "v1"


def test_session_does_not_leak_to_other_store(tmp_path):
    with store.use_store(tmp_path / "x.sqlite"):
        with store.session():
            with store.connect() as x:
                pass
            with store.use_store(tmp_path / "y.sqlite"):
                with store.connect() as y:
                    assert y is not x


def test_recreated_file_is_initialized(tmp_path):
    db = tmp_path / "d.sqlite"
    with store.use_store(db):
        with store.connect():
            pass
    for suffix in ("", "-wal", "-shm"):
        p = db.with_name(db.name + suffix)
        if p.exists():
            p.unlink()
    with store.use_store(db):
        with store.connect() as c:
            assert c.execute("SELECT COUNT(*) FROM review_queue").fetchone()[0] == 0
