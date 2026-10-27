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
from jav.documents.layout import LineLayout

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


def _columns(lines: list[LineLayout], width: float | None) -> str:
    """231 (stage U, U-A2): a page's text, read column by column when it is set in two: the left column's lines, then
    the right one's, so a clause and its sentences stay together (line by line across both columns, the real condition
    documents' clauses came mixed: 1.2, 1.13, 1.3, …). Two columns: no line's text runs across the page's middle except a
    few (a heading over both), every other piece of text stands wholly left or right of it, and most of the right ones
    start at one place (a table's columns start at several). A page that is not so reads line by line, as before."""
    plain = "\n".join(ln.text for ln in lines)
    cells = [c for ln in lines for c in ln.cells]
    if len(cells) < 12:
        return plain
    edge = width or max(c.x1 for c in cells)
    mid, margin = edge / 2, edge * 0.03
    across = [c for c in cells if c.x0 < mid - margin and c.x1 > mid + margin]
    right = [c.x0 for c in cells if c.x0 >= mid - margin]
    left = [c for c in cells if c.x1 <= mid + margin]
    if len(across) > 0.1 * len(cells) or len(right) < 5 or len(left) < 5:
        return plain
    start = sorted(right)[len(right) // 2]
    if sum(1 for x in right if abs(x - start) <= edge * 0.02) < 0.6 * len(right):
        return plain
    left_lines = ["   ".join(c.text for c in ln.cells if c.x0 < mid - margin) for ln in lines]
    right_lines = ["   ".join(c.text for c in ln.cells if c.x0 >= mid - margin) for ln in lines]
    return "\n".join([t for t in left_lines if t] + [t for t in right_lines if t])


def read_pages(path: str | Path, skip_markers: Iterable[str] = ()) -> DocumentPages:
    """A PDF's text by page: its text layer, else local text recognition (cached; never the paid escalation); a page
    set in two columns column by column (231 U-A2)."""
    doc = pdf.read_document(path)
    by_page: dict[int, list[LineLayout]] = {n: [] for n in range(1, doc.page_count + 1)}
    for line in doc.layout:
        by_page.setdefault(line.page, []).append(line)
    sizes = doc.page_sizes
    texts = {n: _columns(lines, sizes[n - 1][0] if n - 1 < len(sizes) else None) for n, lines in by_page.items()}
    kept, skipped = _kept(texts, skip_markers)
    ocr = frozenset(kept) if doc.text_source == "ocr" else frozenset()
    return DocumentPages(kept, doc.page_count, doc.text_source, ocr, skipped, hashlib.sha256(Path(path).read_bytes()).hexdigest())
