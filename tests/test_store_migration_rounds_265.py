"""265 (R4-a): a migration that loads a module registering its own table and migration does not break the store's set-up.

Timing the case page in a stand-alone script, the store's first open failed with "dictionary changed size during
iteration": a migration imported a module, which registered another migration while the registry was being run. Such
a module's schema is now made and its migration runs in the next round. Synthetic store; the registries are copies.
"""

from __future__ import annotations

import pytest

from jav.core import store


@pytest.fixture
def registries(monkeypatch):
    monkeypatch.setattr(store, "_EXTRA_SCHEMAS", dict(store._EXTRA_SCHEMAS))
    monkeypatch.setattr(store, "_EXTRA_MIGRATIONS", dict(store._EXTRA_MIGRATIONS))


def test_a_migration_may_register_another_module_s_table_and_migration(tmp_path, registries) -> None:
    ran: list[str] = []

    def late(conn) -> None:
        conn.execute("INSERT INTO late_things(name) VALUES ('made by the late migration')")
        ran.append("late")

    def loading(conn) -> None:  # as a migration that imports a module: the module registers its table and migration
        store.register_schema("late_things_265", "CREATE TABLE IF NOT EXISTS late_things (name TEXT);")
        store.register_migration("late_things_265", late)
        ran.append("loading")

    store.register_migration("loading_265", loading)
    with store.use_store(tmp_path / "m.sqlite"), store.connect() as c:
        rows = [r["name"] for r in c.execute("SELECT name FROM late_things")]
    assert ran == ["loading", "late"] and rows == ["made by the late migration"]
