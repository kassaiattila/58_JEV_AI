"""The scope of a work package: its own party, its period and its role (181, plan 170 L5; DECISIONS 181).

Plain-language summary: a work package may belong to an own party and a period, and have a role: what it collects
(incoming invoices, outgoing invoices, bank statements). The email routing proposes, for a document that arrived by
email, the open package whose scope fits it. A package's scope comes from the first of these that has one:
1. the scope a person gave the package (any package that processes documents; recorded in the package's log);
2. its logic pack's own (a statement package: its party, its period and the role bank statements);
3. a registered source (a workflow's step: the workflow's party and period and the step's role in its template).
A package with none of these has no scope.

The roles are registered by the domain they belong to (the finance domain: incoming invoices, outgoing invoices, bank
statements): what a role is called, which documents fit it (by their type and direction) and which kinds of package
can hold it.

- `register_role(role)`, `role(name)`, `roles()`: the roles' registry; `register_source(name, fn)`: a source of scopes.
- `scope_of(wp_id)`: the package's scope, with where it comes from (`own`, `logic_pack` or the source's name).
- `set_scope(...)`, `clear_scope(...)`: a person's scope of a package (only one without a scope of its logic pack).
- `fitting(role, party_id, day)`: the open packages whose scope fits a document (the email routing's targets);
  `scoped_packages()`: every open package with a scope, read once for many documents.
- `register_reader(name, fn)`, `place(doc_type, values)`: where a document belongs (its role, party and day), as the
  domains read it from its result (the finance domain: invoices by their two sides, statements by their account).

186 (plan G-full-move T2b): one store for every package's scope, a person's and a logic pack's alike. A logic pack
keeps its package's scope here (`save` in its own write transaction, `stored`): the party, the period and the role in
their columns, its further parts beside them (a reconciliation's accounts, a routing package's email packages), and
one revision step per change, so a person's stale change is refused (`work.RevisionConflict`). The one party reference,
the deletion with the package and the cache marks therefore cover every logic pack. An older store's own scope table
of a logic pack is copied here once (`copy_older`, registered by the logic pack's module).

Layer: business module. It reads the logic packs' registry and the packages (`jav/app/work.py`); the workflows register
their source, so this module imports no application operation.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jav.app import logic_packs, scopes, work
from jav.core import activity_kinds, identity, store
from jav.core.user_messages import explained
from jav.core.clock import utc_stamp as _now

# 181: the actions this module records in a package's log (`jav/core/activity_kinds.py`)
activity_kinds.register_events("package", ("scope_set", "scope_clear"), __name__)

store.register_schema("package_scope", """
CREATE TABLE IF NOT EXISTS workpackage_scopes (
    workpackage_id TEXT PRIMARY KEY,
    party_id       TEXT,               -- the own party (jav.app.parties)
    period_start   TEXT,               -- ISO date
    period_end     TEXT,               -- ISO date, inclusive
    role           TEXT,               -- a registered package role
    set_by         TEXT NOT NULL,
    set_by_id      TEXT,               -- 229 (SZ2c): the stable id beside the name (`jav.core.identity`)
    set_at         TEXT NOT NULL,
    parts          TEXT NOT NULL DEFAULT '{}',  -- 186: JSON, a logic pack's further parts ({name: value})
    revision       INTEGER NOT NULL DEFAULT 1   -- 186: one step per change
);
""")

_COLUMNS = ("workpackage_id", "party_id", "period_start", "period_end", "role", "set_by", "set_at", "parts", "revision")
_WRITTEN = (*_COLUMNS, "set_by_id")  # 229 (SZ2c): the id is written beside the name, the scope shows the name


def _shared_columns(conn: sqlite3.Connection) -> None:
    """186: an older store's scope table (181-185) gets the further parts and the revision."""
    store.add_columns(conn, "workpackage_scopes", {"parts": "TEXT NOT NULL DEFAULT '{}'",
                                                   "revision": "INTEGER NOT NULL DEFAULT 1"})
    store.add_actor_ids(conn, "workpackage_scopes", ("set_by",))  # 229 (SZ2c)


