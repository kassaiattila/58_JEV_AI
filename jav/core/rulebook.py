"""218 (plan G-process-core P3a): the calculation snapshot - the code and the rules a run, an item, a case or an
approval was computed with.

Plain-language summary: every process (the worker, the local service) takes one snapshot when it starts: the
application's version, the commit and whether the working tree had uncommitted changes, and the content fingerprint of
every file under `configs/` (the rule files, the prompts, the schemas), with each JSON config's version. When a run
starts, an item is processed, a case starts or a person approves a package's version, the snapshot is linked to it in
the same transaction. Each file's content is stored once, by its fingerprint, so an earlier rule can be restored byte
for byte years later, and two snapshots show which files changed between them.

- `take(root)` builds a snapshot of a folder; `current()` is this process's, taken once: every JSON config is loaded
  through `cfg.load` at that moment, so the configs the process reads afterwards are the ones the snapshot names
  (`jav.runtime.preload` asks for it at start-up).
- `link_in(c, kind, subject)` stores the current snapshot (only the contents not stored yet) and links it to the
  subject; `of`, `get`, `changes` and `content` read them back.
- `later_in`, `store_content_in` (stage D, D-a): a file's contents stored after a given one, in order (where a key added
  since a case started takes the value it came with); a content a case read, stored under `<path>#effective`.

Limits: the commit names the code only when the working tree was clean (`dirty` says when it was not); a non-JSON
file read lazily after start-up and changed on disk in between is not the content the snapshot names.

Layer: shared core; it imports only the core's config loader, version and store.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jav.core import cfg, store
from jav.core.clock import utc_stamp as _now

RUN, RUN_ITEM, CASE, PACKAGE_VERSION = "run", "run_item", "case", "package_version"  # what a snapshot is linked to
ID_LEN = 16

store.register_schema("rulebook", """
CREATE TABLE IF NOT EXISTS rule_files (
    sha256        TEXT PRIMARY KEY,            -- the content's fingerprint; one row per distinct content
    path          TEXT NOT NULL,               -- under configs/, with '/', where the content was first seen
    version       TEXT,                        -- a JSON config's meta.version; NULL for another file
    content       BLOB NOT NULL,
    first_seen_at TEXT NOT NULL,
    first_commit  TEXT
);
CREATE TABLE IF NOT EXISTS calc_snapshots (
    snapshot_id   TEXT PRIMARY KEY,            -- the fingerprint of everything below
    app_version   TEXT NOT NULL,
    git_commit    TEXT,
    git_dirty     INTEGER,                     -- 1: uncommitted changes; NULL: not known
    files         TEXT NOT NULL,               -- JSON {path: sha256}
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshot_links (
    subject_kind  TEXT NOT NULL,               -- run | run_item | case | package_version
    subject_id    TEXT NOT NULL,
    snapshot_id   TEXT NOT NULL REFERENCES calc_snapshots(snapshot_id),
    linked_at     TEXT NOT NULL,
    PRIMARY KEY (subject_kind, subject_id)
);
CREATE INDEX IF NOT EXISTS ix_snapshot_links_snapshot ON snapshot_links(snapshot_id);
""")


@dataclass(frozen=True)
class RuleFile:
    path: str
    sha256: str
    version: str | None
    content: bytes = field(repr=False)


@dataclass(frozen=True)
class Snapshot:
    """The code and the rules of one process: `files` by path under `configs/`."""

    app_version: str
    commit: str | None
    dirty: bool | None
    files: dict[str, RuleFile]

    @property
    def snapshot_id(self) -> str:
        body = {"app_version": self.app_version, "commit": self.commit, "dirty": self.dirty,
                "files": {p: f.sha256 for p, f in sorted(self.files.items())}}
        text = json.dumps(body, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:ID_LEN]


def _json_version(data: bytes) -> str | None:
    try:
        meta = json.loads(data.decode("utf-8")).get("meta")
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return None
    return str(meta["version"]) if isinstance(meta, dict) and "version" in meta else None


def take(root: Path, *, app_version: str, commit: str | None, dirty: bool | None) -> Snapshot:
    """A snapshot of every file under `root` (its JSON files with their `meta.version`)."""
    files: dict[str, RuleFile] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        data = path.read_bytes()
        rel = path.relative_to(root).as_posix()
        files[rel] = RuleFile(rel, hashlib.sha256(data).hexdigest(), _json_version(data) if path.suffix == ".json" else None,
                              data)
    return Snapshot(app_version, commit, dirty, files)


_CURRENT: Snapshot | None = None


def current() -> Snapshot:
    """This process's snapshot, taken at the first call: every JSON config is loaded through `cfg.load` first (its
    cache then holds what the snapshot names)."""
    global _CURRENT
    if _CURRENT is None:
        from jav.core import version

        for name in cfg.all_names():
            cfg.load(name)
        info = version.commit_info()
        dirty = info["dirty"]
        _CURRENT = take(cfg.CONFIG_DIR, app_version=version.VERSION, commit=info["commit"] and str(info["commit"]),
                        dirty=dirty if isinstance(dirty, bool) else None)
    return _CURRENT


def reset() -> None:
    """Forget this process's snapshot (`cfg.reload`, tests): the next `current()` takes a new one."""
    global _CURRENT
    _CURRENT = None


