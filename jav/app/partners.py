"""The partner register (231, plan stage B, B1; DECISIONS 231): the outside parties every process deals with.

Plain-language summary: beside the own parties (the companies the work is done for, `jav/app/parties.py`) the
processes deal with outside parties: the customers a quote is made for, the suppliers whose invoices come in, and
later the insured persons and the brokers of an insurance quote. One shared register holds them, each with the roles
it plays (a party may be a customer in one process and a supplier in another), and every change is kept as a new
version (the shared versioning of what a person edits, `jav/core/versions.py`): a save makes a new active version, the
one before it is superseded, and a partner is retired rather than deleted, so whatever named it keeps its meaning.
The register starts empty and only a person records a partner (the owner's decision of 2026-10-24); the domains
propose partners from what they have read (an invoice's supplier, say), through a suggestion source they register.

- `create(values, actor)`, `update(partner_id, values, actor, expected_version)`, `retire`, `restore`: a person's
  changes; the same tax number or name as another active partner is a `PartnerConflict` naming it.
- `get(partner_id)`: the partner with its versions; `listing(q, role, retired)`: the partners, by name.
- `roles()`: the roles a partner may play (`configs/partners.json`).
- `own_listing(q, role)` (231, U3e): the own parties as the partner list shows them, with the role `OWN`; they are
  edited in their own register.
- `register_suggestions(source)`, `suggestions()`: the domains' proposals, without the parties already recorded.

Layer: application, the shared library; it uses the shared versioning and the own parties' matching keys.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from jav.app import parties
from jav.core import cfg, completion, identity, store, versions
from jav.core.clock import utc_stamp as _now
from jav.core.user_messages import explained

__all__ = ["CONFIG", "OWN", "PartnerConflict", "PartnerError", "PartnerIn", "SuggestionSource", "UnknownPartner",
           "VERSIONS", "create", "get", "listing", "match", "own_listing", "register_suggestions", "restore", "retire",
           "roles", "suggestions", "update"]

CONFIG = "partners"
# 231 (U3e; the owner's decision of 2026-10-28): the role an own party shows with among the partners; no partner
# record plays it, so a person cannot give it to one
OWN = "own"
FIELDS = ("name", "tax_number", "email", "phone", "address", "note")

store.register_schema("partners", """
-- 231 (B1): the outside parties of the processes, every change a version of its own
CREATE TABLE IF NOT EXISTS partners (
    partner_id    TEXT PRIMARY KEY,
    created_by    TEXT NOT NULL,
    created_by_id TEXT,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS partner_versions (
    partner_id      TEXT NOT NULL REFERENCES partners(partner_id),
    version         INTEGER NOT NULL,
    state           TEXT NOT NULL,     -- draft | active | superseded | retired (`jav/core/versions.py`)
    name            TEXT NOT NULL,
    name_key        TEXT,              -- the name's significant words (the own parties' rule), for matching
    tax_number      TEXT,
    tax_key         TEXT,              -- the tax number's party key, for matching
    email           TEXT,
    phone           TEXT,
    address         TEXT,
    roles           TEXT NOT NULL,     -- JSON list of role keys (`configs/partners.json`)
    note            TEXT,
    made_by         TEXT NOT NULL,
    made_by_id      TEXT,
    made_at         TEXT NOT NULL,
    activated_by    TEXT,
    activated_by_id TEXT,
    activated_at    TEXT,
    retired_by      TEXT,
    retired_by_id   TEXT,
    retired_at      TEXT,
    PRIMARY KEY (partner_id, version)
);
CREATE INDEX IF NOT EXISTS ix_partner_versions_state ON partner_versions(state);
""")


class PartnerError(ValueError):
    """A partner that cannot be recorded as given (no name, an unknown role)."""


class UnknownPartner(versions.VersionNotFound):
    """No such partner."""


class PartnerStateError(versions.VersionStateError):
    """A partner that is not in a state that allows this (a retired one changed, an active one restored)."""


class PartnerConflict(PartnerError):
    """Another active partner has the same tax number or name; `partner_id` names it. A save from a stale page is one
    too (its `partner_id` is the partner itself)."""

    def __init__(self, message: str, partner_id: str) -> None:
        super().__init__(message)
        self.partner_id = partner_id


VERSIONS = versions.VersionTable("partner_versions", "partner_id", UnknownPartner, PartnerStateError)


class PartnerIn(BaseModel):
    """What a person records of a partner."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    tax_number: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=60)
    address: str | None = Field(default=None, max_length=400)
    note: str | None = Field(default=None, max_length=2000)
    roles: list[str] = Field(min_length=1, max_length=10)


def roles() -> dict[str, dict[str, str]]:
    """The roles a partner may play, by key, each with its English label (the interface translates it)."""
    return dict(cfg.load(CONFIG)["roles"])