store.register_migration("package_scope", _shared_columns)


class ScopeRefused(ValueError):
    """A scope that cannot be given to the package: an unknown role, a role the package's kind cannot hold, a package
    whose logic pack has a scope of its own, or a refused party or period."""


class ScopeCopyError(RuntimeError):
    """186: an older store's scope of a package found in two places; the copy stops instead of losing one of them (the
    store is restored from its backup or the two rows are settled by hand)."""


@dataclass(frozen=True)
class Role:
    """A package role: its `name`, the registering `module`, its `title` (an interface label), `fits(doc_type,
    direction)`: whether a document of this type and direction (`parties.direction`) belongs in a package of the role,
    and `package_kinds`: the kinds of work package that can hold it."""

    name: str
    module: str
    title: str
    fits: Callable[[str | None, str | None], bool]
    package_kinds: tuple[str, ...]


@dataclass(frozen=True)
class Placement:
    """Where a document belongs, as a domain reads it from its result: its `role` (None: none of the roles), the own
    party, the ISO `day` that places it in a period, the invoice's `direction` (`parties.direction`) and the `problem`
    that keeps it from being placed by itself (`unknown_party`, `unclear_direction`, `internal`, `not_own`)."""

    role: str | None
    party_id: str | None
    day: str | None
    direction: str | None = None
    problem: str | None = None


_ROLES: dict[str, Role] = {}
# the domains' readers of a document's place: name -> fn(doc_type, values, cache) -> Placement | None (another kind)
_READERS: dict[str, Callable[[str | None, dict[str, Any], dict[str, Any]], Placement | None]] = {}
# a source of scopes after a person's and the logic pack's: name -> fn(wp_id) -> scope or None
_SOURCES: dict[str, Callable[[str], dict[str, Any] | None]] = {}


def register_role(r: Role) -> None:
    known = _ROLES.get(r.name)
    if known is not None and known != r:
        raise ValueError(f"package role {r.name!r} is registered already by {known.module}")
    _ROLES[r.name] = r


def role(name: str) -> Role:
    try:
        return _ROLES[name]
    except KeyError:
        raise explained(ScopeRefused, "unknown package role {{role}}", role=repr(name)) from None


def roles() -> list[Role]:
    return list(_ROLES.values())


def register_source(name: str, fn: Callable[[str], dict[str, Any] | None]) -> None:
    """A source of scopes asked after a person's and the logic pack's (the workflows' steps)."""
    known = _SOURCES.get(name)
    if known is not None and known is not fn:
        raise ValueError(f"scope source {name!r} is registered already")
    _SOURCES[name] = fn


def register_reader(name: str, fn: Callable[[str | None, dict[str, Any], dict[str, Any]], Placement | None]) -> None:
    """A domain's reader of where a document belongs; the same one again adds nothing."""
    known = _READERS.get(name)
    if known is not None and known is not fn:
        raise ValueError(f"placement reader {name!r} is registered already")
    _READERS[name] = fn


def place(doc_type: str | None, values: dict[str, Any], cache: dict[str, Any] | None = None) -> Placement | None:
    """Where a document of this type and these values belongs: the first reader's answer; None for a document no domain
    places (a contract, say). `cache`: kept by the caller across many documents (a reader keeps its lookups there)."""
    cache = {} if cache is None else cache
    for fn in _READERS.values():
        found = fn(doc_type, values, cache)
        if found is not None:
            return found
    return None


def _shown(scope: dict[str, Any], origin: str) -> dict[str, Any]:
    """A scope as the views show it: the party's name and the role's title next to their keys."""
    out = {k: scope.get(k) for k in ("party_id", "period_start", "period_end", "role")}
    out["party"] = scopes.of(scopes.PARTY).label(out["party_id"]) if out["party_id"] else None
    out["role_title"] = _ROLES[out["role"]].title if out["role"] in _ROLES else None
    out["from"] = origin
    return out


