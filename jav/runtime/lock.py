"""Egypéldányos zár (040 K2): egyszerre egy feldolgozó futhat egy adattáron.

A munkasor árvakezelése (`queue.recover_orphans`) induláskor minden foglalást visszaenged; ha közben egy másik
feldolgozó dolgozik, az a fizetős hívás megismétléséhez vezetne. Ezért a feldolgozó indulás előtt kizárólagos
operációsrendszer-zárat vesz az adattár melletti zárfájlon. A zár a folyamat halálakor magától feloldódik, így
összeomlás után nincs „beragadt” zár.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterator

if os.name == "nt":
    import msvcrt
else:  # pragma: no cover - a fejlesztői gép Windows
    import fcntl


class AlreadyRunning(RuntimeError):
    """Egy másik feldolgozó már tartja a zárat."""


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
    """Kizárólagos zár a folyamat élettartamára; foglalt zárnál `AlreadyRunning`."""
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
    """063: nem blokkoló kizárólagos zár folyamatok között (pl. egy munkamappa átnézése): True, ha megkaptuk; False,
    ha más tartja. A zár a blokk végén, vagy a folyamat halálakor oldódik fel."""
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
    """Tartja-e most valaki a zárat (a próbazár azonnal fel is oldódik)."""
    if not path.exists():
        return False
    with open(path, "a+b") as f:
        if _try_lock(f):
            _unlock(f)
            return False
        return True
