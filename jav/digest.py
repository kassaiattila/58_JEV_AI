"""The one fingerprint of a file's content (194, plan G-tidy R3).

Plain-language summary: a document, a frozen source copy, a backup file and an OCR cache entry are each known by the
SHA-256 digest of their bytes. The modules used to carry their own copy of the few lines that compute it; now they
read this one, under their own name (`from jav.digest import file_sha256 as sha256_file`). The file is read in
chunks, so a large document is never held in memory whole.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK = 1 << 20


def file_sha256(path: str | Path) -> str:
    """The hex SHA-256 digest of the file's bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


__all__ = ["CHUNK", "file_sha256"]