def _clean(values: PartnerIn) -> dict[str, Any]:
    known = roles()
    unknown = [r for r in values.roles if r not in known]
    if unknown:
        raise explained(PartnerError, "unknown partner role {{role}}", role=unknown[0])
    out: dict[str, Any] = {k: (" ".join(str(v).split()) or None) if isinstance(v, str) else v
                           for k, v in values.model_dump().items() if k != "roles"}
    if not out["name"]:
        raise explained(PartnerError, "a partner needs a name")
    if out["note"] is not None:
        out["note"] = values.note.strip() if values.note else None  # a note keeps its own lines
    out["roles"] = [r for r in known if r in set(values.roles)]  # the register's order, each once
    return out


def _same(c: Any, out: dict[str, Any], partner_id: str | None) -> str | None:
    """Another active partner with the same tax number, or (without a tax number on either) the same name."""
    tax, name = parties.tax_key(out["tax_number"]), parties.name_key(out["name"])
    for row in c.execute("SELECT partner_id, tax_key, name_key FROM partner_versions WHERE state=?", (versions.ACTIVE,)):
        if row["partner_id"] == partner_id:
            continue
        if tax and row["tax_key"] == tax:
            return str(row["partner_id"])
        if name and row["name_key"] == name and not (tax and row["tax_key"]):
            return str(row["partner_id"])
    return None


def match(name: str | None, tax_number: str | None = None) -> dict[str, Any] | None:
    """231 (B1): the active partner a party read from a document is (the same tax number, or the same name without a
    tax number on either), or None: a case offers to link it instead of recording it again."""
    if not (name or "").strip():
        return None
    with store.connect() as c:
        found = _same(c, {"name": name, "tax_number": tax_number}, None)
    return get(found) if found else None


def _insert(c: Any, partner_id: str, version: int, out: dict[str, Any], actor: identity.Who) -> None:
    c.execute("INSERT INTO partner_versions(partner_id, version, state, name, name_key, tax_number, tax_key, email, phone,"
              " address, roles, note, made_by, made_by_id, made_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (partner_id, version, versions.DRAFT, out["name"], parties.name_key(out["name"]), out["tax_number"],
               parties.tax_key(out["tax_number"]), out["email"], out["phone"], out["address"], json.dumps(out["roles"]),
               out["note"], identity.name_of(actor), identity.id_of(actor), _now()))
    VERSIONS.activate(c, partner_id, version, actor=actor)


def create(values: PartnerIn, actor: identity.Who) -> dict[str, Any]:
    """A new partner, its first version active. `PartnerConflict` when an active partner has the same tax number or
    name."""
    out = _clean(values)
    partner_id = f"partner-{uuid.uuid4().hex[:12]}"
    with store.connect() as c:
        store.begin_immediate(c)
        if (other := _same(c, out, None)) is not None:
            raise explained(PartnerConflict, "another partner has the same tax number or name", other)
        c.execute("INSERT INTO partners(partner_id, created_by, created_by_id, created_at) VALUES (?,?,?,?)",
                  (partner_id, identity.name_of(actor), identity.id_of(actor), _now()))
        _insert(c, partner_id, 1, out, actor)
    return get(partner_id)


def update(partner_id: str, values: PartnerIn, actor: identity.Who, *, expected_version: int) -> dict[str, Any]:
    """The partner's new version, active at once; the one before is superseded. A page showing another version than
    the active one is a `PartnerConflict` (it was changed meanwhile); a retired partner is restored first."""
    out = _clean(values)
    with store.connect() as c:
        store.begin_immediate(c)
        current = VERSIONS.active(c, partner_id)
        if current is None:
            VERSIONS.latest(c, partner_id)  # an unknown partner: `UnknownPartner`
            raise explained(PartnerStateError, "a retired partner is restored before it is changed")
        if int(current["version"]) != expected_version:
            raise explained(PartnerConflict, "the partner was changed meanwhile", partner_id)
        if (other := _same(c, out, partner_id)) is not None:
            raise explained(PartnerConflict, "another partner has the same tax number or name", other)
        _insert(c, partner_id, int(VERSIONS.latest(c, partner_id)["version"]) + 1, out, actor)
    return get(partner_id)


def retire(partner_id: str, actor: identity.Who) -> dict[str, Any]:
    """The partner is no longer offered; whatever named it keeps it."""
    with store.connect() as c:
        store.begin_immediate(c)
        VERSIONS.retire(c, partner_id, actor=actor)
    return get(partner_id)


def restore(partner_id: str, actor: identity.Who) -> dict[str, Any]:
    """A retired partner offered again, with the version it was retired with."""
    with store.connect() as c:
        store.begin_immediate(c)
        if VERSIONS.active(c, partner_id) is not None:
            raise explained(PartnerStateError, "the partner is not retired")
        latest = VERSIONS.latest(c, partner_id)
        if (other := _same(c, _row_values(latest), partner_id)) is not None:
            raise explained(PartnerConflict, "another partner has the same tax number or name", other)
        VERSIONS.activate(c, partner_id, int(latest["version"]), actor=actor)
    return get(partner_id)


def _row_values(row: Any) -> dict[str, Any]:
    return {**{k: row[k] for k in FIELDS}, "roles": json.loads(row["roles"])}


def _version(row: Any) -> dict[str, Any]:
    return {"version": row["version"], "state": row["state"], **_row_values(row), "made_by": row["made_by"],
            "made_at": row["made_at"], "activated_at": row["activated_at"], "retired_by": row["retired_by"],
            "retired_at": row["retired_at"]}


