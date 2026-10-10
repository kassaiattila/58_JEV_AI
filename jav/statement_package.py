"""140 (backlog F-package-kinds K2; DECISIONS 137, 139, 140): the statement package.

A work package of its own kind (`source_kind = 'statements'`) for one own party and a period. Its items are the bank
statements of a folder or of the given files:

- a bank's export read by code (`jav/statement_table.py`): one statement item per account and month, the statement
  file the reader builds (a ledger export with the month's PDF statement as its companion);
- a PDF no export uses as its companion: a document item, processed as any PDF (type recognition, then the extraction
  of the recognised bank statement type, paid within the run's budget).

Before anything is written, a person sees a survey (`survey`): every statement the files hold with its account, month,
checks and source rank, whether the store has it already, which statement it would replace or be replaced by
(`statement_months.resolve` with the store's statements), and whose account it is. The person ticks what goes in
(`create`); the ids are the statement files' fingerprints, so a file changed between the two steps is refused.

In a run, the package's kind adds two rules (`work.PackageRule`, asked by the worker):

- a PDF recognised as anything but a bank statement (the accepted coarse categories are data:
  `configs/statement_tables.json` `package.accepted_parents`) stops after its type is recognised, with a
  `statements:not_a_statement:<type>` to-do: no extraction and no general facts are paid for;
- when a statement is saved, an account no party holds (or one dismissed as no own party's) goes to the package's party
  in a live run (the owner's decision of 2026-10-10, DECISIONS 139), in the package's log; another party's account is a
  `statements:other_party:<party>` to-do and stays where it is.

The same account's same days twice are decided by `jav/statement_months.py` (139), whichever package brought them.

Layer: UI/CLI → **this** (application operation) → `jav.statement_table`, `jav.statement_months`, `jav.parties`,
`jav.reconcile` (business modules) and `jav.work` (the package record and its log). No AI call here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from jav import cfg, parties, reconcile, statement_months, statement_table, store, typepack, work

KIND = "statements"
NOT_A_STATEMENT = "statements:not_a_statement"
OTHER_PARTY = "statements:other_party"
DOC_TYPE = "statement_table"

store.register_schema("statement_package", """
CREATE TABLE IF NOT EXISTS statement_scopes (
    workpackage_id TEXT PRIMARY KEY,
    party_id       TEXT NOT NULL,      -- the own party (jav.parties) whose statements the package holds
    period_start   TEXT NOT NULL,      -- ISO date
    period_end     TEXT NOT NULL,      -- ISO date, inclusive
    revision       INTEGER NOT NULL DEFAULT 1,
    actor          TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
""")
parties.register_reference(
    "statement_package",
    count=lambda c, pid: c.execute("SELECT COUNT(*) FROM statement_scopes WHERE party_id=?", (pid,)).fetchone()[0],
    repoint=lambda c, old, new: c.execute("UPDATE statement_scopes SET party_id=? WHERE party_id=?", (new, old)))


class PackageError(ValueError):
    """A request the statement package refuses (an unknown party, a wrong period, an empty choice, a statement the files
    no longer hold); the interface shows the message (422)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _conf() -> dict[str, Any]:
    return dict(cfg.load(statement_table.CONFIG)["package"])


def _day(value: Any, what: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise PackageError(f"{what}: an ISO date is required") from exc


def _checked(party_id: str, period_start: Any, period_end: Any) -> tuple[dict[str, Any], str, str]:
    try:
        party = parties.get(party_id)
    except KeyError:
        raise PackageError(f"no own party {party_id}") from None
    start, end = _day(period_start, "period_start"), _day(period_end, "period_end")
    if start > end:
        raise PackageError("the period ends before it starts")
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
    found = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"]
    for sub in _companion_folders():
        if (folder / sub).is_dir():
            found += [p for p in (folder / sub).iterdir() if p.is_file() and p.suffix.lower() == ".pdf"]
    return sorted(found, key=lambda p: p.relative_to(folder).as_posix().lower())


def _sources(paths: Iterable[Path]) -> _Found:
    """The exports and the PDFs of a folder or of the given files. A folder's exports are read as a whole (each with its
    companion PDF); the PDFs left are those no export used as its companion. A file no reader knows is listed, not
    dropped."""
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
            pdfs.append(p)
        elif p.suffix.lower() in statement_table.SUFFIXES:
            try:
                out.readings.append(statement_table.read(p))
            except statement_table.StatementTableError as exc:
                out.skipped.append({"file": p.name, "reason": str(exc)})
        else:
            out.skipped.append({"file": p.name, "reason": "neither a statement export nor a PDF"})
    limit = int(cfg.load(statement_table.CONFIG)["limits"]["max_files"])
    if len(pdfs) > limit:
        raise PackageError(f"more than {limit} PDF files")
    companions = {(a.source or {}).get("companion", {}).get("sha256") for r in out.readings for a in r.accounts
                  if (a.source or {}).get("companion")}
    out.pdfs = [p for p in dict.fromkeys(q.resolve() for q in pdfs) if work.sha256_file(p) not in companions]
    return out


def _preview(reading: statement_table.Reading, account: statement_table.Account) -> dict[str, Any]:
    """The statement an export's account would become, in the reconciliation snapshot's shape, checked by the same
    type pack checks as in a run (so its rank is the one it will have)."""
    from jav.validators import run_all

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
    stored = reconcile.statements()
    stored_ids = {s["id"] for s in stored}
    previews = [(r, a, _preview(r, a)) for r in found.readings for a in r.accounts]
    new = {s["id"]: s for _r, _a, s in previews if s["id"] not in stored_ids}
    every = {**{s["id"]: s for s in stored}, **new}
    res = statement_months.resolve(list(every.values()), statement_months.choices())
    files = {**reconcile.file_names(stored_ids), **{s["id"]: (a.source or {}).get("file", r.file_name) for r, a, s in previews}}

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
           pdfs: list[str], actor: str) -> dict[str, Any]:
    """A new statement package of the statements and PDFs a person ticked in the survey of the same files; the creator
    owns it (decision 065). A statement is named by its survey id, so one the files no longer hold is refused, and only
    a PDF the survey listed is taken."""
    party, start, end = _checked(party_id, period_start, period_end)
    found = _sources(paths)
    wanted = set(statements)
    ids = {statement_table.derived_id(r, a): (r, a) for r in found.readings for a in r.accounts}
    if missing := wanted - set(ids):
        raise PackageError(f"{len(missing)} chosen statement(s) are no longer in the files; survey them again")
    listed = {str(p): p for p in found.pdfs}
    picked = []
    for raw in pdfs:
        p = Path(raw).resolve()
        if str(p) not in listed:
            raise PackageError(f"not a PDF of the survey: {p.name}")
        picked.append(p)
    if not wanted and not picked:
        raise PackageError("choose at least one statement or PDF")
    entries: list[tuple[Path, str]] = []
    for r in found.readings:
        keys = [a.key for a in r.accounts if statement_table.derived_id(r, a) in wanted]
        if keys:
            entries += [(p, "statement_table") for p in statement_table.derive(r, keys)]
    entries += [(p, "document") for p in dict.fromkeys(picked)]
    folder = Path(paths[0]).resolve() if len(paths) == 1 and Path(paths[0]).is_dir() else None
    wp = work.create_with_items(name=name, source_kind=KIND, source_ref=str(folder) if folder else None, owner=actor,
                                entries=entries)
    with store.connect() as c:
        store.begin_immediate(c)
        c.execute("INSERT INTO statement_scopes(workpackage_id, party_id, period_start, period_end, revision, actor, updated_at)"
                  " VALUES (?,?,?,?,1,?,?)", (wp["id"], party["id"], start, end, actor, _now()))
        work.record_event(c, wp["id"], "statement_scope", actor, {"party": party["id"], "period": [start, end],
                                                                  "statements": len(wanted), "pdfs": len(picked)})
    return scope(wp["id"])


def _package(wp_id: str) -> dict[str, Any]:
    wp = work.get(wp_id)
    if wp["source_kind"] != KIND:
        raise PackageError("not a statement package")
    return wp


def _scope_row(wp_id: str) -> dict[str, Any] | None:
    with store.connect() as c:
        row = c.execute("SELECT * FROM statement_scopes WHERE workpackage_id=?", (wp_id,)).fetchone()
    return dict(row) if row else None


def scope(wp_id: str) -> dict[str, Any]:
    _package(wp_id)
    row = _scope_row(wp_id)
    if row is None:
        raise KeyError(wp_id)
    names = {p["id"]: p["name"] for p in parties.parties()}
    return {"workpackage_id": wp_id, "party_id": row["party_id"],
            "party": {"id": row["party_id"], "name": names.get(row["party_id"], row["party_id"])},
            "period_start": row["period_start"], "period_end": row["period_end"], "revision": row["revision"],
            "updated_at": row["updated_at"]}


def package_view(wp_id: str) -> dict[str, Any]:
    """The package's scope and each item's statement: valid, replaced (by which), in a conflict a person decides, or
    pending (no statement saved from it yet: not processed, or not a statement)."""
    sc, wp = scope(wp_id), _package(wp_id)
    every = reconcile.statements()
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
    return {"scope": sc, "statements": rows}


# --- in a run (the worker asks these through work.package_rule) ----------------------------------------------------------


def after_detection(run: dict[str, Any], item: dict[str, Any], detected: Any) -> list[str] | None:
    """A document of the package goes on to its extraction only when recognised as a bank statement type; anything
    else stops here with a to-do (no extraction, no general facts). Without a detailed type the detection's own to-do
    stands for a bank statement no type pack reads."""
    if item.get("kind") != "document":
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
    """The saved statement's account and the package's party: an account no party holds goes to the package's party
    in a live run (with an event in the package's log); another party's account is a to-do."""
    st = next((s for s in reconcile.statements() if s["id"] == item["item_id"]), None)
    if st is None:
        return []
    key = reconcile.statement_account(st)
    if key.startswith("doc:"):  # no account printed: nothing to assign
        return []
    row = _scope_row(run["workpackage_id"])
    if row is None:
        return []
    party_id = row["party_id"]
    owner = parties.resolver().account(key)
    if owner == party_id:
        return []
    if owner:
        return [f"{OTHER_PARTY}:{owner}"]
    if run["mode"] == "apply":
        parties.assign("account", key, str(st.get("account") or key), party_id, actor=run["actor"])
        with store.connect() as c:
            work.record_event(c, run["workpackage_id"], "statement_account", run["actor"],
                              {"account": key, "party": party_id, "run_id": run["run_id"]})
    return []


work.register_package_rule(KIND, work.PackageRule(after_detection=after_detection, after_item=after_item))


def _delete_guard(c, wp_id: str) -> None:
    """A statement package is deleted like any package (only without runs); its scope goes with it."""
    c.execute("DELETE FROM statement_scopes WHERE workpackage_id=?", (wp_id,))


work.register_delete_guard(_delete_guard)


__all__ = ["KIND", "NOT_A_STATEMENT", "OTHER_PARTY", "PackageError", "after_detection", "after_item", "create",
           "package_view", "scope", "survey"]
