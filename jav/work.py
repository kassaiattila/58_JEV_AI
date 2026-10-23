"""Work package → recipe → run (040 K1): the framework's business records and rules, independent of the UI.

Terms (docs/GLOSSARY.md): a **work package** is a group of documents from one source, with versioned content; a
**recipe** is a versioned description in `configs/recipes.json`; a **run** is a recipe on the work package's PINNED
input (a content hash per item), in trial (`shadow`) or live (`apply`) mode. The V4 patterns: `businessWorkflowApi.ts`
(assignment with `expected_revision`, readiness with blockers/warnings, idempotent start, approval).

Rules:
- Every change requires `expected_revision`; on a mismatch, `RevisionConflict` (no silent overwrite).
- The run stores a snapshot of the assignment and the input; later changes do not affect it.
- Starting the same package + assignment revision + input + mode again returns the existing run (`deduped`).
- Approval only in live mode, once every item has finished and with no open to-do.
- The run's budget is the recipe's per-item maximum × the item count (`jav.core.calls`, scope = run_id).
- 160-C S3: a run can take only the package's pending items (`scope="pending"`); its input, budget and plan are
  those items' alone, and the earlier runs stay as they are.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jav import item_kinds, logic_packs, source_instances
from jav.core import activity_kinds, store
from jav.documents.native_contracts import DOCUMENT_SUFFIXES
from jav.core.user_messages import explained
from jav.core.clock import utc_stamp as _now
from jav.core.digest import file_sha256 as sha256_file
from jav import work_recipes, work_runs


JOB_KIND = "run_item"


store.register_schema("work", """
CREATE TABLE IF NOT EXISTS workpackages (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    source_kind TEXT NOT NULL,                 -- folder | upload | mailbox | manual | watch | reconcile (131) | statements (140)
    source_ref  TEXT,
    revision    INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workpackage_items (
    workpackage_id TEXT NOT NULL REFERENCES workpackages(id),
    item_id     TEXT NOT NULL,                 -- dokumentumnál a tartalom sha256-a (= documents.doc_id)
    kind        TEXT NOT NULL,                 -- document | email
    source_path TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    added_revision   INTEGER NOT NULL,
    removed_revision INTEGER,
    parent_item_id   TEXT,                     -- 058 K5.2: a levél csatolmányánál a levél tétele (a csatolmány eredete)
    instance    TEXT,                          -- source instance (jav/source_instances.py), relative path; NULL: none
    removed_at  TEXT,                          -- 160-C S1: when, by whom and why the item was removed (NULL: in use)
    removed_by  TEXT,
    removed_reason TEXT,
    PRIMARY KEY (workpackage_id, item_id)
);
CREATE TABLE IF NOT EXISTS recipe_assignments (
    workpackage_id TEXT NOT NULL REFERENCES workpackages(id),
    revision    INTEGER NOT NULL,
    recipe_id   TEXT NOT NULL,
    recipe_version INTEGER NOT NULL,
    recipe_hash TEXT NOT NULL,
    params      TEXT NOT NULL,
    actor       TEXT NOT NULL,
    note        TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (workpackage_id, revision)
);
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    workpackage_id TEXT NOT NULL REFERENCES workpackages(id),
    dedup_key   TEXT UNIQUE NOT NULL,
    mode        TEXT NOT NULL,                 -- shadow | apply
    assignment_revision INTEGER NOT NULL,
    recipe_id   TEXT NOT NULL,
    recipe_version INTEGER NOT NULL,
    recipe_hash TEXT NOT NULL,
    recipe      TEXT NOT NULL,                 -- a recept pillanatképe (JSON)
    params      TEXT NOT NULL,
    input       TEXT NOT NULL,                 -- rögzített bemenet: tételek + hash-ek
    input_hash  TEXT NOT NULL,
    status      TEXT NOT NULL,                 -- queued | running | needs_review | done | failed | cancelled
    approval    TEXT,                          -- NULL | approved
    approved_by TEXT,
    approved_at TEXT,
    actor       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_runs_wp ON runs(workpackage_id, created_at);
-- 204 (R1i): a package's removed items only; the run list leaves their to-dos out (`work_runs.run_rows`), and without it
-- read every item of the package for each open to-do (10.4 s for one run of 10,000 items, 0.014 s with it)
CREATE INDEX IF NOT EXISTS ix_workpackage_items_removed ON workpackage_items(workpackage_id) WHERE removed_revision IS NOT NULL;
-- 058: a csomag elrejtése, visszahozása, átnevezése és törlése (ki, mikor, mit); a törölt csomag nyoma is itt marad
-- 058: a forrásfájl ujjlenyomata méret + módosítási idő szerint megjegyezve (a csomag megnyitása ne hasheljen újra
-- minden fájlt); az indítás és a feldolgozó mindig teljesen ellenőriz
CREATE TABLE IF NOT EXISTS file_fingerprints (
    path        TEXT PRIMARY KEY,
    size        INTEGER NOT NULL,
    mtime_ns    INTEGER NOT NULL,
    sha256      TEXT NOT NULL,
    checked_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workpackage_events (
    workpackage_id TEXT NOT NULL,
    action      TEXT NOT NULL,                 -- archive | restore | rename | delete
    actor       TEXT NOT NULL,
    detail      TEXT,                          -- JSON
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_items (
    run_id      TEXT NOT NULL REFERENCES runs(run_id),
    item_id     TEXT NOT NULL,
    status      TEXT NOT NULL,                 -- done | failed | cancelled
    final_status TEXT,                         -- a folyamat végállapota (done | needs_review | needs_ocr | jev_unavailable ...)
    flow_run_id TEXT,
    error       TEXT,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, item_id)
);
""")


def _migrate(conn) -> None:
    store.add_columns(conn, "workpackage_items", {
        "parent_item_id": "TEXT",  # 058 K5.2: the attachment points to its email
        "instance": "TEXT",  # source instance: the unchanging copy made when the item was added
        # 160-C S1 (decision 163 D2): who removed an item, when and why
        "removed_at": "TEXT", "removed_by": "TEXT", "removed_reason": "TEXT",
    })
    # 061: the person responsible for the package (a name from the name list)
    store.add_columns(conn, "workpackages", {"owner": "TEXT"})
    store.add_columns(conn, "runs", {
        "plan": "TEXT",  # 082: the pre-start overview (`run_plan`), compared with the actual calls
        "stopped_at": "TEXT", "stopped_by": "TEXT",  # 160 (review R-4): a person stopped the run (it ends cancelled)
        "excluded_items": "TEXT",  # 160-C (decision 163 D7): items removed before the approval (JSON)
        "scope": "TEXT",  # 160-C S3: NULL = every item in use, 'pending' = only the pending items
    })
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'").fetchone():
        # 204 (R1i): a run's state without its row, which holds the frozen input (`work_runs.refresh_run_status`): the
        # columns lie after it, so reading one walked the whole input (31 ms in a run of 100,000 items, 0.014 ms here)
        conn.execute("CREATE INDEX IF NOT EXISTS ix_runs_state ON runs(run_id, status, stopped_at, finished_at)")


store.register_migration("work", _migrate)


class RevisionConflict(RuntimeError):
    """The request was based on an earlier revision; the caller should reload the state (in the UI: 409, the working
    copy is kept)."""


class NotReady(RuntimeError):
    def __init__(self, message: str, blockers: list[dict[str, str]] | None = None) -> None:
        super().__init__(message)
        self.blockers = blockers or []


class RetiredRecipe(ValueError):
    """080: the recipe is kept only for old runs and assignments; it cannot be assigned again (in the UI: 422)."""


class SourceChanged(ValueError):
    """167 (review R-7): a document's copy had to be made again while it was added, and the original no longer has
    the content first copied; nothing was added (in the UI: 422)."""


def _pinned_run(c: sqlite3.Connection, run_id: str) -> bool:
    """066 Á06 (decision of 2026-09-29): the to-do reasons of a live run that is not yet approved and not cancelled are
    pinned (another run does not take them over or close them); a trial run's reason is still carried by the latest
    run."""
    row = c.execute("SELECT 1 FROM runs WHERE run_id=? AND mode='apply' AND approval IS NULL AND status<>'cancelled'",
                    (run_id,)).fetchone()
    return row is not None


store.set_pinned_run_check(_pinned_run)


def max_source_bytes() -> int:
    """075: a source larger than the input limit is never read into memory (it could not have been added anyway)."""
    from jav.documents import pdf

    return int(pdf.input_limits().max_document_mb * 1_000_000)


def read_verified(path: Path, sha256: str, *, max_bytes: int) -> bytes:
    """The file's bytes, only if their content hash is still `sha256`: read once and hashed in full, and exactly these
    verified bytes are used (075, repeated security audit S03: a file changed in place, even with the same size and
    modification time, or swapped after the check, cannot pass). `RevisionConflict` if the file changed, disappeared or
    is larger than `max_bytes`. 078: shared by the source view and the content-named copies."""
    conflict = RevisionConflict("the source file changed or disappeared since it was added")
    try:
        if not path.is_file() or path.stat().st_size > max_bytes:
            raise conflict
        data = path.read_bytes()
    except OSError as exc:
        raise conflict from exc
    if hashlib.sha256(data).hexdigest() != sha256:
        raise conflict
    return data


def source_file(item: dict[str, Any]) -> Path:
    """The file an item's bytes are read from: its source instance if it has one, otherwise (an email, or a document
    added before source instances existed) the original path."""
    if item.get("instance"):
        return source_instances.path_of(item["instance"])
    return Path(item["source_path"])


def _instance_ok(item: dict[str, Any], *, verify: bool = False) -> bool:
    try:
        return fingerprint(source_file(item), verify=verify) == item["sha256"]
    except OSError:
        return False


def original_state(item: dict[str, Any], *, verify: bool = False) -> str:
    """The state of the item's original file compared with what was added: `same`, `changed` or `missing` (missing or
    unreadable). By default it uses the size + modification time memo (cheap enough for every package view); with
    `verify=True` (one item's view) the full content hash, so a same-size change with a restored time shows too."""
    try:
        return "same" if fingerprint(Path(item["source_path"]), verify=verify) == item["sha256"] else "changed"
    except OSError:
        return "missing"


def fingerprint(path: Path, *, verify: bool = False) -> str:
    """The file's content hash. `verify=False`: if the size and modification time were the same at the last
    computation, the remembered value (058: opening a package stays fast even with many documents); `verify=True`:
    always a full computation."""
    st = path.stat()
    key = str(path.resolve())
    if not verify:
        with store.connect() as c:
            row = c.execute("SELECT sha256 FROM file_fingerprints WHERE path=? AND size=? AND mtime_ns=?",
                            (key, st.st_size, st.st_mtime_ns)).fetchone()
        if row is not None:
            return row["sha256"]
    digest = sha256_file(path)
    with store.connect() as c:
        c.execute("INSERT INTO file_fingerprints(path, size, mtime_ns, sha256, checked_at) VALUES (?,?,?,?,?) ON CONFLICT(path)"
                  " DO UPDATE SET size=excluded.size, mtime_ns=excluded.mtime_ns, sha256=excluded.sha256, checked_at=excluded.checked_at",
                  (key, st.st_size, st.st_mtime_ns, digest, _now()))
    return digest


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


@store.one_connection
def create_workpackage(*, name: str, source_kind: str, source_ref: str | None, owner: str | None = None) -> dict[str, Any]:
    """`owner` (decision 065): the creator is responsible for the new package; a nameless (automated) creation has no
    owner."""
    if not name.strip():
        raise explained(ValueError, "name required")
    wp_id = f"wp-{uuid.uuid4().hex[:12]}"
    with store.connect() as c:
        c.execute("INSERT INTO workpackages(id, name, source_kind, source_ref, revision, created_at, updated_at, owner) VALUES (?,?,?,?,0,?,?,?)",
                  (wp_id, name.strip(), source_kind, source_ref, _now(), _now(), owner))
    return get(wp_id)


def _bump(c, wp_id: str, expected_revision: int) -> int:
    row = c.execute("SELECT revision FROM workpackages WHERE id=?", (wp_id,)).fetchone()
    if row is None:
        raise KeyError(wp_id)
    if row["revision"] != expected_revision:
        raise explained(RevisionConflict, "workpackage {{wp_id}} is at revision {{revision}}, not {{expected_revision}}",
                        wp_id=wp_id, revision=row["revision"], expected_revision=expected_revision)
    c.execute("UPDATE workpackages SET revision=revision+1, updated_at=? WHERE id=?", (_now(), wp_id))
    return expected_revision + 1


def _begin(c) -> None:
    store.begin_immediate(c)


def packaged_sources(paths: list[Path]) -> set[Path]:
    """063: those of the given files that were ever added to a work package (a removed item counts too). The email
    download uses this to recognise a downloaded email that never made it into a package (e.g. an interrupted
    download)."""
    want = {str(Path(p).resolve()): Path(p) for p in paths}
    keys, found = list(want), set()
    with store.connect() as c:
        for n in range(0, len(keys), 500):  # below SQLite's parameter limit
            chunk = keys[n:n + 500]
            found |= {r["source_path"] for r in c.execute(
                f"SELECT DISTINCT source_path FROM workpackage_items WHERE source_path IN ({','.join('?' * len(chunk))})", chunk)}
    return {want[k] for k in found}


def add_documents(wp_id: str, paths: list[Path], *, expected_revision: int) -> dict[str, Any]:
    """Adds documents in one revision step. A document with identical content appears once; the content hash is pinned
    when it is added."""
    return add_items(wp_id, paths, kind="document", expected_revision=expected_revision)


def add_items(wp_id: str, paths: list[Path], *, kind: str, expected_revision: int,
              parents: dict[Path, str] | None = None) -> dict[str, Any]:
    """Adds items in one revision step (`document`: a document file; `email`: the email's `message.json`, 048 T2;
    `statement_table`: an account's statement file derived from a bank's tabular export, 136).
    The item's identifier is the file's content hash; identical content appears once. `parents` (058 K5.2): the parent
    item's identifier per file — so an email attachment points to its email (the attachment's origin).

    A document is copied into the source instance store as it is added (`jav/source_instances.py`), and its
    fingerprint is that of the copied bytes; an email is hashed in place (it is already the system's own copy). If the
    intake fails, the copies made for it are released again."""
    item_kinds.check([kind])  # 177: the registry knows the kinds (`UnknownItemKind`, a ValueError)
    return add_entries(wp_id, [(Path(p), kind) for p in paths], expected_revision=expected_revision, parents=parents)


def add_entries(wp_id: str, entries: list[tuple[Path, str]], *, expected_revision: int,
                parents: dict[Path, str] | None = None,
                event: tuple[str, str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """`add_items` for items of several kinds in one revision step (140: a statement package holds the statements read
    from exports and the PDF statements together): (path, kind) pairs. `event` (160-C S2): (action, actor, detail)
    written to the package's log in the same transaction. A removed item added again is restored (its removal's who,
    when and why are cleared)."""
    item_kinds.check([kind for _p, kind in entries])
    parents = {Path(k).resolve(): v for k, v in (parents or {}).items()}
    resolved: list[tuple[Path, str, str | None, str]] = []
    made_again: list[str] = []
    try:
        for p, kind in entries:
            p = Path(p).resolve(strict=True)
            if not p.is_file():
                raise explained(ValueError, "not a file: {{p}}", p=p)
            if item_kinds.of(kind).copied:  # 177: a document and a table statement; an email is hashed in place
                resolved.append((*_document_entry(p), kind))
            else:
                resolved.append((p, sha256_file(p), None, kind))
        with store.connect() as c:
            _begin(c)
            rev = _bump(c, wp_id, expected_revision)
            # 167 (review R-7): a shared copy may have been released since it was made (another package deleted, or
            # another intake failed, while no item referred to it yet). `source_instances.release` deletes only under
            # this write lock, so a copy present now stays until these items are recorded.
            for n, (p, digest, instance, kind) in enumerate(resolved):
                if instance and not source_instances.path_of(instance).is_file():
                    resolved[n] = (p, digest, _copy_again(p, digest, made_again), kind)
            for p, digest, instance, kind in resolved:
                c.execute("INSERT INTO workpackage_items(workpackage_id, item_id, kind, source_path, sha256, added_revision, parent_item_id, instance)"
                          " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(workpackage_id, item_id) DO UPDATE SET removed_revision=NULL,"
                          " removed_at=NULL, removed_by=NULL, removed_reason=NULL,"
                          " source_path=excluded.source_path, parent_item_id=COALESCE(workpackage_items.parent_item_id, excluded.parent_item_id),"
                          " instance=COALESCE(workpackage_items.instance, excluded.instance)",
                          (wp_id, digest, kind, str(p), digest, rev, parents.get(p), instance))
            if event is not None:
                _event(c, wp_id, event[0], event[1], event[2])
    except BaseException:
        source_instances.release([i for _p, _d, i, _k in resolved if i] + made_again)
        raise
    return get(wp_id)


def _copy_again(p: Path, digest: str, made: list[str]) -> str:
    """167 (review R-7): the copy of a document being added was released before its item was recorded: it is made
    again from the original, inside the intake's transaction (`made` collects it, for release if the intake fails).
    An original that no longer has the content first copied is refused (`SourceChanged`)."""
    try:
        again, rel = source_instances.freeze(p, max_bytes=max_source_bytes())
    except source_instances.InstanceTooLarge as exc:
        raise explained(SourceChanged, "{{name}} changed while it was being added; add it again", name=p.name) from exc
    made.append(rel)
    if again != digest:
        raise explained(SourceChanged, "{{name}} changed while it was being added; add it again", name=p.name)
    return rel


def _document_entry(p: Path) -> tuple[Path, str, str | None]:
    """(path, fingerprint, source instance) of a document being added. 085 (re-audit A03): a document over the input
    limit is not copied (it could fill the disk before any check); it is added with the fingerprint of the original
    and no instance, and processing stops it with the named size error. The copy also stops at the limit, should the
    file grow while it is copied."""
    limit = max_source_bytes()
    if p.stat().st_size <= limit:
        try:
            return (p, *source_instances.freeze(p, max_bytes=limit))
        except source_instances.InstanceTooLarge:  # it grew past the limit while it was copied: added without a copy
            pass
    return p, sha256_file(p), None


def _addable(wp_id: str) -> dict[str, Any]:
    """160-C S2: a package whose items come from its own survey, or that has none, is added to in its own way (176: its
    logic pack says so)."""
    wp = get(wp_id)
    pack = logic_packs.of(wp["source_kind"])
    if pack is not None and pack.add_refusal:
        raise ValueError(pack.add_refusal)
    return wp


def _held_items(wp_id: str) -> dict[str, int | None]:
    """Every item the package ever held, with its removal revision (None: in use)."""
    with store.connect() as c:
        return {r["item_id"]: r["removed_revision"] for r in c.execute(
            "SELECT item_id, removed_revision FROM workpackage_items WHERE workpackage_id=?", (wp_id,))}


def add_to_package(wp_id: str, paths: list[Path], *, expected_revision: int, actor: str, exclude: Iterable[str] = (),
                   restore: Iterable[str] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """160-C S2: documents a person adds to an existing package, by content: a new one is added, one already in the
    package changes nothing, and a removed one is restored. Only an actual change takes a revision step, and it is
    logged (`items_add`) in the same transaction. Returns the package and what happened, with the names of the
    documents a live run of another package has already processed (a warning: the same file may be counted twice
    later, e.g. by the duplicate check or the reconciliation).

    168 (plan F-item-list-and-adding): what the person unticked in the preview (`preview_additions`) stays out: the
    new documents whose content hash is in `exclude`, and, when `restore` is given, every removed one not in it (the
    preview leaves a removed document unticked, so adding a folder again does not quietly bring back what was taken
    out on purpose). These are counted as `left_out`."""
    wp = _addable(wp_id)
    files = list(dict.fromkeys(Path(p).resolve(strict=True) for p in paths))
    digests = {p: sha256_file(p) for p in files}
    state = _held_items(wp_id)
    skip, back = set(exclude), None if restore is None else set(restore)
    seen: set[str] = set()
    added, restored, already, left_out = [], [], 0, 0
    for p in files:
        d = digests[p]
        if d in seen:
            continue
        seen.add(d)
        if d not in state:
            if d in skip:
                left_out += 1
            else:
                added.append(p)
        elif state[d] is not None:
            if back is None or d in back:
                restored.append(p)
            else:
                left_out += 1
        else:
            already += 1
    summary = {"added": len(added), "already": already, "restored": len(restored), "left_out": left_out}
    changed = added + restored
    if changed:
        wp = add_entries(wp_id, [(p, "document") for p in changed], expected_revision=expected_revision,
                         event=("items_add", actor, summary))
    elsewhere = _processed_live_elsewhere(wp_id, [digests[p] for p in changed])
    return wp, {**summary, "processed_elsewhere": [p.name for p in changed if digests[p] in elsewhere]}


PREVIEW_OTHER_NAMES = 20  # the other files named in a preview; the rest only counted


def preview_additions(wp_id: str, paths: Iterable[Path], *, others: Iterable[Path] = (), root: Path | None = None) -> dict[str, Any]:
    """168 (plan F-item-list-and-adding; the legacy V4 upload page's selection preview): what adding `paths` to the
    package would do, without writing anything. Each document is `new`, `already` in the package, `removed` from it
    (restored only when ticked), or `repeated` (the same content earlier in the selection); `elsewhere` marks one a
    live run of another package has processed. A file that is not a document is left out and named (`others`, with the
    other files of a folder the caller collected). `root`: the folder the files came from (each file's `folder` is its
    subfolder, '' for the folder itself)."""
    _addable(wp_id)
    docs: list[Path] = []
    skipped = list(others)
    for p in dict.fromkeys(Path(x).resolve(strict=True) for x in paths):
        (docs if p.suffix.lower() in DOCUMENT_SUFFIXES else skipped).append(p)
    digests = {p: sha256_file(p) for p in docs}
    state = _held_items(wp_id)
    elsewhere = _processed_live_elsewhere(wp_id, sorted(set(digests.values())))
    base = Path(root).resolve() if root else None
    seen: set[str] = set()
    files = []
    for p in docs:
        d = digests[p]
        kind = "repeated" if d in seen else "new" if d not in state else "already" if state[d] is None else "removed"
        seen.add(d)
        folder = p.parent.relative_to(base).as_posix() if base and p.is_relative_to(base) else str(p.parent)
        files.append({"path": str(p), "name": p.name, "folder": "" if folder == "." else folder, "item_id": d,
                      "state": kind, "elsewhere": d in elsewhere})
    counts = {k: sum(f["state"] == k for f in files) for k in ("new", "already", "removed", "repeated")}
    counts["elsewhere"] = sum(f["elsewhere"] and f["state"] in ("new", "removed") for f in files)
    return {"files": files, "counts": counts, "folder": str(base) if base else None,
            "others": {"count": len(skipped), "names": [Path(p).name for p in skipped[:PREVIEW_OTHER_NAMES]]}}


def _processed_live_elsewhere(wp_id: str, digests: list[str]) -> set[str]:
    """160-C S2: the content hashes among `digests` that a live run of another package has processed (`processed_live`,
    without this package's own runs)."""
    found: set[str] = set()
    with store.connect() as c:
        for i in range(0, len(digests), 500):
            chunk = digests[i:i + 500]
            found |= {r["item_id"] for r in c.execute(
                "SELECT DISTINCT ri.item_id FROM run_items ri JOIN runs r ON r.run_id=ri.run_id WHERE r.mode='apply'"
                f" AND ri.status='done' AND r.workpackage_id<>? AND ri.item_id IN ({','.join('?' * len(chunk))})", (wp_id, *chunk))}
    return found


def remove_item(wp_id: str, item_id: str, *, expected_revision: int, actor: str, reason: str) -> dict[str, Any]:
    """160-C S1 (decision 163 D2, D3): a virtual removal by a named person with a reason, logged. The item stays out
    of the package's next runs; a run already started keeps it in its frozen input, and `restore_item` brings it back."""
    return _remove(wp_id, [item_id], expected_revision=expected_revision, actor=actor, reason=reason,
                   event=("item_remove", {"item_id": item_id}))


def remove_items(wp_id: str, item_ids: Iterable[str], *, expected_revision: int, actor: str, reason: str) -> dict[str, Any]:
    """168 (plan F-item-list-and-adding): several items removed with one reason in one revision step and one log event
    (`items_remove`), e.g. a folder added by mistake. All or nothing: an item not in use (`KeyError`) changes nothing."""
    ids = list(dict.fromkeys(item_ids))
    if not ids:
        raise explained(ValueError, "choose at least one item")
    return _remove(wp_id, ids, expected_revision=expected_revision, actor=actor, reason=reason,
                   event=("items_remove", {"item_ids": ids}))


def _remove(wp_id: str, ids: list[str], *, expected_revision: int, actor: str, reason: str,
            event: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    reason = reason.strip()
    if not reason:
        raise explained(ValueError, "a reason is required to remove an item")
    with store.connect() as c:
        _begin(c)
        rev = _bump(c, wp_id, expected_revision)  # first: a stale page gets a conflict, not "not found"
        in_use = {r["item_id"] for r in c.execute(
            "SELECT item_id FROM workpackage_items WHERE workpackage_id=? AND removed_revision IS NULL", (wp_id,))}
        if missing := [i for i in ids if i not in in_use]:
            raise KeyError(missing[0])
        now = _now()
        c.executemany("UPDATE workpackage_items SET removed_revision=?, removed_at=?, removed_by=?, removed_reason=?"
                      " WHERE workpackage_id=? AND item_id=?", [(rev, now, actor, reason, wp_id, i) for i in ids])
        _event(c, wp_id, event[0], actor, {**event[1], "reason": reason})
    return get(wp_id)


def restore_item(wp_id: str, item_id: str, *, expected_revision: int, actor: str) -> dict[str, Any]:
    """160-C S1 (decision 163 D3): a removed item is back in the package, logged; it takes part in the next run."""
    return _restore(wp_id, [item_id], expected_revision=expected_revision, actor=actor, event=("item_restore", {"item_id": item_id}))


def restore_items(wp_id: str, item_ids: Iterable[str], *, expected_revision: int, actor: str) -> dict[str, Any]:
    """168: several removed items back in the package in one revision step, logged once (`items_restore`)."""
    ids = list(dict.fromkeys(item_ids))
    if not ids:
        raise explained(ValueError, "choose at least one item")
    return _restore(wp_id, ids, expected_revision=expected_revision, actor=actor, event=("items_restore", {"item_ids": ids}))


def _restore(wp_id: str, ids: list[str], *, expected_revision: int, actor: str, event: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    with store.connect() as c:
        _begin(c)
        _bump(c, wp_id, expected_revision)
        removed = {r["item_id"] for r in c.execute(
            "SELECT item_id FROM workpackage_items WHERE workpackage_id=? AND removed_revision IS NOT NULL", (wp_id,))}
        if missing := [i for i in ids if i not in removed]:
            raise KeyError(missing[0])
        c.executemany("UPDATE workpackage_items SET removed_revision=NULL, removed_at=NULL, removed_by=NULL, removed_reason=NULL"
                      " WHERE workpackage_id=? AND item_id=?", [(wp_id, i) for i in ids])
        _event(c, wp_id, event[0], actor, event[1])
    return get(wp_id)


def removed_items(wp_id: str) -> list[dict[str, Any]]:
    """160-C S1: the package's removed items with who removed them, when and why (shown behind a switch)."""
    with store.connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT item_id, kind, source_path, sha256, added_revision, parent_item_id, instance, removed_revision,"
            " removed_at, removed_by, removed_reason FROM workpackage_items WHERE workpackage_id=? AND removed_revision IS NOT NULL"
            " ORDER BY source_path", (wp_id,))]


def folder_documents(folder: Path, *, suffixes: tuple[str, ...] = DOCUMENT_SUFFIXES, recursive: bool = False,
                     exclude: Iterable[Path] = ()) -> list[Path]:
    """The documents of a folder, in path order: by default its direct contents only; with `recursive` (081) every
    subfolder too, except the folders in `exclude` (the caller passes the output folder of the named copies, so they do
    not come back as new documents). A link pointing outside the folder is left out."""
    return folder_contents(folder, suffixes=suffixes, recursive=recursive, exclude=exclude)[0]


def folder_contents(folder: Path, *, suffixes: tuple[str, ...] = DOCUMENT_SUFFIXES, recursive: bool = False,
                    exclude: Iterable[Path] = ()) -> tuple[list[Path], list[Path]]:
    """`folder_documents` and, beside them, the folder's other files under the same rules (168: a preview names what it
    leaves out), each in path order."""
    folder = Path(folder)
    if not folder.is_dir():
        raise explained(ValueError, "folder does not exist: {{folder}}", folder=folder)
    root = folder.resolve(strict=True)
    skip = [Path(p).resolve() for p in exclude]
    found = root.rglob("*") if recursive else root.iterdir()
    files: list[Path] = []
    others: list[Path] = []
    for p in found:
        if not p.is_file():
            continue
        rp = p.resolve()
        inside = rp.parent == root if not recursive else rp.is_relative_to(root)
        if inside and not any(rp.is_relative_to(s) for s in skip):
            (files if p.suffix.lower() in suffixes else others).append(p)
    for paths in (files, others):
        paths.sort(key=lambda p: p.relative_to(root).as_posix().lower())
    return files, others


@store.one_connection
def create_from_folder(folder: Path, *, name: str | None = None, suffixes: tuple[str, ...] = DOCUMENT_SUFFIXES,
                       owner: str | None = None, recursive: bool = False, exclude: Iterable[Path] = (),
                       only: Iterable[Path] | None = None) -> dict[str, Any]:
    """Work package from the documents of a folder (`folder_documents`); with `only` (147) just those of them."""
    files = folder_documents(folder, suffixes=suffixes, recursive=recursive, exclude=exclude)
    if only is not None:
        wanted = {Path(p).resolve() for p in only}
        files = [p for p in files if p.resolve() in wanted]
    root = Path(folder).resolve(strict=True)
    wp = create_workpackage(name=name or root.name, source_kind="folder", source_ref=str(root), owner=owner)
    return fill_new(wp, lambda: add_documents(wp["id"], files, expected_revision=0)) if files else wp


def processed_live(digests: Iterable[str]) -> set[str]:
    """147: the content hashes among `digests` whose document a live run has processed (an item done in an `apply`
    run). A trial run's item or a failed one does not count."""
    wanted = sorted(set(digests))
    found: set[str] = set()
    with store.connect() as c:
        for i in range(0, len(wanted), 500):
            chunk = wanted[i:i + 500]
            found |= {r["item_id"] for r in c.execute(
                "SELECT DISTINCT ri.item_id FROM run_items ri JOIN runs r ON r.run_id=ri.run_id WHERE r.mode='apply'"
                f" AND ri.status='done' AND ri.item_id IN ({','.join('?' * len(chunk))})", chunk)}
    return found


def unprocessed(paths: Iterable[Path]) -> tuple[list[Path], list[Path]]:
    """147: the documents no live run has processed yet, and those one has (by content), each in the given order."""
    paths = list(paths)
    digests = {p: fingerprint(p) for p in paths}
    seen = processed_live(digests.values())
    return [p for p in paths if digests[p] not in seen], [p for p in paths if digests[p] in seen]


def create_from_files(paths: list[Path], *, name: str, owner: str | None = None) -> dict[str, Any]:
    """Work package from the given files (possibly from several folders), in one revision step (040 K3: live trial,
    selection in the UI)."""
    if not paths:
        raise explained(ValueError, "at least one file is required")
    wp = create_workpackage(name=name, source_kind="manual", source_ref=None, owner=owner)
    return fill_new(wp, lambda: add_documents(wp["id"], list(paths), expected_revision=0))


def create_with_items(*, name: str, source_kind: str, source_ref: str | None, owner: str | None,
                      entries: list[tuple[Path, str]]) -> dict[str, Any]:
    """140: a new package of its own kind filled with (path, kind) items in one revision step; a failed intake leaves
    no empty package behind."""
    wp = create_workpackage(name=name, source_kind=source_kind, source_ref=source_ref, owner=owner)
    return fill_new(wp, lambda: add_entries(wp["id"], entries, expected_revision=0))


def fill_new(wp: dict[str, Any], fill: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """063: fills the new package; if adding fails (e.g. a locked file), the empty package does not stay in the
    list. 185: a domain's own way of filling a new package uses it too (`statement_package.create_from_statement_table`)."""
    try:
        return fill()
    except Exception:
        with store.connect() as c:
            c.execute("DELETE FROM workpackages WHERE id=? AND NOT EXISTS (SELECT 1 FROM workpackage_items WHERE workpackage_id=?)",
                      (wp["id"], wp["id"]))
        raise


@store.one_connection
def get(wp_id: str) -> dict[str, Any]:
    with store.connect() as c:
        row = c.execute("SELECT * FROM workpackages WHERE id=?", (wp_id,)).fetchone()
        if row is None:
            raise KeyError(wp_id)
        items = [dict(r) for r in c.execute(
            "SELECT item_id, kind, source_path, sha256, added_revision, parent_item_id, instance FROM workpackage_items"
            " WHERE workpackage_id=? AND removed_revision IS NULL ORDER BY source_path", (wp_id,))]
    for i in items:  # 058 K5.2: only an attachment has a parent (the shape of old items is unchanged)
        parent = i.pop("parent_item_id")
        if parent:
            i["parent_item_id"] = parent
    return {**dict(row), "items": items, "assignment": work_recipes.current_assignment(wp_id)}


def list_workpackages(*, include_archived: bool = False) -> list[dict[str, Any]]:
    """The list of work packages; a hidden (archived) package only on request (058)."""
    where = "" if include_archived else " WHERE w.status <> 'archived'"
    with store.connect() as c:
        rows = c.execute(
            "SELECT w.*, (SELECT COUNT(*) FROM workpackage_items i WHERE i.workpackage_id=w.id AND i.removed_revision IS NULL) items,"
            " (SELECT recipe_id FROM recipe_assignments a WHERE a.workpackage_id=w.id ORDER BY revision DESC LIMIT 1) recipe_id,"
            " (SELECT run_id FROM runs r WHERE r.workpackage_id=w.id ORDER BY created_at DESC, rowid DESC LIMIT 1) last_run_id"
            f" FROM workpackages w{where} ORDER BY w.created_at DESC, w.rowid DESC").fetchall()
    return [dict(r) for r in rows]


def run_briefs(runs: Iterable[str | None]) -> dict[str, dict[str, Any]]:
    """169: each given run's mode, approval and start, and its package's id and name, in one query (a reconciliation
    package's item list names where each input comes from)."""
    ids = sorted({r for r in runs if r})
    if not ids:
        return {}
    with store.connect() as c:
        return {r["run_id"]: dict(r) for r in c.execute(
            "SELECT r.run_id, r.mode, r.approval, r.created_at, r.workpackage_id, w.name AS workpackage_name FROM runs r"
            f" JOIN workpackages w ON w.id = r.workpackage_id WHERE r.run_id IN ({','.join('?' * len(ids))})", ids)}


def approved_runs(runs: Iterable[str | None]) -> set[str]:
    """The approved ones of the given runs (a document's source counts only from an approved run)."""
    ids = sorted({r for r in runs if r})
    if not ids:
        return set()
    with store.connect() as c:
        return {r["run_id"] for r in c.execute(
            f"SELECT run_id FROM runs WHERE approval IS NOT NULL AND run_id IN ({','.join('?' * len(ids))})", ids)}


# 175 (plan 170 E4): the package log's own actions; the other modules register theirs (`jav/core/activity_kinds.py`)
activity_kinds.register_events("package", ("rename", "owner", "archive", "restore", "delete", "items_add", "item_remove",
                                           "items_remove", "item_restore", "items_restore", "run_cancel", "run_supersede"),
                               __name__)


def _event(c, wp_id: str, action: str, actor: str, detail: dict[str, Any] | None = None) -> None:
    activity_kinds.check_event("package", action)  # an action no module registered is refused
    c.execute("INSERT INTO workpackage_events(workpackage_id, action, actor, detail, created_at) VALUES (?,?,?,?,?)",
              (wp_id, action, actor, _canon(detail) if detail else None, _now()))


def record_event(c, wp_id: str, action: str, actor: str, detail: dict[str, Any] | None = None) -> None:
    """131: an event of another module on the package (a reconciliation package's decisions), in the package's log, in
    the caller's transaction."""
    _event(c, wp_id, action, actor, detail)


@dataclass(frozen=True)
class PackageRule:
    """140: what a package kind adds to the processing of its items, registered by the kind's module as part of its
    logic pack (176, `jav/logic_packs.py`; the worker asks it; the runtime never imports an application module).

    - `after_detection(run, item, detected)`: called once a document's type is recognised, before its extraction.
      None lets the item go on as in any package; a list stops it there, and its to-do reasons are raised on the item
      (an empty list: the detection's own to-dos stand for it).
    - `after_item(run, item)`: called when an item's flow has finished; the to-do reasons it returns are raised on the
      item.
    - `after_approval(run)` (153): called once a live run of the package is approved, after the approval is recorded; a
      failure is logged and never undoes the approval."""

    after_detection: Callable[[dict[str, Any], dict[str, Any], Any], list[str] | None] | None = None
    after_item: Callable[[dict[str, Any], dict[str, Any]], list[str]] | None = None
    after_approval: Callable[[dict[str, Any]], None] | None = None


def package_rule(wp_id: str) -> PackageRule | None:
    """The rule of the package's kind, if its logic pack has one."""
    with store.connect() as c:
        row = c.execute("SELECT source_kind FROM workpackages WHERE id=?", (wp_id,)).fetchone()
    pack = logic_packs.of(row["source_kind"]) if row else None
    return pack.rule if pack is not None else None


def raise_item_reasons(run_id: str, item: dict[str, Any], reasons: list[str], *, producer: str) -> None:
    """140: to-do reasons on a run's item, raised under the item's flow identifier (they count as this run's own)."""
    if reasons:
        kind, subject = work_runs.review_subject(item)
        store.review_enqueue(subject_kind=kind, subject_id=subject, run_id=work_runs.flow_run_id(run_id, item["item_id"]),
                             reasons=reasons, producer=producer)


_DELETE_GUARDS: list[Callable[[sqlite3.Connection, str], None]] = []


def register_delete_guard(fn: Callable[[sqlite3.Connection, str], None]) -> None:
    """131: a module with its own rows for a package checks a deletion inside its transaction: it raises `NotReady` to
    refuse it, or deletes its rows. 173: a repeated registration adds nothing. 176: a guard for one kind of package (a
    reconciliation package's scope) belongs to its logic pack; this one is asked for every package (a workflow's
    step)."""
    if fn not in _DELETE_GUARDS:
        _DELETE_GUARDS.append(fn)


def _set_wp(wp_id: str, action: str, actor: str, **fields: Any) -> dict[str, Any]:
    cols = ", ".join(f"{k}=?" for k in fields)
    with store.connect() as c:
        _begin(c)
        before = c.execute("SELECT name, status, owner FROM workpackages WHERE id=?", (wp_id,)).fetchone()
        if before is None:
            raise KeyError(wp_id)
        c.execute(f"UPDATE workpackages SET {cols}, updated_at=? WHERE id=?", (*fields.values(), _now(), wp_id))
        _event(c, wp_id, action, actor, {"before": dict(before), "after": fields})
    return get(wp_id)


def set_owner(wp_id: str, owner: str | None, *, actor: str) -> dict[str, Any]:
    """061: the person responsible for the package (None: nobody). Not part of the run's input, so it does not bump
    the revision; logged."""
    return _set_wp(wp_id, "owner", actor, owner=owner)


def archive_workpackage(wp_id: str, *, actor: str) -> dict[str, Any]:
    """Hides the package from the list: the runs, the call log and the results are kept; the package can still be
    opened directly."""
    return _set_wp(wp_id, "archive", actor, status="archived")


def restore_workpackage(wp_id: str, *, actor: str) -> dict[str, Any]:
    return _set_wp(wp_id, "restore", actor, status="open")


def rename_workpackage(wp_id: str, name: str, *, actor: str) -> dict[str, Any]:
    name = name.strip()
    if not name or len(name) > 200:
        raise explained(ValueError, "name must be 1-200 characters")
    return _set_wp(wp_id, "rename", actor, name=name)


def workpackage_events(wp_id: str) -> list[dict[str, Any]]:
    with store.connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM workpackage_events WHERE workpackage_id=? ORDER BY rowid", (wp_id,))]


def delete_workpackage(wp_id: str, *, actor: str) -> None:
    """Permanent deletion only for a package without runs (one with runs can only be hidden, because the call log and
    the results refer to it). The items' original files stay where they are; their source instances are released
    unless another item still refers to them."""
    with store.connect() as c:
        _begin(c)
        row = c.execute("SELECT name, source_kind, source_ref FROM workpackages WHERE id=?", (wp_id,)).fetchone()
        if row is None:
            raise KeyError(wp_id)
        if c.execute("SELECT 1 FROM runs WHERE workpackage_id=? LIMIT 1", (wp_id,)).fetchone() is not None:
            raise explained(NotReady, "a work package with runs can only be archived",
                            [{"code": "has_runs", "message": "A csomagnak van futása: csak elrejthető."}])
        rows = c.execute("SELECT instance FROM workpackage_items WHERE workpackage_id=?", (wp_id,)).fetchall()
        pack = logic_packs.of(row["source_kind"])  # 176: an unknown kind is refused, not deleted unguarded
        if pack is not None and pack.delete_guard is not None:  # 131: a reconciliation with decisions is hidden
            pack.delete_guard(c, wp_id)
        for guard in _DELETE_GUARDS:  # 153: a package of an open workflow's step is hidden
            guard(c, wp_id)
        for table in ("workpackage_items", "recipe_assignments"):
            c.execute(f"DELETE FROM {table} WHERE workpackage_id=?", (wp_id,))
        c.execute("DELETE FROM workpackages WHERE id=?", (wp_id,))
        _event(c, wp_id, "delete", actor, {**dict(row), "items": len(rows)})
    source_instances.release(r["instance"] for r in rows if r["instance"])
