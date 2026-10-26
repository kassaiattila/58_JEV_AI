"""140 (backlog F-package-kinds K2; DECISIONS 137, 139, 140): the statement package.

A work package for one own party and a period (until 231 C3b5a a kind of its own, `source_kind = 'statements'`; now a
plain package, `manual`, whose scope names the statements rule, `RULE_NAME`, and a bank statements case's step
package). Its items are the bank statements of a folder or of the given files:

- a bank's export read by code (`jav/domains/finance/statement_table.py`): one statement item per account and month, the statement
  file the reader builds (a ledger export with the month's PDF statement as its companion);
- a PDF no export uses as its companion: a document item, processed as any PDF (type recognition, then the extraction
  of the recognised bank statement type, paid within the run's budget).

Before anything is written, a person sees a survey (`survey`): every statement the files hold with its account, month,
checks and source rank, whether the store has it already, which statement it would replace or be replaced by
(`statement_months.resolve` with the store's statements), and whose account it is. The person ticks what goes in
(`create`); the ids are the statement files' fingerprints, so a file changed between the two steps is refused.

In a run, the package's rule adds two rules (`work.PackageRule`, asked by the worker):

- a PDF recognised as anything but a bank statement (the accepted coarse categories are data:
  `configs/statement_tables.json` `package.accepted_parents`) stops after its type is recognised, with a
  `statements:not_a_statement:<type>` to-do: no extraction and no general facts are paid for;
- when a statement is saved, an account no party holds (or one dismissed as no own party's) goes to the package's party
  in a live run (the owner's decision of 2026-10-10, DECISIONS 139), in the package's log; another party's account is a
  `statements:other_party:<party>` to-do and stays where it is.

The same account's same days twice are decided by `jav/domains/finance/statement_months.py` (139), whichever package brought them.

Layer: UI/CLI → **this** (application operation) → `jav.domains.finance.statement_table`, `jav.domains.finance.statement_months`, `jav.app.parties`,
`jav.domains.finance.reconcile` (business modules) and `jav.app.work` (the package record and its log). No AI call here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from jav.app import item_kinds, package_scope, parties, work, work_runs, workflow_steps
from jav.ai import typepack
from jav.core import activity_kinds, cfg, clock, identity, store, values
from jav.domains.finance import reconcile, statement_months, statement_table
from jav.domains.finance import reconcile_store
from jav.core.user_messages import explained

# 175 (plan 170 E4): the actions this module records in the package log (`jav/core/activity_kinds.py`)
activity_kinds.register_events("package", ("statement_scope", "statement_account", "statement_add"), __name__)

KIND = "statements"  # 231 (C3b5a): the kind statement packages had until they were retyped (`_retype`)
RULE_NAME = "statements"  # the name the statements rule is registered by, which a statement package's scope names
PLAIN = "manual"  # the kind a statement package is from 231 (C3b5a): a plain one (a folder's would title its items by it)
RETYPED = "retype:statements"  # the meta mark of the retyping
NOT_A_STATEMENT = "statements:not_a_statement"
OTHER_PARTY = "statements:other_party"
DOC_TYPE = "statement_table"


def _older_scope(row: dict[str, Any]) -> dict[str, Any]:
    """186: a row of the older own scope table (140-185) as the shared scope keeps it."""
    return {"workpackage_id": row["workpackage_id"], "party_id": row["party_id"], "period_start": row["period_start"],
            "period_end": row["period_end"], "role": ROLE, "parts": {}, "revision": row["revision"],
            "set_by": row["actor"], "set_at": row["updated_at"]}


# 186 (plan G-full-move T2b): the package's party and period are in the shared scope store (`jav/app/package_scope.py`); an
# older store's `statement_scopes` is copied there once
store.register_migration("statement_package_scope",
                         lambda conn: package_scope.copy_older(conn, "statement_scopes", _older_scope))


def _retype(conn: Any) -> None:
    """231 (plan stage C, C3b5a): every statement package made while it was a kind of its own becomes a plain package of
    the statements rule, once (the meta mark `RETYPED`, checked again inside one write transaction, so two processes
    starting at once retype once): its kind is `manual`, its scope names the rule (one that did not, a revision further)
    and its log records it (`retyped`). Its revision and everything stored about its runs stay, so its readiness, its
    approvals and its released versions read as before. Registered after the older scope table's copy."""

    def pending() -> bool:
        if conn.execute("SELECT 1 FROM meta WHERE key=?", (RETYPED,)).fetchone() is not None:
            return False
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workpackage_scopes'").fetchone() is not None

    if not pending():
        return
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        if pending():
            actor = identity.machine("statements-retype")
            for (wp_id,) in conn.execute("SELECT id FROM workpackages WHERE source_kind=? ORDER BY id", (KIND,)).fetchall():
                conn.execute("UPDATE workpackages SET source_kind=? WHERE id=?", (PLAIN, wp_id))
                conn.execute("UPDATE workpackage_scopes SET parts=json_set(COALESCE(parts, '{}'), ?, ?), revision=revision+1"
                             " WHERE workpackage_id=? AND json_extract(parts, ?) IS NULL",
                             (f"$.{work.RULE_PART}", RULE_NAME, wp_id, f"$.{work.RULE_PART}"))
                work.record_event(conn, wp_id, "retyped", actor, {"from": KIND, "to": PLAIN, "rule": RULE_NAME})
            conn.execute("INSERT INTO meta(key, value) VALUES (?, ?)", (RETYPED, clock.utc_stamp()))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


