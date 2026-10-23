"""Approve and release a package (plan 170, L1 = plan 160-E S4; DECISIONS 167, 171).

Plain-language summary: a package is approved and released in one step. "Approve and release" approves every open
live run of the package together (each run records who approved it and when, as before), then writes a released
package version: the package's current result of every approved item, as the downloads (workbook, CSV tables, JSON)
were at that moment. The download of a released version is always those stored files, so it never changes, even if
a label or a rule changes later. The package then reads "released"; after a new item or a new result it reads "partly
released" or "changed since the release" until the next release. A package approved before this version got its first
version recorded afterwards, marked as such (DECISIONS 171).

- `view(wp_id)`: the package's current result per item, its mark, the open live runs, what blocks a release, the
  release state and the released versions.
- `release(wp_id, actor=, expected_mark=, confirm_removed=)`: approves the open live runs and records the next version.
- `version_file(wp_id, version, name)`: a stored file of a released version.
- `backfill()`: the first version of every package approved before (idempotent).
- `result_mark(wp_id)`, `current_workbook(wp_id)`, `unreleased_approval(wp_id, c)` (172): the mark a result table's
  page carries, the current result as a workbook, and whether the next step is Approve and release.
- `release_summary(wp_id)` (181): a released package's state and latest version, for the package's stage bar.

A reconciliation package has no runs; it is approved in its own statement (`reconcile_statement.approve`, plan 170 L3
brings the two together).

186 (plan G-full-move T2d): a logic pack without runs keeps its own approved versions in the same store: each one is
its content as the person approved it (the reconciliation: its statement), the fingerprint the person saw, who approved
it and when, what it locks while it holds, and its files in the state they were made in (approved; earlier once a
person reopened it with a reason). The logic pack decides what it approves, what blocks it and what a lock refuses;
this module numbers and stores the versions and their files (`record_own`, `reopen_own`, `store_own_files`) and reads
them back (`own_versions`, `own_version`, `own_approval`, `active_own`, `own_files`, `own_file`, `own_missing_files`).
The release view of a package lists its released results only, so a logic pack's own versions show in its own page as
before. An older store's own version tables of a logic pack are copied in once (`copy_older_own`, registered by the
logic pack).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from jav import corrections, export, logic_packs, package_result, work, work_runs
from jav.core import activity_kinds, card_numbers, store
from jav.outputs import parts, templates
from jav.core.user_messages import explained
from jav.core.clock import utc_stamp as _now

# 175 (plan 170 E4): the actions this module records in the package log (`jav/core/activity_kinds.py`)
activity_kinds.register_events("package", ("package_release",), __name__)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# The stored files of a version: (name, media type). The names are the download's file name suffixes. 178: a domain's
# own output adds its workbook when it has rows (180: `jav/outputs/parts.py`, the utility cost's `utility_cost.xlsx`).
FILES = (("result.xlsx", XLSX), ("result.json", "application/json"),
         ("documents.csv", "text/csv; charset=utf-8"), ("datapoints.csv", "text/csv; charset=utf-8"),
         ("line_items.csv", "text/csv; charset=utf-8"), ("native_facts.csv", "text/csv; charset=utf-8"))
MEDIA = dict(FILES)


DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def media(name: str) -> str:
    """The media type of a version's stored file (an own output's file is a workbook; 196: a Word document by its
    name)."""
    return DOCX if name.endswith(".docx") else MEDIA.get(name, XLSX)

STATES = ("not_released", "released", "partly_released", "changed_since_release")
# 186: the state a version's file was made in: a package's release; a logic pack's own version while it holds, and
# again once reopened (its heading then names it an earlier version)
RELEASED, APPROVED, EARLIER = "released", "approved", "earlier"

store.register_schema("package_release", """
-- 171 (plan 170 L1): a released version of a package: what was released, from which run, by whom and when
CREATE TABLE IF NOT EXISTS package_versions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    workpackage_id TEXT NOT NULL,
    version        INTEGER NOT NULL,
    mark           TEXT NOT NULL,      -- the package result's mark when released (`result_mark`); 186: a logic pack's
                                       -- own version: the fingerprint of the content the person approved
    items          TEXT NOT NULL,      -- JSON: [[item_id, run_id], ...]: each released item and the run it came from
    runs           TEXT NOT NULL,      -- JSON: the live runs this release approved (none for a version recorded afterwards)
    released_by    TEXT NOT NULL,
    released_at    TEXT NOT NULL,
    backfilled_at  TEXT,               -- DECISIONS 171: recorded afterwards for a package approved before v1.20.0
    content        TEXT,               -- 186: JSON, a logic pack's own version's content; NULL: a package's release
    locks          TEXT,               -- 186: JSON, what a logic pack's own version locks while it is not reopened
    reopened_by    TEXT,               -- 186: a logic pack's own version reopened, by whom, when and why
    reopened_at    TEXT,
    reopen_note    TEXT,
    UNIQUE (workpackage_id, version)
);
-- the downloads of a version as they were released (never rebuilt); 186: in the state they were made in
CREATE TABLE IF NOT EXISTS package_version_files (
    version_id       INTEGER NOT NULL,
    state            TEXT NOT NULL DEFAULT 'released',  -- 186: released; a logic pack's own version: approved, earlier
    name             TEXT NOT NULL,    -- result.xlsx, result.json, documents.csv, datapoints.csv, line_items.csv, native_facts.csv
    media            TEXT NOT NULL,
    rows             INTEGER NOT NULL,
    sha256           TEXT NOT NULL,
    content          BLOB NOT NULL,
    template         TEXT,             -- 178: the template that made a workbook (NULL: none, or the built-in before 178)
    template_version TEXT,
    created_at       TEXT,             -- 186: when a logic pack's own version's file was made
    backfilled_at    TEXT,             -- 186: made afterwards for a version approved before its file was stored (178)
    PRIMARY KEY (version_id, state, name)
);
""")

_VERSION_COLUMNS = ("content", "locks", "reopened_by", "reopened_at", "reopen_note")
# 186: the files table as this version makes it, for the rebuild of an older one (`_file_states`)
_FILES_186 = """CREATE TABLE package_version_files_186 (
    version_id INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'released', name TEXT NOT NULL, media TEXT NOT NULL,
    rows INTEGER NOT NULL, sha256 TEXT NOT NULL, content BLOB NOT NULL, template TEXT, template_version TEXT,
    created_at TEXT, backfilled_at TEXT, PRIMARY KEY (version_id, state, name))"""


def _file_states(conn: sqlite3.Connection) -> None:
    """186: an older store's files table (171-185) is rebuilt with each file's state in its key, its rows kept as
    released files; in one write transaction checked again inside it, so two processes starting at once rebuild it
    once."""
    def older() -> bool:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(package_version_files)")}
        return bool(cols) and "state" not in cols

    if not older():
        return
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        if older():
            conn.execute("DROP TABLE IF EXISTS package_version_files_186")
            conn.execute(_FILES_186)
            conn.execute("INSERT INTO package_version_files_186(version_id, state, name, media, rows, sha256, content, template,"
                         " template_version) SELECT version_id, 'released', name, media, rows, sha256, content, template,"
                         " template_version FROM package_version_files")
            conn.execute("DROP TABLE package_version_files")
            conn.execute("ALTER TABLE package_version_files_186 RENAME TO package_version_files")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _migrate(conn: sqlite3.Connection) -> None:
    """178 (plan 170 L4): which template made a workbook of a version (NULL: a file no template makes, or a version
    released before 178 - the built-in template). 186: a logic pack's own versions, and the files' state."""
    store.add_columns(conn, "package_version_files", {"template": "TEXT", "template_version": "TEXT"})
    store.add_columns(conn, "package_versions", dict.fromkeys(_VERSION_COLUMNS, "TEXT"))
    _file_states(conn)


store.register_migration("package_release", _migrate)


class ReleaseError(ValueError):
    """The package cannot be released this way (a reconciliation package, nothing new to release)."""


# --- the package's result and its mark ---------------------------------------------------------------------------

def _releasable(wp: dict[str, Any], counted: dict[str, package_result.Counted],
                runs: dict[str, dict[str, Any]]) -> dict[str, str]:
    """The items whose counted result is an approved live run's released item: item -> run."""
    out = {}
    for item in wp["items"]:
        best = counted.get(item["item_id"])
        if best is None or best.tier != "approved":
            continue
        if item["item_id"] in set(work_runs.excluded_items(runs[best.run_id])):  # removed before that run's approval
            continue
        out[item["item_id"]] = best.run_id
    return out


