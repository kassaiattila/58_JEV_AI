"""279 (the owner's decision of 2026-11-02): JPEG, PNG and TIFF images are documents, read through the PDF of their
pixels (`jav/documents/image_input.py`). Synthetic images only; the real recognition test runs only where the native
tesseract and its language packs are installed. No paid call.
"""

from __future__ import annotations

import io
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from PIL import Image, ImageDraw

from jav.app import work_readiness, work_recipes
from jav.core import store
from jav.documents import image_input, ocr, page_image, tessdata
from jav.documents.native_contracts import DOCUMENT_FORMATS, DOCUMENT_SUFFIXES, NATIVE_FALLBACK_SUFFIXES
from jav.runtime import worker
from tests.pdfgen import INVOICE_LINES, write_text_pdf


def _image(mode: str = "RGB", size: tuple[int, int] = (600, 400)) -> Image.Image:
    img = Image.new(mode, size, "white")
    ImageDraw.Draw(img).text((20, 20), "Payable 1000", fill="black")
    return img


def _bytes(img: Image.Image, fmt: str, **kw) -> bytes:
    out = io.BytesIO()
    img.save(out, fmt, **kw)
    return out.getvalue()


def _pages(pdf: bytes) -> list[tuple[tuple[float, float], tuple[int, int]]]:
    doc = pdfium.PdfDocument(pdf)
    return [(doc[i].get_size(), doc[i].render(scale=300 / 72).to_pil().size) for i in range(len(doc))]


# --- the wrapper PDF ----------------------------------------------------------------------------------------------------


def test_the_same_image_always_gives_the_same_pdf_at_its_own_pixels():
    png = _bytes(_image(), "PNG")
    first, again = image_input.pdf_bytes(png), image_input.pdf_bytes(png)
    assert first == again and first.startswith(b"%PDF-1.4")
    assert b"/CreationDate" not in first and b"/ID" not in first
    assert _pages(first) == [((144.0, 96.0), (600, 400))]  # sized for the OCR's 300 dpi: rendered back 1:1


def test_a_jpeg_goes_in_as_it_is():
    jpg = _bytes(_image(), "JPEG", quality=90)
    pdf = image_input.pdf_bytes(jpg)
    assert b"/DCTDecode" in pdf and jpg in pdf


def test_a_photo_taken_sideways_is_read_upright():
    img = _image()
    exif = img.getexif()
    exif[0x0112] = 6  # turned 90 degrees
    pdf = image_input.pdf_bytes(_bytes(img, "JPEG", exif=exif))
    assert b"/FlateDecode" in pdf and _pages(pdf)[0][0] == (96.0, 144.0)


def test_every_frame_of_a_tiff_is_a_page_and_transparency_is_white():
    out = io.BytesIO()
    _image().save(out, "TIFF", save_all=True, append_images=[_image("L", (300, 600))])
    assert [size for size, _ in _pages(image_input.pdf_bytes(out.getvalue()))] == [(144.0, 96.0), (72.0, 144.0)]
    clear = image_input.pdf_bytes(_bytes(Image.new("RGBA", (10, 10), (0, 0, 0, 0)), "PNG"))
    doc = pdfium.PdfDocument(clear)
    assert doc[0].render(scale=300 / 72).to_pil().convert("L").getpixel((5, 5)) == 255


def test_an_unreadable_image_or_too_many_frames_is_refused(monkeypatch):
    with pytest.raises(image_input.ImageUnreadable):
        image_input.pdf_bytes(b"not an image at all")
    monkeypatch.setattr(image_input, "_max_pages", lambda: 1)
    out = io.BytesIO()
    _image().save(out, "TIFF", save_all=True, append_images=[_image()])
    with pytest.raises(image_input.ImageUnreadable, match="more than 1 frames"):
        image_input.pdf_bytes(out.getvalue())