store.register_migration("statement_package_retype", _retype)


class StatementPackageError(ValueError):
    """A request the statement package refuses (an unknown party, a wrong period, an empty choice, a statement the files
    no longer hold); the interface shows the message (422)."""


def _conf() -> dict[str, Any]:
    return dict(cfg.load(statement_table.CONFIG)["package"])


def _day(value: Any, what: str) -> date:
    try:
        return values.iso_day(value)
    except ValueError as exc:
        raise explained(StatementPackageError, "{{what}}: an ISO date is required", what=what) from exc


def _checked(party_id: str, period_start: Any, period_end: Any) -> tuple[dict[str, Any], str, str]:
    try:
        party = parties.get(party_id)
    except KeyError:
        raise explained(StatementPackageError, "no own party {{party_id}}", party_id=party_id) from None
    start, end = _day(period_start, "period_start"), _day(period_end, "period_end")
    if start > end:
        raise explained(StatementPackageError, "the period ends before it starts")
    return party, start.isoformat(), end.isoformat()


def _last4(account: Any) -> str | None:
    digits = "".join(ch for ch in str(account or "") if ch.isalnum())
    return "…" + digits[-4:] if digits else None


def _field(value: Any, name: str) -> Any:
    """A field of a saved flow state value (a dict after persistence, a model in the same process)."""
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


# --- the files ----------------------------------------------------------------------------------------------------------


@dataclass
class _Found:
    readings: list[statement_table.Reading] = field(default_factory=list)
    pdfs: list[Path] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)


def _companion_folders() -> list[str]:
    """The subfolders where a profile looks for an export's companion PDF (the folder itself is `.`)."""
    folders = (f for p in cfg.load(statement_table.CONFIG)["profiles"] for f in (p.get("companion") or {}).get("folders", []))
    return sorted({f for f in folders if f not in ("", ".")})


def _pdfs_in(folder: Path) -> list[Path]:
    found = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdf" and statement_table.inside(p, folder)]
    for sub in _companion_folders():
        if (folder / sub).is_dir():  # 153 (review C8): a file that stays in the folder once its links are followed
            found += [p for p in (folder / sub).iterdir() if p.is_file() and p.suffix.lower() == ".pdf"
                      and statement_table.inside(p, folder)]
    return sorted(found, key=lambda p: p.relative_to(folder).as_posix().lower())


def expand_folders(paths: Iterable[Path], *, recursive: bool) -> list[Path]:
    """168 (plan F-item-list-and-adding): with `recursive`, each folder among `paths` followed by its subfolders, each
    read as a folder of its own (a bank's exports with their companion PDFs, or PDF statements); a profile's companion
    PDF folder is left to its parent, which already reads it. A folder linked from elsewhere is passed over."""
    out: list[Path] = []
    companions = _companion_folders()
    for raw in paths:
        p = Path(raw)
        out.append(p)
        if not (recursive and p.is_dir()):
            continue
        root = p.resolve()
        for sub in sorted((q for q in root.rglob("*") if q.is_dir()), key=lambda q: q.relative_to(root).as_posix().lower()):
            if statement_table.inside(sub, root) and not any(sub.as_posix().endswith("/" + c) for c in companions):
                out.append(sub)
    return out


