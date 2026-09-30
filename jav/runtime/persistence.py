"""Burr's SQLite state persister with safe closing (062, Q-szál), and thinning of the store (064).

Burr's `SQLitePersister.__del__` closes the connection again even after `cleanup()`. If garbage collection runs on
another thread (e.g. the local service's thread), SQLite reports this as an error even when the connection is already
closed. Every runner uses this class (the worker's `StatePersister` and the learning runners too).

064 (decision of 2026-09-29): Burr saves the full state after every step (for a document, with its full text), so the
store grows by ~0.7 MB per process. Reading back, however, only ever needs the process's last saved state (Burr's
`load` returns the row with the highest sequence number: resume, two-stage recipe). So `prune_to_last` keeps only the
last row of every process; `vacuum` returns the freed space to the disk (only with the worker stopped)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from burr.core.persistence import SQLitePersister

TABLE = "burr_state"


BUSY_TIMEOUT_S = 30  # same as the main store's (jav/store.py)


class ClosingSQLitePersister(SQLitePersister):
    """After `cleanup()`, `__del__` does not touch the connection; an unclosed instance keeps Burr's original behaviour.

    066 Á31: without a connection of its own, the store opens like the main store: concurrent reads (WAL) and a 30 s
    wait on a locked database (Burr's default is 5 s and journal-file mode; the worker's save and a concurrent thinning
    could collide). The backup (`jav/backup.py`) uses SQLite's own backup routine, which gives a full copy in WAL mode
    too."""

    def __init__(self, db_path: str, table_name: str = "burr_state", serde_kwargs: dict | None = None,
                 connect_kwargs: dict | None = None, connection: sqlite3.Connection | None = None) -> None:
        own = connection is None
        if own:
            connection = sqlite3.connect(db_path, **{"timeout": BUSY_TIMEOUT_S, **(connect_kwargs or {})})
            connection.execute("PRAGMA journal_mode=WAL")
        super().__init__(db_path, table_name, serde_kwargs, connect_kwargs, connection=connection)

    def cleanup(self) -> None:
        super().cleanup()
        self._closed = True

    def __del__(self) -> None:
        if not getattr(self, "_closed", False):
            super().__del__()


def prune_to_last(path: Path, *, app_id: str | None = None, skip_prefixes: tuple[str, ...] = ()) -> dict[str, Any]:
    """Only the last saved state of every process is kept. `app_id`: only this process and its stages
    (`<app_id>-<process>`); `skip_prefixes`: processes starting with these are untouched (e.g. those of runs still
    going). It runs as one statement, so it does not touch a new row that the worker saves meanwhile."""
    path = Path(path)
    if not path.is_file():
        return {"deleted": 0}
    where, args = [], []
    if app_id is not None:
        where.append("(app_id = ? OR app_id LIKE ? ESCAPE '\\')")
        args += [app_id, _like_prefix(app_id + "-")]
    for prefix in skip_prefixes:
        where.append("app_id NOT LIKE ? ESCAPE '\\'")
        args.append(_like_prefix(prefix))
    sql = (f"DELETE FROM {TABLE} WHERE sequence_id < (SELECT MAX(s.sequence_id) FROM {TABLE} s"
           f" WHERE s.partition_key = {TABLE}.partition_key AND s.app_id = {TABLE}.app_id)")
    sql += "".join(f" AND {w}" for w in where)
    with closing(sqlite3.connect(str(path), timeout=30)) as c:
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone() is None:
            return {"deleted": 0}
        deleted = c.execute(sql, args).rowcount
        c.commit()
    return {"deleted": deleted}


def vacuum(path: Path) -> dict[str, Any]:
    """Returns the space of deleted rows to the disk (rewrites the file). Needs exclusive access: the worker must not
    run meanwhile."""
    path = Path(path)
    before = path.stat().st_size
    with closing(sqlite3.connect(str(path), timeout=30)) as c:
        c.execute("VACUUM")
    return {"bytes_before": before, "bytes_after": path.stat().st_size}


def _like_prefix(prefix: str) -> str:
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


__all__ = ["ClosingSQLitePersister", "prune_to_last", "vacuum"]
