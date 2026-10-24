"""The finance domain's part of the own parties (229, plan structure stage 1, MD2; until then in `jav/app/parties.py`).

Plain-language summary: the own parties themselves (their names, tax numbers, name variants and accounts as
identities) are the shared own organisation (`jav/app/parties.py`). What only the finance work asks of them is here:

- an own account's or card's details, registered before or after its first statement (138, DECISIONS 137: its kind,
  bank, currencies and the days it was open, `own_accounts`), so an account without a processed statement is known
  too: the reconciliation asks it to be covered and the monthly data status shows its missing months;
- an invoice's direction by the own parties on its two sides (147, 148: incoming, outgoing, internal, not own,
  unclear), by the reconciliation's field names (`reconcile.json` `invoice_fields`);
- an incoming invoice whose supplier tax number is an own party's (134, 157, 218: a to-do, a traced decision point);
- whether that direction settles the detected detailed type's uncertainty between an outgoing and an incoming pack
  (149, 218: a traced decision point);
- the proposal of the parties from the buyer sides of the incoming invoices and the holder text of the statements
  (133, `suggest`), which a person accepts (`apply`).

The decision points keep their codes (`parties.own_tax_as_supplier`, `parties.detail_direction`) and the to-dos their
reasons, so every stored trace and to-do reads as before. The observations it works on (buyer names and tax numbers,
the holder text of a statement) come from the application operation (`jav.domains.finance.party_views`).

Layer: the finance domain's business module with its store table (`own_accounts`). No AI call.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date
from itertools import combinations
from typing import Any, Iterable

from jav.app import parties
from jav.core import cfg, identity, store, trace, type_roles
from jav.core.user_messages import explained
from jav.core.clock import utc_stamp as _now

store.register_schema("party_accounts", """
-- 138 (DECISIONS 137): an own account or card registered with its details, before or after its first statement; whose
-- it is stays in own_party_identities (kind 'account'), so moving and merging work as for every identity
CREATE TABLE IF NOT EXISTS own_accounts (
    key         TEXT PRIMARY KEY,   -- the statement's account key (reconcile.statement_account)
    kind        TEXT NOT NULL,      -- account | card
    bank        TEXT,
    currencies  TEXT NOT NULL,      -- JSON: the ISO 4217 codes it books in
    valid_from  TEXT,               -- ISO date it was opened; NULL: since its first statement
    valid_to    TEXT,               -- ISO date it was closed; NULL: still open
    actor       TEXT NOT NULL,
    actor_id    TEXT,               -- 229 (SZ2c)
    updated_at  TEXT NOT NULL
);
""")

def _actor_ids(conn) -> None:
    """229 (SZ2c): the stable id beside the name of who set an account's details; the earlier rows' from their names."""
    store.add_actor_ids(conn, "own_accounts", ("actor",))


store.register_migration("own_accounts_actor_ids", _actor_ids)
ACCOUNT_KINDS = ("account", "card")
BANK_MAX = 100


def _conf() -> dict[str, Any]:
    return cfg.load("parties")


# --- accounts and cards registered with their details (138) -------------------------------------------------------------


def _account_details(kind: str, bank: str | None, currencies: Iterable[str], valid_from: str | None,
                     valid_to: str | None) -> tuple[str, str | None, str, str | None, str | None]:
    if kind not in ACCOUNT_KINDS:
        raise explained(parties.PartyError, "an account is one of {{account_kinds}}", account_kinds=", ".join(ACCOUNT_KINDS))
    clean_bank = " ".join(str(bank or "").split()) or None
    if clean_bank and len(clean_bank) > BANK_MAX:
        raise explained(parties.PartyError, "a bank's name is at most {{bank_max}} characters", bank_max=BANK_MAX)
    codes = sorted({str(c).strip().upper() for c in currencies})
    if not codes or not all(re.fullmatch(r"[A-Z]{3}", c) for c in codes):
        raise explained(parties.PartyError, "an account books in one currency at least, each an ISO code of three letters")
    days = []
    for value in (valid_from, valid_to):
        try:
            days.append(date.fromisoformat(value).isoformat() if value else None)
        except ValueError as exc:
            raise explained(parties.PartyError, "the days an account was open are ISO dates") from exc
    if days[0] and days[1] and days[0] > days[1]:
        raise explained(parties.PartyError, "the account is closed before it was opened")
    return kind, clean_bank, json.dumps(codes), days[0], days[1]


def _put_account(c, key: str, details: tuple[str, str | None, str, str | None, str | None], actor: identity.Who) -> None:
    c.execute("INSERT INTO own_accounts(key, kind, bank, currencies, valid_from, valid_to, actor, actor_id, updated_at)"
              " VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET kind=excluded.kind, bank=excluded.bank,"
              " currencies=excluded.currencies, valid_from=excluded.valid_from, valid_to=excluded.valid_to,"
              " actor=excluded.actor, actor_id=excluded.actor_id, updated_at=excluded.updated_at",
              (key, *details, identity.name_of(actor), identity.id_of(actor), _now()))


def register_account(party_id: str, key: str, label: str, *, kind: str, currencies: Iterable[str], bank: str | None = None,
                     valid_from: str | None = None, valid_to: str | None = None, actor: identity.Who) -> dict[str, Any]:
    """An own account or card given to a party with its details, whether its statements are processed yet or not; a
    dismissed or unassigned account is taken, another party's is refused (a person moves it on purpose)."""
    canon = parties.canonical("account", key)
    details = _account_details(kind, bank, currencies, valid_from, valid_to)
    with store.connect() as c:
        store.begin_immediate(c)
        parties.require_in(c, party_id)
        held = parties.holder_in(c, "account", canon)
        if held is not None and held["party_id"] != party_id:
            raise explained(parties.PartyError, "the account is {{name}}'s; move it from there", name=held["name"])
        parties.put_in(c, "account", canon, label, party_id, actor)
        _put_account(c, canon, details, actor)
    return parties.get(party_id)


