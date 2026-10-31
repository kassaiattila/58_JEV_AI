"""Single-instance lock (040 K2): one process per lock file. 231 (stage E, E1): a worker takes one numbered slot's lock
(`worker.lock_path`), so several workers may run on a store, one per slot; the claims they make name their process's
holder (`calls.holder`), so a worker's recovery frees only a stopped worker's claims.

Until 231 the work queue's orphan handling (`queue.recover_orphans`) released every claim at start-up, so a second
worker busy meanwhile would have repeated a paid call; one lock file next to the store kept to one worker. The lock is
an exclusive operating-system lock, released by itself when the process dies, so there is no "stuck" lock after a crash.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterator

if os.name == "nt":
    import msvcrt
else:  # pragma: no cover - the development machine runs Windows
    import fcntl


class AlreadyRunning(RuntimeError):
    """Another worker already holds the lock."""


def _try_lock(f: IO[bytes]) -> bool:
    try:
        if os.name == "nt":
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:  # pragma: no cover
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


TAKE_ATTEMPTS = 3
TAKE_RETRY_S = 0.05
"""265 (code review CORE-09): another process's probe (`is_held`) holds a lock for a moment; a lock taken right then is
tried again a few times before it counts as held by someone else."""


def _take(f: IO[bytes]) -> bool:
    for attempt in range(1, TAKE_ATTEMPTS + 1):
        if _try_lock(f):
            return True
        if attempt < TAKE_ATTEMPTS:
            time.sleep(TAKE_RETRY_S)
    return False


def _unlock(f: IO[bytes]) -> None:
    if os.name == "nt":
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:  # pragma: no cover
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


@contextmanager
def single_instance(path: Path) -> Iterator[None]:
    """Exclusive lock for the lifetime of the process; `AlreadyRunning` if the lock is taken."""
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+b")
    try:
        if not _take(f):
            raise AlreadyRunning(f"another worker holds {path.name}")
        try:
            f.seek(0)
            f.truncate()
            f.write(str(os.getpid()).encode("ascii"))
            f.flush()
            yield
        finally:
            _unlock(f)
    finally:
        f.close()


@contextmanager
def try_exclusive(path: Path) -> Iterator[bool]:
    """063: non-blocking exclusive lock across processes (e.g. scanning a work folder): True if we got it, False if
    someone else holds it. The lock is released at the end of the block or when the process dies."""
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+b")
    try:
        got = _try_lock(f)
        try:
            yield got
        finally:
            if got:
                _unlock(f)
    finally:
        f.close()


def hold(path: Path) -> IO[bytes]:
    """092: takes an exclusive lock for as long as the caller keeps the returned file open (normally the life of the
    process; the operating system releases it when the process dies). `AlreadyRunning` if someone else holds it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+b")
    if not _take(f):
        f.close()
        raise AlreadyRunning(f"{path.name} is held by another process")
    return f


def release(f: IO[bytes]) -> None:
    """092: lets go of a lock taken with `hold`."""
    try:
        _unlock(f)
    finally:
        f.close()


def is_held(path: Path) -> bool:
    """Whether anyone holds the lock right now (the probe lock is released at once)."""
    if not path.exists():
        return False
    with open(path, "a+b") as f:
        if _try_lock(f):
            _unlock(f)
            return False
        return True
