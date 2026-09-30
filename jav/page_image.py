"""Page image for source-bound review (045 K3b): one PDF page as PNG, via pypdfium2 (without poppler).

Follows the V4 `sidecar /page-image` pattern (per page, limited dpi), but in colour: stamps and highlighting matter to
the human reviewer too. For a non-PDF (image) source the file is returned unchanged, and only page 1 can be requested.

077: PDFium runs in the isolated PDF reader (`jav/isolated_pdf.py`): one request at a time (PDFium is not thread-safe,
063), with a time and memory limit; over a limit `PdfReaderLimit`, which the local service answers with 422.
"""

from __future__ import annotations

from pathlib import Path

from jav import isolated_pdf, pdf

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
            raise BadPage(f"an image has only page 1, not {page}")
        return data if data is not None else path.read_bytes()
    result = isolated_pdf.run(isolated_pdf.render_page_png, kind="page_image", source=data if data is not None else str(path),
                              page=page, dpi=dpi, max_megapixels=pdf.input_limits().max_page_megapixels)
    if "page_count" in result:
        raise BadPage(f"page {page} is out of range 1..{result['page_count']}")
    return result["png"]
