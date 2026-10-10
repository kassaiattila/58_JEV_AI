"""133 (backlog F-own-parties; DECISIONS 133): the own parties.

An own party is a company, an association or a person whose money the system reconciles: the buyer of the incoming
invoices and the holder of the bank accounts and cards. It has a name and identities:

- `tax`: a tax number by its party key (`fact_checks.tax_party_key`, the domestic stem);
- `name`: a buyer name as printed, by its significant words (legal forms, numbers and single letters left out, the
  order ignored), so "Jane Example" and "EXAMPLE, Jane" are one variant;
- `account`: a bank account or card by its statement key (`reconcile.statement_account`).

An identity belongs to one party at most, or is dismissed as no own party's (a buyer name misread from a ticket).
Nothing is fixed (the owner's decision of 2026-10-10): the store's data proposes the parties (`suggest`), a person
accepts, renames, merges, moves or dismisses, and every reader resolves at read time (`Resolver`), so a change shows at
once in every reconciliation package.

Which party an invoice belongs to: its buyer's tax number first (the company's contact person printed as the buyer
does not move the invoice), then a known name variant, then a name that holds every word of exactly one party's
variant, a misread letter allowed ("similar"); two parties' variants in one name decide nothing ("ambiguous").

Layer: a business module with its store tables. The observations it works on (buyer names and tax numbers, the holder
text of a statement) come from the application operation (`jav.party_views`). No AI call.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from itertools import combinations
from typing import Any, Callable, Iterable

from jav import cfg, fact_checks, store

KINDS = ("tax", "name", "account")
NAME_MAX = 200

store.register_schema("parties", """
CREATE TABLE IF NOT EXISTS own_parties (
    id          TEXT PRIMARY KEY,   -- 'party-' + 12 hex digits
    name        TEXT NOT NULL,
    created_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS own_party_identities (
    kind        TEXT NOT NULL,      -- tax | name | account
    key         TEXT NOT NULL,      -- tax: the party key; name: the name key; account: the statement's account key
    label       TEXT NOT NULL,      -- the form printed most often
    party_id    TEXT,               -- NULL: dismissed, no own party's
    actor       TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (kind, key)
);
CREATE INDEX IF NOT EXISTS ix_own_party_identities_party ON own_party_identities(party_id);
""")


class PartyError(ValueError):
    """A request the own parties cannot take: an empty name, an unknown kind, a party still in use."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def _joins(a: str, b: str) -> bool:
    """Whether two unknown variants name one party: the shorter, of two words at least, is found in the longer, or
    they are the same words with a misread letter (a single word in a longer name would chain people together)."""
    small, large = sorted((a, b), key=lambda k: (len(k.split()), k))
    if len(small.split()) >= int(_conf()["variant"]["min_words"]):
        return contains(small, large)
    return len(small.split()) == len(large.split()) and contains(small, large) and contains(large, small)


def _canonical(kind: str, key: Any) -> str:
    if kind not in KINDS:
        raise PartyError(f"unknown identity kind: {kind}")
    if kind == "name":
        out = name_key(key)
    else:
        out = str(key or "").strip() or None
    if not out:
        raise PartyError(f"an empty {kind} identity")
    return out


def _name(value: str) -> str:
    name = " ".join(str(value or "").split())
    if not name or len(name) > NAME_MAX:
        raise PartyError(f"a party's name is 1 to {NAME_MAX} characters")
    return name


# --- the store ------------------------------------------------------------------------------------------------------------


_REFERENCES: dict[str, tuple[Callable[[Any, str], int], Callable[[Any, str, str], None]]] = {}


def register_reference(name: str, *, count: Callable[[Any, str], int], repoint: Callable[[Any, str, str], None]) -> None:
    """A module whose records name a party (a reconciliation package): `count(conn, party_id)` keeps the party from
    being deleted, `repoint(conn, old, new)` follows a merge, in the same transaction."""
    _REFERENCES[name] = (count, repoint)


def unregister_reference(name: str) -> None:
    _REFERENCES.pop(name, None)


def _identity_rows(c=None) -> list[dict[str, Any]]:
    if c is None:
        with store.connect() as own:
            return _identity_rows(own)
    return [dict(r) for r in c.execute("SELECT kind, key, label, party_id, actor, updated_at FROM own_party_identities"
                                       " ORDER BY kind, key")]


def _party_rows(c) -> dict[str, dict[str, Any]]:
    return {r["id"]: dict(r) for r in c.execute("SELECT * FROM own_parties")}


def get(party_id: str) -> dict[str, Any]:
    for p in parties():
        if p["id"] == party_id:
            return p
    raise KeyError(party_id)


def parties() -> list[dict[str, Any]]:
    """Every own party with its identities (tax numbers, name variants, accounts), by name."""
    with store.connect() as c:
        rows = _party_rows(c)
        idents = _identity_rows(c)
    by_party: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in idents:
        if r["party_id"]:
            by_party[r["party_id"]].append({k: r[k] for k in ("kind", "key", "label", "actor", "updated_at")})
    order = {k: n for n, k in enumerate(KINDS)}
    return [{**p, "identities": sorted(by_party.get(pid, []), key=lambda i: (order[i["kind"]], i["label"].casefold()))}
            for pid, p in sorted(rows.items(), key=lambda kv: (kv[1]["name"].casefold(), kv[0]))]


def dismissed() -> list[dict[str, Any]]:
    """The identities a person dismissed as no own party's."""
    return [{k: r[k] for k in ("kind", "key", "label", "actor", "updated_at")} for r in _identity_rows() if not r["party_id"]]


def _exists(c, party_id: str) -> None:
    if not c.execute("SELECT 1 FROM own_parties WHERE id=?", (party_id,)).fetchone():
        raise KeyError(party_id)


def _put(c, kind: str, key: str, label: str, party_id: str | None, actor: str) -> None:
    c.execute("INSERT INTO own_party_identities(kind, key, label, party_id, actor, updated_at) VALUES (?,?,?,?,?,?)"
              " ON CONFLICT(kind, key) DO UPDATE SET label=excluded.label, party_id=excluded.party_id,"
              " actor=excluded.actor, updated_at=excluded.updated_at",
              (kind, key, " ".join(str(label or key).split())[:NAME_MAX] or key, party_id, actor, _now()))


def create(name: str, *, identities: Iterable[tuple[str, str, str]], actor: str) -> dict[str, Any]:
    """A new own party with its identities (kind, key, label); an identity of another party moves over."""
    clean = _name(name)
    rows = [(kind, _canonical(kind, key), label) for kind, key, label in identities]
    party_id = "party-" + uuid.uuid4().hex[:12]
    with store.connect() as c:
        store.begin_immediate(c)
        now = _now()
        c.execute("INSERT INTO own_parties(id, name, created_by, created_at, updated_at) VALUES (?,?,?,?,?)",
                  (party_id, clean, actor, now, now))
        for kind, key, label in rows:
            _put(c, kind, key, label, party_id, actor)
    return get(party_id)


def rename(party_id: str, name: str, *, actor: str) -> dict[str, Any]:
    clean = _name(name)
    with store.connect() as c:
        store.begin_immediate(c)
        _exists(c, party_id)
        c.execute("UPDATE own_parties SET name=?, updated_at=? WHERE id=?", (clean, _now(), party_id))
    return get(party_id)


def assign(kind: str, key: str, label: str, party_id: str | None, *, actor: str) -> None:
    """Gives an identity to a party, moving it from another one; `party_id=None` dismisses it (no own party's)."""
    canon = _canonical(kind, key)
    with store.connect() as c:
        store.begin_immediate(c)
        if party_id is not None:
            _exists(c, party_id)
        _put(c, kind, canon, label, party_id, actor)


def release(kind: str, key: str, *, actor: str) -> None:
    """Takes an identity back from its party or from the dismissed ones: it is unassigned again (proposed anew)."""
    canon = _canonical(kind, key)
    with store.connect() as c:
        c.execute("DELETE FROM own_party_identities WHERE kind=? AND key=?", (kind, canon))


def merge(source_id: str, target_id: str, *, actor: str) -> dict[str, Any]:
    """The source party's identities go to the target and the source is deleted; its users follow (`repoint`)."""
    if source_id == target_id:
        raise PartyError("a party cannot be merged into itself")
    with store.connect() as c:
        store.begin_immediate(c)
        _exists(c, source_id)
        _exists(c, target_id)
        c.execute("UPDATE own_party_identities SET party_id=?, actor=?, updated_at=? WHERE party_id=?",
                  (target_id, actor, _now(), source_id))
        for _count, repoint in _REFERENCES.values():
            repoint(c, source_id, target_id)
        c.execute("UPDATE own_parties SET updated_at=? WHERE id=?", (_now(), target_id))
        c.execute("DELETE FROM own_parties WHERE id=?", (source_id,))
    return get(target_id)


def delete(party_id: str, *, actor: str) -> None:
    """Deletes a party no record names; its identities are unassigned again."""
    with store.connect() as c:
        store.begin_immediate(c)
        _exists(c, party_id)
        if used := sum(count(c, party_id) for count, _repoint in _REFERENCES.values()):
            raise PartyError(f"the party is used by {used} record(s); merge it into another one instead")
        c.execute("DELETE FROM own_party_identities WHERE party_id=?", (party_id,))
        c.execute("DELETE FROM own_parties WHERE id=?", (party_id,))


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
        tk = tax_key(buyer_tax_id)
        if tk and self.taxes.get(tk):
            return self.taxes[tk], "tax"
        nk = name_key(buyer_name)
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


def resolver() -> Resolver:
    return Resolver(_identity_rows())


# --- the proposal from the data -------------------------------------------------------------------------------------------


def _top(counter: Counter) -> str:
    return min(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))[0]