def _sources(paths: Iterable[Path]) -> _Found:
    """The exports and the PDFs of a folder or of the given files. A folder's exports are read as a whole (each with its
    companion PDF); the PDFs left are those no export used as its companion. A file no reader knows is listed, not
    dropped. 141: a PDF a text profile reads (a CIB statement) is a statement read by code, not a PDF to extract."""
    out = _Found()
    pdfs: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            try:
                reading = statement_table.read(p)
            except statement_table.StatementTableError as exc:  # a folder of PDFs only, or of unreadable exports
                out.skipped += [{"file": f.name, "reason": str(exc)} for f in sorted(p.iterdir())
                                if f.is_file() and f.suffix.lower() in statement_table.SUFFIXES]
            else:
                out.readings.append(reading)
                out.skipped += reading.skipped
            pdfs += _pdfs_in(p)
        elif p.suffix.lower() == ".pdf":
            try:
                out.readings.append(statement_table.read(p))
            except statement_table.StatementTableError:  # no text profile knows it: a PDF to extract
                pdfs.append(p)
        elif p.suffix.lower() in statement_table.SUFFIXES + statement_table.TEXT_SUFFIXES:
            try:
                out.readings.append(statement_table.read(p))
            except statement_table.StatementTableError as exc:
                out.skipped.append({"file": p.name, "reason": str(exc)})
        else:
            out.skipped.append({"file": p.name, "reason": "neither a statement export nor a PDF"})
    limit = int(cfg.load(statement_table.CONFIG)["limits"]["max_files"])
    if len(pdfs) > limit:
        raise explained(StatementPackageError, "more than {{limit}} PDF files", limit=limit)
    read = {(a.source or {}).get("sha256") for r in out.readings for a in r.accounts}  # 141: the text statements
    read |= {(a.source or {}).get("companion", {}).get("sha256") for r in out.readings for a in r.accounts
             if (a.source or {}).get("companion")}
    out.pdfs = [p for p in dict.fromkeys(q.resolve() for q in pdfs) if work.sha256_file(p) not in read]
    return out


def _preview(reading: statement_table.Reading, account: statement_table.Account) -> dict[str, Any]:
    """The statement an export's account would become, in the reconciliation snapshot's shape, checked by the same
    type pack checks as in a run (so its rank is the one it will have)."""
    from jav.ai.validators import run_all

    doc_id = statement_table.derived_id(reading, account)
    pack = typepack.get(DOC_TYPE)
    record, _reasons = pack.normalize(account.statement)
    validation = [r.model_dump() for r in run_all(record, pack.validators, doc_id=doc_id, doc_type=DOC_TYPE)]
    return statement_months.current(doc_id, DOC_TYPE, record.to_datapoints(pack.record_fields), validation)


def _in_period(st: dict[str, Any], start: str, end: str) -> bool:
    days = statement_months.dates(st.get("period_start"), st.get("period_end"))
    return days is None or (days[0].isoformat() <= end and days[1].isoformat() >= start)


def _documents(ids: list[str]) -> set[str]:
    found: set[str] = set()
    with store.connect() as c:
        for n in range(0, len(ids), 500):  # under the SQLite parameter limit
            chunk = ids[n:n + 500]
            found |= {r["doc_id"] for r in c.execute(
                f"SELECT doc_id FROM documents WHERE doc_id IN ({','.join('?' * len(chunk))})", chunk)}
    return found


# --- the survey -------------------------------------------------------------------------------------------------------