def _mark(wp: dict[str, Any], counted: dict[str, package_result.Counted], versions: dict[str, str]) -> str:
    """What a person sees of the package's result: each item in use with the run, tier and reviewed version of its
    counted result (a pending item with none). A changed correction, a new run or a new item changes it."""
    parts = sorted([i["item_id"], *((c.run_id, c.tier, versions[c.run_id]) if (c := counted.get(i["item_id"])) else ())]
                   for i in wp["items"])
    return hashlib.sha256(json.dumps(parts).encode("utf-8")).hexdigest()[:16]


def _versions(wp_id: str, c: sqlite3.Connection) -> list[dict[str, Any]]:
    """The package's released versions, the latest first (186: not a logic pack's own versions)."""
    rows = c.execute("SELECT * FROM package_versions WHERE workpackage_id=? AND content IS NULL ORDER BY version DESC",
                     (wp_id,)).fetchall()
    out = []
    for r in rows:
        files = [dict(f) for f in c.execute("SELECT name, media, rows, sha256, template, template_version FROM package_version_files"
                                            " WHERE version_id=? AND state=? ORDER BY name", (r["id"], RELEASED))]
        out.append({"version": r["version"], "mark": r["mark"], "items": [tuple(x) for x in json.loads(r["items"])],
                    "runs": json.loads(r["runs"]), "released_by": r["released_by"], "released_at": r["released_at"],
                    "backfilled_at": r["backfilled_at"], "files": files})
    return out


