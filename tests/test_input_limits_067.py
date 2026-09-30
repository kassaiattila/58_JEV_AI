"""067: bemeneti korlátok — az irat fájlmérete és oldalszáma, az oldalkép képpontszáma (066 Á38).

Egy óriási oldalméretű vagy több ezer oldalas PDF ne fogyassza el a gép memóriáját: a szövegkinyerés nevesített hibával
áll meg (a tétel hibás lesz, a futás nem hagyható jóvá), a felismerés teendőt ad, az ellenőrző oldalkép kisebb
felbontással készül. A korlátok a `configs/service.json` `input_limits` szakaszában vannak. Minden PDF generált, üres.
"""

from __future__ import annotations

import io

import pypdfium2 as pdfium
import pytest
from PIL import Image

from jav import cfg, ocr, page_image, pdf
from jav.pdf import DocumentTooLarge, InputLimits


def _blank_pdf(path, *, pages: int = 1, size_pt: float = 600.0):
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(size_pt, size_pt)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture()
def tight(monkeypatch):
    limits = InputLimits(max_document_mb=1.0, max_document_pages=2, max_page_megapixels=1.0)
    monkeypatch.setattr(pdf, "input_limits", lambda: limits)
    return limits


def test_limits_come_from_the_service_config():
    got = pdf.input_limits()
    section = cfg.load("service")["input_limits"]
    assert got == InputLimits(**section)
    assert got.max_document_mb > 0 and got.max_document_pages >= 100 and got.max_page_megapixels > 0


def test_document_over_the_page_limit_is_refused_by_name(tmp_path, tight):
    path = _blank_pdf(tmp_path / "hosszu.pdf", pages=3)
    with pytest.raises(DocumentTooLarge, match="3 pages"):
        pdf.read_pdf(path)


def test_document_within_the_limits_is_read(tmp_path, tight):
    assert pdf.read_pdf(_blank_pdf(tmp_path / "rendes.pdf", pages=2)).page_count == 2


def test_file_over_the_size_limit_is_refused_before_parsing(tmp_path, monkeypatch):
    big = tmp_path / "nagy.pdf"
    big.write_bytes(b"%PDF-1.4\n" + b"0" * 2_000_000)  # nem is érvényes PDF: meg sem nyitjuk
    monkeypatch.setattr(pdf, "input_limits", lambda: InputLimits(max_document_mb=1.0, max_document_pages=300,
                                                                 max_page_megapixels=40.0))
    with pytest.raises(DocumentTooLarge, match="MB"):
        pdf.read_pdf(big)


def test_oversized_page_image_is_scaled_into_the_pixel_budget(tmp_path, tight):
    path = _blank_pdf(tmp_path / "plakat.pdf", size_pt=1000.0)  # 144 dpi-n 2000 × 2000 = 4 MP
    img = Image.open(io.BytesIO(page_image.render(path, 1, dpi=144)))
    assert img.width * img.height <= 1_000_000
    assert abs(img.width - img.height) <= 1  # az arány megmarad (a keretek százalékosan kerülnek rá)


def test_normal_page_image_keeps_the_requested_resolution(tmp_path, tight):
    path = _blank_pdf(tmp_path / "a4.pdf", size_pt=300.0)  # 144 dpi-n 600 × 600
    img = Image.open(io.BytesIO(page_image.render(path, 1, dpi=144)))
    assert (img.width, img.height) == (600, 600)


def test_ocr_refuses_a_page_over_the_pixel_budget(tmp_path, tight):
    path = _blank_pdf(tmp_path / "plakat.pdf", size_pt=1000.0)
    with pytest.raises(ocr.PageTooLarge) as exc:
        ocr.render_pages(path, tmp_path)
    assert isinstance(exc.value, ocr.OcrUnavailableError)  # a folyamat teendőt ad („ocr:unavailable:PageTooLarge”)
    assert not list(tmp_path.glob("p-*.png"))


def test_fit_scale_only_ever_shrinks():
    assert pdf.fit_scale(595, 842, scale=2.0, max_megapixels=40) == 2.0
    shrunk = pdf.fit_scale(5000, 5000, scale=2.0, max_megapixels=1)
    assert shrunk < 2.0 and (5000 * shrunk) * (5000 * shrunk) <= 1_000_000