def survey(paths: Iterable[Path], *, party_id: str, period_start: Any, period_end: Any) -> dict[str, Any]:
    """What the files hold for the party and the period, without writing anything: every statement with its account
    (the last four characters), month, checks, source rank, whose account it is, whether the store has it, and what it
    would replace or be replaced by; every PDF no export uses, with what the store knows of it. `chosen` is the
    proposed tick: a statement in the period that the store does not have and nothing better replaces; a PDF the store
    has not processed."""
    party, start, end = _checked(party_id, period_start, period_end)
    found = _sources(paths)
    stored = reconcile_store.statements()
    stored_ids = {s["id"] for s in stored}
    previews = [(r, a, _preview(r, a)) for r in found.readings for a in r.accounts]
    top = max((int(s.get("seq") or 0) for s in stored), default=0) + 1  # 144: a file read now is later than any stored reading
    new = {s["id"]: {**s, "seq": top} for _r, _a, s in previews if s["id"] not in stored_ids}
    every = {**{s["id"]: s for s in stored}, **new}
    res = statement_months.resolve(list(every.values()), statement_months.choices())
    files = {**reconcile_store.file_names(stored_ids), **{s["id"]: (a.source or {}).get("file", r.file_name) for r, a, s in previews}}

    def ref(sid: str) -> dict[str, Any]:
        st = every[sid]
        return {"id": sid, "file": files.get(sid), "period_start": st.get("period_start"), "period_end": st.get("period_end"),
                "rank": statement_months.rank_name(st), "in_store": sid in stored_ids}

    resolver, names = parties.resolver(), {p["id"]: p["name"] for p in parties.parties()}
    rows = []
    for r, a, st in previews:
        sid = st["id"]
        owner_id = resolver.account(reconcile.statement_account(st))
        replaced = res.replaced.get(sid)
        in_period, in_store = _in_period(st, start, end), sid in stored_ids
        companion = (a.source or {}).get("companion")
        rows.append({"id": sid, "institution": r.institution, "file": files[sid], "companion": companion["file"] if companion else None,
                     "title": a.title, "account": _last4(st.get("account")), "currency": st.get("currency"),
                     "period_start": st.get("period_start"), "period_end": st.get("period_end"),
                     "lines": len(st.get("lines") or []), "checks_ok": statement_table.checks_ok(a),
                     "balance_checked": a.balances != "none", "rank": statement_months.rank_name(st),
                     "in_period": in_period, "in_store": in_store,
                     "owner": "package" if owner_id == party["id"] else "other" if owner_id else "none",
                     "owner_party": {"id": owner_id, "name": names.get(owner_id, owner_id)} if owner_id else None,
                     "replaces": [ref(old) for old, rep in sorted(res.replaced.items()) if rep.new == sid],
                     "replaced_by": ref(replaced.new) if replaced else None,
                     "conflicts": [ref(b if x == sid else x) for x, b in res.conflicts if sid in (x, b)],
                     "chosen": in_period and not in_store and replaced is None})
    hashes = [(p, work.sha256_file(p)) for p in found.pdfs]
    known = _documents([h for _p, h in hashes])
    pdfs = [{"path": str(p), "file": p.name, "sha256": h, "in_store": h in known,
             "statement": ref(h) if h in stored_ids else None, "chosen": h not in known} for p, h in hashes]
    return {"party": {"id": party["id"], "name": party["name"]}, "period_start": start, "period_end": end,
            "statements": rows, "pdfs": pdfs, "skipped": found.skipped}


# --- the package ----------------------------------------------------------------------------------------------------------


def create(*, name: str, party_id: str, period_start: Any, period_end: Any, paths: list[Path], statements: list[str],
           pdfs: list[str], actor: identity.Who, case: bool = True) -> dict[str, Any]:
    """A new statement package of the statements and PDFs a person ticked in the survey of the same files; the creator
    owns it (decision 065). A statement is named by its survey id, so one the files no longer hold is refused, and only
    a PDF the survey listed is taken. 231 (C3b4): the package is a bank statements case's step package from the start
    (a new case is made around it, `_wrap`); `case=False` for the one a case's own step makes."""
    party, start, end = _checked(party_id, period_start, period_end)
    entries, wanted, picked = _chosen(_sources(paths), statements, pdfs)
    folder = Path(paths[0]).resolve() if len(paths) == 1 and Path(paths[0]).is_dir() else None
    wp = work.create_with_items(name=name, source_kind=PLAIN, source_ref=str(folder) if folder else None, owner=actor,
                                entries=entries)
    with store.connect() as c:
        store.begin_immediate(c)
        package_scope.save(c, wp["id"], party_id=party["id"], period_start=start, period_end=end, role=ROLE,
                           parts={work.RULE_PART: RULE_NAME}, actor=actor)  # 231 (C3b5a): it runs by the rule
        work.record_event(c, wp["id"], "statement_scope", actor, {"party": party["id"], "period": [start, end],
                                                                  "statements": len(wanted), "pdfs": len(picked)})
    if case:
        _wrap(wp["id"], actor)
    return scope(wp["id"])