# --- 186: the one store of a package's scope ---------------------------------------------------------------------------


def stored(wp_id: str, c: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """The package's stored scope (a person's or its logic pack's): {party_id, period_start, period_end, role, parts,
    revision, set_by, set_at}; None when it has none. `c`: an open connection (inside a write transaction)."""
    if c is None:
        with store.connect() as own:
            return stored(wp_id, own)
    row = c.execute(f"SELECT {', '.join(_COLUMNS)} FROM workpackage_scopes WHERE workpackage_id=?", (wp_id,)).fetchone()
    if row is None:
        return None
    return {k: (json.loads(row[k]) if k == "parts" else row[k]) for k in _COLUMNS if k != "workpackage_id"}


def holding(part: str, value: Any) -> list[dict[str, Any]]:
    """231 (C1a): the packages whose scope holds `value` as its part `part` (the cases started from one record), oldest
    first: {id, name}."""
    with store.connect() as c:
        rows = c.execute("SELECT s.workpackage_id, s.parts, w.name FROM workpackage_scopes s JOIN workpackages w"
                         " ON w.id = s.workpackage_id WHERE s.parts IS NOT NULL ORDER BY w.created_at, w.id").fetchall()
    return [{"id": r["workpackage_id"], "name": r["name"]} for r in rows
            if (json.loads(r["parts"]) or {}).get(part) == value]


def save(c: sqlite3.Connection, wp_id: str, *, party_id: str | None = None, period_start: str | None = None,
         period_end: str | None = None, role: str | None = None, parts: dict[str, Any] | None = None, actor: identity.Who,
         expected_revision: int | None = None) -> dict[str, Any]:
    """The package's whole scope, in the caller's write transaction (its own checks and its log entry go with it): a new
    one at revision 1, a changed one a revision further. `expected_revision`: the revision the person changed (a
    different one is `work.RevisionConflict`); None: the latest write counts. The values are the caller's, checked."""
    row = c.execute("SELECT revision FROM workpackage_scopes WHERE workpackage_id=?", (wp_id,)).fetchone()
    if expected_revision is not None and (row["revision"] if row else 0) != expected_revision:
        raise explained(work.RevisionConflict, "the scope is at revision {{revision}}, not {{expected_revision}}",
                        revision=row["revision"] if row else 0, expected_revision=expected_revision)
    values = (party_id, period_start, period_end, role, identity.name_of(actor), identity.id_of(actor), _now(),
              json.dumps(parts or {}, ensure_ascii=False))
    if row is None:
        c.execute("INSERT INTO workpackage_scopes(workpackage_id, party_id, period_start, period_end, role, set_by, set_by_id,"
                  " set_at, parts, revision) VALUES (?,?,?,?,?,?,?,?,?,1)", (wp_id, *values))
    else:
        c.execute("UPDATE workpackage_scopes SET party_id=?, period_start=?, period_end=?, role=?, set_by=?, set_by_id=?,"
                  " set_at=?, parts=?, revision=revision+1 WHERE workpackage_id=?", (*values, wp_id))
    return stored(wp_id, c) or {}


def remove(c: sqlite3.Connection, wp_id: str) -> bool:
    """The package's scope taken away, in the caller's write transaction; whether it had one."""
    return c.execute("DELETE FROM workpackage_scopes WHERE workpackage_id=?", (wp_id,)).rowcount > 0


def copy_older(conn: sqlite3.Connection, table: str, convert: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    """186: an older store's own scope table of a logic pack (133-185), copied into the shared one once, in one write
    transaction checked again inside it, so two processes starting at once copy it once. `convert(row)`: the older
    row's {workpackage_id, party_id, period_start, period_end, role, parts, revision, set_by, set_at}. The older table
    keeps its rows, read by nothing (left for one release); a scope deleted afterwards does not come back. A package
    that already has a scope here stops the copy (`ScopeCopyError`). Registered by the logic pack's module as one of
    its migrations (`store.register_migration`), so it runs once that module is loaded."""
    key = f"scope_copy:{table}"

    def pending() -> bool:
        if conn.execute("SELECT 1 FROM meta WHERE key=?", (key,)).fetchone() is not None:
            return False
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None

    if not pending():
        return
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        if pending():
            _shared_columns(conn)
            for row in conn.execute(f"SELECT * FROM {table} ORDER BY workpackage_id").fetchall():
                new = convert(dict(row))
                if conn.execute("SELECT 1 FROM workpackage_scopes WHERE workpackage_id=?",
                                (new["workpackage_id"],)).fetchone() is not None:
                    raise ScopeCopyError(f"the scope of package {new['workpackage_id']} is in {table} and in the shared"
                                         " scope table already; settle the two rows by hand or restore the backup")
                new["set_by_id"] = identity.id_of(new["set_by"])  # the older table's name, as a local person
                conn.execute(f"INSERT INTO workpackage_scopes({', '.join(_WRITTEN)}) VALUES ({', '.join('?' * len(_WRITTEN))})",
                             tuple(json.dumps(new[k], ensure_ascii=False) if k == "parts" else new[k] for k in _WRITTEN))
            conn.execute("INSERT INTO meta(key, value) VALUES (?, ?)", (key, _now()))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def collects(kind: str) -> bool:
    """Whether a package of this kind can collect documents for a role (only such a package has a scope)."""
    return any(kind in r.package_kinds for r in _ROLES.values())


def _own_scope(kind: str) -> bool:
    """Whether a package of this kind has its logic pack's own scope (a person cannot give or take one)."""
    pack = logic_packs.of(kind)
    return pack is not None and pack.scope is not None


def scope_of(wp_id: str, *, kind: str | None = None) -> dict[str, Any] | None:
    """The package's scope and where it comes from, or None (also for a package of a kind no role can be held by: a
    mailbox's, a reconciliation). `kind`: the package's kind, when the caller has it. 186: a logic pack's own scope
    comes first (it is in the same store as a person's, and a person can give none to such a package)."""
    if kind is None:
        kind = work.get(wp_id)["source_kind"]
    if not collects(kind):
        return None
    pack = logic_packs.of(kind)
    if pack is not None and pack.scope is not None:
        return _shown(pack.scope(wp_id), "logic_pack")
    own = stored(wp_id)
    if own is not None:
        return _shown(own, "own") | {"set_by": own["set_by"], "set_at": own["set_at"]}
    for name, fn in _SOURCES.items():
        found = fn(wp_id)
        if found is not None:
            return _shown(found, name)
    return None


def _check(wp: dict[str, Any], party_id: str | None, period_start: str | None, period_end: str | None,
           role_name: str | None) -> dict[str, Any]:
    if not collects(wp["source_kind"]):
        raise explained(ScopeRefused, "a package of this kind collects no documents for a role")
    pack = logic_packs.of(wp["source_kind"])
    if pack is not None and (pack.scope is not None or not pack.has_runs):
        raise explained(ScopeRefused, "the package's scope is its own: it cannot be given by hand")
    if role_name is not None and wp["source_kind"] not in role(role_name).package_kinds:
        raise explained(ScopeRefused, "a package of this kind cannot collect {{role}}", role=role(role_name).title)
    given = scopes.check((), {scopes.PARTY: party_id,
                              scopes.PERIOD: (period_start, period_end) if period_start or period_end else None},
                         error=ScopeRefused)
    start, end = given.get(scopes.PERIOD) or (None, None)
    if given.get(scopes.PARTY) is None and start is None and role_name is None:
        raise explained(ScopeRefused, "give the package a party, a period or a role")
    return {"party_id": given.get(scopes.PARTY), "period_start": start, "period_end": end, "role": role_name}


def set_scope(wp_id: str, *, party_id: str | None, period_start: str | None, period_end: str | None,
              role_name: str | None, actor: identity.Who) -> dict[str, Any]:
    """A person gives a package its scope (replacing an earlier one); recorded in the package's log."""
    wp = work.get(wp_id)
    scope = _check(wp, party_id, period_start, period_end, role_name)
    with store.connect() as c:
        store.begin_immediate(c)
        save(c, wp_id, party_id=scope["party_id"], period_start=scope["period_start"], period_end=scope["period_end"],
             role=scope["role"], actor=actor)
        work.record_event(c, wp_id, "scope_set", actor, scope)
    return scope_of(wp_id, kind=wp["source_kind"]) or {}


def clear_scope(wp_id: str, *, actor: identity.Who) -> dict[str, Any] | None:
    """A person takes the package's own scope away (a scope of its workflow shows again). 186: a logic pack's own scope
    stays (it is in the same store; a person never gave it)."""
    wp = work.get(wp_id)
    if not _own_scope(wp["source_kind"]):
        with store.connect() as c:
            store.begin_immediate(c)
            if remove(c, wp_id):
                work.record_event(c, wp_id, "scope_clear", actor, {})
    return scope_of(wp_id, kind=wp["source_kind"])


def scoped_packages() -> list[dict[str, Any]]:
    """Every open package that has a scope, with it: the latest changed first."""
    out = []
    for wp in work.list_workpackages():
        if wp["status"] != "open" or not collects(wp["source_kind"]):
            continue
        sc = scope_of(wp["id"], kind=wp["source_kind"])
        if sc:
            out.append({"id": wp["id"], "name": wp["name"], "source_kind": wp["source_kind"], "items": wp["items"],
                        "updated_at": wp["updated_at"], "scope": sc})
    out.sort(key=lambda e: e["updated_at"] or "", reverse=True)
    return out


def fitting(role_name: str, party_id: str | None, day: str, *, among: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The open packages whose scope fits a document: the same role and party, and the day within the period (a scope
    without a period fits every day). The latest changed first. `among`: `scoped_packages()`, read once by a caller
    asking for many documents."""
    kinds = role(role_name).package_kinds
    out = []
    for wp in scoped_packages() if among is None else among:
        sc = wp["scope"]
        if wp["source_kind"] not in kinds or sc["role"] != role_name or sc["party_id"] != party_id:
            continue
        if sc["period_start"] and not (sc["period_start"] <= day <= (sc["period_end"] or day)):
            continue
        out.append(wp)
    return out


# --- registrations -------------------------------------------------------------------------------------------------


def count_party(c: sqlite3.Connection, pid: str) -> int:
    """186: every package's scope, a logic pack's too (until then each logic pack counted its own)."""
    return c.execute("SELECT COUNT(*) FROM workpackage_scopes WHERE party_id=?", (pid,)).fetchone()[0]


def repoint_party(c: sqlite3.Connection, old: str, new: str) -> None:
    c.execute("UPDATE workpackage_scopes SET party_id=? WHERE party_id=?", (new, old))


def _delete_guard(c: sqlite3.Connection, wp_id: str) -> None:
    """A deleted package's scope goes with it (186: a logic pack's too; inside the deleting transaction, so a logic
    pack's guard that refuses the deletion keeps it)."""
    remove(c, wp_id)


def register() -> None:
    """The package scopes' party reference and the deletion of a deleted package's scope (`registrations.load_all`)."""
    from jav.app import parties

    parties.register_reference("package_scopes", count=count_party, repoint=repoint_party)
    work.register_delete_guard(_delete_guard)


__all__ = ["Placement", "Role", "ScopeCopyError", "ScopeRefused", "clear_scope", "collects", "copy_older", "count_party",
           "fitting", "place", "register", "register_reader", "register_role", "register_source", "remove", "repoint_party",
           "role", "roles", "save", "scope_of", "scoped_packages", "set_scope", "stored"]
