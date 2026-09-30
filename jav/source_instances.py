"""Source instances: an unchanging copy of every document added to a work package.

When a document enters a work package, its bytes are copied once into a content-addressed store next to the SQLite
store (`store/sources/<first two hex digits>/<sha256><suffix>`); the same content in several packages is kept once.
Processing, the source view, the page images, the item view and the named copies read this copy, so what a person
checks is exactly what the result was made from, even if the original file is later changed, moved or deleted. The
original path stays the displayed and stored path; a change to the original is reported, not hidden (`jav.work`).

Emails (`message.json` under `inbox/`) get no instance: they are already the system's own copies, and the email flow
reads the whole message folder.

A stored copy is released when no work package item refers to it any more (deleting a package without runs, or a
failed intake). Retention beyond that belongs to the data inventory (not decided yet).
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path

from jav import store

CHUNK = 1 << 20
_REL = re.compile(r"^[0-9a-f]{2}/[0-9a-f]{64}(\.[a-z0-9]{1,8})?$")
_SUFFIX = re.compile(r"^\.[a-z0-9]{1,8}$")


def root() -> Path:
    """The store of the instances: next to the store in use (tests with their own store get their own folder)."""
    return store.current_path().parent / "sources"


def relative_path(sha256: str, suffix: str) -> str:
    suffix = suffix.lower()
    return f"{sha256[:2]}/{sha256}{suffix if _SUFFIX.match(suffix) else ''}"


def path_of(rel: str) -> Path:
    """The instance file of a recorded relative path. Only the store's own shape is accepted, so a stored value can
    never point outside the instance folder."""
    if not _REL.match(rel):
        raise ValueError(f"not a source instance path: {rel!r}")
    return root() / rel


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def intact(path: Path, sha256: str) -> bool:
    """The file exists and its full content hash is `sha256`."""
    try:
        return path.is_file() and sha256_file(path) == sha256
    except OSError:
        return False


def freeze(path: Path) -> tuple[str, str]:
    """Copies `path` into the store with one read, hashing the bytes as they are copied; returns (sha256, relative
    path). The fingerprint is that of the copied bytes, so the instance and the recorded fingerprint always agree. An
    intact instance with the same fingerprint is kept; a damaged one is replaced."""
    base = root()
    base.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=base, prefix=".incoming-", suffix=".part")
    tmp: Path | None = Path(tmp_name)
    try:
        h = hashlib.sha256()
        with os.fdopen(fd, "wb") as out, open(path, "rb") as src:
            for chunk in iter(lambda: src.read(CHUNK), b""):
                h.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        digest = h.hexdigest()
        rel = relative_path(digest, Path(path).suffix)
        target = base / rel
        if not intact(target, digest):
            target.parent.mkdir(exist_ok=True)
            os.replace(tmp, target)
            tmp = None
        return digest, rel
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def release(rels: Iterable[str]) -> list[str]:
    """Deletes the given instances that no work package item (in any package, removed items included) refers to any
    more; returns the deleted relative paths."""
    removed = []
    with store.connect() as c:
        for rel in sorted(set(r for r in rels if r)):
            if c.execute("SELECT 1 FROM workpackage_items WHERE instance=? LIMIT 1", (rel,)).fetchone() is None:
                path_of(rel).unlink(missing_ok=True)
                removed.append(rel)
    return removed


def files() -> list[Path]:
    """Every instance file in the store (for the backup)."""
    base = root()
    if not base.is_dir():
        return []
    return sorted(p for p in base.glob("??/*") if p.is_file() and _REL.match(p.relative_to(base).as_posix()))


__all__ = ["freeze", "files", "intact", "path_of", "relative_path", "release", "root", "sha256_file"]