PACK = "bank_statements"  # 231 (C3b4): the process pack whose cases hold the statement packages


def _wrap(wp_id: str, actor: identity.Who) -> None:
    """231 (C3b4): a new case of the bank statements pack around the package (its rule in the pack's `wraps`)."""
    from jav.app import process_packs, process_runtime  # lazy: the process packs are loaded after the domains

    rule = next(w for w in process_packs.load(PACK).wraps if w.rule == RULE_NAME)
    process_runtime.wrap_case(PACK, wp_id, rule, actor=actor)


def _chosen(found: _Found, statements: list[str], pdfs: list[str]) -> tuple[list[tuple[Path, str]], set[str], list[Path]]:
    """The items of the statements and PDFs a person ticked in the survey of `found`: a statement is named by its survey
    id, so one the files no longer hold is refused, and only a PDF the survey listed is taken."""
    wanted = set(statements)
    ids = {statement_table.derived_id(r, a): (r, a) for r in found.readings for a in r.accounts}
    if missing := wanted - set(ids):
        raise explained(StatementPackageError, "{{missing}} chosen statement(s) are no longer in the files; survey them again",
                        missing=len(missing))
    listed = {str(p): p for p in found.pdfs}
    picked = []
    for raw in pdfs:
        p = Path(raw).resolve()
        if str(p) not in listed:
            raise explained(StatementPackageError, "not a PDF of the survey: {{name}}", name=p.name)
        picked.append(p)
    if not wanted and not picked:
        raise explained(StatementPackageError, "choose at least one statement or PDF")
    entries: list[tuple[Path, str]] = []
    for r in found.readings:
        keys = [a.key for a in r.accounts if statement_table.derived_id(r, a) in wanted]
        if keys:
            entries += [(p, "statement_table") for p in statement_table.derive(r, keys)]
    entries += [(p, "document") for p in dict.fromkeys(picked)]
    return entries, wanted, picked


def _held(wp_id: str) -> set[str]:
    """The ids of the statements and PDFs in the package now (a removed one is not held: adding it restores it)."""
    return {i["item_id"] for i in work.get(wp_id)["items"]}


def survey_for(wp_id: str, paths: Iterable[Path], *, recursive: bool = False) -> dict[str, Any]:
    """160-C S2: the survey of more files for an existing statement package, with the package's party and period;
    `in_package` marks a statement or PDF the package already holds, and such a one is not proposed again. 168: with
    `recursive`, a folder's subfolders too (`expand_folders`)."""
    sc = scope(wp_id)
    out = survey(expand_folders(paths, recursive=recursive), party_id=sc["party_id"], period_start=sc["period_start"],
                 period_end=sc["period_end"])
    held = _held(wp_id)
    for row in out["statements"]:
        row["in_package"] = row["id"] in held
        row["chosen"] = row["chosen"] and not row["in_package"]
    for pdf in out["pdfs"]:
        pdf["in_package"] = pdf["sha256"] in held
        pdf["chosen"] = pdf["chosen"] and not pdf["in_package"]
    return {**out, "workpackage_id": wp_id}


def add(wp_id: str, *, paths: list[Path], statements: list[str], pdfs: list[str], expected_revision: int,
        actor: identity.Who, recursive: bool = False) -> dict[str, Any]:
    """160-C S2: the statements and PDFs a person ticked in the package's own survey (`survey_for`), added to it in
    one revision step and logged (`statement_add`). One the package already holds is refused, so a stale survey
    cannot add it twice."""
    _package(wp_id)
    entries, wanted, picked = _chosen(_sources(expand_folders(paths, recursive=recursive)), statements, pdfs)
    held = _held(wp_id)
    if dup := (wanted | {work.sha256_file(p) for p in picked}) & held:
        raise explained(StatementPackageError, "{{dup}} chosen statement(s) or PDF(s) are already in the package; survey them again",
                        dup=len(dup))
    return work.add_entries(wp_id, entries, expected_revision=expected_revision,
                            event=("statement_add", actor, {"statements": len(wanted), "pdfs": len(picked)}))


