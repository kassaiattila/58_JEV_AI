"""Single-instance lock (040 K2): only one worker may run on a store at a time.

The work queue's orphan handling (`queue.recover_orphans`) releases every claim at startup; if another worker were
busy meanwhile, that would lead to a paid call being repeated. So before starting, the worker takes an exclusive
operating-system lock on a lock file next to the store. The lock is released by itself when the process dies, so
there is no "stuck" lock after a crash.
"""

from __future__ import annotations

import os
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
        if not _try_lock(f):
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


def is_held(path: Path) -> bool:
    """Whether anyone holds the lock right now (the probe lock is released at once)."""
    if not path.exists():
        return False
    with open(path, "a+b") as f:
        if _try_lock(f):
            _unlock(f)
            return False
        return True