def test_the_wrapper_is_kept_once_under_the_image_s_fingerprint(tmp_path):
    image = tmp_path / "scan.png"
    image.write_bytes(_bytes(_image(), "PNG"))
    with store.use_store(tmp_path / "store" / "w.sqlite"):
        path = image_input.pdf_for(image, "a" * 64)
        assert path == tmp_path / "store" / "derived" / f"{'a' * 64}.pdf"
        assert path.read_bytes() == image_input.pdf_bytes(image.read_bytes())
        path.write_bytes(b"damaged")
        assert image_input.pdf_for(image, "a" * 64).read_bytes() == image_input.pdf_bytes(image.read_bytes())


# --- intake, routing, reading, review ----------------------------------------------------------------------------------


def test_images_are_documents_of_the_document_flow_and_never_continue_into_the_native_one():
    images = {f.suffix: f for f in DOCUMENT_FORMATS if f.suffix in image_input.IMAGE_SUFFIXES}
    assert set(images) == set(image_input.IMAGE_SUFFIXES) <= set(DOCUMENT_SUFFIXES)
    assert all(f.flow == "document" for f in images.values())
    assert not set(image_input.IMAGE_SUFFIXES) & set(NATIVE_FALLBACK_SUFFIXES)


def test_both_active_processings_take_an_image():
    item = {"item_id": "i1", "kind": "document", "source_path": "D:/scans/receipt.png", "sha256": "b" * 64}
    for recipe_id in ("processing", "multi-format-processing"):
        recipe = work_recipes.recipe(recipe_id)
        found = work_readiness._item_checks(recipe, {}, [item], verify=False)
        codes = {f["code"] for _i, level, f in found if level == "blocker"}
        assert not codes & {"unsupported_item", "native_recipe_required"}, (recipe_id, found)  # the file itself is not here
    assert work_readiness.flow_for(work_recipes.recipe("multi-format-processing"), item) == "document"


def test_the_worker_reads_an_image_through_its_wrapper(tmp_path):
    image = tmp_path / "scan.png"
    image.write_bytes(_bytes(_image(), "PNG"))
    with store.use_store(tmp_path / "w.sqlite"):
        read = worker.reading_path({"source_path": str(image), "sha256": "c" * 64, "instance": "x"}, image)
        assert read is not None and read.endswith(f"{'c' * 64}.pdf") and Path(read).read_bytes().startswith(b"%PDF")
        pdf = tmp_path / "a.pdf"
        write_text_pdf(pdf, INVOICE_LINES[:2])
        assert worker.reading_path({"source_path": str(pdf), "sha256": "d" * 64, "instance": "y"}, pdf) == str(pdf)
        assert worker.reading_path({"source_path": str(pdf), "sha256": "d" * 64}, pdf) is None


def test_a_tiff_is_drawn_page_by_page_for_the_review(tmp_path):
    tiff = tmp_path / "scan.tif"
    _image().save(tiff, "TIFF", save_all=True, append_images=[_image()])
    assert page_image.page_count(tiff) == 2
    assert page_image.render(tiff, 2, dpi=72).startswith(b"\x89PNG")
    png = tmp_path / "scan.png"
    png.write_bytes(_bytes(_image(), "PNG"))
    assert page_image.render(png, 1) == png.read_bytes()  # a browser shows a PNG or a JPEG as it is


@pytest.mark.skipif(ocr.native_exe() is None or bool(tessdata.missing(ocr.tessdata_dir())),
                    reason="the native tesseract or its language packs are not installed here")
def test_the_local_recognition_reads_an_image(tmp_path, monkeypatch):
    source = tmp_path / "invoice.pdf"
    write_text_pdf(source, INVOICE_LINES)
    page = pdfium.PdfDocument(str(source))[0].render(scale=300 / 72).to_pil().convert("L")
    image = tmp_path / "invoice.png"
    page.save(image, "PNG")
    monkeypatch.setattr(ocr, "CACHE_DIR", tmp_path / "ocr-cache")
    with store.use_store(tmp_path / "w.sqlite"):
        read = ocr.ocr_pdf(image_input.pdf_for(image, "e" * 64), use_cache=False, engine_name="native")
    words = " ".join(read.lines)
    assert read.text_source == "ocr" and "MINTA-2026-001" in words and "12 700 Ft" in words, words[:200]