cfg.on_reload(reset)


def store_in(c: sqlite3.Connection, snapshot: Snapshot) -> str:
    """Stores the snapshot and the contents not stored yet; returns its id. Idempotent."""
    sid = snapshot.snapshot_id
    if c.execute("SELECT 1 FROM calc_snapshots WHERE snapshot_id=?", (sid,)).fetchone():
        return sid
    now = _now()
    for f in snapshot.files.values():
        c.execute("INSERT INTO rule_files(sha256, path, version, content, first_seen_at, first_commit)"
                  " VALUES (?,?,?,?,?,?) ON CONFLICT(sha256) DO NOTHING",
                  (f.sha256, f.path, f.version, f.content, now, snapshot.commit))
    c.execute("INSERT INTO calc_snapshots(snapshot_id, app_version, git_commit, git_dirty, files, created_at)"
              " VALUES (?,?,?,?,?,?) ON CONFLICT(snapshot_id) DO NOTHING",
              (sid, snapshot.app_version, snapshot.commit, None if snapshot.dirty is None else int(snapshot.dirty),
               json.dumps({p: f.sha256 for p, f in sorted(snapshot.files.items())}, separators=(",", ":")), now))
    return sid


def link_in(c: sqlite3.Connection, kind: str, subject: str, snapshot: Snapshot | None = None) -> str:
    """Links the subject to the snapshot (this process's by default) in the caller's transaction; a later link of the
    same subject replaces it (an item processed again). Returns the snapshot's id."""
    if kind not in (RUN, RUN_ITEM, CASE, PACKAGE_VERSION):
        raise ValueError(f"unknown snapshot subject kind: {kind!r}")
    sid = store_in(c, snapshot or current())
    c.execute("INSERT INTO snapshot_links(subject_kind, subject_id, snapshot_id, linked_at) VALUES (?,?,?,?)"
              " ON CONFLICT(subject_kind, subject_id) DO UPDATE SET snapshot_id=excluded.snapshot_id,"
              " linked_at=excluded.linked_at", (kind, subject, sid, _now()))
    return sid


EFFECTIVE = "#effective"  # D-a: the mark of a stored content a case read (its kept copy with the keys added since)


def later_in(c: sqlite3.Connection, path: str, sha256: str) -> list[bytes]:
    """Stage D (D-a): the contents of the file at `path` stored after the one with this fingerprint, oldest first (a
    process stores its configs when it starts, `jav.runtime.preload`); none when that one is not stored."""
    return [bytes(r["content"]) for r in c.execute(
        "SELECT content FROM rule_files WHERE path=? AND rowid > (SELECT rowid FROM rule_files WHERE sha256=?) ORDER BY rowid",
        (path, sha256))]


