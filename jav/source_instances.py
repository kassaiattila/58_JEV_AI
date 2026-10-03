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

A document over the input limit gets no instance (085, re-audit A03): the intake checks the size before copying, and
the copy itself stops at the limit (a file growing while it is copied), so such a file never fills the disk; its item
is stopped by the named size error when it is processed, as before.
"""

from __future__ import annotations

import errno
import hashlib
import logging
import os
import re
import shutil
import stat
import tempfile
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from jav import store
from jav.runtime import lock

CHUNK = 1 << 20
SPACE_HEADROOM = 1 << 20
log = logging.getLogger(__name__)
_PART = re.compile(r"^\.incoming-([0-9a-f]{32})-[a-z0-9_]+\.part$")
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


class InstanceTooLarge(ValueError):
    """085 (re-audit A03): the file is larger than the byte limit of the copy; nothing was kept."""


class InstanceStorageFull(ValueError):
    """The source copy cannot be stored; intake must not record it as a successful item."""


def _require_space(base: Path, required: int) -> None:
    if shutil.disk_usage(base).free < required + SPACE_HEADROOM:
        raise InstanceStorageFull("Insufficient disk space for a source copy; free space and try again.")


def _remove_lease(lease: Path) -> None:
    try:
        lease.unlink(missing_ok=True)
    except OSError as exc:
        # A concurrent collector may still have the lease open on Windows. The empty lease is harmless.
        log.warning("Could not remove source copy lease %s: %s", lease.name, type(exc).__name__)


def freeze(path: Path, *, max_bytes: int | None = None) -> tuple[str, str]:
    """Copies `path` into the store with one read, hashing the bytes as they are copied; returns (sha256, relative
    path). The fingerprint is that of the copied bytes, so the instance and the recorded fingerprint always agree. An
    intact instance with the same fingerprint is kept; a damaged one is replaced. `max_bytes` (085): the copy stops
    with `InstanceTooLarge` as soon as it passes this many bytes. Space is checked before and during the copy;
    a storage shortage raises `InstanceStorageFull`. Failed copies are removed, and a process lock protects active
    temporary files from explicit maintenance."""
    try:
        return _freeze(path, max_bytes=max_bytes)
    except OSError as exc:
        if exc.errno in (errno.ENOSPC, errno.EDQUOT) or getattr(exc, "winerror", None) in (39, 112):
            raise InstanceStorageFull("Insufficient disk space for a source copy; free space and try again.") from exc
        raise


def _freeze(path: Path, *, max_bytes: int | None) -> tuple[str, str]:
    base = root()
    base.mkdir(parents=True, exist_ok=True)
    size = path.stat().st_size
    if max_bytes is not None and size > max_bytes:
        raise InstanceTooLarge(f"{path.name}: more than {max_bytes} bytes")
    _require_space(base, size)
    token = uuid.uuid4().hex
    lease = base / f".incoming-{token}.lock"
    try:
        with lock.single_instance(lease):
            fd, tmp_name = tempfile.mkstemp(dir=base, prefix=f".incoming-{token}-", suffix=".part")
            tmp = Path(tmp_name)
            try:
                h = hashlib.sha256()
                copied = 0
                with os.fdopen(fd, "wb", buffering=0) as out, open(path, "rb") as src:
                    for chunk in iter(lambda: src.read(CHUNK), b""):
                        copied += len(chunk)
                        if max_bytes is not None and copied > max_bytes:
                            raise InstanceTooLarge(f"{path.name}: more than {max_bytes} bytes")
                        _require_space(base, len(chunk))
                        h.update(chunk)
                        view = memoryview(chunk)
                        while view:
                            written = out.write(view)
                            if not written:
                                raise OSError(errno.EIO, "Source copy write made no progress")
                            view = view[written:]
                    out.flush()
                    os.fsync(out.fileno())
                digest = h.hexdigest()
                rel = relative_path(digest, path.suffix)
                target = base / rel
                if not intact(target, digest):
                    target.parent.mkdir(exist_ok=True)
                    os.replace(tmp, target)
                return digest, rel
            finally:
                tmp.unlink(missing_ok=True)
    finally:
        _remove_lease(lease)


@dataclass(frozen=True)
class PartialCopy:
    """An exact local maintenance candidate, bound to its source store and file identity."""

    source_root: str
    name: str
    identity: tuple[int, int, int, int, int]


def _identity(path: Path) -> tuple[int, int, int, int, int]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise ValueError("Not a regular temporary source file")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def partial_copies() -> list[PartialCopy]:
    """List temporary files without changing them. Older unowned copies remain visible but cannot be deleted."""
    base = root()
    result = []
    for path in sorted(base.glob(".incoming-*.part")):
        try:
            result.append(PartialCopy(str(base.resolve()), path.name, _identity(path)))
        except (FileNotFoundError, ValueError):
            continue  # disappeared during listing, or is not a regular file
    return result


def cleanup_partials(candidates: Iterable[PartialCopy], *, dry_run: bool = True,
                     min_age_seconds: float = 86400) -> dict[str, str]:
    """Inspect exact candidates, or explicitly remove old, unreferenced, unlocked partial copies.

    No automatic caller exists. Real-data maintenance needs an agreed retention scope. Final sources, old copies
    without ownership metadata, changed candidates and active writers are never removed.
    """
    if not 0 < min_age_seconds < float("inf"):
        raise ValueError("The minimum age must be finite and positive")
    base = root()
    result = {}
    for candidate in candidates:
        match = _PART.fullmatch(candidate.name)
        if not match or candidate.source_root != str(base.resolve()):
            result[candidate.name] = "unowned_or_outside_store"
            continue
        path = base / candidate.name
        lease = base / f".incoming-{match[1]}.lock"
        try:
            _identity(lease)
            with lock.try_exclusive(lease) as acquired:
                if not acquired:
                    result[candidate.name] = "active"
                    continue
                if _identity(path) != candidate.identity:
                    result[candidate.name] = "changed"
                    continue
                if time.time_ns() - candidate.identity[3] < min_age_seconds * 1_000_000_000:
                    result[candidate.name] = "recent"
                    continue
                with store.connect() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    referenced = conn.execute(
                        "SELECT 1 FROM workpackage_items WHERE instance=? OR source_path=? COLLATE NOCASE LIMIT 1",
                        (candidate.name, str(path)),
                    ).fetchone()
                    if referenced:
                        result[candidate.name] = "referenced"
                    elif dry_run:
                        result[candidate.name] = "eligible"
                    else:
                        path.unlink()
                        result[candidate.name] = "removed"
            if not dry_run and result.get(candidate.name) == "removed":
                _remove_lease(lease)
        except FileNotFoundError:
            result[candidate.name] = "missing_file_or_lease"
        except ValueError:
            result[candidate.name] = "not_regular"
    return result


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
