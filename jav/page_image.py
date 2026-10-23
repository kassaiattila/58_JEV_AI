"""Page image for source-bound review (045 K3b): one PDF page as PNG, via pypdfium2 (without poppler).

Follows the V4 `sidecar /page-image` pattern (per page, limited dpi), but in colour: stamps and highlighting matter to
the human reviewer too. For a non-PDF (image) source the file is returned unchanged, and only page 1 can be requested.

077: PDFium runs in the isolated PDF reader (`jav/isolated_pdf.py`): one request at a time (PDFium is not thread-safe,
063), with a time and memory limit; over a limit `PdfReaderLimit`, which the local service answers with 422.
"""

from __future__ import annotations

from pathlib import Path

from jav import isolated_pdf, pdf
from jav.core.user_messages import explained

IMAGE_TYPES = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG"}


class BadPage(ValueError):
    """The requested page does not exist (the service returns 422)."""


def page_count(path: Path) -> int:
    if path.suffix.lower() in IMAGE_TYPES:
        return 1
    return isolated_pdf.run(isolated_pdf.page_count, kind="page_image", path=str(path))


def render(path: Path, page: int, *, dpi: int = 144, data: bytes | None = None) -> bytes:
    """The 1-based page `page` as PNG. `data` (075): the already verified bytes of `path`; the file is then not read
    again, so the image shows exactly the content that was checked."""
    if path.suffix.lower() in IMAGE_TYPES:
        if page != 1:
            raise explained(BadPage, "An image has only page 1, not {{page}}", page=page)
        return data if data is not None else path.read_bytes()
    head = data[:1024] if data is not None else _head(path)
    if b"%PDF" not in head:
        # 167 (review 153 E): a Word, Excel, text or statement file has no page image; PDFium's raw error said so badly
        raise explained(BadPage, "This kind of document ({{kind}}) has no page image; open the file itself",
                        kind=path.suffix.lower() or "?")
    result = isolated_pdf.run(isolated_pdf.render_page_png, kind="page_image", source=data if data is not None else str(path),
                              page=page, dpi=dpi, max_megapixels=pdf.input_limits().max_page_megapixels)
    if "page_count" in result:
        raise explained(BadPage, "Page {{page}} is out of range 1..{{count}}", page=page, count=result["page_count"])
    return result["png"]


def _head(path: Path) -> bytes:
    """The first kilobyte of a file: a PDF's header may stand anywhere in it."""
    with path.open("rb") as f:
        return f.read(1024)
