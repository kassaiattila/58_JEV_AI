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
- The run's budget is the recipe's per-item maximum × the item count (`jav.runtime.calls`, scope = run_id).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from jav import cfg, source_instances, store, typepack
from jav.runtime import calls, queue

JOB_KIND = "run_item"

store.register_schema("work", """
CREATE TABLE IF NOT EXISTS workpackages (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    source_kind TEXT NOT NULL,                 -- folder | upload | mailbox | manual
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
    cols = {r[1] for r in conn.execute("PRAGMA table_info(workpackage_items)")}
    if cols and "parent_item_id" not in cols:  # 058 K5.2: the attachment points to its email
        conn.execute("ALTER TABLE workpackage_items ADD COLUMN parent_item_id TEXT")
    if cols and "instance" not in cols:  # source instance: the unchanging copy made when the item was added
        conn.execute("ALTER TABLE workpackage_items ADD COLUMN instance TEXT")
    wcols = {r[1] for r in conn.execute("PRAGMA table_info(workpackages)")}
    if wcols and "owner" not in wcols:  # 061: the person responsible for the package (a name from the name list)
        conn.execute("ALTER TABLE workpackages ADD COLUMN owner TEXT")
    rcols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
    if rcols and "plan" not in rcols:  # 082: the pre-start overview (`run_plan`), compared with the actual calls
        conn.execute("ALTER TABLE runs ADD COLUMN plan TEXT")


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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pinned_run(c: sqlite3.Connection, run_id: str) -> bool:
    """066 Á06 (decision of 2026-09-29): the to-do reasons of a live run that is not yet approved and not cancelled are
    pinned (another run does not take them over or close them); a trial run's reason is still carried by the latest
    run."""
    row = c.execute("SELECT 1 FROM runs WHERE run_id=? AND mode='apply' AND approval IS NULL AND status<>'cancelled'",
                    (run_id,)).fetchone()
    return row is not None


store.set_pinned_run_check(_pinned_run)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def max_source_bytes() -> int:
    """075: a source larger than the input limit is never read into memory (it could not have been added anyway)."""
    from jav import pdf

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


# --- recipes ----------------------------------------------------------------------------------------


def recipes() -> list[dict[str, Any]]:
    """Every recipe, whatever its status (080): `active` is offered in the UI, `internal` (a given document type
    without recognition) only on the command line and in tests, `retired` stays readable for old runs and
    assignments but cannot be assigned again."""
    return list(cfg.load("recipes")["recipes"])


def recipe_status(r: dict[str, Any]) -> str:
    return r.get("status", "active")


def active_recipes() -> list[dict[str, Any]]:
    return [r for r in recipes() if recipe_status(r) == "active"]


def default_recipe() -> dict[str, Any]:
    """080: the processing every package gets unless it says otherwise (the first active recipe)."""
    return active_recipes()[0]


def recipe(recipe_id: str) -> dict[str, Any]:
    for r in recipes():
        if r["id"] == recipe_id:
            return r
    raise ValueError(f"unknown recipe {recipe_id!r}")


def carried_params(r: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """080: the settings of an old assignment that the recipe `r` also has (path, JEV reuse, Azure, task proposal),
    the rest with `r`'s defaults. A given document type is dropped: the processing recognises it."""
    return _validated_params(r, {k: v for k, v in params.items() if k in r["params"]})


def recipe_hash(r: dict[str, Any]) -> str:
    return hashlib.sha256(_canon(r).encode("utf-8")).hexdigest()[:16]


def _validated_params(r: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    unknown = set(params) - set(r["params"])
    if unknown:
        raise ValueError(f"unknown params: {sorted(unknown)}")
    for name, spec in r["params"].items():
        value = params.get(name, spec.get("default"))
        allowed = spec.get("allowed") or (typepack.keys() if spec.get("allowed_from") == "typepacks" else None)
        if allowed is not None and value not in allowed:
            raise ValueError(f"param {name}={value!r} not in {sorted(allowed)}")
        out[name] = value
    return out


# --- work package ------------------------------------------------------------------------------------


def create_workpackage(*, name: str, source_kind: str, source_ref: str | None, owner: str | None = None) -> dict[str, Any]:
    """`owner` (decision 065): the creator is responsible for the new package; a nameless (automated) creation has no
    owner."""
    if not name.strip():
        raise ValueError("name required")
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
        raise RevisionConflict(f"workpackage {wp_id} is at revision {row['revision']}, not {expected_revision}")
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
    """Adds items in one revision step (`document`: a document file; `email`: the email's `message.json`, 048 T2).
    The item's identifier is the file's content hash; identical content appears once. `parents` (058 K5.2): the parent
    item's identifier per file — so an email attachment points to its email (the attachment's origin).

    A document is copied into the source instance store as it is added (`jav/source_instances.py`), and its
    fingerprint is that of the copied bytes; an email is hashed in place (it is already the system's own copy). If the
    intake fails, the copies made for it are released again."""
    if kind not in ("document", "email"):
        raise ValueError(f"unknown item kind: {kind}")
    parents = {Path(k).resolve(): v for k, v in (parents or {}).items()}
    resolved: list[tuple[Path, str, str | None]] = []
    try:
        for p in paths:
            p = Path(p).resolve(strict=True)
            if not p.is_file():
                raise ValueError(f"not a file: {p}")
            if kind == "document":
                resolved.append((p, *source_instances.freeze(p)))
            else:
                resolved.append((p, sha256_file(p), None))
        with store.connect() as c:
            _begin(c)
            rev = _bump(c, wp_id, expected_revision)
            for p, digest, instance in resolved:
                c.execute("INSERT INTO workpackage_items(workpackage_id, item_id, kind, source_path, sha256, added_revision, parent_item_id, instance)"
                          " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(workpackage_id, item_id) DO UPDATE SET removed_revision=NULL,"
                          " source_path=excluded.source_path, parent_item_id=COALESCE(workpackage_items.parent_item_id, excluded.parent_item_id),"
                          " instance=COALESCE(workpackage_items.instance, excluded.instance)",
                          (wp_id, digest, kind, str(p), digest, rev, parents.get(p), instance))
    except BaseException:
        source_instances.release(i for _p, _d, i in resolved if i)
        raise
    return get(wp_id)


def add_document(wp_id: str, path: Path, *, expected_revision: int) -> dict[str, Any]:
    return add_documents(wp_id, [path], expected_revision=expected_revision)


def remove_item(wp_id: str, item_id: str, *, expected_revision: int) -> dict[str, Any]:
    with store.connect() as c:
        _begin(c)
        rev = _bump(c, wp_id, expected_revision)
        c.execute("UPDATE workpackage_items SET removed_revision=? WHERE workpackage_id=? AND item_id=? AND removed_revision IS NULL",
                  (rev, wp_id, item_id))
    return get(wp_id)


def create_from_folder(folder: Path, *, name: str | None = None, suffixes: tuple[str, ...] = (".pdf",),
                       owner: str | None = None, recursive: bool = False, exclude: Iterable[Path] = ()) -> dict[str, Any]:
    """Work package from the documents of a folder, in path order: by default its direct contents only; with
    `recursive` (081) every subfolder too, except the folders in `exclude` (the caller passes the output folder of the
    named copies, so they do not come back as new documents). A link pointing outside the folder is left out."""
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError(f"folder does not exist: {folder}")
    root = folder.resolve(strict=True)
    skip = [Path(p).resolve() for p in exclude]
    found = root.rglob("*") if recursive else root.iterdir()
    files = []
    for p in found:
        if not p.is_file() or p.suffix.lower() not in suffixes:
            continue
        rp = p.resolve()
        inside = rp.parent == root if not recursive else rp.is_relative_to(root)
        if inside and not any(rp.is_relative_to(s) for s in skip):
            files.append(p)
    files.sort(key=lambda p: p.relative_to(root).as_posix().lower())
    wp = create_workpackage(name=name or root.name, source_kind="folder", source_ref=str(root), owner=owner)
    return _fill_new(wp, lambda: add_documents(wp["id"], files, expected_revision=0)) if files else wp


def create_from_files(paths: list[Path], *, name: str, owner: str | None = None) -> dict[str, Any]:
    """Work package from the given files (possibly from several folders), in one revision step (040 K3: live trial,
    selection in the UI)."""
    if not paths:
        raise ValueError("at least one file is required")
    wp = create_workpackage(name=name, source_kind="manual", source_ref=None, owner=owner)
    return _fill_new(wp, lambda: add_documents(wp["id"], list(paths), expected_revision=0))


def _fill_new(wp: dict[str, Any], fill: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """063: fills the new package; if adding fails (e.g. a locked file), the empty package does not stay in the
    list."""
    try:
        return fill()
    except Exception:
        with store.connect() as c:
            c.execute("DELETE FROM workpackages WHERE id=? AND NOT EXISTS (SELECT 1 FROM workpackage_items WHERE workpackage_id=?)",
                      (wp["id"], wp["id"]))
        raise


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
    return {**dict(row), "items": items, "assignment": current_assignment(wp_id)}


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


# --- hiding, renaming, deleting (058) ----------------------------------------------------------------
# The name and the hiding are not part of the run's input, so they do not bump the revision (runs and readiness stay).


def _event(c, wp_id: str, action: str, actor: str, detail: dict[str, Any] | None = None) -> None:
    c.execute("INSERT INTO workpackage_events(workpackage_id, action, actor, detail, created_at) VALUES (?,?,?,?,?)",
              (wp_id, action, actor, _canon(detail) if detail else None, _now()))


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
        raise ValueError("name must be 1-200 characters")
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
            raise NotReady("a work package with runs can only be archived",
                           [{"code": "has_runs", "message": "A csomagnak van futása: csak elrejthető."}])
        rows = c.execute("SELECT instance FROM workpackage_items WHERE workpackage_id=?", (wp_id,)).fetchall()
        for table in ("workpackage_items", "recipe_assignments"):
            c.execute(f"DELETE FROM {table} WHERE workpackage_id=?", (wp_id,))
        c.execute("DELETE FROM workpackages WHERE id=?", (wp_id,))
        _event(c, wp_id, "delete", actor, {**dict(row), "items": len(rows)})
    source_instances.release(r["instance"] for r in rows if r["instance"])


# --- recipe assignment ---------------------------------------------------------------------------------


def current_assignment(wp_id: str, c: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """`c`: an open connection (inside a write transaction, so the new row is visible)."""
    if c is None:
        with store.connect() as c:
            return current_assignment(wp_id, c)
    row = c.execute("SELECT * FROM recipe_assignments WHERE workpackage_id=? ORDER BY revision DESC LIMIT 1", (wp_id,)).fetchone()
    return {**dict(row), "params": json.loads(row["params"])} if row else None


def assignment_history(wp_id: str) -> list[dict[str, Any]]:
    with store.connect() as c:
        rows = c.execute("SELECT * FROM recipe_assignments WHERE workpackage_id=? ORDER BY revision", (wp_id,)).fetchall()
    return [{**dict(r), "params": json.loads(r["params"])} for r in rows]


def assign_recipe(wp_id: str, recipe_id: str, *, params: dict[str, Any], expected_revision: int, actor: str,
                  note: str | None = None) -> dict[str, Any]:
    """The assignment gets its own revision (the V4 `expected_revision` pattern); earlier ones stay as history. A
    retired recipe (080) cannot be assigned again."""
    r = recipe(recipe_id)
    if recipe_status(r) == "retired":
        raise RetiredRecipe(f"recipe {recipe_id!r} is retired; assign {default_recipe()['id']!r} instead")
    clean = _validated_params(r, params)
    with store.connect() as c:
        _begin(c)
        if c.execute("SELECT 1 FROM workpackages WHERE id=?", (wp_id,)).fetchone() is None:
            raise KeyError(wp_id)
        _insert_assignment(c, wp_id, r, clean, expected_revision=expected_revision, actor=actor, note=note)
    return current_assignment(wp_id)


def _insert_assignment(c, wp_id: str, r: dict[str, Any], params: dict[str, Any], *, expected_revision: int, actor: str,
                       note: str | None) -> int:
    cur = c.execute("SELECT MAX(revision) m FROM recipe_assignments WHERE workpackage_id=?", (wp_id,)).fetchone()["m"] or 0
    if cur != expected_revision:
        raise RevisionConflict(f"assignment of {wp_id} is at revision {cur}, not {expected_revision}")
    c.execute("INSERT INTO recipe_assignments VALUES (?,?,?,?,?,?,?,?,?)",
              (wp_id, cur + 1, r["id"], r["version"], recipe_hash(r), _canon(params), actor, note, _now()))
    return cur + 1


MIGRATION_ACTOR = "rendszer"  # data: the actor of the 080 migration in the assignment history (shown in the UI)


def migrate_assignments(*, write: bool) -> list[dict[str, Any]]:
    """080 (owner's decision of 2026-10-01: automatic migration): every package whose current assignment is not an
    active recipe moves onto the default processing, keeping its settings (`carried_params`); hidden packages too.
    Without `write` it only lists what it would do. Repeatable: a package already on the active recipe is left alone.
    Old runs keep their own recipe snapshot."""
    target = default_recipe()
    with store.connect() as c:
        rows = c.execute("SELECT a.* FROM recipe_assignments a WHERE a.revision = (SELECT MAX(revision) FROM recipe_assignments b"
                         " WHERE b.workpackage_id = a.workpackage_id) ORDER BY a.workpackage_id").fetchall()
    out = []
    for row in rows:
        old = recipe(row["recipe_id"])
        if recipe_status(old) == "active":
            continue
        params = json.loads(row["params"])
        new = carried_params(target, params)
        doc_type = f", típus: {params['doc_type']}" if params.get("doc_type") else ""
        # data (the assignment history, shown in the UI as written), not a label
        note = f"080: átállítás az egységes feldolgozásra (előtte: {old['title']}, {old['version']}. változat{doc_type})"
        out.append({"workpackage_id": row["workpackage_id"], "from": row["recipe_id"], "from_params": params, "params": new,
                    "revision": row["revision"] + 1, "note": note})
        if write:
            with store.connect() as c:
                _begin(c)
                _insert_assignment(c, row["workpackage_id"], target, new, expected_revision=row["revision"],
                                   actor=MIGRATION_ACTOR, note=note)
    return out


# --- readiness ---------------------------------------------------------------------------------------


def _input_snapshot(wp: dict[str, Any]) -> dict[str, Any]:
    items = [{"item_id": i["item_id"], "kind": i["kind"], "source_path": i["source_path"], "sha256": i["sha256"],
              **({"parent_item_id": i["parent_item_id"]} if i.get("parent_item_id") else {}),
              **({"instance": i["instance"]} if i.get("instance") else {})} for i in wp["items"]]
    return {"workpackage_id": wp["id"], "workpackage_revision": wp["revision"], "items": items}


def _snapshot_hash(snapshot: dict[str, Any]) -> str:
    """The identifier of the frozen input (the `input_hash` of readiness)."""
    return hashlib.sha256(_canon(snapshot).encode("utf-8")).hexdigest()[:16]


def item_budget(r: dict[str, Any], params: dict[str, Any], kind: str | None = None, arm: str | None = None) -> dict[str, Decimal]:
    """The budget maximum of one item. A recipe handling several item kinds (058 K5.2) gives a budget per kind
    (`max_item_usd_by_kind`); where there is no path, the `*` row applies. `arm` (066 Á07): the item's actual path,
    known in advance; without it, the row of the requested path (a requested S path runs on G for a G-only type, which
    needs the G row)."""
    table = (r.get("max_item_usd_by_kind") or {}).get(kind or "") or r["max_item_usd"]
    per = table.get(arm or params.get("arm", "*"), table.get(params.get("arm", "*"), table.get("*", {})))
    out = {provider: Decimal(v) for provider, v in per.items()}
    for extra in r.get("param_item_usd") or []:  # 058 K5.3: parameter-bound extra (e.g. task proposal on the email)
        # 075: a parameter missing from an older assignment counts with the recipe's default (e.g. the Azure switch)
        value = params.get(extra["param"], (r.get("params", {}).get(extra["param"]) or {}).get("default"))
        if value == extra["value"] and extra.get("kind") in (None, kind):
            for provider, v in extra["usd"].items():
                out[provider] = out.get(provider, Decimal(0)) + Decimal(v)
    return out


def run_budget(r: dict[str, Any], params: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Decimal]:
    """The run's budget maximum: the sum of the items' budgets (per item kind, 058 K5.2).

    Decision 065: the reservation follows the actual path. Where the item's path is known in advance and is S
    (candidate finder + JEV), there is no OpenAI reservation: on the invoice recipe from the given type, in document
    processing from the detailed type already detected earlier. For a document of unknown type the worst case stays.
    If the path still turns out to be G (e.g. a different type is detected), the GPT call does not start because of
    the budget, and the item gets a to-do (`llm:failed:BudgetExceeded`)."""
    return _run_budget(r, params, items, _item_arms(r, params, items))


def _run_budget(r: dict[str, Any], params: dict[str, Any], items: list[dict[str, Any]],
                arms: list[str | None]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for i, arm in zip(items, arms, strict=True):
        per = item_budget(r, params, i.get("kind"), arm=arm)
        if arm == "S":
            per.pop("openai", None)
        for provider, v in per.items():
            out[provider] = out.get(provider, Decimal(0)) + v
    return out


def _item_arms(r: dict[str, Any], params: dict[str, Any], items: list[dict[str, Any]]) -> list[str | None]:
    from jav import typepack

    packs, known = set(typepack.keys()), _known_detail_types(items)
    return [_item_arm(r, params, i, known, packs) for i in items]


def run_plan(r: dict[str, Any], params: dict[str, Any], items: list[dict[str, Any]],
             arms: list[str | None] | None = None) -> dict[str, Any]:
    """080 (the pre-start overview of F-külső-kapcsolók): what the run will do, for the UI to explain the budget per
    provider. Documents (attachments counted separately too) by their path known in advance (S / G / type not known
    yet), emails, emails that get a task proposal, whether Azure may be used and whether earlier JEV answers are
    reused. The budget itself is `run_budget`."""
    arms = _item_arms(r, params, items) if arms is None else arms

    def value(name: str) -> Any:
        return params.get(name, (r.get("params", {}).get(name) or {}).get("default"))

    docs = [(i, a) for i, a in zip(items, arms, strict=True) if i.get("kind") == "document"]
    emails = sum(1 for i in items if i.get("kind") == "email")
    paths = {"S": 0, "G": 0, "unknown": 0}
    for _i, a in docs:
        paths[a if a in ("S", "G") else "unknown"] += 1
    return {"documents": len(docs), "emails": emails,
            "attachments": sum(1 for i, _a in docs if i.get("parent_item_id")), "paths": paths,
            "tasks_emails": emails if value("tasks") == "propose" else 0,
            "azure": value("azure_ocr") == "on" and bool(docs), "jev_reuse": value("jev_cache") != "live"}


def _known_detail_types(items: list[dict[str, Any]]) -> dict[str, str]:
    """The detailed type of documents already detected (content hash → type), from the `documents` table (065)."""
    ids = [i["sha256"] for i in items if i.get("kind") == "document" and i.get("sha256")]
    out: dict[str, str] = {}
    with store.connect() as c:
        for k in range(0, len(ids), 500):
            chunk = ids[k:k + 500]
            out.update({row["doc_id"]: row["detail_type"] for row in c.execute(
                f"SELECT doc_id, detail_type FROM documents WHERE detail_type IS NOT NULL AND doc_id IN ({','.join('?' * len(chunk))})", chunk)})
    return out


def _item_arm(r: dict[str, Any], params: dict[str, Any], item: dict[str, Any], known: dict[str, str], packs: set[str]) -> str | None:
    """The item's path known in advance (S / G), or None if the type is not known before the run (065)."""
    from jav import typepack

    flow = flow_for(r, item.get("kind"))
    doc_type = params.get("doc_type") if flow == "invoice" else known.get(item.get("sha256", "")) if flow == "document" else None
    return typepack.resolve_arm(doc_type, params.get("arm", "auto")) if doc_type in packs else None


def flow_for(r: dict[str, Any], kind: str | None) -> str:
    """The item's flow: a recipe handling several item kinds chooses per kind (`flows`), otherwise the recipe's
    flow."""
    return (r.get("flows") or {}).get(kind or "", r["flow"])


def readiness(wp_id: str, *, verify: bool = False) -> dict[str, Any]:
    """Pre-run check: blockers (cannot start) and warnings, with the hash of the input to be pinned.
    `verify=True` (at start): full re-check of the source files, without the remembered fingerprint.

    An item with a source instance is processed from the instance: only a missing or damaged instance blocks, and a
    changed or missing original is a warning. An item without one follows the original file, as before.

    080: a package without an assignment runs with the default processing and its default settings
    (`assignment_default`); starting the run saves them (`start_run`)."""
    wp = get(wp_id)
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    a = wp["assignment"]
    if not wp["items"]:
        blockers.append({"code": "no_items", "message": "A munkacsomagban nincs tétel."})
    r = recipe(a["recipe_id"]) if a else default_recipe()
    params = a["params"] if a else _validated_params(r, {})
    if a is not None and recipe_status(r) == "retired":
        warnings.append({"code": "recipe_retired", "message": "The package uses a retired processing; switch it to the current processing settings."})
    elif a is not None and recipe_hash(r) != a["recipe_hash"]:
        warnings.append({"code": "recipe_changed", "message": "The processing changed since the settings were saved; save them again."})
    for i in wp["items"]:
        p = Path(i["source_path"])
        if i["kind"] not in r["input_kinds"] or p.suffix.lower() not in r.get("file_suffixes", [p.suffix.lower()]):
            blockers.append({"code": "unsupported_item", "message": f"The processing does not handle: {p.name}"})
        if i.get("instance"):
            if not _instance_ok(i, verify=verify):
                blockers.append({"code": "instance_damaged", "message": f"The copy kept when it was added is missing or damaged: {p.name}"})
            elif (state := original_state(i)) != "same":
                warnings.append({"code": f"original_{state}", "message": (
                    f"The original file has {'changed' if state == 'changed' else 'disappeared'} since it was added; "
                    f"the copy kept then is processed: {p.name}")})
        elif not p.exists():
            blockers.append({"code": "source_missing", "message": f"Hiányzó forrás: {p.name}"})
        elif fingerprint(p, verify=verify) != i["sha256"]:
            blockers.append({"code": "source_changed", "message": f"A forrás tartalma a felvétel óta változott: {p.name}"})
    snapshot = _input_snapshot(wp)
    arms = _item_arms(r, params, wp["items"])
    return {"workpackage_id": wp_id, "ready": not blockers, "blockers": blockers, "warnings": warnings,
            "counts": {"items": len(wp["items"])}, "budget": _run_budget(r, params, wp["items"], arms),
            "plan": run_plan(r, params, wp["items"], arms),
            "assignment_revision": a["revision"] if a else 0, "assignment_default": a is None,
            "input_hash": _snapshot_hash(snapshot)}


# --- runs --------------------------------------------------------------------------------------------


def start_run(wp_id: str, *, mode: str, expected_assignment_revision: int, input_hash: str, actor: str,
              rerun_of: str | None = None) -> dict[str, Any]:
    """Idempotent start with a pinned input: one queue job per item, with a run-level cost budget.

    Rerun (057): for the same input and recipe, starting returns the existing run; `rerun_of` (the run being repeated)
    asks for a new run. A repeated request with the same `rerun_of` still yields only one new run (against double
    clicks); an active run cannot be rerun."""
    if mode not in ("shadow", "apply"):
        raise ValueError("mode must be shadow or apply")
    if rerun_of is not None:
        prev = get_run(rerun_of)
        if prev["workpackage_id"] != wp_id:
            raise ValueError("rerun_of belongs to another workpackage")
        if prev["status"] in ("queued", "running"):
            raise ValueError("run is still active; stop it before rerunning")
    ready = readiness(wp_id, verify=True)
    if ready["assignment_revision"] != expected_assignment_revision:
        raise RevisionConflict(f"assignment is at revision {ready['assignment_revision']}, not {expected_assignment_revision}")
    if ready["input_hash"] != input_hash:
        raise RevisionConflict("workpackage input changed since readiness check")
    if not ready["ready"]:
        raise NotReady("workpackage is not ready", ready["blockers"])
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    with store.connect() as c:
        _begin(c)
        # 066 Á19: the frozen input is read under the write lock (nobody else can write meanwhile), and it is exactly
        # what the readiness check saw; an edit in between is a conflict, not a run with an unchecked input
        wp = get(wp_id)
        a = wp["assignment"]
        snapshot = _input_snapshot(wp)
        if (a["revision"] if a else 0) != expected_assignment_revision or _snapshot_hash(snapshot) != input_hash:
            raise RevisionConflict("workpackage changed while the run was being started")
        if a is None:  # 080: the default settings the readiness check used are saved, in the starter's name
            d = default_recipe()
            # data (the assignment history, shown in the UI as written), not a label
            _insert_assignment(c, wp_id, d, _validated_params(d, {}), expected_revision=0, actor=actor,
                               note="alapbeállítás, a futás indításakor mentve")
            a = current_assignment(wp_id, c)
        r = recipe(a["recipe_id"])
        dedup = f"{wp_id}:{a['revision']}:{input_hash}:{mode}" + (f":rerun:{rerun_of}" if rerun_of else "")
        existing = c.execute("SELECT run_id, input FROM runs WHERE dedup_key=?", (dedup,)).fetchone()
        if not existing:
            c.execute("INSERT INTO runs(run_id, workpackage_id, dedup_key, mode, assignment_revision, recipe_id, recipe_version, recipe_hash,"
                      " recipe, params, input, input_hash, status, actor, created_at, plan) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'queued',?,?,?)",
                      (run_id, wp_id, dedup, mode, a["revision"], r["id"], r["version"], recipe_hash(r), _canon(r), _canon(a["params"]),
                       _canon(snapshot), input_hash, actor, _now(), _canon(ready["plan"])))
    if existing:
        # 063: if the previous start broke off after the run row, the repeated start fills in the budget and the jobs
        _ensure_run_work(existing["run_id"], json.loads(existing["input"])["items"], ready["budget"], replace_budget=False)
        return {"run_id": existing["run_id"], "deduped": True}
    _ensure_run_work(run_id, snapshot["items"], ready["budget"], replace_budget=True)
    return {"run_id": run_id, "deduped": False}


def _ensure_run_work(run_id: str, items: list[dict[str, Any]], budget: dict[str, Decimal], *, replace_budget: bool) -> None:
    """The run's budget and one queue job per item. Idempotent: the job is created once per `dedup_key`, and an
    existing budget does not change when filling in (063)."""
    for provider, amount in budget.items():
        (calls.set_budget if replace_budget else calls.ensure_budget)(run_id, provider, amount)
    for item in items:
        queue.enqueue(JOB_KIND, run_id=run_id, dedup_key=f"{run_id}:{item['item_id']}",
                      payload={"run_id": run_id, "item_id": item["item_id"]})


def get_run(run_id: str) -> dict[str, Any]:
    with store.connect() as c:
        row = c.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        items = [dict(r) for r in c.execute("SELECT * FROM run_items WHERE run_id=? ORDER BY item_id", (run_id,))]
    out = dict(row)
    for k in ("recipe", "params", "input"):
        out[k] = json.loads(out[k])
    out["plan"] = json.loads(out["plan"]) if out.get("plan") else None  # 082: None for a run started before it was saved
    out["items"] = items
    out["jobs"] = queue.counts(run_id=run_id)
    return out


def run_rows(wp_id: str | None = None) -> list[dict[str, Any]]:
    """Runs as list rows, in one query, without truncation (056 U1 dataset): package name, item count, the finished
    items and the run's own open to-do reasons (the item's flow identifier starts with `<run>:`)."""
    sql = ("SELECT r.run_id, r.workpackage_id, w.name AS workpackage_name, r.recipe_id, r.recipe_version, r.mode, r.status,"
           " r.approval, r.approved_by, r.actor, r.created_at, r.finished_at,"
           " json_array_length(r.input, '$.items') AS items,"
           " (SELECT COUNT(*) FROM run_items i WHERE i.run_id=r.run_id) AS items_done,"
           " (SELECT COUNT(*) FROM review_reasons x WHERE x.status='open' AND x.run_id LIKE r.run_id || ':%') AS open_reasons"
           " FROM runs r JOIN workpackages w ON w.id=r.workpackage_id")
    args: tuple = ()
    if wp_id is not None:
        sql, args = sql + " WHERE r.workpackage_id=?", (wp_id,)
    with store.connect() as c:
        rows = [dict(r) for r in c.execute(sql + " ORDER BY r.created_at DESC, r.rowid DESC", args)]
    for r in rows:  # 058: a stored "needs review" after to-dos closed without a refresh is really done (queue empty)
        if r["status"] == "needs_review" and not r["open_reasons"]:
            r["status"] = "done"
    return rows


def runs(wp_id: str) -> list[dict[str, Any]]:
    with store.connect() as c:
        ids = [r["run_id"] for r in c.execute("SELECT run_id FROM runs WHERE workpackage_id=? ORDER BY created_at DESC, rowid DESC", (wp_id,))]
    return [get_run(i) for i in ids]


def record_item_result(run_id: str, item_id: str, *, status: str, final_status: str | None = None,
                       flow_run_id: str | None = None, error: str | None = None) -> None:
    with store.connect() as c:
        c.execute("INSERT INTO run_items(run_id, item_id, status, final_status, flow_run_id, error, updated_at) VALUES (?,?,?,?,?,?,?)"
                  " ON CONFLICT(run_id, item_id) DO UPDATE SET status=excluded.status, final_status=excluded.final_status,"
                  " flow_run_id=excluded.flow_run_id, error=excluded.error, updated_at=excluded.updated_at",
                  (run_id, item_id, status, final_status, flow_run_id, error, _now()))


def flow_run_id(run_id: str, item_id: str) -> str:
    """The item's flow identifier (the worker builds the Burr application with it; the to-dos get it as `run_id`)."""
    return f"{run_id}:{item_id[:16]}"


def review_subject(item: dict[str, Any]) -> tuple[str, str]:
    """The subject of the item's to-dos: for a document, the content hash; for an email, the message identifier (= the
    name of the email's folder, written by the receiver and used by the email flow, 048 T2)."""
    if item.get("kind") == "email":
        return "email", Path(item["source_path"]).parent.name
    return "document", item["item_id"]


def is_own_reason(reason: dict[str, Any], own: str) -> bool:
    """Whether the to-do reason was raised for the item in this run: under the item's flow identifier, or under one of
    its stages (`<identifier>-<stage>`, e.g. detection in document processing: `-doc_detect`; 066 Á02: until then it
    counted as "earlier")."""
    rid = reason.get("run_id") or ""
    return rid == own or rid.startswith(own + "-")


def item_reasons(run_id: str, item_id: str, item: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    """An item's open to-do reasons split in two: raised in this run (`run`) and earlier (`earlier`).

    The earlier reasons (from old measurements or earlier runs on the same document) stay open on the document and are
    shown, but they are not about this run's result, so they do not affect the run's status or approval (040 K3 live
    trial)."""
    if item is None:
        item = next((i for i in get_run(run_id)["input"]["items"] if i["item_id"] == item_id), {"item_id": item_id})
    return items_reasons(run_id, [{**item, "item_id": item_id}])[item_id]


def items_reasons(run_id: str, items: list[dict[str, Any]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """`item_reasons` for several items, with one store query (061: instead of the list views' per-item queries)."""
    by_subject = store.review_open_reasons_many([review_subject(i) for i in items])
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for i in items:
        own = flow_run_id(run_id, i["item_id"])
        split: dict[str, list[dict[str, Any]]] = {"run": [], "earlier": []}
        for r in by_subject[review_subject(i)]:
            split["run" if is_own_reason(r, own) else "earlier"].append(r)
        out[i["item_id"]] = split
    return out


def open_reasons_for_run(run_id: str) -> int:
    """The run's OWN open to-do reasons (the reasons raised under the items' flow identifiers)."""
    run = get_run(run_id)
    return sum(len(s["run"]) for s in items_reasons(run_id, run["input"]["items"]).values())


def refresh_run_status(run_id: str) -> str:
    """The run's status from the queue and the to-dos: running → failed / needs review / done."""
    run = get_run(run_id)
    jobs = run["jobs"]
    # 063: an item without a job (an interrupted start) is pending too — until then the run cannot be "done"
    missing = max(0, len(run["input"]["items"]) - sum(jobs.values()))
    pending = jobs.get("queued", 0) + jobs.get("claimed", 0) + missing
    if run["status"] == "cancelled":
        status = "cancelled"
    elif pending:
        status = "running" if (jobs.get("claimed") or any(v for k, v in jobs.items() if k in ("done", "dead"))) else "queued"
    elif jobs.get("dead"):
        status = "failed"
    elif jobs.get("cancelled"):
        status = "cancelled"
    else:
        status = "needs_review" if open_reasons_for_run(run_id) else "done"
    with store.connect() as c:
        # 066 Á32: a run cancelled between computing and writing stays cancelled (condition in the write, not before)
        c.execute("UPDATE runs SET status=?, finished_at=CASE WHEN ? IN ('queued','running') THEN NULL ELSE COALESCE(finished_at, ?) END"
                  " WHERE run_id=? AND (status <> 'cancelled' OR ? = 'cancelled')", (status, status, _now(), run_id, status))
        return c.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()["status"]


def resolve_reason(reason_id: int, *, actor: str, resolution: dict[str, Any] | None, note: str | None) -> dict[str, Any]:
    """Human resolution of one to-do reason, then a refresh of the owning run's status (058: after the last reason is
    closed the run is "done", and the list badge does not stay at "needs review"). A reason from an earlier
    measurement is not owned by a run."""
    with store.connect() as c:
        row = c.execute("SELECT status, run_id FROM review_reasons WHERE id=?", (reason_id,)).fetchone()
    if row is None:
        raise KeyError(reason_id)
    if row["status"] != "open":
        raise RevisionConflict(f"review reason {reason_id} is already {row['status']}")
    store.review_resolve(reason_id, actor=actor, resolution=resolution, note=note)
    owner = (row["run_id"] or "").split(":", 1)[0]
    run_status = None
    with store.connect() as c:
        hit = c.execute("SELECT status FROM runs WHERE run_id=?", (owner,)).fetchone()
    if hit is not None and hit["status"] in ("needs_review", "done"):
        run_status = refresh_run_status(owner)
    return {"reason_id": reason_id, "status": "resolved", "actor": actor, "run_status": run_status}


def cancel_run(run_id: str, *, actor: str | None = None) -> dict[str, int]:
    """Queued items stop at once, an active one at the next step boundary. 066 Á35: the actor (if any) goes into the
    package's event log."""
    with store.connect() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM jobs WHERE run_id=? AND status IN ('queued','claimed')", (run_id,))]
        if actor is not None:
            wp_row = c.execute("SELECT workpackage_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if wp_row is not None:
                _event(c, wp_row["workpackage_id"], "run_cancel", actor, {"run_id": run_id})
    out: dict[str, int] = {}
    for job_id in ids:
        res = queue.cancel(job_id)
        out[res] = out.get(res, 0) + 1
    if not out.get("cancel_requested"):
        with store.connect() as c:
            c.execute("UPDATE runs SET status='cancelled', finished_at=? WHERE run_id=?", (_now(), run_id))
    return out


def approve_run(run_id: str, *, actor: str) -> dict[str, Any]:
    """Approval of a live run: only with finished items and no open to-do; who approved it and when is recorded."""
    run = get_run(run_id)
    if run["mode"] != "apply":
        raise ValueError("only apply runs can be approved")
    status = refresh_run_status(run_id)
    if status != "done":
        raise NotReady(f"run is {status}; approval needs a finished run without open review reasons")
    done = {i["item_id"] for i in get_run(run_id)["items"] if i["status"] == "done"}
    if any(i["item_id"] not in done for i in run["input"]["items"]):  # 063: every input item has a finished result
        raise NotReady("run has input items without a finished result")
    with store.connect() as c:
        c.execute("UPDATE runs SET approval='approved', approved_by=?, approved_at=? WHERE run_id=? AND approval IS NULL",
                  (actor, _now(), run_id))
    return get_run(run_id)
