"""Probes for the isolated PDF reader tests (077): functions the helper process runs in place of a PDF parser.

They stand in for a parser that hangs, runs out of memory, crashes or raises, without needing a hostile PDF.
"""

from __future__ import annotations

import os
import time


def echo(value: object) -> object:
    return value


def helper_pid() -> int:
    return os.getpid()


def sleep_for(seconds: float) -> str:
    time.sleep(seconds)
    return "woke up"


def allocate(mb: int) -> int:
    block = bytearray(mb * 1_048_576)  # zero-filled, so the memory is committed at once
    return len(block)


def crash() -> None:
    os._exit(3)


def fail(message: str) -> None:
    raise ValueError(message)