def _state(latest: dict[str, Any] | None, releasable: dict[str, str], in_use: set[str]) -> str:
    if latest is None:
        return "not_released"
    released = dict(latest["items"])
    if any(item not in in_use or releasable.get(item) != run for item, run in released.items()):
        return "changed_since_release"
    return "partly_released" if in_use - set(released) else "released"


def view(wp_id: str) -> dict[str, Any]:
    """The package's current result and its release: per item the counted result (tier, run, final status, whether the
    latest version holds it), the mark, the open live runs with what blocks them, the state and the versions."""
    wp = work.get(wp_id)
    has_runs = logic_packs.has_runs(wp["source_kind"])  # 176: a logic pack without runs is approved its own way
    with store.session(), store.connect() as c:
        counted = package_result.counted_results(wp_id, c)
        runs = {rid: work_runs.get_run(rid) for rid in sorted({x.run_id for x in counted.values()})}
        reviewed = {rid: corrections.review_version(rid, c) for rid in runs}
        open_runs = work_runs.open_live_runs(wp_id) if has_runs else []
        versions = _versions(wp_id, c)
    releasable = _releasable(wp, counted, runs)
    latest = versions[0] if versions else None
    released = dict(latest["items"]) if latest else {}
    in_use = {i["item_id"] for i in wp["items"]}
    blockers = []
    removed = 0
    for rid in open_runs:
        run = work_runs.get_run(rid)
        if run["status"] != "done":  # kept current when a to-do is settled (`work_runs.resolve_reason`)
            blockers.append({"code": "run_not_ready", "run_id": rid, "status": run["status"],
                             "open_reasons": work_runs.open_reasons_for_run(rid)})
        removed += len(work_runs.excluded_items(run))
    if not has_runs:
        blockers.append({"code": "own_approval"})
    elif not open_runs and (not releasable or releasable == released):
        blockers.append({"code": "nothing_to_release"})
    items = [{"item_id": i["item_id"], "kind": i.get("kind"), "file": Path(i["source_path"]).name,
              "tier": (x := counted.get(i["item_id"])) and x.tier, "run_id": x.run_id if x else None,
              "final_status": x.final_status if x else None,
              "released": released.get(i["item_id"]) == (x.run_id if x else None) and i["item_id"] in released}
             for i in wp["items"]]
    return {"workpackage_id": wp_id, "items": items, "mark": _mark(wp, counted, reviewed),
            "open_live_runs": open_runs, "reviewed": {rid: reviewed[rid] for rid in open_runs if rid in reviewed},
            "removed_items": removed, "blockers": blockers,
            "state": _state(latest, releasable, in_use), "versions": versions}


def release_summary(wp_id: str) -> dict[str, Any] | None:
    """181: a released package's release state and latest version, for its page's stage bar (a trial run after a
    release no longer reads as only a trial result there); None for a package never released (one query then)."""
    with store.connect() as c:
        if c.execute("SELECT 1 FROM package_versions WHERE workpackage_id=? AND content IS NULL LIMIT 1",
                     (wp_id,)).fetchone() is None:
            return None
    current = view(wp_id)
    return {"state": current["state"], "version": current["versions"][0]["version"]}


# --- rendering a version -----------------------------------------------------------------------------------------

