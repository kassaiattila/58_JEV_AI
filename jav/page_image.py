"""Oldalkép a forráshoz kötött ellenőrzéshez (045 K3b): egy PDF-oldal PNG-ként, pypdfium2-vel (poppler nélkül).

A V4 `sidecar /page-image` mintája (oldalanként, korlátozott dpi), de színesen: az ellenőrző embernek a bélyegző és a
kiemelés is számít. Nem PDF (kép) forrásnál a fájl változatlanul megy ki, csak az 1. oldal kérhető.
"""

from __future__ import annotations

import io
import threading
from pathlib import Path

from jav import pdf

IMAGE_TYPES = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG"}
# 063: a PDFium (pypdfium2) nem szálbiztos, a helyi szolgáltatás viszont párhuzamos szálakon szolgál ki (két oldalkép
# egyszerre, két felhasználó). Minden PDFium-hívás ezen a zár alatt fut; az OCR oldalképei is (`jav/ocr.py`).
PDFIUM_LOCK = threading.RLock()


class BadPage(ValueError):
    """A kért oldal nem létezik (a szolgáltatás 422-t ad)."""


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
    """Az 1-alapú `page` oldal PNG-ként."""
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
                # 067: óriási oldalméretnél kisebb felbontás (a felület a kereteket százalékosan teszi a képre)
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