def _package(wp_id: str) -> dict[str, Any]:
    wp = work.get(wp_id)
    if work.rule_name(wp_id) != RULE_NAME:  # 231 (C3b5a): a package of the rule
        raise explained(StatementPackageError, "not a statement package")
    return wp


def scope(wp_id: str) -> dict[str, Any]:
    _package(wp_id)
    row = package_scope.stored(wp_id)
    if row is None:
        raise KeyError(wp_id)
    names = {p["id"]: p["name"] for p in parties.parties()}
    return {"workpackage_id": wp_id, "party_id": row["party_id"],
            "party": {"id": row["party_id"], "name": names.get(row["party_id"], row["party_id"])},
            "period_start": row["period_start"], "period_end": row["period_end"], "revision": row["revision"],
            "updated_at": row["set_at"]}


def package_view(wp_id: str) -> dict[str, Any]:
    """The package's scope and each item's statement: valid, replaced (by which), in a conflict a person decides, or
    pending (no statement saved from it yet: not processed, or not a statement)."""
    sc, wp = scope(wp_id), _package(wp_id)
    every = reconcile_store.statements()
    by_id = {s["id"]: s for s in every}
    res = statement_months.resolve(every, statement_months.choices())
    rows = []
    for item in wp["items"]:
        st = by_id.get(item["item_id"])
        row: dict[str, Any] = {"item_id": item["item_id"], "kind": item["kind"], "file": Path(item["source_path"]).name}
        if st is None:
            rows.append({**row, "state": "pending"})
            continue
        sid = st["id"]
        conflicts = [b if x == sid else x for x, b in res.conflicts if sid in (x, b)]
        state = "replaced" if sid in res.replaced else "conflict" if conflicts else "valid"
        rows.append({**row, "state": state, "account": _last4(st.get("account")), "currency": st.get("currency"),
                     "period_start": st.get("period_start"), "period_end": st.get("period_end"),
                     "rank": statement_months.rank_name(st), "work_run": st.get("work_run"),
                     "replaced_by": res.replaced[sid].new if sid in res.replaced else None,
                     "replaces": sorted(old for old, rep in res.replaced.items() if rep.new == sid), "conflicts": conflicts})
    return {"scope": sc, "statements": sorted(rows, key=_in_order)}


def _in_order(row: dict[str, Any]) -> tuple[bool, str, str, str]:
    """167 (review 153 E): the statements by account and then in time; a statement not read yet comes last, by file
    name. They were listed in the order they were added (by file name), so the months of several years interleaved."""
    return (row.get("period_start") is None, row.get("account") or "", row.get("period_start") or "", row["file"])


# --- in a run (the worker asks these through work.package_rule) ----------------------------------------------------------


def after_detection(run: dict[str, Any], item: dict[str, Any], detected: Any) -> list[str] | None:
    """A document of the package goes on to its extraction only when recognised as a bank statement type; anything
    else stops here with a to-do (no extraction, no general facts). Without a detailed type the detection's own to-do
    stands for a bank statement no type pack reads."""
    if not item_kinds.of(item).detected:
        return None
    accepted = set(_conf()["accepted_parents"])
    key = _field(detected.get("detail"), "key")
    if key:
        try:
            parent = typepack.get(key).parent
        except FileNotFoundError:  # no type pack of that name
            parent = None
        return None if parent in accepted else [f"{NOT_A_STATEMENT}:{key}"]
    if detected.get("final_status") != "done":
        return []
    coarse = _field(detected.get("result"), "doc_type") or "unknown"
    return [] if coarse in accepted else [f"{NOT_A_STATEMENT}:{coarse}"]


def after_item(run: dict[str, Any], item: dict[str, Any]) -> list[str]:
    """The saved statement's account and the package's party: another party's account is a to-do. 153 (decision of
    2026-10-13): an account no party holds goes to the package's party only when the live run is approved
    (`after_approval`); until then a payment to it is no transfer between own accounts."""
    st = next((s for s in reconcile_store.statements() if s["id"] == item["item_id"]), None)
    if st is None:
        return []
    key = reconcile.statement_account(st)
    if key.startswith("doc:"):  # no account printed: nothing to assign
        return []
    row = package_scope.stored(run["workpackage_id"])
    if row is None:
        return []
    party_id = row["party_id"]
    owner = parties.resolver().account(key)
    if owner == party_id:
        return []
    if owner:
        return [f"{OTHER_PARTY}:{owner}"]
    return []


