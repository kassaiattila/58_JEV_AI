"""Settings (057, decision of 2026-09-28): the user name list and the watched work folders.

**Users:** the choices of "Ki dolgozik?" (Who is working?). Kept only in the local store (a name is personal data and
never goes into git).

**Watched work folders** — modelled on the legacy V4 "Figyelt mappák" (watched folders) behaviour
(`orchestrator/framework/intakeconfig.py`, `scripts/intake_bridge.ps1`, read only): per folder a name, a path, whether
it is enabled, whether subfolders are included, the packaging (`folder` = one shared package, `daily` = daily packages),
an optional recipe and a scan interval. The worker scans the folder periodically (`tick`); new documents become a
package or extend the existing one. Differences from the legacy version:
- the path must lie under the allowed roots (the legacy version did not check this on save);
- the source folder is only read (nothing is moved or deleted); a file still being written is skipped while it changes
  between two scans (the wait of the legacy `watch.py`); a file already seen (path + size + modification time) is not
  hashed again;
- a document removed from the package by hand does not come back; no paid run starts by itself (the recipe is only
  assigned, as for a package arriving from a mailbox, decision 048).

**Output folder** (078): where the content-named copies of a run are written (`jav/app/naming.py`). It may not overlap a
watched folder in either direction, so the watcher never takes the copies in again.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from jav.app import work, work_recipes
from jav.core import display, identity, store
from jav.documents.native_contracts import DOCUMENT_SUFFIXES
from jav.core import lock
from jav.core.user_messages import explained
from jav.core.clock import utc_now as _now

log = logging.getLogger("jav.folders")

store.register_schema("app_settings", """
CREATE TABLE IF NOT EXISTS app_users (
    name        TEXT PRIMARY KEY COLLATE NOCASE,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watched_folders (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    path        TEXT NOT NULL,
    enabled     INTEGER NOT NULL,
    recursive   INTEGER NOT NULL,
    batch_mode  TEXT NOT NULL,                 -- folder | daily
    recipe_id   TEXT,
    params      TEXT NOT NULL,                 -- JSON
    interval_min INTEGER NOT NULL,
    next_at     TEXT,
    last_at     TEXT,
    last_status TEXT,                          -- ok | error
    last_result TEXT,                          -- JSON
    updated_at  TEXT NOT NULL
);
-- a mappa csomagjai: vödör = 'folder' vagy a nap (ÉÉÉÉ-HH-NN)
CREATE TABLE IF NOT EXISTS watched_packages (
    folder_id   TEXT NOT NULL,
    bucket      TEXT NOT NULL,
    workpackage_id TEXT NOT NULL,
    PRIMARY KEY (folder_id, bucket)
);
-- a már látott fájlok (útvonal + méret + módosítás ideje), hogy ne kelljen mindent újra hashelni
CREATE TABLE IF NOT EXISTS watched_seen (
    folder_id   TEXT NOT NULL,
    path        TEXT NOT NULL,
    size        INTEGER NOT NULL,
    mtime_ns    INTEGER NOT NULL,
    sha256      TEXT,
    PRIMARY KEY (folder_id, path)
);
""")
# 078: single-valued settings (the output folder of the content-named copies)
store.register_schema("app_options", """
CREATE TABLE IF NOT EXISTS app_options (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    actor       TEXT,
    actor_id    TEXT,               -- 229 (SZ2c): the stable id beside the name (`jav.core.identity`)
    updated_at  TEXT NOT NULL
);
""")
store.register_migration("app_options_actor_ids", lambda conn: store.add_actor_ids(conn, "app_options", ("actor",)))

SUFFIXES = DOCUMENT_SUFFIXES
OUTPUT_FOLDER_KEY = "output_folder"
SETTLE_S = 10  # a file modified more recently than this may still be being written: it waits for the next scan
DEFAULT_INTERVAL_MIN = 15


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat(timespec="seconds")


# --- users --------------------------------------------------------------------------------------------------


def users(c: sqlite3.Connection | None = None) -> list[str]:
    """The name list; with `c` (215) on the caller's connection, inside its transaction."""
    if c is None:
        with store.connect() as own:
            return users(own)
    return [r["name"] for r in c.execute("SELECT name FROM app_users ORDER BY name COLLATE NOCASE")]


def canonical_user(name: str, c: sqlite3.Connection | None = None) -> str | None:
    """061 (active user): the name in the form it has on the name list (ignoring case and the number of spaces);
    a name not on the list gives None. With an empty list any name is accepted (first setup: the list is not filled in
    yet, but authorship is mandatory even then). With `c` (215) on the caller's connection."""
    wanted = " ".join(name.split()).casefold()
    listed = users(c)
    if not listed:
        return " ".join(name.split())
    return next((u for u in listed if u.casefold() == wanted), None)


# The author-name rule (shared by the local service's `X-Actor` header and the name list, 066 Á25): letters (accented
# ones too), digits, space, dot, @ and hyphen, at most 64 characters.
ACTOR_RE = re.compile(r"^[\w.@ -]{1,64}$")


def save_users(names: list[str]) -> list[str]:
    """Replaces the whole name list. Empty and duplicate (case-insensitive) names are dropped; 066 Á25: a name that
    breaks the author rule (with which nothing could be done afterwards) is an error, and the list does not change."""
    clean: dict[str, str] = {}
    bad: list[str] = []
    for n in names:
        n = " ".join(str(n).split())
        if not n:
            continue
        if not ACTOR_RE.match(n):
            bad.append(n[:80])
            continue
        clean.setdefault(n.casefold(), n)
    if bad:
        raise ValueError("user names may contain letters, digits, space, dot, @ or hyphen (max 64): " + ", ".join(bad))
    if len(clean) > 200:
        raise explained(ValueError, "at most 200 users")
    with store.connect() as c:
        c.execute("DELETE FROM app_users")
        c.executemany("INSERT INTO app_users(name, created_at) VALUES (?,?)", [(n, _iso(_now())) for n in clean.values()])
    return users()


# --- watched work folders -----------------------------------------------------------------------------------


class WatchedFolder(BaseModel):
    """The settings of one watched folder (what the UI sends and receives)."""

    id: str | None = Field(default=None, max_length=40)
    name: str = Field(default="", max_length=160)
    path: str = Field(min_length=1, max_length=1024)
    enabled: bool = True
    recursive: bool = False
    batch_mode: Literal["folder", "daily"] = "folder"
    recipe_id: str | None = Field(default=None, max_length=100)
    params: dict[str, str] = Field(default_factory=dict, max_length=20)
    interval_min: int = Field(default=DEFAULT_INTERVAL_MIN, ge=5, le=7 * 24 * 60)


def _folder_row(r: Any) -> dict[str, Any]:
    d = dict(r)
    d["enabled"], d["recursive"] = bool(d["enabled"]), bool(d["recursive"])
    d["params"] = json.loads(d["params"])
    d["last_result"] = json.loads(d["last_result"]) if d["last_result"] else None
    return d


def folders() -> list[dict[str, Any]]:
    with store.connect() as c:
        return [_folder_row(r) for r in c.execute("SELECT * FROM watched_folders ORDER BY name COLLATE NOCASE")]


def save_folders(items: list[WatchedFolder], *, check_dir: Callable[[str], Path]) -> list[dict[str, Any]]:
    """Replaces the whole list (like the legacy V4 PUT). `check_dir`: the service's path check (under an allowed
    root, an existing folder) — on error nothing is saved. A folder that stays keeps its scan time and result."""
    if len(items) > 50:
        raise explained(ValueError, "at most 50 watched folders")
    known = {f["id"]: f for f in folders()}
    out = output_folder()
    rows = []
    for f in items:
        p = check_dir(f.path)
        if out and _overlaps(p, Path(out)):  # 078: the watcher would take the named copies in again
            raise explained(FolderOverlap, "a watched folder cannot overlap the output folder of the named copies: {{p}}",
                            p=p)
        recipe_id, params = f.recipe_id or None, f.params
        if recipe_id is not None and work_recipes.recipe_status(work_recipes.recipe(recipe_id)) == "retired":  # unknown: ValueError → 422
            # 080: the UI no longer shows the folder's recipe, so a retired one is moved onto the default processing
            # (keeping its settings) instead of making the whole list unsavable
            recipe_id, params = work_recipes.default_recipe()["id"], work_recipes.carried_params(work_recipes.default_recipe(), params)
        fid = f.id if f.id in known else f"wf-{uuid.uuid4().hex[:10]}"
        prev = known.get(fid)
        name = " ".join(f.name.split()) or p.name
        rows.append((fid, name, str(p), int(f.enabled), int(f.recursive), f.batch_mode, recipe_id, json.dumps(params, ensure_ascii=False),
                     f.interval_min, (prev or {}).get("next_at") or _iso(_now()), (prev or {}).get("last_at"),
                     (prev or {}).get("last_status"), json.dumps((prev or {}).get("last_result")) if prev and prev.get("last_result") else None,
                     _iso(_now())))
    with store.connect() as c:
        c.execute("DELETE FROM watched_folders")
        c.executemany("INSERT INTO watched_folders(id, name, path, enabled, recursive, batch_mode, recipe_id, params, interval_min,"
                      " next_at, last_at, last_status, last_result, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return folders()


def migrate_folder_recipes(*, write: bool) -> list[dict[str, Any]]:
    """080: watched folders set to a retired recipe move onto the default processing, keeping their settings (like
    `work_recipes.migrate_assignments`). Without `write` it only lists them; repeatable."""
    target = work_recipes.default_recipe()
    out = []
    for f in folders():
        if not f["recipe_id"] or work_recipes.recipe_status(work_recipes.recipe(f["recipe_id"])) != "retired":
            continue
        params = work_recipes.carried_params(target, f["params"])
        out.append({"id": f["id"], "name": f["name"], "from": f["recipe_id"], "params": params})
        if write:
            with store.connect() as c:
                c.execute("UPDATE watched_folders SET recipe_id=?, params=?, updated_at=? WHERE id=? AND recipe_id=?",
                          (target["id"], json.dumps(params, ensure_ascii=False), _iso(_now()), f["id"], f["recipe_id"]))
    return out


def _bucket(folder: dict[str, Any], now: datetime) -> str:
    return now.astimezone().strftime("%Y-%m-%d") if folder["batch_mode"] == "daily" else "folder"


def _package_for(folder: dict[str, Any], bucket: str) -> str | None:
    """The live package of the folder (or of the day). No new document goes into a hidden or deleted package (058): a
    new package is created instead; the files seen earlier stay on the seen list, so they are not processed again."""
    with store.connect() as c:
        row = c.execute("SELECT p.workpackage_id FROM watched_packages p JOIN workpackages w ON w.id = p.workpackage_id"
                        " WHERE p.folder_id=? AND p.bucket=? AND w.status <> 'archived'", (folder["id"], bucket)).fetchone()
    return row["workpackage_id"] if row else None


def _new_files(folder: dict[str, Any], now: datetime) -> tuple[list[tuple[Path, str, os.stat_result]], int, int]:
    """(new files with content hash and stat, the number of files still being written, the number of unreadable files).
    A file already seen is not hashed again. 063: the "seen" mark is not written here — only after a successful intake
    (`_mark_seen`) — and an unreadable (e.g. locked) file is skipped without aborting the scan; both wait for the next
    scan."""
    root = Path(folder["path"])
    walk = root.rglob("*") if folder["recursive"] else root.iterdir()
    out, settling, unreadable = [], 0, 0
    with store.connect() as c:
        seen = {r["path"]: r for r in c.execute("SELECT * FROM watched_seen WHERE folder_id=?", (folder["id"],))}
    for p in sorted(walk):
        if not p.is_file() or p.suffix.lower() not in SUFFIXES:
            continue
        rp = p.resolve()
        if not (rp == root or rp.is_relative_to(root)):  # a link pointing outside the folder is not taken in
            continue
        st = p.stat()
        if now.timestamp() - st.st_mtime < SETTLE_S:
            settling += 1
            continue
        prev = seen.get(str(rp))
        if prev and prev["size"] == st.st_size and prev["mtime_ns"] == st.st_mtime_ns:
            continue
        try:
            digest = work.sha256_file(rp)
        except OSError as exc:
            log.warning("watched folder %s: cannot read %s: %s", folder["id"], rp, exc)
            unreadable += 1
            continue
        out.append((rp, digest, st))
    return out, settling, unreadable


def _mark_seen(folder_id: str, files: list[tuple[Path, str, os.stat_result]]) -> None:
    with store.connect() as c:
        c.executemany("INSERT INTO watched_seen(folder_id, path, size, mtime_ns, sha256) VALUES (?,?,?,?,?) ON CONFLICT(folder_id, path)"
                      " DO UPDATE SET size=excluded.size, mtime_ns=excluded.mtime_ns, sha256=excluded.sha256",
                      [(folder_id, str(rp), st.st_size, st.st_mtime_ns, digest) for rp, digest, st in files])


# data: the name the package log and the settings history show for a scheduled scan (229: the machine's id beside it;
# 231, D4: the id is made of the name, so it stays as stored)
WATCHER = identity.machine("figyelt mappa")


DOCUMENTS = "documents"  # 231 (U2b): the process pack whose cases hold a watched folder's batches


def _own_case(wp_id: str, actor: identity.Who) -> None:
    """231 (U2b; the owner's decision of 2026-10-28: a watched folder starts a case): the batch gets a case of the
    documents process, its owner the batch's; its live run stays a person's action. A failure is logged and never loses
    the batch or the scan's outcome."""
    from jav.app import process_runtime  # lazy: the process packs build on the settings

    try:
        owner = work.get(wp_id).get("owner") or actor
        process_runtime.wrap_into(DOCUMENTS, wp_id, scope={}, actor=owner)
    except Exception:  # noqa: BLE001 - the batch stays, as an ordinary one
        log.exception("the watched folder's batch %s got no case", wp_id)


def scan(folder_id: str, *, now: datetime | None = None, actor: identity.Who = WATCHER) -> dict[str, Any]:
    """Scans one folder now: new documents go into the package of the folder (or of the day). The result is recorded on
    the folder too. 063: one folder is scanned by one process at a time (the "now" button and the scheduled scan cannot
    create two packages)."""
    now = now or _now()
    folder = next((f for f in folders() if f["id"] == folder_id), None)
    if folder is None:
        raise KeyError(folder_id)
    with lock.try_exclusive(store.current_path().with_name(f"watch-{folder_id}.lock")) as got:
        if not got:
            return {"status": "busy", "error": display.text("The scan is running right now; try again in a few seconds.")}
        return _scan(folder, now, actor)


def _scan(folder: dict[str, Any], now: datetime, actor: identity.Who) -> dict[str, Any]:
    try:
        files, settling, unreadable = _new_files(folder, now)
        bucket = _bucket(folder, now)
        wp_id = _package_for(folder, bucket)
        existing = set()
        if wp_id:
            with store.connect() as c:  # a document removed by hand is also "known": it does not come back
                existing = {r["item_id"] for r in c.execute("SELECT item_id FROM workpackage_items WHERE workpackage_id=?", (wp_id,))}
        fresh = [p for p, digest, _st in files if digest not in existing]
        fresh = list(dict.fromkeys(fresh))
        if fresh:
            if wp_id is None:
                name = folder["name"] if bucket == "folder" else f"{folder['name']} — {bucket}"
                # 065: whoever scans with the "now" button owns the package; a scheduled scan leaves the owner empty
                wp = work.create_workpackage(name=name, source_kind="watch", source_ref=folder["path"],
                                             owner=None if actor == WATCHER else actor)
                wp_id = wp["id"]
                with store.connect() as c:
                    c.execute("INSERT INTO watched_packages(folder_id, bucket, workpackage_id) VALUES (?,?,?) ON CONFLICT(folder_id, bucket)"
                              " DO UPDATE SET workpackage_id=excluded.workpackage_id", (folder["id"], bucket, wp_id))
                if folder["recipe_id"]:  # 080: without one, the package runs with the default processing settings
                    r = work_recipes.recipe(folder["recipe_id"])
                    if work_recipes.recipe_status(r) == "retired":  # not migrated yet (e.g. restored from a backup)
                        r, params = work_recipes.default_recipe(), work_recipes.carried_params(work_recipes.default_recipe(), folder["params"])
                    else:
                        params = folder["params"]
                    work_recipes.assign_recipe(wp_id, r["id"], params=params, expected_revision=0, actor=actor, note=WATCHER.name)
            wp = work.get(wp_id)
            work.add_documents(wp_id, fresh, expected_revision=wp["revision"])
            if not existing:  # U2b: a new batch gets its case of the documents process at once
                _own_case(wp_id, actor)
        _mark_seen(folder["id"], files)  # 063: "seen" only after a successful intake
        result = {"new": len(fresh), "settling": settling, "unreadable": unreadable,
                  "workpackage": wp_id if fresh else _package_for(folder, bucket)}
        status = "ok"
    except (OSError, ValueError) as exc:
        result, status = {"error": str(exc)}, "error"
    except Exception as exc:  # noqa: BLE001 - 063: e.g. concurrent package edit; error shown on the folder, files kept
        log.exception("watched folder %s scan failed", folder["id"])
        result, status = {"error": f"{type(exc).__name__}: {exc}"}, "error"
    with store.connect() as c:
        c.execute("UPDATE watched_folders SET last_at=?, last_status=?, last_result=?, next_at=? WHERE id=?",
                  (_iso(now), status, json.dumps(result, ensure_ascii=False), _iso(now + timedelta(minutes=folder["interval_min"])), folder["id"]))
    return {"status": status, **result}


def tick(now: datetime | None = None) -> list[str]:
    """Called by the worker each round: scans the enabled, due folders and returns their ids."""
    now = now or _now()
    due = [f["id"] for f in folders() if f["enabled"] and (f["next_at"] or "") <= _iso(now)]
    for fid in due:
        scan(fid, now=now)
    return due


# --- output folder of the content-named copies (078) --------------------------------------------------------


class FolderOverlap(ValueError):
    """The output folder and a watched folder (or the application's own data folders) overlap."""


class NoOutputFolder(ValueError):
    """Writing the named copies was asked for, but no output folder is set."""


def _overlaps(a: Path, b: Path) -> bool:
    a, b = a.resolve(), b.resolve()
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def check_output_folder(p: Path) -> Path:
    """The output folder may not lie inside a watched folder or contain one (the watcher would take the copies in
    again as new documents), nor overlap the store or the mailbox folders. Returns the resolved path; `ValueError`
    otherwise."""
    from jav.core.config import DATA_ROOT

    p = p.resolve()
    if not p.is_dir():
        raise explained(ValueError, "the output folder does not exist: {{p}}", p=p)
    for f in folders():
        if _overlaps(p, Path(f["path"])):
            raise explained(FolderOverlap, "the output folder cannot overlap the watched folder {{name}}",
                            name=repr(f["name"]))
    for internal in (DATA_ROOT / "store", DATA_ROOT / "inbox", DATA_ROOT / "runs"):  # 231 (E2): the data folder's
        if _overlaps(p, internal):
            raise explained(FolderOverlap, "the output folder cannot overlap the application's own data folders (store, inbox, runs)")
    return p


def output_folder() -> str | None:
    with store.connect() as c:
        row = c.execute("SELECT value FROM app_options WHERE key=?", (OUTPUT_FOLDER_KEY,)).fetchone()
    return row["value"] if row else None


def save_output_folder(path: str | None, *, check_dir: Callable[[str], Path], actor: identity.Who) -> str | None:
    """Sets (or with an empty value clears) the output folder. `check_dir`: the service's path check (an existing
    folder, under the allowed roots when they are restricted); then `check_output_folder`."""
    if not path or not path.strip():
        with store.connect() as c:
            c.execute("DELETE FROM app_options WHERE key=?", (OUTPUT_FOLDER_KEY,))
        return None
    p = check_output_folder(check_dir(path.strip()))
    with store.connect() as c:
        c.execute("INSERT INTO app_options(key, value, actor, actor_id, updated_at) VALUES (?,?,?,?,?) ON CONFLICT(key)"
                  " DO UPDATE SET value=excluded.value, actor=excluded.actor, actor_id=excluded.actor_id,"
                  " updated_at=excluded.updated_at",
                  (OUTPUT_FOLDER_KEY, str(p), identity.name_of(actor), identity.id_of(actor), _iso(_now())))
    return str(p)


# --- the AI engine (160-D, plan F-csak-gpt Sz4) -------------------------------------------------------------------

ENGINE_KEY = "engine"
ENGINES = ("jev", "gpt")  # JEV and GPT (the default, decision 160) | GPT only, without JEV
DEFAULT_ENGINE = "jev"


def engine_setting() -> dict[str, Any]:
    """The application's AI engine with who set it and when (both None while it is the default)."""
    with store.connect() as c:
        row = c.execute("SELECT value, actor, updated_at FROM app_options WHERE key=?", (ENGINE_KEY,)).fetchone()
    if row is None:
        return {"engine": DEFAULT_ENGINE, "actor": None, "updated_at": None}
    return {"engine": row["value"], "actor": row["actor"], "updated_at": row["updated_at"]}


def engine_default() -> str:
    """The engine of every new processing setting that does not name one (`work_recipes.default_params`); saved settings and
    runs keep their own."""
    return engine_setting()["engine"]


def save_engine_default(engine: str, *, actor: identity.Who) -> dict[str, Any]:
    if engine not in ENGINES:
        raise explained(ValueError, "unknown engine {{engine}}; expected one of {{engines}}",
                        engine=repr(engine), engines=list(ENGINES))
    with store.connect() as c:
        c.execute("INSERT INTO app_options(key, value, actor, actor_id, updated_at) VALUES (?,?,?,?,?) ON CONFLICT(key)"
                  " DO UPDATE SET value=excluded.value, actor=excluded.actor, actor_id=excluded.actor_id,"
                  " updated_at=excluded.updated_at",
                  (ENGINE_KEY, engine, identity.name_of(actor), identity.id_of(actor), _iso(_now())))
    log.info("AI engine set to %s by %s", engine, identity.name_of(actor))
    return engine_setting()


__all__ = ["WatchedFolder", "check_output_folder", "engine_default", "engine_setting", "folders", "output_folder",
           "save_engine_default", "save_folders", "save_output_folder", "save_users", "scan", "tick", "users"]