def _suggestion_id(party_id: str | None, identities: Iterable[tuple[str, str]]) -> str:
    raw = json.dumps([party_id or "new", sorted(identities)], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def suggest(invoices: Iterable[dict[str, Any]], accounts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """What the data proposes beside the parties already there.

    `invoices`: {name, tax_id, supplier_name, supplier_tax_id} of the buyer side of every incoming invoice;
    `accounts`: {key, label, holder_text, statements} of every own account (the holder text: the top of the first page).
    A buyer identity that is the invoice's own supplier is a misreading and left out. The stored identities (given or
    dismissed) stay as they are. Returns the suggestions (a new party, or what an existing one gains, with how many
    invoices it would hold) and the identities nothing claims."""
    conf = _conf()
    min_n = int(conf["suggestion"]["min_invoices"])
    stored = _identity_rows()
    fixed = {(r["kind"], r["key"]) for r in stored}
    with store.connect() as c:
        existing = _party_rows(c)
    seen: list[tuple[Any, Any]] = []
    tax_n, name_n = Counter(), Counter()
    tax_labels: dict[str, Counter] = defaultdict(Counter)
    tax_printed: dict[str, Counter] = defaultdict(Counter)
    name_labels: dict[str, Counter] = defaultdict(Counter)
    name_taxes: dict[str, Counter] = defaultdict(Counter)
    supplier_named = no_buyer = 0
    for inv in invoices:
        tk, nk = tax_key(inv.get("tax_id")), name_key(inv.get("name"))
        if not tk and not nk:
            no_buyer += 1
            continue
        if (tk and tk == tax_key(inv.get("supplier_tax_id"))) or (nk and nk == name_key(inv.get("supplier_name"))):
            supplier_named += 1
            continue
        seen.append((inv.get("name"), inv.get("tax_id")))
        label = " ".join(str(inv.get("name") or "").split())
        if tk:
            tax_n[tk] += 1
            tax_printed[tk][" ".join(str(inv["tax_id"]).split())] += 1
            if label:
                tax_labels[tk][label] += 1
        if nk:
            name_n[nk] += 1
            name_labels[nk][label] += 1
            name_taxes[nk][tk] += 1

    groups: dict[str, dict[str, Any]] = {pid: {"party_id": pid, "name": p["name"], "new": set()} for pid, p in existing.items()}
    variants = {r["key"]: r["party_id"] for r in stored if r["kind"] == "name" and r["party_id"]}
    taxes = {r["key"]: r["party_id"] for r in stored if r["kind"] == "tax" and r["party_id"]}
    unassigned: list[tuple[str, str]] = []

    def add(group: str, kind: str, key: str) -> None:
        groups[group]["new"].add((kind, key))
        if kind == "name":
            variants[key] = group
        elif kind == "tax":
            taxes[key] = group

    tops: dict[str, str] = {}  # the name printed most often with a new group's tax number -> the group
    for tk, n in sorted(tax_n.items(), key=lambda kv: (-kv[1], kv[0])):  # 1. a tax number on enough invoices is a party;
        if ("tax", tk) in fixed:  # the numbers printed under one name (a party's own name) are one party's
            continue
        if n < min_n:
            unassigned.append(("tax", tk))
            continue
        top = name_key(_top(tax_labels[tk])) if tax_labels[tk] else None
        named = {g for v, g in [*variants.items(), *tops.items()] if top and _joins(v, top)}
        if len(named) == 1:
            add(named.pop(), "tax", tk)
            continue
        groups["tax:" + tk] = {"party_id": None, "name": _top(tax_labels[tk]) if tax_labels[tk] else _top(tax_printed[tk]), "new": set()}
        add("tax:" + tk, "tax", tk)
        if top:
            tops[top] = "tax:" + tk
    pending = []
    for nk in sorted(name_n):  # 2. a name printed only with grouped tax numbers is their party's
        if ("name", nk) in fixed:
            continue
        homes = name_taxes[nk]
        if None not in homes and all(t in taxes for t in homes):
            add(taxes[max(homes, key=lambda t: (homes[t], t))], "name", nk)
        else:
            pending.append(nk)
    anchors = {**tops, **variants}
    rest = []
    for nk in pending:  # 3. a name holding one party's variant (or a new party's own name) joins it
        hits = {g for v, g in anchors.items() if contains(v, nk)}
        if len(hits) == 1:
            add(hits.pop(), "name", nk)
        else:
            rest.append(nk)
    parent = {nk: nk for nk in rest}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in combinations(rest, 2):  # 4. the other names group among themselves
        if _joins(a, b):
            parent[find(a)] = find(b)
    clusters: dict[str, list[str]] = defaultdict(list)
    for nk in rest:
        clusters[find(nk)].append(nk)
    for members in clusters.values():
        if sum(name_n[m] for m in members) >= min_n:
            g = "name:" + min(members)
            groups[g] = {"party_id": None, "name": _top(sum((name_labels[m] for m in members), Counter())), "new": set()}
            for m in members:
                add(g, "name", m)
        else:
            unassigned.extend(("name", m) for m in members)
    account_labels, account_statements = {}, {}
    for acc in accounts:  # 5. an account goes to the one party whose variant stands at the top of its statement
        key = str(acc["key"])
        account_labels[key], account_statements[key] = str(acc.get("label") or key), int(acc.get("statements") or 0)
        if ("account", key) in fixed:
            continue
        held = name_key(acc.get("holder_text"))
        hits = {g for v, g in variants.items() if contains(v, held)}
        if len(hits) == 1:
            add(hits.pop(), "account", key)
        else:
            unassigned.append(("account", key))

    def label(kind: str, key: str) -> str:
        if kind == "name":
            return _top(name_labels[key])
        return _top(tax_printed[key]) if kind == "tax" else account_labels.get(key, key)

    def count(kind: str, key: str) -> int:
        return tax_n[key] if kind == "tax" else name_n[key] if kind == "name" else account_statements.get(key, 0)

    proposed = Resolver([*stored, *({"kind": k, "key": key, "party_id": g} for g, grp in groups.items() for k, key in grp["new"])])
    held_by = Counter(proposed.invoice(name, tax)[0] for name, tax in seen)
    order = {k: n for n, k in enumerate(KINDS)}
    suggestions = []
    for g, grp in groups.items():
        if not grp["new"]:
            continue
        idents = sorted(grp["new"], key=lambda ik: (order[ik[0]], ik[1]))
        suggestions.append({"id": _suggestion_id(grp["party_id"], idents), "party_id": grp["party_id"], "name": grp["name"],
                            "invoices": held_by[g],
                            "identities": [{"kind": k, "key": key, "label": label(k, key), "invoices": count(k, key)} for k, key in idents]})
    suggestions.sort(key=lambda s: (-s["invoices"], s["name"].casefold()))
    return {"suggestions": suggestions,
            "unassigned": sorted(({"kind": k, "key": key, "label": label(k, key), "invoices": count(k, key)} for k, key in unassigned),
                                 key=lambda u: (-u["invoices"], order[u["kind"]], u["key"])),
            "buyer_is_supplier": supplier_named, "no_buyer": no_buyer}


def apply(suggestion: dict[str, Any], *, actor: str, name: str | None = None) -> dict[str, Any]:
    """Carries out one suggestion of `suggest`: a new party with its identities, or what an existing one gains."""
    idents = [(i["kind"], i["key"], i["label"]) for i in suggestion["identities"]]
    if suggestion["party_id"] is None:
        return create(name or suggestion["name"], identities=idents, actor=actor)
    for kind, key, lab in idents:
        assign(kind, key, lab, suggestion["party_id"], actor=actor)
    if name:
        rename(suggestion["party_id"], name, actor=actor)
    return get(suggestion["party_id"])