def _records(released: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """The documents, each item kind's part (185: by its name; the emails) and native results of the released items,
    each from the run it came from."""
    from jav import datasets

    by_run: dict[str, set[str]] = {}
    for item, run_id in released.items():
        by_run.setdefault(run_id, set()).add(item)
    records: list[dict[str, Any]] = []
    rows: dict[str, list[dict[str, Any]]] = {part.name: [] for part in parts.item_parts()}
    native: list[dict[str, Any]] = []
    for run_id, items in sorted(by_run.items()):
        records += [r for r in datasets.run_records(run_id) if r["item_id"] in items]
        for part in parts.item_parts():
            rows[part.name] += [m for m in part.read(run_id) if m["item_id"] in items]
        native += [n for n in export.native_records(run_id) if n["item_id"] in items]

    def order(r: dict[str, Any]) -> tuple[str, str]:
        return (str(r.get("file") or r.get("subject") or ""), r["item_id"])

    return (sorted(records, key=order), {name: sorted(found, key=order) for name, found in rows.items()},
            sorted(native, key=order))


def _files(wp: dict[str, Any], meta: dict[str, Any], released: dict[str, str]) -> list[tuple[str, int, bytes, dict[str, str] | None]]:
    """(name, rows, content, the template that made it) of every download of the version: the workbooks with the
    package's chosen templates (178), a domain's own output only when it says so (the utility cost's when the package
    has utility bills; its row count is its first table's)."""
    records, items, native = _records(released)
    values = export.package_values(wp, meta)
    result, made = templates.render(export.result_data(records, items, native, values), wp["id"])
    count = len(records) + sum(len(found) for found in items.values()) + len(native)
    files: list[tuple[str, int, bytes, dict[str, str] | None]] = [("result.xlsx", count, result, made)]
    for own in parts.own_outputs():
        data = own.data(records, values)
        if own.stored(data):
            content, made = templates.render(data, wp["id"])
            files.append((own.file, len(data.tables[0].rows), content, made))
    runs = {}
    for run_id in sorted(set(released.values())):
        run = work_runs.get_run(run_id)
        runs[run_id] = {k: run.get(k) for k in ("recipe_id", "recipe_version", "params", "mode", "approval",
                                                  "approved_by", "approved_at")}
        runs[run_id]["review_version"] = corrections.review_version(run_id)
    body = {"workpackage_id": wp["id"], "name": wp["name"], **meta,
            "items": [{"item_id": item, "run_id": run} for item, run in sorted(released.items())], "runs": runs,
            "documents": [{k: v for k, v in r.items() if k != "kinds"} for r in records],
            **{part.json_key: items[part.name] for part in parts.item_parts()},  # 185: the emails
            **export.json_parts(records)}
    if native:
        body["native_items"] = native
    body = card_numbers.mask_values(body)
    files.append(("result.json", count,
                  json.dumps(body, ensure_ascii=False, indent=1, default=str).encode("utf-8"), None))
    for table in ("documents", "datapoints", "line_items"):
        head, rows = export.TABLES[table](records)
        files.append((f"{table}.csv", len(rows), export.csv_bytes(head, rows), None))
    head, rows = export.native_facts_table(native)
    files.append(("native_facts.csv", len(rows), export.csv_bytes(head, rows), None))
    return files


def _next_version(wp_id: str) -> int:
    with store.connect() as c:
        return (c.execute("SELECT MAX(version) FROM package_versions WHERE workpackage_id=?", (wp_id,)).fetchone()[0] or 0) + 1


def _insert(wp: dict[str, Any], *, n: int, mark: str, released: dict[str, str], runs: list[str], actor: str, at: str,
            backfilled_at: str | None, files: list[tuple[str, int, bytes, dict[str, str] | None]], c: sqlite3.Connection) -> int:
    """Records version `n` with its rendered files, in the caller's write transaction; `RevisionConflict` if another
    version took the number meanwhile."""
    latest = c.execute("SELECT MAX(version) FROM package_versions WHERE workpackage_id=?", (wp["id"],)).fetchone()[0] or 0
    if latest + 1 != n:
        raise explained(work.RevisionConflict, "another version of the package was released meanwhile; reload it")
    cur = c.execute("INSERT INTO package_versions(workpackage_id, version, mark, items, runs, released_by, released_at,"
                    " backfilled_at) VALUES (?,?,?,?,?,?,?,?)",
                    (wp["id"], n, mark, json.dumps(sorted(released.items())), json.dumps(runs), actor, at, backfilled_at))
    for name, rows, content, made in files:
        c.execute("INSERT INTO package_version_files(version_id, name, media, rows, sha256, content, template, template_version)"
                  " VALUES (?,?,?,?,?,?,?,?)", (cur.lastrowid, name, media(name), rows, hashlib.sha256(content).hexdigest(), content,
                                                (made or {}).get("template"), (made or {}).get("template_version")))
    return n


# --- the release -------------------------------------------------------------------------------------------------

def release(wp_id: str, *, actor: str, expected_mark: str, confirm_removed: int | None = None) -> dict[str, Any]:
    """Approves the package's open live runs and records its next released version.

    `expected_mark`: the mark of the result the person saw (`view`); a different one is `RevisionConflict`. Every open
    live run must be finished without open to-dos (`work.NotReady` otherwise, before any approval). Items removed from
    the package since a run started are left out, and the person confirms their count (`confirm_removed`), as for a
    run's approval. Each run is approved in its own transaction (`work_runs.approve_run`, with the reviewed version shown):
    if a later one fails, the earlier ones stay approved and no version is recorded; the next view shows it."""
    current = view(wp_id)
    wp = work.get(wp_id)
    if (pack := logic_packs.of(wp["source_kind"])) is not None and not pack.has_runs:
        raise pack.release_refusal()  # 176: the logic pack says why (a reconciliation: in its own statement)
    if expected_mark != current["mark"]:
        raise explained(work.RevisionConflict, "the package's result changed since it was shown; reload it and check it again")
    if waiting := [b for b in current["blockers"] if b["code"] == "run_not_ready"]:
        raise explained(work.NotReady, "a live run of the package is not ready for approval",
                        [{"code": "run_not_ready", "message": b["run_id"]} for b in waiting])
    if current["removed_items"] and confirm_removed != current["removed_items"]:
        raise explained(work.NotReady, "{{removed}} of the runs' items were removed from the package; their results are not released. Confirm the count to release the rest.",
                        [{"code": "removed_items", "message": "Items were removed from the package after the run started",
                          "count": str(current["removed_items"])}], removed=current["removed_items"])
    approved = []
    for rid in current["open_live_runs"]:
        run = work_runs.get_run(rid)
        work_runs.approve_run(rid, actor=actor, review_version=current["reviewed"].get(rid),
                         confirm_removed=len(work_runs.excluded_items(run)) or None)
        approved.append(rid)
    wp = work.get(wp_id)
    with store.session():
        mark, releasable, versions = _result(wp)
        if not releasable or (versions and dict(versions[0]["items"]) == releasable and not approved):
            raise explained(ReleaseError, "the package has nothing new to release")
        n, at = _next_version(wp_id), _now()
        files = _files(wp, {"version": n, "released_by": actor, "released_at": at, "backfilled_at": None}, releasable)
    with store.connect() as c:
        store.begin_immediate(c)
        if _result(wp, c)[0] != mark:  # a correction, a run or an item changed while the files were made
            raise explained(work.RevisionConflict, "the package's result changed during the release; release it again")
        _insert(wp, n=n, mark=mark, released=releasable, runs=approved, actor=actor, at=at, backfilled_at=None,
                files=files, c=c)
        work.record_event(c, wp_id, "package_release", actor, {"version": n, "items": len(releasable), "runs": approved})
    return next(v for v in view(wp_id)["versions"] if v["version"] == n)


def result_mark(wp_id: str) -> str:
    """172: the mark of the package's current result now (a page of the package's result table carries it, so Approve
    and release names the result the person saw)."""
    return _result(work.get(wp_id))[0]


def current_workbook(wp_id: str) -> tuple[bytes, str]:
    """172: (content, file name) of the package's current result as a workbook: each item in use from its counted run,
    written as a released version's workbook is (an item of a trial too; only a release stores it)."""
    wp = work.get(wp_id)
    with store.session():
        current = {item: x.run_id for item, x in package_result.in_use(wp).items()}
        records, items, native = _records(current)
        content, _made = templates.render(export.result_data(records, items, native, export.package_values(wp)), wp_id)
    return content, f"{wp_id}-result-{datetime.now().strftime('%Y%m%d-%H%M')}.xlsx"


def current_output_workbook(wp_id: str, output: str) -> tuple[bytes, str]:
    """178 (DECISIONS 178): (content, file name) of a domain's own output of the package's current result (the utility
    cost), with the package's chosen template. `parts.UnknownOutput` for an output no domain registered."""
    own = parts.own_output(output)
    wp = work.get(wp_id)
    with store.session():
        current = {item: x.run_id for item, x in package_result.in_use(wp).items()}
        records, _mails, _native = _records(current)
        content, _made = templates.render(own.data(records, export.package_values(wp)), wp_id)
    return content, f"{wp_id}-{own.slug}-{datetime.now().strftime('%Y%m%d-%H%M')}.xlsx"


def unreleased_approval(wp_id: str, c: sqlite3.Connection) -> bool:
    """172: whether a live run of the package was approved after its latest released version (or with none), as when
    a run was approved the way before v1.20.0 or a release stopped after its approvals: the package's next step is
    then Approve and release. A release records its version after the approvals, and a version recorded afterwards
    carries the latest approval's time, so neither reads as unreleased."""
    approved = c.execute("SELECT MAX(approved_at) FROM runs WHERE workpackage_id=? AND mode='apply' AND approval='approved'",
                         (wp_id,)).fetchone()[0]
    if approved is None:
        return False
    # a connection opened before this module was imported may not have the table yet: no version then
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='package_versions'").fetchone() is None:
        return True
    released = c.execute("SELECT MAX(released_at) FROM package_versions WHERE workpackage_id=?", (wp_id,)).fetchone()[0]
    return released is None or approved > released


def _result(wp: dict[str, Any], c: sqlite3.Connection | None = None) -> tuple[str, dict[str, str], list[dict[str, Any]]]:
    """(mark, releasable items, versions) of the package now."""
    if c is None:
        with store.connect() as own:
            return _result(wp, own)
    counted = package_result.counted_results(wp["id"], c)
    runs = {rid: work_runs.get_run(rid) for rid in sorted({x.run_id for x in counted.values()})}
    mark = _mark(wp, counted, {rid: corrections.review_version(rid, c) for rid in runs})
    return mark, _releasable(wp, counted, runs), _versions(wp["id"], c)


def version_file(wp_id: str, version: int, name: str) -> tuple[bytes, str, str]:
    """(content, media type, file name) of a released version's stored download; KeyError if there is none."""
    with store.connect() as c:
        row = c.execute("SELECT f.content, f.media FROM package_version_files f JOIN package_versions v ON v.id=f.version_id"
                        " WHERE v.workpackage_id=? AND v.version=? AND f.state=? AND f.name=?",
                        (wp_id, version, RELEASED, name)).fetchone()
    if row is None:
        raise KeyError(f"{wp_id} version {version} {name}")
    return bytes(row["content"]), row["media"], f"{wp_id}-v{version}-{name}"


# --- 186 (plan G-full-move T2d): a logic pack's own versions ------------------------------------------------------------

_OWN_META = ("version", "fingerprint", "approved_by", "approved_at", "reopened_by", "reopened_at", "reopen_note")
_OWN_SELECT = ("SELECT id, workpackage_id, version, mark AS fingerprint, released_by AS approved_by,"
               " released_at AS approved_at, reopened_by, reopened_at, reopen_note, content, locks FROM package_versions")
_FILE_COLUMNS_OWN = ("version_id, state, name, media, rows, sha256, content, template, template_version, created_at,"
                     " backfilled_at")


def _own_meta(row: Any) -> dict[str, Any]:
    return {k: row[k] for k in _OWN_META}


def _connected(c: sqlite3.Connection | None, fn: Any) -> Any:
    if c is None:
        with store.connect() as own:
            return fn(own)
    return fn(c)


def own_versions(wp_id: str, c: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    """A logic pack's own versions of the package, the latest first: {version, fingerprint, approved_by, approved_at,
    reopened_by, reopened_at, reopen_note}."""
    return _connected(c, lambda conn: [_own_meta(r) for r in conn.execute(
        _OWN_SELECT + " WHERE workpackage_id=? AND content IS NOT NULL ORDER BY version DESC", (wp_id,))])


def own_version(wp_id: str, n: int, c: sqlite3.Connection | None = None) -> dict[str, Any]:
    """A logic pack's own version `n` of the package with its `content` as approved (KeyError: no such version)."""
    row = _connected(c, lambda conn: conn.execute(
        _OWN_SELECT + " WHERE workpackage_id=? AND version=? AND content IS NOT NULL", (wp_id, n)).fetchone())
    if row is None:
        raise KeyError(f"{wp_id} version {n}")
    return {"content": json.loads(row["content"]), **_own_meta(row)}


def own_approval(wp_id: str, c: sqlite3.Connection | None = None) -> dict[str, Any]:
    """A logic pack's approval of its package (192: one view for the reconciliation and the quote): its active version
    (None while it has none) and every version, the latest first."""
    versions = own_versions(wp_id, c)
    return {"active": next((v for v in versions if v["reopened_at"] is None), None), "versions": versions}


def active_own(c: sqlite3.Connection | None = None) -> dict[str, dict[str, Any]]:
    """The logic packs' own versions not reopened, per package, with what each locks (`locks`)."""
    return _connected(c, lambda conn: {r["workpackage_id"]: {**_own_meta(r), "locks": json.loads(r["locks"] or "[]")}
                                       for r in conn.execute(_OWN_SELECT + " WHERE content IS NOT NULL AND reopened_at IS NULL"
                                                             " ORDER BY id")})


def record_own(c: sqlite3.Connection, wp_id: str, *, content: dict[str, Any], fingerprint: str, locks: list[str],
               actor: str) -> int:
    """Records the package's next own version, in the caller's write transaction (its checks, files and log entry go
    with it): the content as the person approved it, its fingerprint and what it locks. Returns its number."""
    n = (c.execute("SELECT MAX(version) FROM package_versions WHERE workpackage_id=?", (wp_id,)).fetchone()[0] or 0) + 1
    c.execute("INSERT INTO package_versions(workpackage_id, version, mark, items, runs, released_by, released_at, content,"
              " locks) VALUES (?,?,?,?,?,?,?,?,?)", (wp_id, n, fingerprint, "[]", "[]", actor, _now(),
                                                     json.dumps(content, ensure_ascii=False, default=str), json.dumps(locks)))
    return n


def reopen_own(c: sqlite3.Connection, wp_id: str, *, note: str, actor: str) -> int | None:
    """Reopens the package's own version that holds, in the caller's write transaction: its lock goes, it stays as an
    earlier version. Returns its number; None when no version holds."""
    row = c.execute("SELECT id, version FROM package_versions WHERE workpackage_id=? AND content IS NOT NULL"
                    " AND reopened_at IS NULL", (wp_id,)).fetchone()
    if row is None:
        return None
    c.execute("UPDATE package_versions SET reopened_by=?, reopened_at=?, reopen_note=? WHERE id=?",
              (actor, _now(), note, row["id"]))
    return row["version"]


def store_own_files(c: sqlite3.Connection, wp_id: str, n: int, state: str,
                    files: list[tuple[str, int, bytes, dict[str, str]]], *, backfilled_at: str | None = None) -> None:
    """Records the files (name, rows, content, the template that made it) of the package's own version `n` in its
    `state` (approved or earlier), in the caller's write transaction."""
    version_id = c.execute("SELECT id FROM package_versions WHERE workpackage_id=? AND version=?", (wp_id, n)).fetchone()["id"]
    for name, rows, content, made in files:
        c.execute("INSERT INTO package_version_files(version_id, state, name, media, rows, sha256, content, template,"
                  " template_version, created_at, backfilled_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (version_id, state, name, media(name), rows, hashlib.sha256(content).hexdigest(), content, made["template"],
                   made["template_version"], _now(), backfilled_at))


_OWN_FILES = ("SELECT f.state, f.name, f.template, f.template_version, f.sha256, f.created_at, f.backfilled_at, f.content"
              " FROM package_version_files f JOIN package_versions v ON v.id = f.version_id"
              " WHERE v.workpackage_id=? AND v.version=? AND v.content IS NOT NULL")


def own_files(wp_id: str, n: int, c: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    """The stored files of the package's own version `n` (without their content), in the order they were recorded."""
    return _connected(c, lambda conn: [{k: r[k] for k in r.keys() if k != "content"} for r in conn.execute(
        _OWN_FILES + " ORDER BY f.created_at, f.rowid", (wp_id, n))])


def own_file(wp_id: str, n: int, state: str, c: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """The stored file of the package's own version `n` in its `state` ({name, content, template, template_version,
    ...}); None when it has none (a version approved before its file was stored, 178)."""
    row = _connected(c, lambda conn: conn.execute(_OWN_FILES + " AND f.state=? ORDER BY f.rowid LIMIT 1",
                                                  (wp_id, n, state)).fetchone())
    return None if row is None else {**dict(row), "content": bytes(row["content"])}


def own_missing_files(c: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    """Every own version without a file of its current state (approved while it holds, earlier once reopened), in the
    order of the packages and the versions: {workpackage_id, version, state}."""
    rows = _connected(c, lambda conn: conn.execute(
        "SELECT v.workpackage_id, v.version, CASE WHEN v.reopened_at IS NULL THEN ? ELSE ? END AS state FROM package_versions v"
        " WHERE v.content IS NOT NULL AND NOT EXISTS (SELECT 1 FROM package_version_files f WHERE f.version_id = v.id"
        " AND f.state = (CASE WHEN v.reopened_at IS NULL THEN ? ELSE ? END)) ORDER BY v.workpackage_id, v.version",
        (APPROVED, EARLIER, APPROVED, EARLIER)).fetchall())
    return [dict(r) for r in rows]


def copy_older_own(conn: sqlite3.Connection, versions: str, files: str) -> None:
    """186: an older store's own version tables of a logic pack (145-185: its `versions` with `fingerprint` and the
    `line_ids` it locks, and their `files` with their state), copied into the shared ones once, in one write transaction
    checked again inside it; each file keeps its bytes, its template and its times. The older tables keep their rows,
    read by nothing (left for one release). Registered by the logic pack's module as one of its migrations."""
    key = f"version_copy:{versions}"

    def pending() -> bool:
        if conn.execute("SELECT 1 FROM meta WHERE key=?", (key,)).fetchone() is not None:
            return False
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (versions,)).fetchone() is not None

    if not pending():
        return
    _migrate(conn)
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        if pending():
            has_files = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (files,)).fetchone()
            for v in conn.execute(f"SELECT * FROM {versions} ORDER BY id").fetchall():
                cur = conn.execute("INSERT INTO package_versions(workpackage_id, version, mark, items, runs, released_by,"
                                   " released_at, content, locks, reopened_by, reopened_at, reopen_note)"
                                   " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                   (v["workpackage_id"], v["version"], v["fingerprint"], "[]", "[]", v["approved_by"],
                                    v["approved_at"], v["content"], v["line_ids"], v["reopened_by"], v["reopened_at"],
                                    v["reopen_note"]))
                if not has_files:
                    continue
                for f in conn.execute(f"SELECT * FROM {files} WHERE version_id=? ORDER BY rowid", (v["id"],)).fetchall():
                    conn.execute(f"INSERT INTO package_version_files({_FILE_COLUMNS_OWN}) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                 (cur.lastrowid, f["state"], f["name"], media(f["name"]), 0, f["sha256"], f["content"],
                                  f["template"], f["template_version"], f["created_at"], f["backfilled_at"]))
            conn.execute("INSERT INTO meta(key, value) VALUES (?, ?)", (key, _now()))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise



