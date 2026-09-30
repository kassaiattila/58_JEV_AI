"""Page image for source-bound review (045 K3b): one PDF page as PNG, via pypdfium2 (without poppler).

Follows the V4 `sidecar /page-image` pattern (per page, limited dpi), but in colour: stamps and highlighting matter to
the human reviewer too. For a non-PDF (image) source the file is returned unchanged, and only page 1 can be requested.
"""

from __future__ import annotations

import io
import threading
from pathlib import Path

from jav import pdf

IMAGE_TYPES = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG"}
# 063: PDFium (pypdfium2) is not thread-safe, but the local service serves requests on parallel threads (two page
# images at once, two users). Every PDFium call runs under this lock, including the OCR page images (`jav/ocr.py`).
PDFIUM_LOCK = threading.RLock()


class BadPage(ValueError):
    """The requested page does not exist (the service returns 422)."""


def page_count(path: Path) -> int:
    if path.suffix.lower() in IMAGE_TYPES:
        return 1
    import pypdfium2 as pdfium

    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(str(path))
        try:
            return len(doc)
        finally:
            doc.close()


def render(path: Path, page: int, *, dpi: int = 144) -> bytes:
    """The 1-based page `page` as PNG."""
    if path.suffix.lower() in IMAGE_TYPES:
        if page != 1:
            raise BadPage(f"an image has only page 1, not {page}")
        return path.read_bytes()
    import pypdfium2 as pdfium

    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(str(path))
        try:
            if not 1 <= page <= len(doc):
                raise BadPage(f"page {page} is out of range 1..{len(doc)}")
            pdf_page = doc[page - 1]
            try:
                # 067: lower resolution for huge page sizes (the UI places the boxes on the image in percentages)
                w, h = pdf_page.get_size()
                scale = pdf.fit_scale(w, h, scale=dpi / 72.0, max_megapixels=pdf.input_limits().max_page_megapixels)
                img = pdf_page.render(scale=scale).to_pil()
            finally:
                pdf_page.close()
        finally:
            doc.close()
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