def after_approval(run: dict[str, Any]) -> None:
    """153 (decision of 2026-10-13, review A4): the accounts of an approved live run's statements that no party holds
    go to the package's party, each with an event in the package's log (who approved, which run). 174 (plan 170 L2):
    the statements as that run read them; before, the store's latest reading of each, a later one's too."""
    if run["mode"] != "apply":
        return
    row = package_scope.stored(run["workpackage_id"])
    if row is None:
        return
    res = parties.resolver()
    statements = {s["id"]: s for s in reconcile_store.run_statements(run["run_id"])}
    done: set[str] = set()
    actor = run.get("approved_by") or run["actor"]
    for item in work_runs.released_items(run):  # 160-C: not a statement removed before the approval (decision 163 D7)
        st = statements.get(item["item_id"])
        if st is None:
            continue
        key = reconcile.statement_account(st)
        if key.startswith("doc:") or key in done or res.account(key):
            continue
        parties.assign("account", key, str(st.get("account") or key), row["party_id"], actor=actor)
        done.add(key)
        with store.connect() as c:
            work.record_event(c, run["workpackage_id"], "statement_account", actor,
                              {"account": key, "party": row["party_id"], "run_id": run["run_id"]})


def _page(wp_id: str) -> dict[str, Any]:
    return {"statements": package_view(wp_id)}


# --- a workflow's statements step (181, plan 170 L5; until then in `jav/app/workflows.py`) ----------------------------


def workflow_offer(ctx: workflow_steps.StepStart) -> str | None:
    """A workflow's statements step: the folder's or the files' statements of the workflow's party and period that the
    store has not got yet become the step's statement package; nothing new: the step is done without a package. 231
    (C3b5b): the statements maker's workflow offer (`jav/app/document_processing.py`): the bank statements pack's step
    kind wraps the package by its case, notes it on the step and starts its live run within the step's budget."""
    wf = ctx.workflow
    paths = workflow_steps.paths_of(ctx.source)
    found = survey(paths, party_id=wf["party_id"], period_start=wf["period_start"], period_end=wf["period_end"])
    chosen = [s["id"] for s in found["statements"] if s["chosen"]]
    pdfs = [p["path"] for p in found["pdfs"] if p["chosen"]]
    if not chosen and not pdfs:
        ctx.nothing_new(f"no new statement: {len(found['statements'])} statement(s) and {len(found['pdfs'])} PDF(s) "
                        "are in the store or outside the period")
        return None
    return str(create(name=ctx.state["name"], party_id=wf["party_id"], period_start=wf["period_start"],
                      period_end=wf["period_end"], paths=paths, statements=chosen, pdfs=pdfs, actor=wf["actor"],
                      case=False)["workpackage_id"])


def make_for_case(scope: dict[str, Any], name: str, owner: identity.Who | None) -> str | None:
    """231 (C3b2): the statements maker of a process pack's document processing step: the source's statements of the
    case's party and period that the store has not got yet, as the workflow's statements step chooses them; none, no
    package."""
    from jav.app import document_processing

    period = scope["period"]
    paths = document_processing.paths_of(scope[document_processing.SOURCE_PART])
    found = survey(paths, party_id=scope["party"], period_start=period[0], period_end=period[1])
    chosen = [s["id"] for s in found["statements"] if s["chosen"]]
    pdfs = [p["path"] for p in found["pdfs"] if p["chosen"]]
    if not chosen and not pdfs:
        return None
    return create(name=name, party_id=scope["party"], period_start=period[0], period_end=period[1], paths=paths,
                  statements=chosen, pdfs=pdfs, actor=owner or "machine", case=False)["workpackage_id"]


def workflow_estimate(paths: list[Path], *, party_id: str | None, period_start: str, period_end: str) -> dict[str, Any]:
    """The step's items: the statements the code reads (free) and the PDFs no reader knows (`paid`: extracted by AI)."""
    found = survey(paths, party_id=str(party_id), period_start=period_start, period_end=period_end)
    statements = sum(1 for s in found["statements"] if s["chosen"])
    pdfs = sum(1 for p in found["pdfs"] if p["chosen"])
    return {"items": statements + pdfs, "paid": pdfs, "statements": statements, "pdfs": pdfs}


