"""279: image files (JPEG, PNG, TIFF) as documents: each image is read through a PDF that holds exactly its pixels.

Plain-language summary: a scanned or photographed document often arrives as an image rather than a PDF. Instead of a
second processing chain, the system wraps the image into a PDF of its own pixels (one page per image, a multi-page TIFF
page by page) and processes that PDF like any scan: local text recognition, Azure when the local result is weak, type
recognition, extraction, the review page. The wrapper PDF is written by this module byte by byte (no date, no random
identifier), so the same image always gives the same PDF, and with it the same OCR cache entry and Azure request: an
image is never recognised or paid for twice. It is kept once under the image's content fingerprint, next to the source
instances; the image itself stays the item's source.

Rules:
- the page is sized as if the image were scanned at the OCR resolution (`configs/ocr.json` `dpi`), so the recognition
  renders the page back at exactly the image's pixels: nothing is resampled;
- a JPEG that needs no turning goes in as it is (its compressed bytes, `DCTDecode`); any other image is decoded once
  into plain grey or RGB pixels, compressed without loss (`FlateDecode`);
- the camera's orientation mark (EXIF) is applied, so a photo taken sideways is read upright; transparency is laid on
  white;
- the frames of a TIFF are the pages, up to the input limit's page count (`configs/service.json`).

Reuse (CLAUDE.md §3): new. The legacy sidecar sent images to Azure as they were and had no local route for them; here an
image takes the PDF route the framework already has.
"""

from __future__ import annotations

import io
import os
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path

from jav.core import cfg

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".tif", ".tiff")
_EXIF_ORIENTATION = 0x0112


class ImageUnreadable(ValueError):
    """The file is not an image this module can read, or it has more frames than the input limit allows."""


@dataclass(frozen=True)
class _Page:
    width: int
    height: int
    colour: str  # /DeviceGray or /DeviceRGB
    filter: str  # /DCTDecode or /FlateDecode
    data: bytes


def is_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_SUFFIXES


def _dpi() -> int:
    return int(cfg.load("ocr")["dpi"])


def _max_pages() -> int:
    from jav.documents import pdf

    return int(pdf.input_limits().max_document_pages)


def _flat(img) -> _Page:
    """Plain pixels, grey or RGB, transparency laid on white, compressed without loss."""
    from PIL import Image

    if img.mode in ("RGBA", "LA", "P", "PA") or (img.mode == "RGB" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(white, rgba).convert("RGB")
    elif img.mode in ("1", "L", "I;16", "I", "F"):
        img = img.convert("L")
    elif img.mode != "RGB":
        img = img.convert("RGB")
    colour = "/DeviceGray" if img.mode == "L" else "/DeviceRGB"
    return _Page(img.width, img.height, colour, "/FlateDecode", zlib.compress(img.tobytes(), 6))


def _pages(data: bytes) -> list[_Page]:
    from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageUnreadable(f"not a readable image: {type(exc).__name__}") from exc
    if img.format == "JPEG":
        upright = img.getexif().get(_EXIF_ORIENTATION, 1) in (0, 1)
        if upright and img.mode in ("L", "RGB"):
            return [_Page(img.width, img.height, "/DeviceGray" if img.mode == "L" else "/DeviceRGB", "/DCTDecode", data)]
        return [_flat(ImageOps.exif_transpose(img))]
    limit = _max_pages()
    pages: list[_Page] = []
    for n, frame in enumerate(ImageSequence.Iterator(img)):
        if n >= limit:
            raise ImageUnreadable(f"the image has more than {limit} frames")
        pages.append(_flat(ImageOps.exif_transpose(frame.copy())))
    return pages


def _num(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def pdf_bytes(data: bytes) -> bytes:
    """The PDF of an image's pixels (see the module's rules); the same image always gives the same bytes."""
    pages = _pages(data)
    scale = 72.0 / _dpi()
    objects: list[bytes] = []
    kids = []
    for n, page in enumerate(pages):
        page_no, image_no, content_no = 3 + 3 * n, 4 + 3 * n, 5 + 3 * n
        kids.append(f"{page_no} 0 R")
        w, h = _num(page.width * scale), _num(page.height * scale)
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] /Resources << /XObject << /Im0 {image_no} 0 R >> >>"
                       f" /Contents {content_no} 0 R >>".encode("ascii"))
        head = (f"<< /Type /XObject /Subtype /Image /Width {page.width} /Height {page.height} /ColorSpace {page.colour}"
                f" /BitsPerComponent 8 /Filter {page.filter} /Length {len(page.data)} >>\nstream\n").encode("ascii")
        objects.append(head + page.data + b"\nendstream")
        content = f"q {w} 0 0 {h} 0 0 cm /Im0 Do Q".encode("ascii")
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"\nendstream")
    catalogue = b"<< /Type /Catalog /Pages 2 0 R >>"
    tree = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode("ascii")
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate([catalogue, tree, *objects], start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(offsets) + 1}\n0000000000 65535 f \n".encode("ascii")
    out += b"".join(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets)
    out += f"trailer\n<< /Size {len(offsets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    return bytes(out)


def page_count(data: bytes) -> int:
    return len(_pages(data))


def derived_root() -> Path:
    """Where the wrapper PDFs are kept: beside the source instances, under the store's folder."""
    from jav.core import store

    return store.current_path().parent / "derived"


def pdf_for(image: Path, sha256: str) -> Path:
    """The wrapper PDF of `image` (whose content fingerprint is `sha256`), written once and kept under that fingerprint.
    A kept file that is not exactly what the image gives now (damaged, or written by an older rule) is written again."""
    root = derived_root()
    target = root / f"{sha256}.pdf"
    wanted = pdf_bytes(Path(image).read_bytes())
    if target.is_file() and target.read_bytes() == wanted:
        return target
    root.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=root, prefix=".tmp-", suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(wanted)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return target
