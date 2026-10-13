"""139 (DECISIONS 139): one valid statement per own account, currency and day.

Two files can bring the same account's same days into the store: the Erste export without its PDF and later with it, or
a PDF statement extracted by AI and the same month read by code from the bank's export. Both went on as statements,
so the reconciliation saw every line twice, and a pair or a mark made on a line of the first did not count on the second
(a line's id comes from its statement).

The rule (the owner's decisions of 2026-10-10):

- two statements of the same account and currency that book the same days (a card cycle starting on the previous
  cycle's closing day is adjacent, not an overlap) are a pair to decide;
- the better source replaces the other when it covers the other's whole period. The order is data
  (`configs/reconcile.json` `replacement.ranks`): read by code and checked by its balances, then extracted and
  checked, then unchecked. 154 (`replacement.keep_every_line`, DECISIONS 154): only when every line of the other has
  its same line on it, or when it comes from an approved live run (a person has checked it); otherwise a line the
  replacement would drop makes the pair a conflict, so a file nobody approved cannot hide real lines;
- an equal rank, a better statement that does not cover the other's period or would drop one of its lines, is a
  conflict: both stay, and the later processed one gets a `statement:overlap:<the other's id prefix>` to-do in a
  worker run;
- a person's choice on a pair (`statement_choices`) wins over the rule and can keep either; the latest choice counts,
  and choosing the rule again undoes it;
- 144 (`replacement.reread`): two statements of the same rank and period whose lines are the same lines (booking day,
  amount, direction) are one statement read twice, for example by a newer reader that keeps more of its facts: the later
  processed reading replaces the earlier (`how: reread`), with no to-do;
- the decisions on a replaced statement's lines (allocations, marks, pair decisions) go to the same line of the
  statement that replaced it: the same booking day, amount and direction, repeated lines in their order. A decision
  whose line has no same line is left over, and the reconciliation package lists it.

Nothing is deleted: a replaced statement keeps its document and run, the snapshot leaves it out (`reconcile.snapshot`)
and says what replaced it. Reuse: the pair decision follows the duplicate decision of invoices (`jav/duplicates.py`).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any, Iterable

from jav import cfg, store

REASON = "statement"
OVERLAP = "overlap"
PREFIX = 16  # the other statement's id prefix in the to-do (as the duplicates' one)
HOWS = ("rule", "person")

store.register_schema("statement_months", """
CREATE TABLE IF NOT EXISTS statement_choices (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_key     TEXT NOT NULL,   -- the two statements' document ids in order, joined by '|'
    keep_doc_id  TEXT,            -- the statement a person keeps valid; NULL: the rule decides again
    run_id       TEXT,            -- the run in which the person chose
    actor        TEXT NOT NULL,
    note         TEXT,
    decided_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS statement_choices_pair ON statement_choices(pair_key, seq);
""")


class ChoiceError(ValueError):
    """A choice that cannot be recorded (the statements do not book the same days, a statement kept that is not of the
    pair)."""


@dataclass(frozen=True)
class Replacement:
    old: str
    new: str  # the live statement that replaces it (a chain is followed to its end)
    how: str  # rule | person | reread (144: a later reading of the same statement)


@dataclass
class Resolution:
    replaced: dict[str, Replacement] = field(default_factory=dict)
    conflicts: list[tuple[str, str]] = field(default_factory=list)  # live pairs booking the same days, undecided
    line_map: dict[str, str] = field(default_factory=dict)  # a replaced statement's line -> the same line that replaces it
    orphans: dict[str, str] = field(default_factory=dict)  # a replaced statement's line without a same line -> its statement

    def live(self, statements: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return [s for s in statements if s["id"] not in self.replaced]


@lru_cache(maxsize=None)
def _conf() -> dict[str, Any]:
    return dict(cfg.load("reconcile")["replacement"])


def pair_key(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


def rank(statement: dict[str, Any]) -> int:
    """The place of a statement's source in the configured order (0 is the best); the last place when none fits."""
    ranks = _conf()["ranks"]
    for i, r in enumerate(ranks):
        if "doc_types" in r and statement.get("doc_type") not in r["doc_types"]:
            continue
        if "verified" in r and bool(statement.get("verified")) is not bool(r["verified"]):
            continue
        return i
    return len(ranks) - 1


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def dates(start: Any, end: Any) -> tuple[date, date] | None:
    """A statement's period as days; None without both days or with the end before the start."""
    a, b = _day(start), _day(end)
    return (a, b) if a and b and a <= b else None


def overlaps(a: tuple[date, date] | None, b: tuple[date, date] | None) -> bool:
    """Whether two periods book the same days. A card cycle that starts on the previous cycle's closing day (as a credit
    card statement prints it) is adjacent: the shared day alone is no overlap when each starts on a different day."""
    if a is None or b is None:
        return False
    (s1, e1), (s2, e2) = sorted((a, b))
    if s2 > e1:
        return False
    return not (s2 == e1 and s1 < s2 and e2 > e1)


def covers(a: tuple[date, date], b: tuple[date, date]) -> bool:
    return a[0] <= b[0] and a[1] >= b[1]


def _amount(value: Any) -> Decimal | str:
    try:
        return Decimal(str(value)).normalize()
    except (InvalidOperation, ValueError):
        return str(value)


def _line_key(line: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(_amount(line.get(f)) if f == "amount" else str(line.get(f) or "")[:10] if f == "booking_date" else
                 str(line.get(f) or "") for f in _conf()["carry_over"])


def match_lines(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> tuple[dict[str, str], list[str]]:
    """The old statement's lines on the new one: the same configured fields (booking day, amount, direction), repeated
    lines in their order. Returns the map and the old lines without a same line."""
    waiting: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for line in new:
        waiting[_line_key(line)].append(str(line["id"]))
    mapped, left = {}, []
    for line in old:
        free = waiting.get(_line_key(line))
        if free:
            mapped[str(line["id"])] = free.pop(0)
        else:
            left.append(str(line["id"]))
    return mapped, left


def _same_lines(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """144: every line of each has its same line on the other (booking day, amount, direction; repeats in order)."""
    la, lb = a.get("lines") or [], b.get("lines") or []
    return len(la) == len(lb) and not match_lines(la, lb)[1]


def _keeps_lines(better: dict[str, Any], worse: dict[str, Any]) -> bool:
    """154 (DECISIONS 154): every line of the worse statement has its same line on the better one, or the rule may
    drop lines (`replacement.keep_every_line` off)."""
    if not _conf().get("keep_every_line"):
        return True
    return not match_lines(worse.get("lines") or [], better.get("lines") or [])[1]


def _group(statement: dict[str, Any]) -> tuple[str, str]:
    from jav import reconcile

    return reconcile.statement_account(statement), str(statement.get("currency") or "")


def resolve(statements: list[dict[str, Any]], choices: dict[str, str | None], *,
            approved: Iterable[str] | None = None) -> Resolution:
    """Which statements stay valid. `choices`: a person's statement kept per pair key (None: the rule decides).
    `approved`: the approved live runs, which may replace a statement whose lines they lack (154; None: looked up in the
    store, only when a replacement would drop a line)."""
    trusted_runs: set[str] | None = set(approved) if approved is not None else None

    def trusted(st: dict[str, Any]) -> bool:
        nonlocal trusted_runs
        if trusted_runs is None:
            from jav import work

            trusted_runs = work.approved_runs(s.get("work_run") for s in statements)
        return st.get("work_run") in trusted_runs

    beaten: dict[str, list[tuple[str, str]]] = defaultdict(list)  # loser -> [(winner, how)]
    undecided: list[tuple[str, str]] = []
    by_group: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for st in statements:
        by_group[_group(st)].append(st)
    for group in by_group.values():
        group = sorted(group, key=lambda s: str(s["id"]))
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                pa, pb = dates(a.get("period_start"), a.get("period_end")), dates(b.get("period_start"), b.get("period_end"))
                if not overlaps(pa, pb):
                    continue
                kept = choices.get(pair_key(a["id"], b["id"]))
                if kept in (a["id"], b["id"]):
                    loser = b["id"] if kept == a["id"] else a["id"]
                    beaten[loser].append((kept, "person"))
                    continue
                ra, rb = rank(a), rank(b)
                if _conf().get("reread") and ra == rb and pa == pb and _same_lines(a, b):
                    # 144: the same statement read again (a newer reader keeping more of its facts): the later reading
                    later, earlier = sorted((a, b), key=lambda s: (int(s.get("seq") or 0), str(s["id"])))[::-1]
                    beaten[earlier["id"]].append((later["id"], "reread"))
                    continue
                better, worse = (a, b) if ra < rb else (b, a)
                if (ra != rb and covers(pa if better is a else pb, pb if better is a else pa)
                        and (_keeps_lines(better, worse) or trusted(better))):
                    beaten[worse["id"]].append((better["id"], "rule"))
                else:
                    undecided.append((a["id"], b["id"]))
    res = Resolution()
    by_id = {s["id"]: s for s in statements}

    def end_of(sid: str, seen: frozenset[str]) -> tuple[str, str] | None:
        """The live statement a beaten one ends on, and how its first step was decided; None in a cycle."""
        for winner, how in sorted(beaten[sid], key=lambda w: (w[1] != "person", rank(by_id[w[0]]), w[0])):
            if winner in seen:
                continue
            if winner not in beaten:
                return winner, how
            further = end_of(winner, seen | {winner})
            if further is not None:
                return further[0], how
        return None

    for sid in sorted(beaten):
        found = end_of(sid, frozenset({sid}))
        if found is not None:
            res.replaced[sid] = Replacement(sid, found[0], found[1])
    res.conflicts = sorted(p for p in undecided if p[0] not in res.replaced and p[1] not in res.replaced)
    for old_id, rep in sorted(res.replaced.items()):
        mapped, left = match_lines(by_id[old_id].get("lines") or [], by_id[rep.new].get("lines") or [])
        res.line_map.update(mapped)
        res.orphans.update({lid: old_id for lid in left})
    return res


def carry(rows: Iterable[dict[str, Any]], res: Resolution) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Decision rows (allocations, marks, pair decisions: `line_id`, `statement_id`) on the valid statements: a row of a
    replaced statement's line moves to the same line (`carried_from` keeps the line it was made on); a row whose line
    has no same line is left over."""
    kept, left = [], []
    for row in rows:
        lid = str(row.get("line_id"))
        if lid in res.line_map:
            sid = str(row.get("statement_id") or "")
            new_sid = res.replaced[sid].new if sid in res.replaced else row.get("statement_id")
            kept.append({**row, "line_id": res.line_map[lid], "statement_id": new_sid, "carried_from": lid})
        elif lid in res.orphans:
            left.append(row)
        else:
            kept.append(row)
    return kept, left


# --- the store ----------------------------------------------------------------------------------------------------


def _has_table(c, name: str) -> bool:
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def choice_rows(c=None) -> list[dict[str, Any]]:
    """The latest choice per pair."""
    if c is None:
        with store.connect() as own:
            return choice_rows(own)
    if not _has_table(c, "statement_choices"):
        return []
    return [dict(r) for r in c.execute(
        "SELECT s.* FROM statement_choices s JOIN (SELECT pair_key, MAX(seq) AS m FROM statement_choices GROUP BY pair_key) l"
        " ON l.m = s.seq ORDER BY s.pair_key")]


def choices(c=None) -> dict[str, str | None]:
    return {r["pair_key"]: r["keep_doc_id"] for r in choice_rows(c)}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def reason(other_doc_id: str) -> str:
    return f"{REASON}:{OVERLAP}:{other_doc_id[:PREFIX]}"


def parse_reason(code: str) -> str | None:
    """The other statement's id prefix of an overlap to-do; None for any other to-do."""
    parts = code.split(":")
    return parts[2] if len(parts) == 3 and parts[0] == REASON and parts[1] == OVERLAP and parts[2] else None


def review_reasons(current: dict[str, Any]) -> list[str]:
    """The overlap to-dos of the statement being processed (`current`: the snapshot's statement shape), against the
    store's statements, in a worker run only: one per live statement it books the same days with, undecided."""
    from jav import duplicates, reconcile

    if not duplicates.enabled():
        return []
    others = [s for s in reconcile.statements() if s["id"] != current["id"]]
    res = resolve([*others, current], choices())
    return sorted(reason(b if a == current["id"] else a) for a, b in res.conflicts if current["id"] in (a, b))


def decide(run_id: str, item_id: str, other_doc_id: str, *, keep: str | None, actor: str, note: str | None = None) -> dict[str, Any]:
    """A person's choice on a pair of statements made on a run's item: which one stays valid (`keep`: one of the two;
    None: the rule decides again). Possible until the run is approved, as the duplicate decisions; the pair's overlap
    to-dos close on both documents."""
    from jav import reconcile, work

    if other_doc_id == item_id:
        raise ChoiceError("a statement does not overlap itself")
    if keep not in (None, item_id, other_doc_id):
        raise ChoiceError("the statement kept must be one of the pair")
    run = work.get_run(run_id)
    if run["approval"]:
        raise work.RevisionConflict(f"run {run_id} is approved; its statement choices are frozen")
    if not any(i["item_id"] == item_id for i in run["input"]["items"]):
        raise KeyError(item_id)
    found = {s["id"]: s for s in reconcile.statements() if s["id"] in (item_id, other_doc_id)}
    if other_doc_id not in found or item_id not in found:
        raise KeyError(other_doc_id if item_id in found else item_id)
    a, b = found[item_id], found[other_doc_id]
    if _group(a) != _group(b) or not overlaps(dates(a.get("period_start"), a.get("period_end")),
                                              dates(b.get("period_start"), b.get("period_end"))):
        raise ChoiceError("the two statements do not book the same days of one account")
    with store.connect() as c:
        store.begin_immediate(c)
        row = c.execute("SELECT approval FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is not None and row["approval"]:
            raise work.RevisionConflict(f"run {run_id} is approved; its statement choices are frozen")
        c.execute("INSERT INTO statement_choices(pair_key, keep_doc_id, run_id, actor, note, decided_at) VALUES (?,?,?,?,?,?)",
                  (pair_key(item_id, other_doc_id), keep, run_id, actor, note, _now()))
    resolution = {"statement_choice": keep, "pair": pair_key(item_id, other_doc_id)}
    for subject, other in ((item_id, other_doc_id), (other_doc_id, item_id)):
        for r in store.review_open_reasons("document", subject):
            prefix = parse_reason(r["reason"])
            if prefix is not None and other.startswith(prefix):
                work.resolve_reason(r["id"], actor=actor, resolution=resolution, note=note)
    return next(r for r in choice_rows() if r["pair_key"] == pair_key(item_id, other_doc_id))


def choices_for(doc_ids: Iterable[str], c=None) -> list[dict[str, Any]]:
    """The latest choices on the pairs that include any of the documents (part of a run's reviewed version)."""
    ids = set(doc_ids)
    return [r for r in choice_rows(c) if ids & set(r["pair_key"].split("|"))] if ids else []


def current(doc_id: str, doc_type: str, values: dict[str, Any], validation: list[dict[str, Any]]) -> dict[str, Any]:
    """The statement being processed in the snapshot's shape (its stored values and check results)."""
    from jav import reconcile

    return reconcile._statement({"doc_id": doc_id, "doc_type": doc_type, "values": values, "validation": validation})


def rank_name(statement: dict[str, Any]) -> str:
    ranks = _conf()["ranks"]
    return str(ranks[rank(statement)]["name"])


def item_view(item_id: str, reasons: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the review page shows of a statement's relations: the statement that replaced it, the ones it replaced,
    and the ones it books the same days with undecided (with the open to-do), each with both periods and sources, how
    it was decided, and how many lines of the replaced statement found their same line."""
    from jav import reconcile

    # 153 (review B6): only a stored statement has relations; a document of another kind returns before every stored
    # statement is built (0.10 s of each review page's 0.15-0.19 s, growing with the store; 102 s for a run's results)
    with store.connect() as c:
        row = c.execute("SELECT doc_type FROM datapoints WHERE doc_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                        (item_id,)).fetchone()
    if row is None or row["doc_type"] not in reconcile._conf()["statement_types"]:
        return []
    every = reconcile.statements()
    by_id = {s["id"]: s for s in every}
    if item_id not in by_id:
        return []
    res = resolve(every, choices())
    rows = {r["pair_key"]: r for r in choice_rows()}
    todo = {p: r["id"] for r in reasons if (p := parse_reason(r["reason"]))}
    related: list[tuple[str, str, str | None]] = []  # (other, relation, how)
    if item_id in res.replaced:
        related.append((res.replaced[item_id].new, "replaced_by", res.replaced[item_id].how))
    related += [(old, "replaces", r.how) for old, r in sorted(res.replaced.items()) if r.new == item_id]
    related += [(b if a == item_id else a, "conflict", None) for a, b in res.conflicts if item_id in (a, b)]
    if not related:
        return []
    files = reconcile.file_names([item_id, *(o for o, _r, _h in related)])
    runs = sorted({str(by_id[o].get("work_run")) for o, _r, _h in related if by_id[o].get("work_run")})
    with store.connect() as c:
        packages = {r["run_id"]: r["workpackage_id"] for r in c.execute(
            f"SELECT run_id, workpackage_id FROM runs WHERE run_id IN ({','.join('?' * len(runs))})", runs)} if runs else {}
    me = by_id[item_id]
    out = []
    for other, relation, how in related:
        st = by_id[other]
        old, new = (me, st) if relation == "replaced_by" else (st, me) if relation == "replaces" else (None, None)
        carried = match_lines(old.get("lines") or [], new.get("lines") or []) if old and new else None
        choice = rows.get(pair_key(item_id, other))
        out.append({"other_doc_id": other, "other_file": files.get(other), "relation": relation, "how": how,
                    "other_run_id": st.get("work_run"), "other_item_id": st.get("item_id"),
                    "other_workpackage_id": packages.get(str(st.get("work_run"))),
                    "period": [me.get("period_start"), me.get("period_end")],
                    "other_period": [st.get("period_start"), st.get("period_end")],
                    "rank": rank_name(me), "other_rank": rank_name(st),
                    "lines": len(me.get("lines") or []), "other_lines": len(st.get("lines") or []),
                    "carried": len(carried[0]) if carried else None, "left_over": len(carried[1]) if carried else None,
                    "reason_id": next((rid for p, rid in todo.items() if other.startswith(p)), None),
                    "kept": choice["keep_doc_id"] if choice else None,
                    "decided_by": choice["actor"] if choice else None, "decided_at": choice["decided_at"] if choice else None})
    return out
