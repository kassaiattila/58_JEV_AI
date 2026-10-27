"""A document's text page by page, with the pages its marking keeps out (231, stage D, D-c7b).

Plain-language summary: a rule proposal reads a condition document page by page and cites the page a rule comes from,
so its checks need each page's text as the reader gave it, whether it came from the file's text layer or from text
recognition (whose numbers a person confirms), and the pages a marking keeps out: a page that carries a marking line
(for example "Internal", the owner's decision of 2026-10-26: such pages are never sent to a model) is left out whole,
and only its number is kept, with the marking that left it out. The text of an invented document's pages can be given
directly, without a file.

- `read_pages(path, skip_markers)`: a PDF's pages (the text layer, else local text recognition, never the paid one).
- `from_rows(pages, skip_markers)`: pages given as rows of text (an invented document).

Layer: documents (reading only); it names no process and no business.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from jav.documents import pdf

__all__ = ["DocumentPages", "from_rows", "read_pages"]


@dataclass(frozen=True)
class DocumentPages:
    pages: dict[int, str]  # page number (from 1) -> its text, lines joined by line breaks; a left-out page is not here
    page_count: int
    source: str | None  # "pdf" (text layer) | "ocr" | "given" | None (no usable text)
    ocr_pages: frozenset[int] = frozenset()  # pages whose text came from text recognition
    skipped: dict[int, str] = field(default_factory=dict)  # page -> the marking that kept it out
    sha256: str | None = None


def _kept(texts: dict[int, str], markers: Iterable[str]) -> tuple[dict[int, str], dict[int, str]]:
    patterns = [re.compile(m) for m in markers]
    kept: dict[int, str] = {}
    skipped: dict[int, str] = {}
    for n, text in sorted(texts.items()):
        hit = next((m.group(0).strip() for p in patterns if (m := p.search(text))), None)
        if hit is None:
            kept[n] = text
        else:
            skipped[n] = hit
    return kept, skipped


def from_rows(pages: list[list[str]], skip_markers: Iterable[str] = ()) -> DocumentPages:
    kept, skipped = _kept({n: "\n".join(rows) for n, rows in enumerate(pages, 1)}, skip_markers)
    return DocumentPages(kept, len(pages), "given", skipped=skipped)


def read_pages(path: str | Path, skip_markers: Iterable[str] = ()) -> DocumentPages:
    """A PDF's text by page: its text layer, else local text recognition (cached; never the paid escalation)."""
    doc = pdf.read_document(path)
    texts: dict[int, list[str]] = {n: [] for n in range(1, doc.page_count + 1)}
    for line in doc.layout:
        texts.setdefault(line.page, []).append(line.text)
    kept, skipped = _kept({n: "\n".join(lines) for n, lines in texts.items()}, skip_markers)
    ocr = frozenset(kept) if doc.text_source == "ocr" else frozenset()
    return DocumentPages(kept, doc.page_count, doc.text_source, ocr, skipped, hashlib.sha256(Path(path).read_bytes()).hexdigest())