def set_account(key: str, *, kind: str, currencies: Iterable[str], bank: str | None = None, valid_from: str | None = None,
                valid_to: str | None = None, actor: identity.Who) -> None:
    """The details of an account a party holds (one found on statements included)."""
    canon = parties.canonical("account", key)
    details = _account_details(kind, bank, currencies, valid_from, valid_to)
    with store.connect() as c:
        store.begin_immediate(c)
        if parties.holder_in(c, "account", canon) is None:
            raise KeyError(key)
        _put_account(c, canon, details, actor)

def accounts() -> dict[str, dict[str, Any]]:
    """The registered details of the accounts, by key: kind, bank, currencies, the days open, who set them."""
    with store.connect() as c:
        rows = c.execute("SELECT * FROM own_accounts ORDER BY key").fetchall()
    return {r["key"]: {"kind": r["kind"], "bank": r["bank"], "currencies": json.loads(r["currencies"]),
                       "valid_from": r["valid_from"], "valid_to": r["valid_to"], "actor": r["actor"],
                       "updated_at": r["updated_at"]} for r in rows}

DIRECTIONS = ("incoming", "outgoing", "internal", "not_own", "unclear")


def direction_values(records: list[dict[str, Any]]) -> list[tuple[str | None]]:
    """147: the documents table's direction column of each record: an invoice's direction from the own parties
    (`direction`); None for a document of another kind (180: the finance domain's column, `jav/domains/finance/__init__.py`;
    until then in `jav/app/export.py`)."""
    kinds = {*type_roles.types("incoming_invoice"), *type_roles.types("outgoing_invoice")}
    if not any(r["doc_type"] in kinds for r in records):
        return [(None,)] * len(records)
    res = parties.resolver()
    return [(direction(res, r["doc_type"], r["fields"])[0] if r["doc_type"] in kinds else None,) for r in records]