def get(partner_id: str) -> dict[str, Any]:
    """The partner: its current values (the active version's, or the retired one's), whether it is retired, and its
    versions newest first. `UnknownPartner` when there is none."""
    with store.connect() as c:
        rows = c.execute("SELECT * FROM partner_versions WHERE partner_id=? ORDER BY version DESC", (partner_id,)).fetchall()
    if not rows:
        raise UnknownPartner(partner_id)
    current = next((r for r in rows if r["state"] in (versions.ACTIVE, versions.RETIRED)), rows[0])
    return {"partner_id": partner_id, **_row_values(current), "version": current["version"],
            "retired": current["state"] == versions.RETIRED, "versions": [_version(r) for r in rows]}


def listing(q: str | None = None, role: str | None = None, *, retired: bool = False) -> list[dict[str, Any]]:
    """The active partners (with `retired`, the retired ones too), by name; `q` matches the name, the tax number or the
    email, `role` a role they play."""
    states = (versions.ACTIVE, versions.RETIRED) if retired else (versions.ACTIVE,)
    with store.connect() as c:
        rows = c.execute(f"SELECT * FROM partner_versions WHERE state IN ({','.join('?' * len(states))})"
                         " ORDER BY name COLLATE NOCASE, partner_id", states).fetchall()
    needle = " ".join((q or "").lower().split())
    out = []
    for r in rows:
        values = _row_values(r)
        if role and role not in values["roles"]:
            continue
        text = " ".join(str(values[k] or "") for k in ("name", "tax_number", "email")).lower()
        if needle and needle not in text:
            continue
        out.append({"partner_id": r["partner_id"], **values, "version": r["version"], "retired": r["state"] == versions.RETIRED,
                    "changed_at": r["activated_at"] or r["made_at"]})
    return out


def own_listing(q: str | None = None, role: str | None = None) -> list[dict[str, Any]]:
    """231 (U3e; the owner's decision of 2026-10-28: an own party shows among the partners with the role "own" and is
    still edited in its own register): the own parties by name, each with its id, its first tax number and when it last
    changed; none when `role` names another role; `q` matches the name or a tax number."""
    if role and role != OWN:
        return []
    needle = " ".join((q or "").lower().split())
    out = []
    for p in parties.parties():
        taxes = [i["label"] for i in p["identities"] if i["kind"] == "tax"]
        if needle and needle not in " ".join([p["name"], *taxes]).lower():
            continue
        out.append({"party_id": p["id"], "name": p["name"], "tax_number": taxes[0] if taxes else None,
                    "changed_at": p["updated_at"]})
    return out


# --- the domains' proposals ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SuggestionSource:
    """A domain's proposals of partners from what it has read: `read()` gives rows with `name`, `tax_number`, `role`
    and `seen` (how many times), and may give `first`/`last` (the days it was seen)."""

    name: str
    module: str
    read: Callable[[], list[dict[str, Any]]]


_SOURCES: dict[str, SuggestionSource] = {}


def register_suggestions(source: SuggestionSource) -> None:
    prior = _SOURCES.get(source.name)
    if prior is not None and prior.module != source.module:
        raise ValueError(f"partner suggestion source {source.name!r} is registered by {prior.module}")
    _SOURCES[source.name] = source


def suggestion_sources() -> list[str]:
    """264 (F6): the names of the registered proposal sources (a part of the proposal list's fingerprint)."""
    completion.complete("partner suggestion sources")
    return list(_SOURCES)


def suggestions(limit: int = 200) -> list[dict[str, Any]]:
    """The domains' proposals not yet in the register (no active or retired partner with the same tax number, or the
    same name without a tax number), one per party with the roles it was seen in, most seen first."""
    completion.complete("partner suggestion sources")
    with store.connect() as c:
        known = c.execute("SELECT tax_key, name_key FROM partner_versions WHERE state IN (?, ?)",
                          (versions.ACTIVE, versions.RETIRED)).fetchall()
    taxes = {r["tax_key"] for r in known if r["tax_key"]}
    names = {r["name_key"] for r in known if r["name_key"]}
    merged: dict[str, dict[str, Any]] = {}
    for source in _SOURCES.values():
        for row in source.read():
            name = " ".join(str(row.get("name") or "").split())
            tax, key = parties.tax_key(row.get("tax_number")), parties.name_key(name)
            if not name or (tax and tax in taxes) or (not tax and key in names):
                continue
            entry = merged.setdefault(tax or f"name:{key}", {"name": name, "tax_number": row.get("tax_number"),
                                                              "roles": [], "seen": 0, "sources": [], "last": None})
            entry["seen"] += int(row.get("seen") or 1)
            if row.get("role") and row["role"] not in entry["roles"]:
                entry["roles"].append(row["role"])
            if source.name not in entry["sources"]:
                entry["sources"].append(source.name)
            entry["last"] = max(filter(None, (entry["last"], row.get("last"))), default=None)
    return sorted(merged.values(), key=lambda e: (-e["seen"], e["name"].lower()))[:limit]
