"""144 (backlog F-finder-line-facts; DECISIONS 144): the bank's own document behind a statement read by code.

A statement read by code (`jav/domains/finance/statement_table.py`: a CIB PDF's text, a bank's table or XML export) is stored as the
statement file the reader builds, and that file, not the bank's PDF, is the package item: the pairing page's documents
showed a broken image for it. The statement file names its source (`source.file`, `source.sha256`) and, for a ledger
export, the month's PDF statement (`source.companion`). This module finds that PDF again and gives its verified bytes,
its page images and its word layer, so the pairing page can frame the line on the bank's own page.

Where it looks: first the paths the store has fingerprinted with that content (`file_fingerprints`), then the file's
name under the folders of the packages that hold the statement (`workpackages.source_ref`; a file there stands for its
folder). Only a file whose content hash is the one the reader recorded is used, and exactly the verified bytes are
shown or read (075). A table or XML export without a PDF companion has no original page (`EXPORT`); a PDF that is no
longer where it was is `MISSING`. Nothing is written but the fingerprint memo (`work.fingerprint`); the found path and
the word layer are kept in memory.

Layer: `jav.domains.finance.reconcile_package` (application operation) → **this** (business module) → `jav.app.work` (items, verified
reads, fingerprints), `jav.documents.page_image`, `jav.documents.pdf` (the isolated PDF reader), `jav.documents.source_layer`, `jav.core.store`.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jav.app import work
from jav.documents import page_image, source_layer
from jav.core import store

DOC_TYPE = "statement_table"  # the statements read by code (jav/domains/finance/flow_statement_table.py)
FORMAT = "jav.domains.finance.statement_table"  # the statement file's `format`

FOUND, EXPORT, MISSING = "found", "export", "missing"
MAX_VISITED = 20_000  # the entries one name search visits under a package's folder (a folder tree may be large)
_CACHE_MAX = 64


@dataclass(frozen=True)
class Original:
    """The bank's PDF behind a statement read by code: its name and content hash as the reader recorded them, where it
    was found (None: not found) and the state (`FOUND`, `EXPORT`: the source has no PDF, `MISSING`)."""
    file: str | None
    sha256: str | None
    path: Path | None
    state: str


_found: OrderedDict[tuple[str, str], Path] = OrderedDict()
_layers: OrderedDict[tuple[str, str], source_layer.SourceLayer | None] = OrderedDict()
_lock = threading.Lock()


def _remember(cache: OrderedDict, key: tuple[str, str], value: Any) -> None:
    with _lock:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > _CACHE_MAX:
            cache.popitem(last=False)


def _cached(cache: OrderedDict, key: tuple[str, str]) -> tuple[bool, Any]:
    with _lock:
        if key in cache:
            cache.move_to_end(key)
            return True, cache[key]
    return False, None


def _items(item_id: str) -> list[dict[str, Any]]:
    """The package items with this id (a statement file may be in several packages), with their package's source."""
    with store.connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT i.item_id, i.kind, i.source_path, i.sha256, i.instance, w.source_ref FROM workpackage_items i"
            " JOIN workpackages w ON w.id = i.workpackage_id WHERE i.item_id=? AND i.removed_revision IS NULL", (item_id,))]