# --- the first version of a package approved before ----------------------------------------------------------------

def backfill(*, dry_run: bool = False) -> list[dict[str, Any]]:
    """DECISIONS 171: every package with an approved live run and no released version gets its first version, recorded
    now from its approved results (the downloads as they are today), with the latest approver and approval time and
    the time it was recorded (`backfilled_at`). Idempotent: a package with a version is left as it is."""
    without_runs = logic_packs.kinds_without_runs()  # 176: their logic packs' own approval
    with store.connect() as c:
        ids = [r[0] for r in c.execute(
            "SELECT DISTINCT r.workpackage_id FROM runs r JOIN workpackages w ON w.id=r.workpackage_id"
            " WHERE r.mode='apply' AND r.approval='approved' AND w.source_kind NOT IN (%s)"
            " AND NOT EXISTS (SELECT 1 FROM package_versions v WHERE v.workpackage_id=r.workpackage_id)"
            " ORDER BY r.workpackage_id" % ",".join("?" * len(without_runs)), without_runs)]  # noqa: S608 - placeholders
    out = []
    for wp_id in ids:
        wp = work.get(wp_id)
        with store.session():
            mark, releasable, versions = _result(wp)
            if versions or not releasable:
                continue
            runs = {rid: work_runs.get_run(rid) for rid in set(releasable.values())}
            last = max(runs.values(), key=lambda r: (r["approved_at"] or "", r["run_id"]))
            entry = {"workpackage_id": wp_id, "items": len(releasable), "released_by": last["approved_by"],
                     "released_at": last["approved_at"]}
            if dry_run:
                out.append(entry)
                continue
            at = _now()
            files = _files(wp, {"version": 1, "released_by": last["approved_by"], "released_at": last["approved_at"],
                                "backfilled_at": at}, releasable)
        with store.connect() as c:
            store.begin_immediate(c)
            if _result(wp, c)[0] != mark:
                continue  # changed while its files were made: the next backfill takes it
            entry["version"] = _insert(wp, n=1, mark=mark, released=releasable, runs=[], actor=last["approved_by"],
                                       at=last["approved_at"], backfilled_at=at, files=files, c=c)
        out.append(entry)
    return out