def store_content_in(c: sqlite3.Connection, path: str, version: str | None, content: bytes) -> str:
    """D-a: one content stored by its fingerprint (once), under `path`; returns the fingerprint."""
    sha = hashlib.sha256(content).hexdigest()
    c.execute("INSERT INTO rule_files(sha256, path, version, content, first_seen_at, first_commit) VALUES (?,?,?,?,?,?)"
              " ON CONFLICT(sha256) DO NOTHING", (sha, path, version, content, _now(), None))
    return sha


def run_item_subject(run_id: str, item_id: str) -> str:
    return f"{run_id}/{item_id}"


def of_in(c: sqlite3.Connection, kind: str, subject: str) -> str | None:
    """The snapshot linked to the subject; None for one made before snapshots (218)."""
    row = c.execute("SELECT snapshot_id FROM snapshot_links WHERE subject_kind=? AND subject_id=?",
                    (kind, subject)).fetchone()
    return row["snapshot_id"] if row else None


def of_run_in(c: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    """A run's snapshots: the one it started with and those its items were processed with (by item)."""
    prefix = run_id + "/"  # the items' subjects sort between "<run>/" and "<run>0" ('0' follows '/')
    items = {r["subject_id"][len(prefix):]: r["snapshot_id"] for r in c.execute(
        "SELECT subject_id, snapshot_id FROM snapshot_links WHERE subject_kind=? AND subject_id >= ? AND subject_id < ?",
        (RUN_ITEM, prefix, run_id + "0"))}
    return {"start": of_in(c, RUN, run_id), "items": items}


def get_in(c: sqlite3.Connection, snapshot_id: str) -> dict[str, Any] | None:
    """A stored snapshot: version, commit, dirty, the files by path with their fingerprint and version."""
    row = c.execute("SELECT * FROM calc_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
    if row is None:
        return None
    files: dict[str, str] = json.loads(row["files"])
    shas = sorted(set(files.values()))
    versions: dict[str, str | None] = {}
    for n in range(0, len(shas), 500):  # well under every database's limit of bound values
        part = shas[n:n + 500]
        versions.update((r["sha256"], r["version"]) for r in c.execute(
            f"SELECT sha256, version FROM rule_files WHERE sha256 IN ({','.join('?' * len(part))})", part))  # noqa: S608 - placeholders only
    return {"snapshot_id": snapshot_id, "app_version": row["app_version"], "commit": row["git_commit"],
            "dirty": None if row["git_dirty"] is None else bool(row["git_dirty"]), "created_at": row["created_at"],
            "files": {p: {"sha256": s, "version": versions.get(s)} for p, s in files.items()}}


def changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """The files that differ between two stored snapshots (`get_in`): path, and the version and fingerprint before
    and after (None where the file is missing on that side)."""
    a, b = before["files"], after["files"]
    out = []
    for path in sorted(set(a) | set(b)):
        x, y = a.get(path), b.get(path)
        if (x or {}).get("sha256") != (y or {}).get("sha256"):
            out.append({"path": path, "before": x and x["version"], "after": y and y["version"],
                        "before_sha256": x and x["sha256"], "after_sha256": y and y["sha256"]})
    return out


def content_in(c: sqlite3.Connection, sha256: str) -> bytes | None:
    """A stored file's content by its fingerprint (to restore an earlier rule)."""
    row = c.execute("SELECT content FROM rule_files WHERE sha256=?", (sha256,)).fetchone()
    return bytes(row["content"]) if row else None


__all__ = ["CASE", "EFFECTIVE", "PACKAGE_VERSION", "RUN", "RUN_ITEM", "RuleFile", "Snapshot", "changes", "content_in", "current",
           "get_in", "later_in", "link_in", "of_in", "of_run_in", "reset", "run_item_subject", "store_content_in", "store_in", "take"]