def source_of(item_id: str) -> dict[str, Any] | None:
    """The `source` of the statement file behind a stored statement (its item), read from the item's verified bytes;
    None when no package holds the item or it is not a statement file."""
    for item in _items(item_id):
        try:
            data = work.read_verified(work.source_file(item), item["sha256"], max_bytes=work.max_source_bytes())
            doc = json.loads(data)
        except (work.RevisionConflict, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("format") == FORMAT:
            return {**(doc.get("source") or {}), "institution": doc.get("institution")}
    return None


def _pdf(source: dict[str, Any]) -> tuple[str, str] | None:
    """The PDF the statement was read from: its own source, or a ledger export's companion; None for an export only."""
    if str(source.get("file") or "").lower().endswith(".pdf") and source.get("sha256"):
        return source["file"], source["sha256"]
    companion = source.get("companion") or {}
    if str(companion.get("file") or "").lower().endswith(".pdf") and companion.get("sha256"):
        return companion["file"], companion["sha256"]
    return None


def _folders(item_id: str) -> list[Path]:
    out: list[Path] = []
    for item in _items(item_id):
        ref = Path(item["source_ref"]) if item.get("source_ref") else None
        if ref is None:
            continue
        folder = ref if ref.is_dir() else ref.parent
        if folder.is_dir() and folder not in out:
            out.append(folder)
    return out


def _by_name(folder: Path, name: str) -> list[Path]:
    """The files called `name` (case-insensitively) under `folder`, visiting at most `MAX_VISITED` entries."""
    want, out, visited = name.casefold(), [], 0
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        visited += len(dirs) + len(files)
        out += [Path(root) / f for f in files if f.casefold() == want]
        if visited > MAX_VISITED:
            break
    return out


def _holds(path: Path, sha: str) -> bool:
    """Whether the file still has this content (the fingerprint memo: a full hash after a size or time change)."""
    try:
        return path.is_file() and work.fingerprint(path) == sha
    except OSError:
        return False


def _search(item_id: str, name: str, sha: str) -> Path | None:
    with store.connect() as c:
        remembered = [Path(r["path"]) for r in c.execute("SELECT path FROM file_fingerprints WHERE sha256=?", (sha,))]
    return next((p for p in [*remembered, *(p for folder in _folders(item_id) for p in _by_name(folder, name))]
                 if _holds(p, sha)), None)


def find(item_id: str) -> Original:
    """The bank's PDF behind a stored statement read by code (`item_id`: its item, the same as its document id)."""
    source = source_of(item_id)
    ref = _pdf(source) if source else None
    if ref is None:
        return Original(file=(source or {}).get("file"), sha256=None, path=None, state=EXPORT)
    name, sha = ref
    key = (str(store.active_path()), sha)
    hit, path = _cached(_found, key)
    if hit and _holds(path, sha):
        return Original(file=name, sha256=sha, path=path, state=FOUND)
    path = _search(item_id, name, sha)
    if path is None:
        return Original(file=name, sha256=sha, path=None, state=MISSING)
    _remember(_found, key, path)
    return Original(file=name, sha256=sha, path=path, state=FOUND)


def _verified(original: Original) -> bytes:
    """The original's bytes, only while its content is still the one the reader read (`work.RevisionConflict`)."""
    if original.path is None or original.sha256 is None:
        raise KeyError(original.file or "original")
    try:
        return work.read_verified(original.path, original.sha256, max_bytes=work.max_source_bytes())
    except work.RevisionConflict:
        with _lock:
            _found.pop((str(store.active_path()), original.sha256), None)
        raise


@contextmanager
def _copy(original: Original) -> Iterator[Path]:
    """A temporary copy of the original's verified bytes, removed on leaving (the PDF reader reads a path)."""
    data = _verified(original)
    with tempfile.TemporaryDirectory(prefix="jav_original_") as tmp:
        path = Path(tmp) / "original.pdf"
        path.write_bytes(data)
        yield path


def page_count(original: Original) -> int:
    """The original's page count (for a scanned PDF, which has no word layer)."""
    with _copy(original) as path:
        return page_image.page_count(path)


def page(original: Original, number: int, *, dpi: int) -> bytes:
    """One page of the original as PNG (the isolated PDF reader; `page_image.BadPage` out of range)."""
    return page_image.render(original.path or Path("original.pdf"), number, dpi=dpi, data=_verified(original))


def layer(original: Original) -> source_layer.SourceLayer | None:
    """The original's word layer from its text layer (None: a scanned PDF without one; no OCR runs here). The verified
    bytes are read from a temporary copy, which is removed at once."""
    from jav.documents import pdf

    key = (str(store.active_path()), original.sha256 or "")
    hit, found = _cached(_layers, key)
    if hit:
        return found
    with _copy(original) as path:
        text = pdf.read_pdf(path)
    built = (source_layer.build(f"original:{original.sha256}", text.words, text.page_sizes, text_source=text.text_source,
                                engine="pdfplumber") if text.has_text_layer else None)
    _remember(_layers, key, built)
    return built
