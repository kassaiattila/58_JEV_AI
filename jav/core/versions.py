"""224 (plan G-process-core P3c): the versions of something a person edits - a draft, the active one, superseded and
retired ones.

Plain-language summary: a price list (191) and an own output template (178) are each kept as numbered versions. A new
upload or a changed setting is a draft; a person makes a version active, and the active one before it is superseded; a
person can retire the whole thing, so its active version is no longer offered; making any version active again brings
a retired one back. A stored version never changes. Until 224 the price lists and the output templates each wrote these
steps out; now both use this module on their own table, with their own data and their own errors, so the states and
their changes are the same everywhere and a third kind of editable rule gets them by naming its table.

- `VersionTable(table, key, ...)`: a table with the columns `<key>` (the thing's identifier, the same for all its
  versions), `version`, `state`, `activated_by`, `activated_by_id`, `activated_at`, `retired_by`, `retired_by_id` and
  `retired_at` (229: who acted, by name and stable id, `jav.core.identity`).
- `row`, `latest`, `active`: reading versions; `activate`, `retire`: the state changes, in the caller's write
  transaction; `grouped`: the rows of a listing, one entry per thing with its versions.
- `VersionNotFound`, `VersionStateError`: the shared errors; an owner raises its own subclasses of them.

Layer: shared core; it imports only the clock and who acts.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from jav.core import identity
from jav.core.clock import utc_stamp as _now

DRAFT, ACTIVE, SUPERSEDED, RETIRED = "draft", "active", "superseded", "retired"
STATES = (DRAFT, ACTIVE, SUPERSEDED, RETIRED)


class VersionNotFound(KeyError):
    """No such thing or version."""


class VersionStateError(ValueError):
    """The version is not in a state that allows this (an active one made active again, a thing without an active
    version retired)."""


@dataclass(frozen=True)
class VersionTable:
    """The versions in one owner's table. `table` and `key` are the owner's own names, never a person's input."""

    table: str
    key: str
    not_found: type[VersionNotFound] = VersionNotFound
    state_error: type[VersionStateError] = VersionStateError

    def row(self, c: sqlite3.Connection, ident: str, version: int) -> Any:
        """One version; `not_found` when there is none."""
        found = c.execute(f"SELECT * FROM {self.table} WHERE {self.key}=? AND version=?", (ident, version)).fetchone()
        if found is None:
            raise self.not_found(f"{ident} version {version}")
        return found

    def latest(self, c: sqlite3.Connection, ident: str) -> Any:
        """The thing's latest version (the next one is its number + 1); `not_found` when it has none."""
        found = c.execute(f"SELECT * FROM {self.table} WHERE {self.key}=? ORDER BY version DESC LIMIT 1", (ident,)).fetchone()
        if found is None:
            raise self.not_found(ident)
        return found

    def active(self, c: sqlite3.Connection, ident: str) -> Any:
        """The thing's active version, or None."""
        return c.execute(f"SELECT * FROM {self.table} WHERE {self.key}=? AND state=?", (ident, ACTIVE)).fetchone()

    def activate(self, c: sqlite3.Connection, ident: str, version: int, *, actor: identity.Who) -> None:
        """Makes the version the active one (a draft, or an earlier version again), in the caller's write transaction;
        the active one before it is superseded, and a retired thing comes back with it."""
        if self.row(c, ident, version)["state"] == ACTIVE:
            raise self.state_error(f"{ident} version {version} is already active")
        c.execute(f"UPDATE {self.table} SET state=? WHERE {self.key}=? AND state IN (?, ?)", (SUPERSEDED, ident, ACTIVE, RETIRED))
        c.execute(f"UPDATE {self.table} SET state=?, activated_by=?, activated_by_id=?, activated_at=?, retired_by=NULL,"
                  f" retired_by_id=NULL, retired_at=NULL WHERE {self.key}=? AND version=?",
                  (ACTIVE, identity.name_of(actor), identity.id_of(actor), _now(), ident, version))

    def retire(self, c: sqlite3.Connection, ident: str, *, actor: identity.Who) -> int:
        """Retires the thing, in the caller's write transaction: its active version is no longer offered. Returns that
        version's number; `state_error` when it has no active version."""
        found = c.execute(f"SELECT version FROM {self.table} WHERE {self.key}=? AND state=?", (ident, ACTIVE)).fetchone()
        if found is None:
            raise self.state_error(f"{ident} has no active version")
        c.execute(f"UPDATE {self.table} SET state=?, retired_by=?, retired_by_id=?, retired_at=? WHERE {self.key}=?"
                  f" AND version=?", (RETIRED, identity.name_of(actor), identity.id_of(actor), _now(), ident, found["version"]))
        return int(found["version"])

    def grouped(self, rows: Iterable[Any], head: Callable[[Any], dict[str, Any]],
                view: Callable[[Any], dict[str, Any]]) -> list[dict[str, Any]]:
        """A listing's rows (in the owner's order, newest first), one entry per thing in the order it first appears:
        `head(row)` (its identifier and name), its `versions` as `view(row)` gives them, its `active` version's number
        (None without one) and whether it is `retired`."""
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            entry = out.setdefault(r[self.key], {**head(r), "active": None, "retired": False, "versions": []})
            v = view(r)
            entry["versions"].append(v)
            if r["state"] == ACTIVE:
                entry["active"] = r["version"]
            if r["state"] == RETIRED:
                entry["retired"] = True
        return list(out.values())


__all__ = ["ACTIVE", "DRAFT", "RETIRED", "STATES", "SUPERSEDED", "VersionNotFound", "VersionStateError", "VersionTable"]