def workflow_repeat_from(wp_id: str) -> dict[str, Any] | None:
    """A repeated statements step's source: the folder its statement package was surveyed from, if still there."""
    try:
        wp = work.get(wp_id)
    except KeyError:
        return None
    return workflow_steps.folder_source(wp, (PLAIN,))




# 181 (plan 170 L5): a statement package's party and period, and the role of the packages that collect bank statements
# (`jav/app/package_scope.py`; registered by the finance domain)
ROLE = "statements"


def own_scope(wp_id: str) -> dict[str, Any]:
    """The package's own scope: its party and period, collecting bank statements."""
    sc = scope(wp_id)
    return {"party_id": sc["party_id"], "period_start": sc["period_start"], "period_end": sc["period_end"], "role": ROLE}


# --- 136 (E4): a plain package of a bank's tabular export's chosen accounts, the statement package's forerunner (185,
# plan G-full-move T1a: until then in `jav/app/work.py`) ---------------------------------------------------------------------


def add_statement_tables(wp_id: str, export: Path, keys: list[str], *, expected_revision: int) -> dict[str, Any]:
    """136 (E4, DECISIONS 136): the chosen accounts of a bank's tabular export as items of the package, one statement
    file per account (`statement_table.derive`), read by code; the accounts not chosen are never written. The export
    itself is not an item, so only the chosen accounts' lines are kept."""
    reading = statement_table.read(Path(export))
    return work.add_items(wp_id, statement_table.derive(reading, keys), kind="statement_table",
                          expected_revision=expected_revision)


def create_from_statement_table(export: Path, keys: list[str], *, name: str, owner: identity.Who | None = None) -> dict[str, Any]:
    """136 (E4): a work package of the chosen accounts of a bank's tabular export, one statement item each
    (`add_statement_tables`); the export's path is the package's source."""
    wp = work.create_workpackage(name=name, source_kind="manual", source_ref=str(export), owner=owner)
    return work.fill_new(wp, lambda: add_statement_tables(wp["id"], export, keys, expected_revision=0))


def take_files(wp_id: str, paths: list[Path], *, expected_revision: int, actor: identity.Who) -> None:
    """204 (R1j): adds files to a statement package the way its survey would tick them (the email routing's adding,
    through the logic pack registry)."""
    found = survey_for(wp_id, paths)
    add(wp_id, paths=list(paths), statements=[s["id"] for s in found["statements"] if s["chosen"]],
        pdfs=[p["path"] for p in found["pdfs"] if p["chosen"]], expected_revision=expected_revision, actor=actor)


def create_with_files(*, name: str, paths: list[Path], scope: dict[str, Any], actor: identity.Who) -> str:
    """204 (R1j): a new statement package of the scope's party and period from files, ticked as its survey would
    tick them; returns its id."""
    found = survey(paths, party_id=scope["party_id"], period_start=scope["period_start"], period_end=scope["period_end"])
    made = create(name=name, party_id=scope["party_id"], period_start=scope["period_start"],
                  period_end=scope["period_end"], paths=list(paths),
                  statements=[s["id"] for s in found["statements"] if s["chosen"]],
                  pdfs=[p["path"] for p in found["pdfs"] if p["chosen"]], actor=actor)
    return made["workpackage_id"]


REFUSAL = "add statements to a statement package through its survey"
# 140: the statement package's rule in a run; 231 (C3b5a): with what the logic pack gave its kind (the page part, its own
# scope, its survey's adding, the email routing's adding and making), for a package that names it in its scope
RULE = work.PackageRule(after_detection=after_detection, after_item=after_item, after_approval=after_approval,
                        page=_page, own_scope=True, add_refusal=REFUSAL, adds="own", take_files=take_files,
                        make_with_files=create_with_files)


__all__ = ["KIND", "NOT_A_STATEMENT", "OTHER_PARTY", "RULE", "StatementPackageError", "add_statement_tables",
           "after_detection", "after_item", "create", "create_from_statement_table", "package_view", "scope", "survey"]
