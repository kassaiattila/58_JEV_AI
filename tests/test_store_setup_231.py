"""231 (D-d4): a migration that reads the store through a connection of its own does not set the store up again.

A store's migrations run when it is first connected to, and again whenever a module registers its tables later. One
migration loads process packs, and loading a pack may read the store (a price list): that connection set the same
store up again inside the set-up, without end. Both ways of connecting - a connection of its own and the shared
session - set a store up once while a migration reads it. Invented store; no paid call.
"""

from __future__ import annotations

from jav.core import store


def _reader(runs: list[int]):
    def migration(conn) -> None:
        runs.append(1)
        with store.connect() as c:  # reads the store as a pack's loading does
            assert c.execute("SELECT 1").fetchone()[0] == 1
    return migration


def test_a_migration_reading_the_store_sets_it_up_once(monkeypatch, tmp_path) -> None:
    runs: list[int] = []
    monkeypatch.setattr(store, "_EXTRA_MIGRATIONS", {**store._EXTRA_MIGRATIONS, "invented_reader": _reader(runs)})
    with store.use_store(tmp_path / "own.sqlite"):
        with store.connect() as c:
            assert c.execute("SELECT 1").fetchone()[0] == 1
        with store.connect():
            pass
    assert runs == [1]


def test_in_a_session_too(monkeypatch, tmp_path) -> None:
    runs: list[int] = []
    with store.use_store(tmp_path / "shared.sqlite"), store.session():
        with store.connect():
            pass
        # a module registers its migration after the store was set up: the next block sets it up again, once
        monkeypatch.setattr(store, "_EXTRA_MIGRATIONS", {**store._EXTRA_MIGRATIONS, "invented_reader": _reader(runs)})
        with store.connect() as c:
            assert c.execute("SELECT 1").fetchone()[0] == 1
        with store.connect():
            pass
    assert runs == [1]
