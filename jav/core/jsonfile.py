"""A JSON file written whole or not at all, and read without stopping on a broken one (265, code review AI-04).

Plain-language summary: a cache file is written to a temporary file next to it and then put in place in one step, so
a reader never sees half of it (a crash or a full disk mid-write left a truncated file before). A file that cannot be
read (truncated, not JSON) is reported once and treated as missing, so the work asks again and a new, intact file
takes its place, instead of failing every later item. The JEV cache did this since 066 (Á37); the OCR cache now
shares it.

Layer: core (no application code).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def write_atomic(path: Path, data: Any) -> None:
    """`data` as JSON at `path`: written to a temporary file of this process beside it, then replaced in one step."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def read_tolerant(path: Path) -> Any | None:
    """The JSON at `path`, or None when it is missing or cannot be read (an unreadable one is logged, not raised)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("an unreadable cache file is read again from its source: %s (%s)", path.name, type(exc).__name__)
        return None


__all__ = ["read_tolerant", "write_atomic"]
