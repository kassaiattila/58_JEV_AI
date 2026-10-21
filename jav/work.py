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
- 160-C S3: a run can take only the package's pending items (`scope="pending"`); its input, budget and plan are
  those items' alone, and the earlier runs stay as they are.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from jav import activity_kinds, cfg, item_kinds, logic_packs, source_instances, store, typepack
from jav.native_contracts import DOCUMENT_SUFFIXES, NATIVE_SUFFIXES
from jav.runtime import calls, flows, queue
from jav.user_messages import explained

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
    if rcols and "stopped_at" not in rcols:  # 160 (review R-4): a person stopped the run (it ends cancelled)
        conn.execute("ALTER TABLE runs ADD COLUMN stopped_at TEXT")
        conn.execute("ALTER TABLE runs ADD COLUMN stopped_by TEXT")
    if rcols and "excluded_items" not in rcols:  # 160-C (decision 163 D7): items removed before the approval (JSON)
        conn.execute("ALTER TABLE runs ADD COLUMN excluded_items TEXT")
    if rcols and "scope" not in rcols:  # 160-C S3: NULL = every item in use, 'pending' = only the pending items
        conn.execute("ALTER TABLE runs ADD COLUMN scope TEXT")
    if cols and "removed_at" not in cols:  # 160-C S1 (decision 163 D2): who removed an item, when and why
        conn.execute("ALTER TABLE workpackage_items ADD COLUMN removed_at TEXT")
        conn.execute("ALTER TABLE workpackage_items ADD COLUMN removed_by TEXT")
        conn.execute("ALTER TABLE workpackage_items ADD COLUMN removed_reason TEXT")


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
    raise explained(ValueError, "unknown recipe {{recipe_id}}", recipe_id=repr(recipe_id))


