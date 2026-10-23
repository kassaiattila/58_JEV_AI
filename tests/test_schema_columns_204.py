"""The store's shared column addition (204, plan R1e).

Plain-language summary: when a newer version of the program needs a new column in a table that an older store already
has, the column is added when the store is opened. Every module used to write this by hand; one shared helper now does
it. These tests check that a missing column is added with exactly the definition given, that opening the store again
changes nothing, that a column already there is left alone, and that two processes starting at once (the service and
the worker after an update) do not fail when the other one has just added the same column.

No AI call; temporary SQLite files only.
"""

from __future__ import annotations

import sqlite3

import pytest

from jav import corrections, store, work, workflows  # noqa: F401 - their tables and migrations
from jav.domains.finance import reconcile_ai  # noqa: F401 - their tables and migrations
from jav.domains.email import mailbox  # noqa: F401 - their tables and migrations
from jav.runtime import calls  # noqa: F401


def _db(tmp_path, ddl: str = "CREATE TABLE t (id INTEGER PRIMARY KEY)") -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "t.sqlite")
    conn.execute(ddl)
    conn.execute("INSERT INTO t(id) VALUES (1)")
    conn.commit()
    return conn


def _columns(conn: sqlite3.Connection, table: str = "t") -> list[tuple]:
    """name, declared type, not null, default - in the table's order."""
    return [(r[1], r[2], r[3], r[4]) for r in conn.execute(f"PRAGMA table_info({table})")]


def _sql(conn: sqlite3.Connection, table: str = "t") -> str:
    return conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]


def test_a_missing_column_is_added_with_its_definition(tmp_path):
    conn = _db(tmp_path)
    added = store.add_columns(conn, "t", {"parts": "TEXT NOT NULL DEFAULT '{}'",
                                          "revision": "INTEGER NOT NULL DEFAULT 1", "note": "TEXT"})
    assert added == ["parts", "revision", "note"]
    assert _columns(conn) == [("id", "INTEGER", 0, None), ("parts", "TEXT", 1, "'{}'"), ("revision", "INTEGER", 1, "1"),
                              ("note", "TEXT", 0, None)]
    # the definition is kept word for word, as a hand-written ALTER TABLE kept it
    assert _sql(conn).endswith("parts TEXT NOT NULL DEFAULT '{}', revision INTEGER NOT NULL DEFAULT 1, note TEXT)")
    assert conn.execute("SELECT parts, revision, note FROM t").fetchone() == ("{}", 1, None)  # a row from before


def test_a_second_run_changes_nothing(tmp_path):
    conn = _db(tmp_path)
    store.add_columns(conn, "t", {"owner": "TEXT", "plan": "TEXT"})
    before = (_sql(conn), conn.execute("PRAGMA schema_version").fetchone()[0])
    assert store.add_columns(conn, "t", {"owner": "TEXT", "plan": "TEXT"}) == []
    assert (_sql(conn), conn.execute("PRAGMA schema_version").fetchone()[0]) == before


def test_an_existing_column_is_left_alone(tmp_path):
    conn = _db(tmp_path, "CREATE TABLE t (id INTEGER PRIMARY KEY, note TEXT NOT NULL DEFAULT 'x')")
    assert store.add_columns(conn, "t", {"note": "INTEGER", "extra": "TEXT"}) == ["extra"]
    assert _columns(conn) == [("id", "INTEGER", 0, None), ("note", "TEXT", 1, "'x'"), ("extra", "TEXT", 0, None)]


def test_a_table_not_there_is_left_alone(tmp_path):
    conn = _db(tmp_path)
    assert store.add_columns(conn, "absent", {"owner": "TEXT"}) == []
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='absent'").fetchone() is None


class _Late:
    """A connection on which the other process adds `column` right after this one has read the table's columns: the
    service and the worker starting at the same time after an update (063)."""

    def __init__(self, conn: sqlite3.Connection, path, column: str) -> None:
        self._conn, self._path, self._column, self._done = conn, path, column, False

    def execute(self, sql: str, *args):
        cur = self._conn.execute(sql, *args)
        if sql.startswith("PRAGMA table_info") and not self._done:
            rows = cur.fetchall()
            other = sqlite3.connect(self._path)
            other.execute(f"ALTER TABLE t ADD COLUMN {self._column} TEXT")
            other.commit()
            other.close()
            self._done = True
            return rows
        return cur


def test_the_duplicate_column_race_is_tolerated(tmp_path):
    conn = _db(tmp_path)
    late = _Late(conn, tmp_path / "t.sqlite", "owner")
    # the other process added `owner` between the look and this ALTER: SQLite says "duplicate column name"
    assert store.add_columns(late, "t", {"owner": "TEXT", "plan": "TEXT"}) == ["plan"]
    assert [c[0] for c in _columns(conn)] == ["id", "owner", "plan"]


def test_any_other_error_is_raised(tmp_path):
    conn = _db(tmp_path)
    with pytest.raises(sqlite3.OperationalError, match="NOT NULL"):
        store.add_columns(conn, "t", {"owner": "TEXT NOT NULL"})  # a NOT NULL column needs a default


def test_only_plain_names_are_taken(tmp_path):
    conn = _db(tmp_path)
    with pytest.raises(ValueError):
        store.add_columns(conn, "t; DROP TABLE t", {"owner": "TEXT"})
    with pytest.raises(ValueError):
        store.add_columns(conn, "t", {"owner TEXT, other": "TEXT"})


def test_an_older_store_gets_every_module_column_back(tmp_path):
    """The modules' own migrations, now made of the helper, still bring an older store up to date on opening."""
    path = tmp_path / "s.sqlite"
    dropped = {"datapoints": "source_layer_id", "email_results": "folder", "run_item_corrections": "result_version",
               "mailbox_schedules": "changed_at", "reconcile_ai_proposals": "kind_question", "invocations": "holder",
               "runs": "scope", "workpackage_items": "instance", "workflow_steps": "engine",
               "workflows": "previous_id"}
    with store.use_store(path), store.connect() as c:
        for table, col in dropped.items():
            c.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
    store._initialized.pop(str(path), None)  # a new process: the structure check runs again
    with store.use_store(path), store.connect() as c:
        for table, col in dropped.items():
            assert col in {r[1] for r in c.execute(f"PRAGMA table_info({table})")}, (table, col)
