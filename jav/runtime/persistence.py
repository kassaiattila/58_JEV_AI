"""A Burr SQLite-állapotmentője biztonságos lezárással (062, Q-szál), és a tár ritkítása (064).

A Burr `SQLitePersister.__del__` a `cleanup()` után is újra lezárja a kapcsolatot. Ha a szemétgyűjtés egy másik szálon
fut (pl. a helyi szolgáltatás szálán), az SQLite ezt hibának jelzi, akkor is, ha a kapcsolat már zárva van. Minden
futtató ezt az osztályt használja (a feldolgozó `StatePersister`-e és a tanulási futtatók is).

064 (döntés 2026-09-29): a Burr minden lépés után teljes állapotot ment (egy iratnál a teljes szövegével), így a tár
folyamatonként ~0,7 MB-tal nő. Visszaolvasni viszont mindig csak a folyamat utolsó mentett állapotát kell (a Burr
`load` a legnagyobb sorszámú sort adja: folytatás, kétlépcsős recept). A `prune_to_last` ezért minden folyamatból csak
az utolsó sort tartja meg; a `vacuum` a felszabadult helyet visszaadja a lemeznek (csak leállított feldolgozóval)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from burr.core.persistence import SQLitePersister

TABLE = "burr_state"


BUSY_TIMEOUT_S = 30  # mint a fő adattáré (jav/store.py)


class ClosingSQLitePersister(SQLitePersister):
    """`cleanup()` után a `__del__` nem nyúl a kapcsolathoz; lezáratlan példánynál a Burr eredeti viselkedése marad.

    066 Á31: saját kapcsolat nélkül a tár a fő adattárhoz hasonlóan nyílik meg: párhuzamos olvasás (WAL) és 30 s várakozás
    zárolt adatbázisnál (a Burr alapja 5 s és naplófájl-mód; a feldolgozó mentése és a közben futó ritkítás ütközhetett).
    A mentés (`jav/backup.py`) az SQLite saját mentő eljárását használja, ez WAL módban is teljes másolatot ad."""

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
    """Minden folyamatból csak az utolsó mentett állapot marad. `app_id`: csak ez a folyamat és a lépcsői
    (`<app_id>-<folyamat>`); `skip_prefixes`: ezekkel kezdődő folyamatok érintetlenek (pl. a még futó futásoké).
    Egy utasításban fut, így a közben mentő feldolgozó új sorát nem érinti."""
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
    """A törölt sorok helyének visszaadása a lemeznek (a fájl újraírása). Kizárólagos hozzáférést kér: a feldolgozó
    ne fusson közben."""
    path = Path(path)
    before = path.stat().st_size
    with closing(sqlite3.connect(str(path), timeout=30)) as c:
        c.execute("VACUUM")
    return {"bytes_before": before, "bytes_after": path.stat().st_size}


def _like_prefix(prefix: str) -> str:
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


__all__ = ["ClosingSQLitePersister", "prune_to_last", "vacuum"]