def carried_params(r: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """080: the settings of an old assignment that the recipe `r` also has (path, JEV reuse, Azure, task proposal),
    the rest with `r`'s defaults. A given document type is dropped: the processing recognises it."""
    return _validated_params(r, {k: v for k, v in params.items() if k in r["params"]})


ENGINE_JEV = {"jev": "on", "gpt": "off"}  # 160-D: the AI engine as the recipes' `jev` setting


def engine_params(r: dict[str, Any], engine: str | None = None) -> dict[str, str]:
    """160-D (plan F-csak-gpt Sz4): the engine setting a new processing setting gets when it does not name one:
    `engine`, or the application's (`app_settings.engine_default`). Empty for a recipe without the setting."""
    if "jev" not in r["params"]:
        return {}
    if engine is None:
        from jav import app_settings  # it imports this module

        engine = app_settings.engine_default()
    return {"jev": ENGINE_JEV[engine]}


def default_params(r: dict[str, Any], engine: str | None = None) -> dict[str, Any]:
    """The settings of a package without saved ones: the recipe's defaults with the application's engine (or
    `engine`, a workflow step's own)."""
    return _validated_params(r, engine_params(r, engine))


def recipe_hash(r: dict[str, Any]) -> str:
    return hashlib.sha256(_canon(r).encode("utf-8")).hexdigest()[:16]


def _validated_params(r: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    unknown = set(params) - set(r["params"])
    if unknown:
        raise explained(ValueError, "unknown params: {{unknown}}", unknown=sorted(unknown))
    for name, spec in r["params"].items():
        value = params.get(name, spec.get("default"))
        allowed = spec.get("allowed") or (typepack.extractable_keys() if spec.get("allowed_from") == "typepacks" else None)
        if allowed is not None and value not in allowed:
            raise explained(ValueError, "param {{name}}={{value}} not in {{allowed}}",
                            name=name, value=repr(value), allowed=sorted(allowed))
        out[name] = value
    return out


# --- work package ------------------------------------------------------------------------------------


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


def add_document(wp_id: str, path: Path, *, expected_revision: int) -> dict[str, Any]:
    return add_documents(wp_id, [path], expected_revision=expected_revision)


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


# --- hiding, renaming, deleting (058) ----------------------------------------------------------------
# The name and the hiding are not part of the run's input, so they do not bump the revision (runs and readiness stay).


# 175 (plan 170 E4): the package log's own actions; the other modules register theirs (`jav/activity_kinds.py`)
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
        kind, subject = review_subject(item)
        store.review_enqueue(subject_kind=kind, subject_id=subject, run_id=flow_run_id(run_id, item["item_id"]),
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
    retired recipe (080) cannot be assigned again. 160-D: a setting that does not name the engine takes the
    application's."""
    r = recipe(recipe_id)
    if recipe_status(r) == "retired":
        raise explained(RetiredRecipe, "recipe {{recipe_id}} is retired; assign {{id}} instead",
                        recipe_id=repr(recipe_id), id=repr(default_recipe()["id"]))
    clean = _validated_params(r, {**engine_params(r), **params})
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
        raise explained(RevisionConflict, "assignment of {{wp_id}} is at revision {{cur}}, not {{expected_revision}}",
                        wp_id=wp_id, cur=cur, expected_revision=expected_revision)
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


def _input_snapshot(wp: dict[str, Any], items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The frozen input of a run: the package's items in use, or only `items` (160-C S3: the pending ones)."""
    frozen = [{"item_id": i["item_id"], "kind": i["kind"], "source_path": i["source_path"], "sha256": i["sha256"],
               **({"parent_item_id": i["parent_item_id"]} if i.get("parent_item_id") else {}),
               **({"instance": i["instance"]} if i.get("instance") else {})} for i in (wp["items"] if items is None else items)]
    return {"workpackage_id": wp["id"], "workpackage_revision": wp["revision"], "items": frozen}


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
    drop: set[str] = set()
    for extra in r.get("param_item_usd") or []:  # 058 K5.3: parameter-bound extra (e.g. task proposal on the email)
        # 075: a parameter missing from an older assignment counts with the recipe's default (e.g. the Azure switch)
        value = params.get(extra["param"], (r.get("params", {}).get(extra["param"]) or {}).get("default"))
        if value == extra["value"] and extra.get("kind") in (None, kind):
            for provider, v in extra["usd"].items():
                out[provider] = out.get(provider, Decimal(0)) + Decimal(v)
            drop.update(extra.get("drop") or ())  # 086: e.g. without JEV the item has no JEV budget at all
    return {provider: v for provider, v in out.items() if provider not in drop}


def jev_off(r: dict[str, Any], params: dict[str, Any]) -> bool:
    """086: processing without JEV (the `jev` setting off): every document on the G path, the type recognised by GPT,
    no JEV budget."""
    return params.get("jev", (r.get("params", {}).get("jev") or {}).get("default", "on")) == "off"


def run_engine(run: dict[str, Any]) -> str:
    """160-D (plan F-csak-gpt L6, decision 160 D3): the AI engine a run ran with, from its frozen recipe and settings:
    `gpt` (GPT only) when its `jev` setting is off, `jev` (JEV and GPT) otherwise, a recipe without the setting
    included. The approval and the review show it with the results."""
    return "gpt" if jev_off(run["recipe"], run["params"]) else "jev"


def run_budget(r: dict[str, Any], params: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Decimal]:
    """The run's budget maximum: the sum of the items' budgets (per item kind, 058 K5.2).

    Decision 065: the reservation follows the actual path. Where the item's path is known in advance and is S
    (candidate finder + JEV), there is no OpenAI reservation: on the invoice recipe from the given type, in document
    processing from the detailed type already detected earlier. For a document of unknown type the worst case stays.
    If the path still turns out to be G (e.g. a different type is detected), the GPT call does not start because of
    the budget, and the item gets a to-do (`llm:failed:BudgetExceeded`)."""
    return _run_budget(r, params, items, _item_arms(r, params, items))


def _item_extras(r: dict[str, Any], params: dict[str, Any], item: dict[str, Any]) -> list[tuple[Any, int]]:
    """192 (B6c): the budget extras the domains count on the item that the recipe's settings price now: (extra, its
    units on the item)."""
    return [(e, n) for e in item_kinds.item_extras(item.get("kind") or "")
            if _extras(r, params, e.extra) and (n := e.count(item))]


def _extra_counts(r: dict[str, Any], params: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        for e, n in _item_extras(r, params, i):
            out[e.plan_key] = out.get(e.plan_key, 0) + n
    return out


def _extras(r: dict[str, Any], params: dict[str, Any], kind: str) -> dict[str, Decimal]:
    """192: the parameter-bound extras of a kind that is no item (an email's table attachment), without a base budget."""
    out: dict[str, Decimal] = {}
    for extra in r.get("param_item_usd") or []:
        value = params.get(extra["param"], (r.get("params", {}).get(extra["param"]) or {}).get("default"))
        if value == extra["value"] and extra.get("kind") == kind:
            for provider, v in extra["usd"].items():
                out[provider] = out.get(provider, Decimal(0)) + Decimal(v)
    return out


def _run_budget(r: dict[str, Any], params: dict[str, Any], items: list[dict[str, Any]],
                arms: list[str | None]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for i, arm in zip(items, arms, strict=True):
        if native_flow(r, i):
            from jav.native_processing import estimate_limits

            per = dict(estimate_limits(params).provider_limits_usd) if params.get("arm") != "S" else {}
        else:
            per = item_budget(r, params, i.get("kind"), arm=arm)
            # 192 (B6c): what the domains count on the item (an email's table attachments), each unit priced
            for extra, n in _item_extras(r, params, i):
                for provider, v in _extras(r, params, extra.extra).items():
                    per[provider] = per.get(provider, Decimal(0)) + v * n
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

    docs = [(i, a) for i, a in zip(items, arms, strict=True) if item_kinds.of(i).detected]
    paths = {"S": 0, "G": 0, "unknown": 0}
    for _i, a in docs:
        paths[a if a in ("S", "G") else "unknown"] += 1
    # 177: each item kind under its own key, in the registry's order (a table statement, 136: code, free, only if any)
    counts = {k.plan_key: sum(1 for i in items if item_kinds.of(i) is k) for k in item_kinds.ITEM_KINDS}
    emails = counts[item_kinds.of(item_kinds.EMAIL).plan_key]
    plan = {**{k.plan_key: counts[k.plan_key] for k in item_kinds.ITEM_KINDS if k.plan_always or counts[k.plan_key]},
            "attachments": sum(1 for i, _a in docs if i.get("parent_item_id")), "paths": paths,
            "tasks_emails": emails if value("tasks") == "propose" else 0,
            "text_emails": emails if value("email_text") == "extract" else 0,  # 190: a quote request in the email
            # 192 (B6c): what the domains count on the items as a budget extra (an email's table attachments), while any
            **_extra_counts(r, params, items),
            "azure": value("azure_ocr") == "on" and any(not native_flow(r, i) for i, _a in docs),
            "jev_reuse": value("jev_cache") != "live",
            "arm": value("arm"),  # 082: with S chosen, a document on the G path has a type without a JEV path
            "jev": not jev_off(r, params)}  # 086: without JEV, GPT recognises the type and every document runs on G
    if r.get("flows_by_suffix"):
        plan.update(native_documents=sum(native_flow(r, i) for i, _a in docs),
                    item_flows={i["item_id"]: flow_for(r, i) for i in items})
    return plan


def _known_detail_types(items: list[dict[str, Any]]) -> dict[str, str]:
    """The detailed type of documents already detected (content hash → type), from the `documents` table (065)."""
    ids = [i["sha256"] for i in items if item_kinds.of(i).detected and i.get("sha256")]
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

    spec = flows.get(flow_for(r, item))
    if spec.native:
        return "S" if params.get("arm") == "S" else "G"
    # 173: where the document type is known before the run is the flow's registry entry
    doc_type = (params.get("doc_type") if spec.doc_type == "params"
                else known.get(item.get("sha256", "")) if spec.doc_type == "detected" else None)
    arm = "G" if jev_off(r, params) else params.get("arm", "auto")  # 086: without JEV only the G path runs
    return typepack.resolve_arm(doc_type, arm) if doc_type in packs else None


def native_flow(r: dict[str, Any], item: dict[str, Any]) -> bool:
    """173: whether the item's flow takes its budget and path from the native reader's estimate (the flow registry)."""
    return flows.get(flow_for(r, item)).native


def flow_for(r: dict[str, Any], item: dict[str, Any] | str | None) -> str:
    """Use the frozen source suffix for mixed documents (177: an item whose type is recognised from its content), then
    the recipe's item-kind routing."""
    kind = item.get("kind") if isinstance(item, dict) else item
    if isinstance(item, dict) and item_kinds.of(item).detected:
        suffix = Path(item["source_path"]).suffix.lower()
        routed = (r.get("flows_by_suffix") or {}).get(suffix)
        if routed:
            return routed
    return (r.get("flows") or {}).get(kind or "", r["flow"])


def readiness(wp_id: str, *, verify: bool = False) -> dict[str, Any]:
    """Pre-run check: blockers (cannot start) and warnings, with the hash of the input to be pinned.
    `verify=True` (at start): full re-check of the source files, without the remembered fingerprint.

    An item with a source instance is processed from the instance: only a missing or damaged instance blocks, and a
    changed or missing original is a warning. An item without one follows the original file, as before.

    080: a package without an assignment runs with the default processing and its default settings
    (`assignment_default`); starting the run saves them (`start_run`).

    153 (review B1): one connection for the whole check; a package of 468 documents opened in 4 s, as each item's
    instance and original check opened its own (944 connections)."""
    with store.session():
        return _readiness(wp_id, verify=verify)


def _readiness(wp_id: str, *, verify: bool) -> dict[str, Any]:
    wp = get(wp_id)
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    a = wp["assignment"]
    if not wp["items"]:
        blockers.append({"code": "no_items", "message": "A munkacsomagban nincs tétel."})
    r = recipe(a["recipe_id"]) if a else default_recipe()
    params = a["params"] if a else default_params(r)  # 160-D: with the application's engine
    if a is not None and recipe_status(r) == "retired":
        warnings.append({"code": "recipe_retired", "message": "The package uses a retired processing; switch it to the current processing settings."})
    elif a is not None and recipe_hash(r) != a["recipe_hash"]:
        warnings.append({"code": "recipe_changed", "message": "The processing changed since the settings were saved; save them again."})
    checks = _item_checks(r, params, wp["items"], verify=verify)
    snapshot = _input_snapshot(wp)
    arms = _item_arms(r, params, wp["items"])
    out = {"workpackage_id": wp_id, "ready": not blockers and not any(level == "blocker" for _i, level, _f in checks),
           "blockers": blockers + [f for _i, level, f in checks if level == "blocker"],
           "warnings": warnings + [f for _i, level, f in checks if level == "warning"],
           "counts": {"items": len(wp["items"])}, "budget": _run_budget(r, params, wp["items"], arms),
           "plan": run_plan(r, params, wp["items"], arms),
           "assignment_revision": a["revision"] if a else 0, "assignment_default": a is None,
           "input_hash": _snapshot_hash(snapshot)}
    if supplement := _supplements(wp, r, params, warnings, checks):
        out["supplement"] = supplement
    return out


def _item_checks(r: dict[str, Any], params: dict[str, Any], items: list[dict[str, Any]], *,
                 verify: bool) -> list[tuple[str, str, dict[str, str]]]:
    """The readiness findings of each item, in item order: (item id, "blocker" | "warning", finding)."""
    out: list[tuple[str, str, dict[str, str]]] = []
    for i in items:
        p = Path(i["source_path"])
        found: list[tuple[str, dict[str, str]]] = []
        if i["kind"] not in r["input_kinds"] or p.suffix.lower() not in r.get("file_suffixes", [p.suffix.lower()]):
            found.append(("blocker", {"code": "unsupported_item", "message": f"The processing does not handle: {p.name}"}))
        elif p.suffix.lower() in NATIVE_SUFFIXES and not native_flow(r, i):
            found.append(("blocker", {"code": "native_recipe_required", "message": f"Choose multi-format processing for: {p.name}"}))
        if native_flow(r, i) and params.get("arm") == "S":
            found.append(("blocker", {"code": "native_s_unsupported", "message": "Native documents require GPT extraction; the JEV-only path has no predefined field contract."}))
        if i.get("instance"):
            if not _instance_ok(i, verify=verify):
                found.append(("blocker", {"code": "instance_damaged", "message": f"The copy kept when it was added is missing or damaged: {p.name}"}))
            elif (state := original_state(i)) != "same":
                found.append(("warning", {"code": f"original_{state}", "message": (
                    f"The original file has {'changed' if state == 'changed' else 'disappeared'} since it was added; "
                    f"the copy kept then is processed: {p.name}")}))
        elif not p.exists():
            found.append(("blocker", {"code": "source_missing", "message": f"Hiányzó forrás: {p.name}"}))
        elif fingerprint(p, verify=verify) != i["sha256"]:
            found.append(("blocker", {"code": "source_changed", "message": f"A forrás tartalma a felvétel óta változott: {p.name}"}))
        out += [(i["item_id"], level, finding) for level, finding in found]
    return out


def _supplements(wp: dict[str, Any], r: dict[str, Any], params: dict[str, Any], warnings: list[dict[str, str]],
                 checks: list[tuple[str, str, dict[str, str]]]) -> dict[str, dict[str, Any]]:
    """160-C S3: per mode (shadow / apply), the run over only the package's pending items, offered when a run of that
    mode has already finished some of the items in use and others are pending. Its blockers and warnings are the
    pending items' own (an earlier item's changed source does not hold it up), its budget, plan and input hash are
    theirs alone; `start_run(scope="pending")` starts it."""
    out: dict[str, dict[str, Any]] = {}
    for mode in ("shadow", "apply"):
        pending = set(pending_items(wp["id"], mode, wp))
        if not 0 < len(pending) < len(wp["items"]):
            continue
        items = [i for i in wp["items"] if i["item_id"] in pending]
        found = [(level, f) for item_id, level, f in checks if item_id in pending]
        arms = _item_arms(r, params, items)
        out[mode] = {"items": len(items), "ready": not any(level == "blocker" for level, _f in found),
                     "blockers": [f for level, f in found if level == "blocker"],
                     "warnings": warnings + [f for level, f in found if level == "warning"],
                     "budget": _run_budget(r, params, items, arms), "plan": run_plan(r, params, items, arms),
                     "input_hash": _snapshot_hash(_input_snapshot(wp, items))}
    return out


# --- runs --------------------------------------------------------------------------------------------


def start_run(wp_id: str, *, mode: str, expected_assignment_revision: int, input_hash: str, actor: str,
              rerun_of: str | None = None, scope: str = "all") -> dict[str, Any]:
    """Idempotent start with a pinned input: one queue job per item, with a run-level cost budget.

    Rerun (057): for the same input and recipe, starting returns the existing run; `rerun_of` (the run being repeated)
    asks for a new run. A repeated request with the same `rerun_of` still yields only one new run (against double
    clicks); an active run cannot be rerun.

    160-C S3: `scope="pending"` takes only the package's pending items in `mode`, with the input hash, budget and plan
    of the readiness check's `supplement` for that mode. It does not start while another run of the package is queued
    or running (its items would be pending there too); a repeated request returns the same run, and once that run was
    stopped or failed, the same pending items can be started again."""
    if mode not in ("shadow", "apply"):
        raise ValueError("mode must be shadow or apply")
    if scope not in ("all", "pending"):
        raise ValueError("scope must be all or pending")
    if scope == "pending" and rerun_of is not None:
        raise ValueError("a run over the pending items is not a rerun")
    if rerun_of is not None:
        prev = get_run(rerun_of)
        if prev["workpackage_id"] != wp_id:
            raise ValueError("rerun_of belongs to another workpackage")
        if prev["status"] in ("queued", "running"):
            raise explained(ValueError, "run is still active; stop it before rerunning")
    ready = readiness(wp_id, verify=True)
    if ready["assignment_revision"] != expected_assignment_revision:
        raise explained(RevisionConflict, "assignment is at revision {{assignment_revision}}, not {{expected_assignment_revision}}",
                        assignment_revision=ready["assignment_revision"], expected_assignment_revision=expected_assignment_revision)
    if scope == "pending":
        offer = ready.get("supplement", {}).get(mode)
        if offer is None or offer["input_hash"] != input_hash:
            raise explained(RevisionConflict, "the package's pending items changed since the readiness check")
        ready = {**ready, **{k: offer[k] for k in ("ready", "blockers", "budget", "plan")}}
    elif ready["input_hash"] != input_hash:
        raise explained(RevisionConflict, "workpackage input changed since readiness check")
    if not ready["ready"]:
        raise explained(NotReady, "workpackage is not ready", ready["blockers"])
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    with store.connect() as c:
        _begin(c)
        # 066 Á19: the frozen input is read under the write lock (nobody else can write meanwhile), and it is exactly
        # what the readiness check saw; an edit in between is a conflict, not a run with an unchecked input
        wp = get(wp_id)
        a = wp["assignment"]
        if scope == "pending":
            pending = set(pending_items(wp_id, mode, wp))
            snapshot = _input_snapshot(wp, [i for i in wp["items"] if i["item_id"] in pending])
        else:
            snapshot = _input_snapshot(wp)
        if (a["revision"] if a else 0) != expected_assignment_revision or _snapshot_hash(snapshot) != input_hash:
            raise explained(RevisionConflict, "workpackage changed while the run was being started")
        if a is None:  # 080: the default settings the readiness check used are saved, in the starter's name
            d = default_recipe()
            # data (the assignment history, shown in the UI as written), not a label
            # 160-D: with the engine the readiness check (its budget) used, even if the application's changed since
            _insert_assignment(c, wp_id, d, default_params(d, "jev" if ready["plan"]["jev"] else "gpt"), expected_revision=0, actor=actor,
                               note="alapbeállítás, a futás indításakor mentve")
            a = current_assignment(wp_id, c)
        r = recipe(a["recipe_id"])
        dedup = f"{wp_id}:{a['revision']}:{input_hash}:{mode}" + (f":rerun:{rerun_of}" if rerun_of else "")
        if scope == "pending":
            # a stopped or failed run over the same pending items does not stand in the way of a new one: the key
            # counts them (a double click meanwhile counts the same, so it gets the run the first click started)
            ended = c.execute("SELECT COUNT(*) FROM runs WHERE workpackage_id=? AND mode=? AND status IN ('cancelled','failed')",
                              (wp_id, mode)).fetchone()[0]
            dedup += f":pending:{ended}"
        existing = c.execute("SELECT run_id, input FROM runs WHERE dedup_key=?", (dedup,)).fetchone()
        if not existing and scope == "pending" and c.execute(
                "SELECT 1 FROM runs WHERE workpackage_id=? AND status IN ('queued','running')", (wp_id,)).fetchone():
            raise explained(NotReady, "another run of the package is still going; start the pending items after it",
                            [{"code": "run_active", "message": "Another run of the package is still going."}])
        if not existing:
            c.execute("INSERT INTO runs(run_id, workpackage_id, dedup_key, mode, assignment_revision, recipe_id, recipe_version, recipe_hash,"
                      " recipe, params, input, input_hash, status, actor, created_at, plan, scope) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'queued',?,?,?,?)",
                      (run_id, wp_id, dedup, mode, a["revision"], r["id"], r["version"], recipe_hash(r), _canon(r), _canon(a["params"]),
                       _canon(snapshot), input_hash, actor, _now(), _canon(ready["plan"]), "pending" if scope == "pending" else None))
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
    out["excluded_items"] = json.loads(out["excluded_items"]) if out.get("excluded_items") else []
    out["items"] = items
    out["jobs"] = queue.counts(run_id=run_id)
    return out


def run_rows(wp_id: str | None = None) -> list[dict[str, Any]]:
    """Runs as list rows, in one query, without truncation (056 U1 dataset): package name, item count, the finished
    items and the run's own open to-do reasons (the item's flow identifier starts with `<run>:`)."""
    sql = ("SELECT r.run_id, r.workpackage_id, w.name AS workpackage_name, r.recipe_id, r.recipe_version, r.mode, r.status,"
           " r.approval, r.approved_by, r.actor, r.created_at, r.finished_at, r.scope,"
           " json_array_length(r.input, '$.items') AS items,"
           " (SELECT COUNT(*) FROM run_items i WHERE i.run_id=r.run_id) AS items_done,"
           # 153 (review B4): a range on the item flow ids `<run>:...` (';' follows ':'), so the index is used
           " (SELECT COUNT(*) FROM review_reasons x WHERE x.status='open' AND x.run_id >= r.run_id || ':'"
           " AND x.run_id < r.run_id || ';'"
           # 160-C (decision 163 D7): not the to-dos of an item left out of the release (as `excluded_items` says)
           " AND NOT EXISTS (SELECT 1 FROM workpackage_items wi WHERE r.approval IS NULL AND wi.workpackage_id=r.workpackage_id"
           " AND wi.removed_revision IS NOT NULL AND x.run_id = r.run_id || ':' || substr(wi.item_id, 1, 16))"
           " AND NOT EXISTS (SELECT 1 FROM json_each(COALESCE(r.excluded_items, '[]')) e WHERE r.approval IS NOT NULL"
           " AND x.run_id = r.run_id || ':' || substr(e.value, 1, 16))) AS open_reasons"
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


def pending_items(wp_id: str, mode: str, wp: dict[str, Any] | None = None) -> list[str]:
    """160-C S2/S3 (pending item): the package's items in use that no run of the package in `mode` (shadow / apply)
    has finished — a cancelled or superseded run does not count, a failed item stays pending. In package order. `wp`:
    the package already read (`get`), if at hand."""
    with store.connect() as c:
        done = {r["item_id"] for r in c.execute(
            "SELECT DISTINCT ri.item_id FROM run_items ri JOIN runs r ON r.run_id=ri.run_id WHERE r.workpackage_id=?"
            " AND r.mode=? AND r.status<>'cancelled' AND ri.status='done'", (wp_id, mode))}
    return [i["item_id"] for i in (wp or get(wp_id))["items"] if i["item_id"] not in done]


def item_states(wp_id: str, items: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """168 (plan F-item-list-and-adding; the rule of plan F-flexible work package S4): per item, its state in the package
    and the run whose result counts now (`package_result.counted_results`, 171: the rule in one place): the latest
    finished one of an approved live run, else of a live run, else of a trial run; a stopped or superseded run does not
    count. State: `approved` / `live` / `trial` by that result; `running` while a queued or running run still has the
    item to do (the counted result stays beside it); otherwise `failed` if a run failed it, else `pending`."""
    from jav import package_result

    with store.connect() as c:
        counted = package_result.counted_results(wp_id, c)
        failed = {r["item_id"] for r in c.execute(
            "SELECT DISTINCT ri.item_id FROM run_items ri JOIN runs r ON r.run_id=ri.run_id"
            " WHERE r.workpackage_id=? AND r.status<>'cancelled' AND ri.status='failed'", (wp_id,))}
        active = [(r["run_id"], json.loads(r["input"])) for r in c.execute(
            "SELECT run_id, input FROM runs WHERE workpackage_id=? AND status IN ('queued', 'running')", (wp_id,))]
        finished = {(r["run_id"], r["item_id"]) for r in c.execute(
            "SELECT ri.run_id, ri.item_id FROM run_items ri JOIN runs r ON r.run_id=ri.run_id"
            " WHERE r.workpackage_id=? AND r.status IN ('queued', 'running') AND ri.status='done'", (wp_id,))}
    running = {i["item_id"] for run_id, given in active for i in given["items"] if (run_id, i["item_id"]) not in finished}
    out = {}
    for item in items:
        iid = item["item_id"]
        best = counted.get(iid)
        state = ("running" if iid in running else best.tier if best else "failed" if iid in failed else "pending")
        out[iid] = {"state": state, "run_id": best.run_id if best else None, "mode": best.mode if best else None,
                    "run_at": best.created_at if best else None, "final_status": best.final_status if best else None}
    return out


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
    name of the email's folder, written by the receiver and used by the email flow, 048 T2). 177: the item kind's
    (`jav/item_kinds.py`)."""
    return item_kinds.of(item).subject(item)


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
    """`item_reasons` for several items, with one store query (061: instead of the list views' per-item queries).
    150: an earlier reason carries `trial`: it was raised by a trial run (the interface hides those by default)."""
    by_subject = store.review_open_reasons_many([review_subject(i) for i in items])
    trial = trial_runs(r["run_id"] for rs in by_subject.values() for r in rs)
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for i in items:
        own = flow_run_id(run_id, i["item_id"])
        split: dict[str, list[dict[str, Any]]] = {"run": [], "earlier": []}
        for r in by_subject[review_subject(i)]:
            if is_own_reason(r, own):
                split["run"].append(r)
            else:
                split["earlier"].append({**r, "trial": owning_run(r) in trial})
        out[i["item_id"]] = split
    return out


def owning_run(reason: dict[str, Any]) -> str:
    """The work run a to-do reason was raised in (its flow identifier is `<run>:<item>`); a command-line measurement's
    identifier has no such part and names no run."""
    return (reason.get("run_id") or "").split(":", 1)[0]


def trial_runs(flow_run_ids: Iterable[str | None]) -> set[str]:
    """150: which of the work runs behind these flow identifiers are trial runs."""
    owners = sorted({(rid or "").split(":", 1)[0] for rid in flow_run_ids} - {""})
    found: set[str] = set()
    with store.connect() as c:
        for start in range(0, len(owners), 500):  # stays under the SQLite parameter limit
            chunk = owners[start:start + 500]
            found |= {r["run_id"] for r in c.execute(
                f"SELECT run_id FROM runs WHERE mode='shadow' AND run_id IN ({','.join('?' * len(chunk))})", chunk)}
    return found


def _removed_from_package(c: sqlite3.Connection, run: dict[str, Any]) -> list[str]:
    """The run's input items that are removed from its package now, in input order."""
    removed = {r["item_id"] for r in c.execute("SELECT item_id FROM workpackage_items WHERE workpackage_id=?"
                                               " AND removed_revision IS NOT NULL", (run["workpackage_id"],))}
    return [i["item_id"] for i in run["input"]["items"] if i["item_id"] in removed]


def excluded_items(run: dict[str, Any]) -> list[str]:
    """160-C (decision 163 D7): the run's items whose result is not released. For an approved run, those removed from
    its package before the approval (recorded with it, so a later removal or restore changes nothing: decision 160
    D1); for any other run, those removed now."""
    if run.get("approval"):
        return list(run.get("excluded_items") or [])
    with store.connect() as c:
        return _removed_from_package(c, run)


def released_items(run: dict[str, Any]) -> list[dict[str, Any]]:
    """160-C: the run's input items whose result counts (the input without `excluded_items`)."""
    excluded = set(excluded_items(run))
    return [i for i in run["input"]["items"] if i["item_id"] not in excluded]


def open_reasons_for_run(run_id: str) -> int:
    """The run's OWN open to-do reasons (the reasons raised under the items' flow identifiers). 160-C: an item removed
    from the package does not count; its result is not released (decision 163 D7)."""
    run = get_run(run_id)
    return sum(len(s["run"]) for s in items_reasons(run_id, released_items(run)).values())


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
    elif run.get("stopped_at"):  # 160 (review R-4): a person's stop ends as stopped, whatever an earlier item did
        status = "cancelled"
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
        raise explained(RevisionConflict, "review reason {{reason_id}} is already {{status}}",
                        reason_id=reason_id, status=row["status"])
    store.review_resolve(reason_id, actor=actor, resolution=resolution, note=note)
    owner = (row["run_id"] or "").split(":", 1)[0]
    run_status = None
    with store.connect() as c:
        hit = c.execute("SELECT status FROM runs WHERE run_id=?", (owner,)).fetchone()
    if hit is not None and hit["status"] in ("needs_review", "done"):
        run_status = refresh_run_status(owner)
    return {"reason_id": reason_id, "status": "resolved", "actor": actor, "run_status": run_status}


STOPPABLE = ("queued", "running")  # 160 (review R-3): a finished run is superseded instead (`supersede_run`)


def cancel_run(run_id: str, *, actor: str | None = None) -> dict[str, int]:
    """Queued items stop at once, an active one at the next step boundary. 066 Á35: the actor (if any) goes into the
    package's event log. 082: the run's jobs are stopped in one step (`queue.cancel_run_jobs`); with an item still
    running, the run's status is refreshed here too (the worker's own refresh after that item ends it as cancelled).

    160 (review R-3): only a queued or running run can be stopped (`RevisionConflict` otherwise, also when it finishes
    meanwhile: the write is conditional). R-4: the stop is noted on the run (`stopped_at`, `stopped_by`), so it ends
    cancelled even when an earlier item failed."""
    with store.connect() as c:
        store.begin_immediate(c)
        row = c.execute("SELECT workpackage_id, status FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        if row["status"] not in STOPPABLE:
            raise explained(RevisionConflict, "the run is {{status}}: only a queued or running run can be stopped; supersede a finished one instead",
                            status=row["status"])
        c.execute("UPDATE runs SET stopped_at=?, stopped_by=? WHERE run_id=?", (_now(), actor, run_id))
        if actor is not None:
            _event(c, row["workpackage_id"], "run_cancel", actor, {"run_id": run_id})
    out = queue.cancel_run_jobs(run_id)
    if out.get("cancel_requested"):
        refresh_run_status(run_id)
    else:
        with store.connect() as c:
            c.execute("UPDATE runs SET status='cancelled', finished_at=? WHERE run_id=? AND status IN ('queued','running')",
                      (_now(), run_id))
    return out


SUPERSEDABLE = ("needs_review", "done", "failed")  # a finished live run (151)


def _superseding_run(c: sqlite3.Connection, run: dict[str, Any]) -> str | None:
    """151: the latest LATER live run of the same package that has finished (to-dos raised, not cancelled) and has
    every item of `run` among its own items; None if there is none."""
    items = {i["item_id"] for i in run["input"]["items"]}
    rows = c.execute("SELECT r.run_id, r.input FROM runs r, runs o WHERE o.run_id=? AND r.workpackage_id=o.workpackage_id"
                     " AND r.mode='apply' AND r.status IN ('needs_review','done') AND (r.created_at, r.rowid) > (o.created_at, o.rowid)"
                     " ORDER BY r.created_at DESC, r.rowid DESC", (run["run_id"],)).fetchall()
    for r in rows:
        if items <= {i["item_id"] for i in json.loads(r["input"])["items"]}:
            return r["run_id"]
    return None


def _supersedable(c: sqlite3.Connection, run_id: str) -> bool:
    row = c.execute("SELECT mode, approval, status FROM runs WHERE run_id=?", (run_id,)).fetchone()
    return row is not None and row["mode"] == "apply" and row["approval"] is None and row["status"] in SUPERSEDABLE


def _own_reason_count(c: sqlite3.Connection, run_id: str, status: str) -> int:
    """The run's reasons in `status` (raised under its items' flow identifiers `<run>:<item>[-stage]`)."""
    return c.execute("SELECT COUNT(*) FROM review_reasons WHERE status=? AND substr(run_id, 1, ?) = ?",
                     (status, len(run_id) + 1, run_id + ":")).fetchone()[0]


def supersede_info(run_id: str) -> dict[str, Any] | None:
    """151: whether a person can supersede this run, and what the confirmation shows: the later live run that processed
    the same items again (`by`), the run's own open reasons that would close, and the human work done on it (closed
    reasons, corrected items), which stays with this run and is not carried over. None if it cannot be superseded:
    a trial, an approved or an active run, or no later finished live run covers its items."""
    from jav import corrections  # noqa: F401 - registers the corrections table

    run = get_run(run_id)
    with store.connect() as c:
        if not _supersedable(c, run_id):
            return None
        by = _superseding_run(c, run)
        if by is None:
            return None
        corrected = c.execute("SELECT COUNT(DISTINCT item_id) FROM run_item_corrections WHERE run_id=?", (run_id,)).fetchone()[0]
        return {"by": by, "open_reasons": _own_reason_count(c, run_id, "open"),
                "resolved_reasons": _own_reason_count(c, run_id, "resolved"), "corrected_items": corrected}


def open_live_runs(wp_id: str) -> list[str]:
    """160-C S3: the package's open live runs, oldest first: finished (to-dos raised, done, or failed), not approved,
    not stopped, and not repeated on all their items by a later finished live run (such a run is to be superseded, not
    reviewed: `supersede_info`). Each waits for a person; with a run over the pending items a package can have more
    than one, and its step is not done while one is open."""
    with store.connect() as c:
        rows = c.execute("SELECT run_id, input FROM runs WHERE workpackage_id=? AND mode='apply' AND approval IS NULL"
                         " AND status IN (?, ?, ?) ORDER BY created_at, rowid", (wp_id, *SUPERSEDABLE)).fetchall()
        return [r["run_id"] for r in rows
                if _superseding_run(c, {"run_id": r["run_id"], "input": json.loads(r["input"])}) is None]


def supersedable_runs(wp_id: str) -> list[dict[str, Any]]:
    """152: the package's older live runs a person can supersede, oldest first, each with the offer of its own page
    (`supersede_info`) and its start, so the package's processing section can offer them too."""
    with store.connect() as c:
        rows = c.execute("SELECT run_id, created_at FROM runs WHERE workpackage_id=? AND mode='apply' AND approval IS NULL"
                         " AND status IN (?, ?, ?) ORDER BY created_at, rowid", (wp_id, *SUPERSEDABLE)).fetchall()
    out = []
    for row in rows:
        info = supersede_info(row["run_id"])
        if info is not None:
            out.append({"run_id": row["run_id"], "created_at": row["created_at"], **info})
    return out


def supersede_run(run_id: str, *, actor: str) -> dict[str, Any]:
    """151 (decision of 2026-10-12): a person supersedes an older live run that a later live run has repeated. The run
    is kept as cancelled, its own open reasons close as `superseded` (they stay in the store), and the package's event
    log records who did it and which run superseded it. Checked and done in one transaction; `NotReady` if the run
    cannot be superseded (see `supersede_info`). The pin of 066 stays: no run closes another run's reasons by itself."""
    run = get_run(run_id)
    with store.connect() as c:
        _begin(c)
        by = _superseding_run(c, run) if _supersedable(c, run_id) else None
        if by is None:
            raise explained(NotReady, "only an unapproved, finished live run that a later finished live run has repeated can be superseded")
        c.execute("UPDATE runs SET status='cancelled', finished_at=COALESCE(finished_at, ?) WHERE run_id=?", (_now(), run_id))
        closed = store.close_run_reasons(c, run_id, status="superseded")
        detail = {"run_id": run_id, "superseded_by": by, "reasons_closed": closed}
        _event(c, run["workpackage_id"], "run_supersede", actor, detail)
    return detail


def superseded(run_id: str) -> dict[str, Any] | None:
    """151: who superseded the run, when and by which run (from the package's event log); None if it was not."""
    with store.connect() as c:
        row = c.execute("SELECT e.actor, e.detail, e.created_at FROM workpackage_events e JOIN runs r ON r.workpackage_id=e.workpackage_id"
                        " WHERE r.run_id=? AND e.action='run_supersede' AND json_extract(e.detail, '$.run_id')=?"
                        " ORDER BY e.rowid DESC LIMIT 1", (run_id, run_id)).fetchone()
    if row is None:
        return None
    detail = json.loads(row["detail"])
    return {"by": detail["superseded_by"], "actor": row["actor"], "at": row["created_at"], "reasons_closed": detail["reasons_closed"]}


def approve_run(run_id: str, *, actor: str, review_version: str | None = None,
                confirm_removed: int | None = None) -> dict[str, Any]:
    """Approval of a live run: only with finished items and no open to-do; who approved it and when is recorded.
    `review_version` (085, re-audit A01): the version of the result the approver saw (`corrections.review_version`);
    if a correction changed it since, `RevisionConflict`. Checked and recorded in one transaction, so a correction
    cannot slip between the check and the approval (and none is written after it: `corrections`).

    160-C (decision 163 D7): items removed from the package since the run started are left out of the approval: their
    results are not released and their to-dos do not block it. Then the approver confirms how many were removed
    (`confirm_removed`, the count shown); a missing or different count is `NotReady` (`removed_items`), so a removal
    made after the page was loaded is never approved unseen. The left-out items are recorded with the approval."""
    from jav import corrections

    run = get_run(run_id)
    if run["mode"] != "apply":
        raise explained(ValueError, "only apply runs can be approved")
    status = refresh_run_status(run_id)
    if status != "done":
        raise explained(NotReady, "run is {{status}}; approval needs a finished run without open review reasons",
                        status=status)
    done = {i["item_id"] for i in get_run(run_id)["items"] if i["status"] == "done"}
    if any(i["item_id"] not in done for i in released_items(run)):  # 063: every input item has a finished result
        raise explained(NotReady, "run has input items without a finished result")
    with store.connect() as c:
        _begin(c)
        from jav import native_results

        # Recheck the run, its items and its open reasons under the approval's write lock (153, review: the check above
        # ran before it, so a run superseded or stopped in between ended both cancelled and approved)
        latest = c.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if latest["status"] != "done":
            raise explained(NotReady, "The run is no longer ready for approval")
        removed = _removed_from_package(c, run)
        if removed and confirm_removed != len(removed):
            raise explained(NotReady, "{{removed}} of the run's items were removed from the package; their results are not released. Confirm the count to approve the rest.",
                            [{"code": "removed_items", "message": "Items were removed from the package after the run started", "count": str(len(removed))}], removed=len(removed))
        kept = [i for i in run["input"]["items"] if i["item_id"] not in set(removed)]
        for item in kept:
            result = c.execute("SELECT status FROM run_items WHERE run_id=? AND item_id=?",
                               (run_id, item["item_id"])).fetchone()
            if result is None or result["status"] != "done":
                raise explained(NotReady, "The run has an unfinished input item")
            subject_kind, subject_id = review_subject(item)
            # 167 (review R-10): the subject drives the join (`store.SUBJECT_REASONS`), not every open reason of the store
            reasons = c.execute("SELECT r.run_id FROM " + store.SUBJECT_REASONS
                                + " WHERE q.subject_kind=? AND q.subject_id=? AND r.status='open'",
                                (subject_kind, subject_id)).fetchall()
            if any(is_own_reason(dict(reason), flow_run_id(run_id, item["item_id"])) for reason in reasons):
                raise explained(NotReady, "The run still has open review reasons")
        native_items = [i for i in kept if native_results.native_item(run_id, i, c)]
        if native_items:
            if review_version is None:
                raise explained(RevisionConflict, "Native approval requires the exact reviewed version")
            for item in native_items:
                publication = native_results.get_publication(run_id, item["item_id"], c=c)
                if publication is None or publication.interpretation_outcome.status != "succeeded":
                    raise explained(NotReady, "Every native item needs a published successful interpretation")
                if publication.reading.status not in {"complete", "partial"}:
                    raise explained(NotReady, "The source reading is not suitable for approval")
                native_results.verify_publication(publication, c=c)
        if review_version is not None and corrections.review_version(run_id, c) != review_version:
            raise explained(RevisionConflict, "the result of run {{run_id}} changed since it was reviewed; review it again",
                            run_id=run_id)
        c.execute("UPDATE runs SET approval='approved', approved_by=?, approved_at=?, excluded_items=? WHERE run_id=?"
                  " AND approval IS NULL AND status='done'", (actor, _now(), json.dumps(removed) if removed else None, run_id))
    approved = get_run(run_id)
    rule = package_rule(run["workpackage_id"])
    if rule is not None and rule.after_approval is not None and approved["approval"]:
        try:
            rule.after_approval(approved)
        except Exception:  # noqa: BLE001 - the approval stands; the rule's failure is logged with its traceback
            logging.getLogger("jav.work").exception("the approval rule of package %s failed", run["workpackage_id"])
    return approved
