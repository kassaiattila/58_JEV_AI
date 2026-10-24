"""133 (backlog F-own-parties; DECISIONS 133): the own parties.

An own party is a company, an association or a person the work is done for (whose money the system reconciles: the
buyer of the incoming invoices and the holder of the bank accounts and cards). It has a name and identities:

- `tax`: a tax number by its party key (`fact_checks.tax_party_key`, the domestic stem);
- `name`: a buyer name as printed, by its significant words (legal forms, numbers and single letters left out, the
  order ignored), so "Jane Example" and "EXAMPLE, Jane" are one variant;
- `account`: a bank account or card by its statement key (`reconcile.statement_account`).

An identity belongs to one party at most, or is dismissed as no own party's (a buyer name misread from a ticket).
Nothing is fixed (the owner's decision of 2026-10-10): the store's data proposes the parties, a person accepts, renames,
merges, moves or dismisses, and every reader resolves at read time (`Resolver`), so a change shows at once in every
reconciliation package.

229 (plan structure stage 1, MD2): this is the shared own organisation any domain uses: the parties, their identities,
their merging and the references that keep a party in use. The finance domain's part is its own module
(`jav/domains/finance/own_parties.py`): the accounts' details (138), an invoice's direction (147, 148), the own tax
number as the supplier's (134) and the detailed type's direction (149) with their decision points, and the proposal
from the invoices and the statements (133).

Which party an invoice belongs to: its buyer's tax number first (the company's contact person printed as the buyer
does not move the invoice), then a known name variant, then a name that holds every word of exactly one party's
variant, a misread letter allowed ("similar"); two parties' variants in one name decide nothing ("ambiguous").

Layer: a business module with its store tables. No AI call.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any, Callable, Iterable

from jav.documents import fact_checks
from jav.core import cfg, identity, store
from jav.core.user_messages import explained
from jav.core.clock import utc_stamp as _now

KINDS = ("tax", "name", "account")
NAME_MAX = 200

store.register_schema("parties", """
CREATE TABLE IF NOT EXISTS own_parties (
    id          TEXT PRIMARY KEY,   -- 'party-' + 12 hex digits
    name        TEXT NOT NULL,
    created_by  TEXT NOT NULL,
    created_by_id TEXT,             -- 229 (SZ2c): the stable ids beside the names (`jav.core.identity`)
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS own_party_identities (
    kind        TEXT NOT NULL,      -- tax | name | account
    key         TEXT NOT NULL,      -- tax: the party key; name: the name key; account: the statement's account key
    label       TEXT NOT NULL,      -- the form printed most often
    party_id    TEXT,               -- NULL: dismissed, no own party's
    actor       TEXT NOT NULL,
    actor_id    TEXT,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (kind, key)
);
CREATE INDEX IF NOT EXISTS ix_own_party_identities_party ON own_party_identities(party_id);
""")


def _actor_ids(conn) -> None:
    """229 (SZ2c): the stable id beside every name of who acted; the earlier rows' from their names."""
    store.add_actor_ids(conn, "own_parties", ("created_by",))
    store.add_actor_ids(conn, "own_party_identities", ("actor",))


store.register_migration("parties_actor_ids", _actor_ids)


class PartyError(ValueError):
    """A request the own parties cannot take: an empty name, an unknown kind, a party still in use."""


def _conf() -> dict[str, Any]:
    return cfg.load("parties")


def config_hash() -> str:
    return cfg.config_hash("parties")


# --- keys and comparison -------------------------------------------------------------------------------------------------


def _words(value: Any) -> list[str]:
    """The significant words of a name without its numbers (an address, a tax number) and single letters; a word with
    a misread digit ("examp1etrade") stays."""
    return [w for w in fact_checks.significant_words(value) if len(w) > 1 and sum(ch.isdigit() for ch in w) * 2 < len(w)]


def name_key(value: Any) -> str | None:
    """A buyer name as a variant: its significant words sorted and deduplicated, so their order does not count."""
    return " ".join(sorted(set(_words(value)))) or None


def tax_key(value: Any) -> str | None:
    return fact_checks.tax_party_key(value)


def _similar(a: str, b: str) -> bool:
    c = _conf()["similar_word"]
    return a == b or (min(len(a), len(b)) >= int(c["min_chars"]) and SequenceMatcher(None, a, b).ratio() >= float(c["min_ratio"]))


def distinctive(variant: str) -> bool:
    """Whether a variant may decide by being found in another name: two words at least, or one long word."""
    v = _conf()["variant"]
    words = variant.split()
    return len(words) >= int(v["min_words"]) or any(len(w) >= int(v["min_single_word_chars"]) for w in words)


def contains(variant: str | None, name: str | None) -> bool:
    """Whether every word of a known variant is found in a name (both name keys), a misread letter allowed."""
    if not variant or not name or not distinctive(variant):
        return False
    words = name.split()
    return all(any(_similar(w, o) for o in words) for w in variant.split())


def joins(a: str, b: str) -> bool:
    """Whether two unknown variants name one party: the shorter, of two words at least, is found in the longer, or
    they are the same words with a misread letter (a single word in a longer name would chain people together)."""
    small, large = sorted((a, b), key=lambda k: (len(k.split()), k))
    if len(small.split()) >= int(_conf()["variant"]["min_words"]):
        return contains(small, large)
    return len(small.split()) == len(large.split()) and contains(small, large) and contains(large, small)


def canonical(kind: str, key: Any) -> str:
    if kind not in KINDS:
        raise explained(PartyError, "unknown identity kind: {{kind}}", kind=kind)
    if kind == "name":
        out = name_key(key)
    else:
        out = str(key or "").strip() or None
    if not out:
        raise explained(PartyError, "an empty {{kind}} identity", kind=kind)
    return out


def _name(value: str) -> str:
    name = " ".join(str(value or "").split())
    if not name or len(name) > NAME_MAX:
        raise explained(PartyError, "a party's name is 1 to {{name_max}} characters", name_max=NAME_MAX)
    return name


# --- the store ------------------------------------------------------------------------------------------------------------


_REFERENCES: dict[str, tuple[Callable[[Any, str], int], Callable[[Any, str, str], None]]] = {}


def register_reference(name: str, *, count: Callable[[Any, str], int], repoint: Callable[[Any, str, str], None]) -> None:
    """A module whose records name a party (a reconciliation package): `count(conn, party_id)` keeps the party from
    being deleted, `repoint(conn, old, new)` follows a merge, in the same transaction."""
    _REFERENCES[name] = (count, repoint)


def unregister_reference(name: str) -> None:
    _REFERENCES.pop(name, None)


def identity_rows(c=None) -> list[dict[str, Any]]:
    if c is None:
        with store.connect() as own:
            return identity_rows(own)
    return [dict(r) for r in c.execute("SELECT kind, key, label, party_id, actor, updated_at FROM own_party_identities"
                                       " ORDER BY kind, key")]


def party_rows(c) -> dict[str, dict[str, Any]]:
    return {r["id"]: dict(r) for r in c.execute("SELECT * FROM own_parties")}


def holder_in(c, kind: str, key: str) -> dict[str, Any] | None:
    """229 (MD1-MD2): the party an identity is given to ({party_id, name}), in the caller's transaction; None for an
    unassigned or a dismissed one."""
    row = c.execute("SELECT i.party_id, p.name FROM own_party_identities i JOIN own_parties p ON p.id = i.party_id"
                    " WHERE i.kind=? AND i.key=?", (kind, key)).fetchone()
    return dict(row) if row is not None else None


def get(party_id: str) -> dict[str, Any]:
    for p in parties():
        if p["id"] == party_id:
            return p
    raise KeyError(party_id)


def parties() -> list[dict[str, Any]]:
    """Every own party with its identities (tax numbers, name variants, accounts), by name."""
    with store.connect() as c:
        rows = party_rows(c)
        idents = identity_rows(c)
    by_party: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in idents:
        if r["party_id"]:
            by_party[r["party_id"]].append({k: r[k] for k in ("kind", "key", "label", "actor", "updated_at")})
    order = {k: n for n, k in enumerate(KINDS)}
    return [{**p, "identities": sorted(by_party.get(pid, []), key=lambda i: (order[i["kind"]], i["label"].casefold()))}
            for pid, p in sorted(rows.items(), key=lambda kv: (kv[1]["name"].casefold(), kv[0]))]


def dismissed() -> list[dict[str, Any]]:
    """The identities a person dismissed as no own party's."""
    return [{k: r[k] for k in ("kind", "key", "label", "actor", "updated_at")} for r in identity_rows() if not r["party_id"]]


def require_in(c, party_id: str) -> None:
    if not c.execute("SELECT 1 FROM own_parties WHERE id=?", (party_id,)).fetchone():
        raise KeyError(party_id)


def put_in(c, kind: str, key: str, label: str, party_id: str | None, actor: identity.Who) -> None:
    c.execute("INSERT INTO own_party_identities(kind, key, label, party_id, actor, actor_id, updated_at) VALUES (?,?,?,?,?,?,?)"
              " ON CONFLICT(kind, key) DO UPDATE SET label=excluded.label, party_id=excluded.party_id,"
              " actor=excluded.actor, actor_id=excluded.actor_id, updated_at=excluded.updated_at",
              (kind, key, " ".join(str(label or key).split())[:NAME_MAX] or key, party_id, identity.name_of(actor),
               identity.id_of(actor), _now()))


def create(name: str, *, identities: Iterable[tuple[str, str, str]], actor: identity.Who) -> dict[str, Any]:
    """A new own party with its identities (kind, key, label); an identity of another party moves over."""
    clean = _name(name)
    rows = [(kind, canonical(kind, key), label) for kind, key, label in identities]
    party_id = "party-" + uuid.uuid4().hex[:12]
    with store.connect() as c:
        store.begin_immediate(c)
        now = _now()
        c.execute("INSERT INTO own_parties(id, name, created_by, created_by_id, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                  (party_id, clean, identity.name_of(actor), identity.id_of(actor), now, now))
        for kind, key, label in rows:
            put_in(c, kind, key, label, party_id, actor)
    return get(party_id)


def rename(party_id: str, name: str, *, actor: identity.Who) -> dict[str, Any]:
    clean = _name(name)
    with store.connect() as c:
        store.begin_immediate(c)
        require_in(c, party_id)
        c.execute("UPDATE own_parties SET name=?, updated_at=? WHERE id=?", (clean, _now(), party_id))
    return get(party_id)


def assign(kind: str, key: str, label: str, party_id: str | None, *, actor: identity.Who) -> None:
    """Gives an identity to a party, moving it from another one; `party_id=None` dismisses it (no own party's)."""
    canon = canonical(kind, key)
    with store.connect() as c:
        store.begin_immediate(c)
        if party_id is not None:
            require_in(c, party_id)
        put_in(c, kind, canon, label, party_id, actor)


def release(kind: str, key: str, *, actor: identity.Who) -> None:
    """Takes an identity back from its party or from the dismissed ones: it is unassigned again (proposed anew)."""
    canon = canonical(kind, key)
    with store.connect() as c:
        c.execute("DELETE FROM own_party_identities WHERE kind=? AND key=?", (kind, canon))


def merge(source_id: str, target_id: str, *, actor: identity.Who) -> dict[str, Any]:
    """The source party's identities go to the target and the source is deleted; its users follow (`repoint`)."""
    if source_id == target_id:
        raise explained(PartyError, "a party cannot be merged into itself")
    with store.connect() as c:
        store.begin_immediate(c)
        require_in(c, source_id)
        require_in(c, target_id)
        c.execute("UPDATE own_party_identities SET party_id=?, actor=?, actor_id=?, updated_at=? WHERE party_id=?",
                  (target_id, identity.name_of(actor), identity.id_of(actor), _now(), source_id))
        for _count, repoint in _REFERENCES.values():
            repoint(c, source_id, target_id)
        c.execute("UPDATE own_parties SET updated_at=? WHERE id=?", (_now(), target_id))
        c.execute("DELETE FROM own_parties WHERE id=?", (source_id,))
    return get(target_id)


def delete(party_id: str, *, actor: identity.Who) -> None:
    """Deletes a party no record names; its identities are unassigned again."""
    with store.connect() as c:
        store.begin_immediate(c)
        require_in(c, party_id)
        if used := sum(count(c, party_id) for count, _repoint in _REFERENCES.values()):
            raise explained(PartyError, "the party is used by {{used}} record(s); merge it into another one instead",
                            used=used)
        c.execute("DELETE FROM own_party_identities WHERE party_id=?", (party_id,))
        c.execute("DELETE FROM own_parties WHERE id=?", (party_id,))


def registered_accounts(c=None) -> set[str]:
    """153 (decision of 2026-10-13): the account keys an own party holds (a person assigned them, or an approved live
    run of a statement package did): a payment to one of them is a transfer between own accounts."""
    if c is None:
        with store.connect() as own:
            return registered_accounts(own)
    return {r["key"] for r in c.execute("SELECT key FROM own_party_identities WHERE kind='account' AND party_id IS NOT NULL")}


# --- reading ------------------------------------------------------------------------------------------------------------


class Resolver:
    """Which party a document belongs to, from the identities as they stand (`resolver()`); fuzzy lookups are cached."""

    def __init__(self, rows: Iterable[dict[str, Any]]):
        self.taxes: dict[str, str | None] = {}
        self.names: dict[str, str | None] = {}
        self.accounts: dict[str, str | None] = {}
        for r in rows:
            {"tax": self.taxes, "name": self.names, "account": self.accounts}[r["kind"]][r["key"]] = r["party_id"]
        self._similar: dict[str, tuple[str | None, str | None]] = {}

    def invoice(self, buyer_name: Any, buyer_tax_id: Any) -> tuple[str | None, str | None]:
        """(party id, how): `tax`, `name`, `similar`; (None, `ambiguous`) when two parties' variants are in the name;
        (None, None) when nothing ties it, or its identity is dismissed."""
        party = self.by_tax(buyer_tax_id)
        return (party, "tax") if party else self.by_name(buyer_name)

    def by_tax(self, tax_id: Any) -> str | None:
        """The party a tax number is registered to; None for an unknown or a dismissed one."""
        tk = tax_key(tax_id)
        return self.taxes.get(tk) if tk else None

    def by_name(self, name: Any) -> tuple[str | None, str | None]:
        """(party id, how) by a name alone: `name`, `similar`; (None, `ambiguous`) when two parties' variants are in
        it; (None, None) when nothing ties it, or its identity is dismissed."""
        nk = name_key(name)
        if not nk:
            return None, None
        if nk in self.names:
            pid = self.names[nk]
            return (pid, "name") if pid else (None, None)
        if nk not in self._similar:
            hits = {pid for variant, pid in self.names.items() if pid and contains(variant, nk)}
            self._similar[nk] = (next(iter(hits)), "similar") if len(hits) == 1 else (None, "ambiguous" if hits else None)
        return self._similar[nk]

    def account(self, key: str) -> str | None:
        return self.accounts.get(key)

    def has_tax(self, party_id: str) -> bool:
        """Whether the party has a tax number registered (148: then another number read beside its name contradicts it)."""
        return party_id in self.taxes.values()


def resolver() -> Resolver:
    return Resolver(identity_rows())