def direction(res: parties.Resolver, doc_type: str | None, values: dict[str, Any]) -> tuple[str, str | None]:
    """147 (DECISIONS 147): an invoice's direction and the own party it is that direction for, from the identities on
    its two sides (the supplier read as the buyer is: tax number, name, a similar name), by the reconciliation's field
    names (`reconcile.json` `invoice_fields`): `incoming` (the buyer is an own party), `outgoing` (the supplier is, or
    the type is an outgoing invoice), `internal` (two own parties: incoming for the buyer, outgoing for the supplier),
    `not_own` (neither side), `unclear` (the same party on both sides, or a name two parties' variants fit).

    148 (DECISIONS 148): each side is weighed for a party (`_Side`), since the store's misread sides showed an own name
    beside another company's tax number, swapped tax numbers and one number on both sides. An invoice is outgoing only on
    consistent evidence (an outgoing invoice is left out of the pairing of payments); conflicting evidence leaves it
    unclear; when the same party is on both sides, it is incoming if only the supplier side has evidence against the
    party, otherwise unclear. The outgoing type
    decides only when the parties do not say incoming (an own buyer and a supplier no own party is tied to)."""
    conf = cfg.load("reconcile")
    fields = conf["invoice_fields"]

    def first(keys: str | list[str]) -> Any:
        return next((values.get(k) for k in ([keys] if isinstance(keys, str) else keys) if values.get(k) not in (None, "")), None)

    s_side = _Side.read(res, first(fields["supplier_name"]), first(fields["supplier_tax_id"]))
    b_side = _Side.read(res, first(fields["buyer_name"]), first(fields["buyer_tax_id"]))
    if s_side.ambiguous or b_side.ambiguous:
        return "unclear", None
    if s_side.tax_key and s_side.tax_key == b_side.tax_key and not s_side.by_tax:
        s_side.tax_key = b_side.tax_key = None  # another company's number on both sides is a copy: no evidence
    supplier, buyer = s_side.best(res), b_side.best(res)
    if type_roles.has(doc_type, "outgoing_invoice") and (supplier or not buyer):
        return "outgoing", supplier
    if supplier and buyer:
        if supplier != buyer:
            return "internal", None
        # the same party on both sides: one side is misread. Only the incoming reading may win (a clean buyer side, a
        # supplier side with evidence against it): an own name on the buyer side is evidence enough against outgoing.
        if not b_side.against(res, buyer) and s_side.against(res, supplier):
            return "incoming", buyer
        return "unclear", None
    if supplier:
        return ("outgoing", supplier) if s_side.net(res, supplier) > 0 else ("unclear", None)
    if buyer:
        return ("incoming", buyer) if b_side.net(res, buyer) > 0 else ("unclear", None)
    return "not_own", None


class _Side:
    """148: what one side of an invoice says of the own parties, by its name and by its tax number."""

    def __init__(self, by_name: str | None, named: bool, by_tax: str | None, tax_key: str | None, ambiguous: bool):
        self.by_name, self.named, self.by_tax, self.tax_key, self.ambiguous = by_name, named, by_tax, tax_key, ambiguous

    @classmethod
    def read(cls, res: parties.Resolver, name: Any, tax_id: Any) -> _Side:
        by_name, how = res.by_name(name)
        by_tax = res.by_tax(tax_id)
        return cls(by_name, bool(parties.name_key(name)), by_tax, parties.tax_key(tax_id), how == "ambiguous" and not by_tax)

    def parties(self) -> set[str]:
        return {p for p in (self.by_name, self.by_tax) if p}

    def support(self, party: str) -> int:
        """The evidence for the party being on this side: its tax number counts two, its name one."""
        return (self.by_name == party) + 2 * (self.by_tax == party)

    def against(self, res: parties.Resolver, party: str) -> int:
        """The evidence against: another name, and another tax number when the party has one registered."""
        return (self.named and self.by_name != party) + 2 * bool(self.tax_key and self.by_tax != party and res.has_tax(party))

    def net(self, res: parties.Resolver, party: str) -> int:
        return self.support(party) - self.against(res, party)

    def best(self, res: parties.Resolver) -> str | None:
        """The party this side names with the most net evidence (by id on a tie), or None."""
        return max(sorted(self.parties()), key=lambda p: self.net(res, p), default=None)

# --- the proposal from the data -------------------------------------------------------------------------------------------


def _top(counter: Counter) -> str:
    return min(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))[0]


def _suggestion_id(party_id: str | None, identities: Iterable[tuple[str, str]]) -> str:
    raw = json.dumps([party_id or "new", sorted(identities)], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _supplier_tax_numbers(invoices: list[dict[str, Any]]) -> set[int]:
    """134: the invoices (by position) whose buyer tax number is a supplier's, read on the wrong side: either the two
    numbers are swapped (the supplier's side holds a number printed as the buyer's on more invoices than this buyer
    number), or the buyer number is printed as a supplier's more often than as a buyer's elsewhere. The store showed
    both: a rail company's and a service provider's numbers had been proposed as the buyer company's."""
    supplier_n: Counter[str] = Counter()
    buyer_n: Counter[str] = Counter()
    sides = []
    for inv in invoices:
        st, bt = parties.tax_key(inv.get("supplier_tax_id")), parties.tax_key(inv.get("tax_id"))
        sides.append((st, bt))
        if st:
            supplier_n[st] += 1
        if bt and bt != st:
            buyer_n[bt] += 1
    swapped = {i for i, (st, bt) in enumerate(sides) if st and bt and st != bt and buyer_n[st] > buyer_n[bt]}
    clean: Counter[str] = Counter(bt for i, (st, bt) in enumerate(sides) if bt and bt != st and i not in swapped)
    return swapped | {i for i, (st, bt) in enumerate(sides) if bt and bt != st and supplier_n[bt] > clean[bt]}


def supplier_check_types() -> frozenset[str]:
    """The incoming invoice types the supplier tax check looks at (`supplier_check.doc_types`; 175: the types' role,
    `jav/core/type_roles.py`)."""
    return frozenset(type_roles.types("own_tax_check"))


OWN_TAX_REASON = "parties:own_tax_as_supplier"
SCAN_PRODUCER = "parties"  # 157: the producer of the to-dos opened by `scan_own_tax`; the flow's own ones are the M2 step's


def own_tax_reasons(doc_type: str | None, values: dict[str, Any], c=None) -> list[str]:
    """134: an incoming invoice whose supplier tax number is an own party's (a given identity) while the buyer's is
    another number or missing: the two parties' numbers are likely swapped, or it is an outgoing invoice typed as an
    incoming one. A to-do for a person (`parties:own_tax_as_supplier`); the same number on both sides is the role-pair
    check's (`validator:parties.same_entity`). 157: the check itself, shared by the flow and the store scan; 218: by
    the traced rule (`own_tax_rule`)."""
    inputs = own_tax_inputs(doc_type, values, c)
    return own_tax_rule(inputs)["reasons"] if inputs is not None else []


def review_reasons(doc_type: str | None, values: dict[str, Any]) -> list[str]:
    """134: the own-tax check in a flow (`own_tax_reasons`). It reads the store: the check registry runs it in a worker
    run only, as the duplicates, so a measurement's result never depends on the store (175, `jav/ai/checks.py`)."""
    found = traced(doc_type, values)
    return found.reasons if found is not None else []


def traced(doc_type: str | None, values: dict[str, Any]) -> Any:
    """218 (P3b): the own-tax check in a flow with its decision's trace (`checks.Traced`); None for a type it does not
    look at."""
    from jav.ai import checks

    inputs = own_tax_inputs(doc_type, values)
    if inputs is None:
        return None
    return checks.Traced(own_tax_rule(inputs)["reasons"], OWN_TAX_POINT, inputs, OWN_TAX_KEYS)


# --- 218 (plan P3 P3b): the own tax number as the supplier's, a pure rule traced with the to-do it opens -----------

OWN_TAX_POINT = "parties.own_tax_as_supplier"
OWN_TAX_KEYS = {"parties.json": ("supplier_check.doc_types", "supplier_check.supplier_tax_field", "supplier_check.buyer_tax_field"),
                "fact_checks.json": ("parties.domestic_tax_stem_digits", "parties.domestic_tax_prefixes")}


def own_tax_inputs(doc_type: str | None, values: dict[str, Any], c=None) -> dict[str, Any] | None:
    """What the check reads: the two tax numbers as printed and as party keys, and the own party whose given identity
    the supplier's key is (the store's identities); None for a type the check does not look at."""
    if doc_type not in supplier_check_types():
        return None
    if c is None:
        with store.connect() as own_conn:
            return own_tax_inputs(doc_type, values, own_conn)
    check = _conf()["supplier_check"]
    supplier, buyer = values.get(check["supplier_tax_field"]), values.get(check["buyer_tax_field"])
    st = parties.tax_key(supplier)
    own = parties.holder_in(c, "tax", st) if st else None
    return {"doc_type": doc_type, "supplier_tax_id": supplier, "buyer_tax_id": buyer, "supplier_tax": st,
            "buyer_tax": parties.tax_key(buyer), "own_party": own["party_id"] if own else None}


def own_tax_rule(inputs: dict[str, Any]) -> dict[str, Any]:
    """The to-do when the supplier's number is an own party's while the buyer's is another number or missing."""
    st, bt = inputs["supplier_tax"], inputs["buyer_tax"]
    if inputs["doc_type"] not in supplier_check_types() or not st or st == bt:
        return {"reasons": []}
    return {"reasons": [OWN_TAX_REASON] if inputs["own_party"] else []}


trace.register(trace.Point(
    OWN_TAX_POINT, owner=__name__, files=("parties.json", "fact_checks.json"), rule=own_tax_rule,
    what="whether an incoming invoice names an own party's tax number as the supplier's while the buyer's is another "
         "number or missing (the numbers are likely swapped, or it is an outgoing invoice)",
    not_for="the same number on both sides (the role-pair check's) or the invoice's direction by the own parties"))


def confirm_detail_by_direction(state: Any) -> None:
    """149: the detection's detailed type was uncertain between an outgoing and an incoming pack; the direction the
    own parties give the extracted invoice settles it (`policy.detail_direction`). The parties alone decide here: the
    outgoing type is evidence in `direction`, and would confirm itself. A match closes the detailed type's uncertainty
    to-do, a contradiction is a to-do of its own; anything else is left as it was. 185 (plan G-full-move T1f): the
    finance domain's check of the saved stage (`jav/ai/checks.py`; until then in `jav/flows/flow.py`)."""
    if state.record is None or not state.detail_probabilities:
        return
    inputs = {"doc_type": state.doc_type, "probabilities": dict(state.detail_probabilities),
              "direction": direction(parties.resolver(), None, state.record.model_dump())[0]}
    out = direction_rule(inputs)
    # 218 (P3b): its to-dos and its trace in one write (inside the extraction's save, a part of its transaction)
    with store.session(), store.connect() as c:
        store.begin_immediate(c)
        for prefix in out["closes"]:
            store.review_close(subject_kind="document", subject_id=state.doc_id, producer="detect_detail",
                               reason_prefix=prefix, run_id=state.run_id)
        if out["reasons"]:
            store.review_enqueue(subject_kind="document", subject_id=state.doc_id, run_id=state.run_id,
                                 producer="detect_detail_direction", reasons=out["reasons"])
        trace.record_in(c, DIRECTION_POINT, subject=("document", state.doc_id), inputs=inputs, outcome=out,
                        keys={"policy.json": ("detect_detail.direction_sides",)}, run_id=state.run_id)


DIRECTION_POINT = "parties.detail_direction"


def direction_rule(inputs: dict[str, Any]) -> dict[str, Any]:
    """149: whether the own parties' direction settles the detailed type's uncertainty between an outgoing and an
    incoming pack (`policy.detail_direction`): a match closes the uncertainty's to-dos (`closes`: their prefixes), a
    contradiction is a `detect_detail:direction_mismatch` to-do; otherwise nothing changes."""
    from jav.ai import policy

    doc_type = inputs["doc_type"]
    verdict = policy.detail_direction(doc_type, inputs["probabilities"], inputs["direction"])
    return {"verdict": verdict,
            "closes": [f"detect_detail:{kind}:{doc_type}:" for kind in ("low_conf", "second_option")] if verdict == "confirmed" else [],
            "reasons": [f"detect_detail:direction_mismatch:{doc_type}:{inputs['direction']}"] if verdict == "contradicted" else []}


trace.register(trace.Point(
    DIRECTION_POINT, owner=__name__, files=("policy.json",), rule=direction_rule,
    what="whether the direction the own parties give an extracted invoice settles its detailed type's uncertainty "
         "between an outgoing and an incoming pack: confirmed (the uncertainty's to-dos close) or contradicted (a to-do)",
    not_for="the direction itself (the own parties' identities on its two sides: an input) or any other uncertainty "
            "of the detailed type"))


def suggest(invoices: Iterable[dict[str, Any]], accounts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """What the data proposes beside the parties already there.

    `invoices`: {name, tax_id, supplier_name, supplier_tax_id} of the buyer side of every incoming invoice;
    `accounts`: {key, label, holder_text, statements} of every own account (the holder text: the top of the first page).
    A buyer identity that is the invoice's own supplier is a misreading and left out. The stored identities (given or
    dismissed) stay as they are. Returns the suggestions (a new party, or what an existing one gains, with how many
    invoices it would hold) and the identities nothing claims."""
    conf = _conf()
    min_n = int(conf["suggestion"]["min_invoices"])
    stored = parties.identity_rows()
    fixed = {(r["kind"], r["key"]) for r in stored}
    with store.connect() as c:
        existing = parties.party_rows(c)
    invoices = list(invoices)
    foreign = _supplier_tax_numbers(invoices)
    seen: list[tuple[Any, Any]] = []
    tax_n, name_n = Counter(), Counter()
    tax_labels: dict[str, Counter] = defaultdict(Counter)
    tax_printed: dict[str, Counter] = defaultdict(Counter)
    name_labels: dict[str, Counter] = defaultdict(Counter)
    name_taxes: dict[str, Counter] = defaultdict(Counter)
    supplier_named = no_buyer = 0
    for i, inv in enumerate(invoices):
        tk, nk = parties.tax_key(inv.get("tax_id")), parties.name_key(inv.get("name"))
        if not tk and not nk:
            no_buyer += 1
            continue
        if (tk and tk == parties.tax_key(inv.get("supplier_tax_id"))) or (nk and nk == parties.name_key(inv.get("supplier_name"))):
            supplier_named += 1
            continue
        seen.append((inv.get("name"), inv.get("tax_id")))
        label = " ".join(str(inv.get("name") or "").split())
        if i in foreign:  # 134: a supplier's tax number read as the buyer's: the buyer counts as one without a number
            tk = None
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
        top = parties.name_key(_top(tax_labels[tk])) if tax_labels[tk] else None
        named = {g for v, g in [*variants.items(), *tops.items()] if top and parties.joins(v, top)}
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
        hits = {g for v, g in anchors.items() if parties.contains(v, nk)}
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
        if parties.joins(a, b):
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
        held = parties.name_key(acc.get("holder_text"))
        hits = {g for v, g in variants.items() if parties.contains(v, held)}
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

    proposed = parties.Resolver([*stored, *({"kind": k, "key": key, "party_id": g} for g, grp in groups.items() for k, key in grp["new"])])
    held_by = Counter(proposed.invoice(name, tax)[0] for name, tax in seen)
    order = {k: n for n, k in enumerate(parties.KINDS)}
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


def apply(suggestion: dict[str, Any], *, actor: identity.Who, name: str | None = None) -> dict[str, Any]:
    """Carries out one suggestion of `suggest`: a new party with its identities, or what an existing one gains."""
    idents = [(i["kind"], i["key"], i["label"]) for i in suggestion["identities"]]
    if suggestion["party_id"] is None:
        return parties.create(name or suggestion["name"], identities=idents, actor=actor)
    for kind, key, lab in idents:
        parties.assign(kind, key, lab, suggestion["party_id"], actor=actor)
    if name:
        parties.rename(suggestion["party_id"], name, actor=actor)
    return parties.get(suggestion["party_id"])
