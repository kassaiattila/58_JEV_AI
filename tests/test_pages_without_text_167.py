"""167 (review AI-3): scanned pages without a text layer of their own are a visible to-do.

The text-layer test looked at the whole document. When one page has text (for example an electronically signed cover
page) and the others are scans, the document passed as text: the scanned pages never went to OCR, and nothing said
that their content was not read. Now each page gets the same test, and a page that fails it counts when it is a scan:
its images cover at least 30 % of it (`pdf.MIN_SCAN_IMAGE_SHARE`). A blank page, a page with a few characters and no
image, or a page with only a logo is not a scan (the first rule, without the image condition, flagged 11 of the
owner's 243 multi-page text PDFs, every one of them falsely). When some pages (not all) are such scans in a document
that has a text layer, both the detection and the extraction raise `pdf:pages_without_text:<n>/<total>`. Per-page OCR
of those pages is a later step. Synthetic PDFs and word boxes only; no model call.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from jav import isolated_pdf, pdf, policy
from jav.core import store
from jav.flow import load_pdf as invoice_load
from jav.flow_detect import DetectState, load_pdf as detect_load, save as detect_save
from jav.models import FlowState
from tests.pdfgen import _escape

TEXT_PAGE = [
    "Synthetic Supplier Ltd   Invoice number INV-2026-0042",
    "Issue date 2026-09-12   Due date 2026-10-12",
    "Consulting services for September   Net amount 1000.00 EUR",
    "Total payable 1270.00 EUR   Thank you for your business",
]


def _words(lines: list[str]) -> list[dict]:
    """Word boxes in points, one line every 20 pt, 6 pt per character."""
    out = []
    for i, line in enumerate(lines):
        x = 50.0
        for w in line.split():
            out.append({"text": w, "x0": x, "x1": x + 6 * len(w), "top": 100.0 + 20 * i, "bottom": 110.0 + 20 * i})
            x += 6 * len(w) + 6
    return out


def _read(tmp_path: Path, pages: list[list[str]], shares: list[float]) -> pdf.PdfText:
    """`read_pdf` over synthetic pages (the isolated reader's answer stands in for pdfplumber)."""
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"%PDF-1.4 synthetic")
    raw = [_words(p) for p in pages]
    with patch("jav.isolated_pdf.run", return_value=(len(pages), [(595.0, 842.0)] * len(pages), raw, shares)):
        return pdf.read_pdf(source)


def test_a_page_counts_when_it_fails_the_text_test_and_is_a_scan(tmp_path):
    signed_cover_then_scans = _read(tmp_path, [TEXT_PAGE, [], ["Page", "3"]], [0.0, 1.0, 0.98])
    assert signed_cover_then_scans.has_text_layer  # the whole document still counts as text, as before
    assert signed_cover_then_scans.pages_without_text == [2, 3]
    assert signed_cover_then_scans.page_image_shares == [0.0, 1.0, 0.98]  # the raw shares are kept
    assert _read(tmp_path, [TEXT_PAGE, TEXT_PAGE], [0.0, 1.0]).pages_without_text == []  # a page with its own text
    assert _read(tmp_path, [TEXT_PAGE], [0.0]).pages_without_text == []


def test_a_blank_page_a_few_characters_or_a_logo_is_not_a_scan(tmp_path):
    assert _read(tmp_path, [TEXT_PAGE, []], [0.0, 0.0]).pages_without_text == []  # blank
    assert _read(tmp_path, [TEXT_PAGE, ["Page 2 of 2"]], [0.0, 0.0]).pages_without_text == []  # a few characters
    assert _read(tmp_path, [TEXT_PAGE, ["Page 2 of 2"]], [0.0, 0.05]).pages_without_text == []  # a logo
    assert _read(tmp_path, [TEXT_PAGE, []], [0.0, pdf.MIN_SCAN_IMAGE_SHARE]).pages_without_text == [2]  # the limit counts


def test_the_image_share_clips_to_the_page_and_sums():
    page = (0.0, 0.0, 600.0, 800.0)
    assert isolated_pdf.image_share([], page) == 0.0
    assert isolated_pdf.image_share([{"x0": -10, "x1": 610, "top": -5, "bottom": 805}], page) == 1.0  # a bleed scan
    assert isolated_pdf.image_share([{"x0": 0, "x1": 60, "top": 0, "bottom": 40}], page) == 0.005  # a corner logo
    strips = [{"x0": 0, "x1": 600, "top": t, "bottom": t + 200} for t in (0, 200, 400)]  # a scan in three strips
    assert isolated_pdf.image_share(strips, page) == 0.75


# --- the real reader on synthetic PDFs ----------------------------------------------------------------------------


def _write_pdf(path: Path, pages: list[tuple[list[str], tuple[float, float, float, float] | None]]) -> Path:
    """A PDF whose pages carry text lines (Helvetica) and, optionally, one 2×2 grey image drawn over the rectangle
    (x, y, width, height in points, PDF coordinates). Built by hand, like `tests/pdfgen.py`."""
    n = len(pages)
    font, image = 3, 4  # object numbers; the pages start at 5 (page, contents) pairs
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{' '.join(f'{5 + 2 * i} 0 R' for i in range(n))}] /Count {n} >>".encode(),
        font: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        image: (b"<< /Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceGray /BitsPerComponent 8"
                b" /Length 4 >>\nstream\n\x00\xff\xff\x00\nendstream"),
    }
    for i, (lines, rect) in enumerate(pages):
        draw = f"q {rect[2]} 0 0 {rect[3]} {rect[0]} {rect[1]} cm /Im1 Do Q " if rect else ""
        text = ("BT /F1 11 Tf 14 TL 50 800 Td " + " ".join(f"({_escape(ln)}) Tj T*" for ln in lines) + " ET") if lines else ""
        stream = (draw + text).encode("latin-1")
        objects[5 + 2 * i] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font} 0 R >>"
                              f" /XObject << /Im1 {image} 0 R >> >> /Contents {6 + 2 * i} 0 R >>").encode()
        objects[6 + 2 * i] = f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for no in sorted(objects):
        offsets.append(len(out))
        out += f"{no} 0 obj\n".encode() + objects[no] + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode() + "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))
    return path


FULL_PAGE = (0.0, 0.0, 595.0, 842.0)
LOGO = (480.0, 780.0, 80.0, 40.0)


def test_the_reader_finds_the_scans_of_a_real_pdf(tmp_path):
    scans = pdf.read_pdf(_write_pdf(tmp_path / "scans.pdf", [(TEXT_PAGE, None), ([], FULL_PAGE), (["3"], FULL_PAGE)]))
    assert scans.has_text_layer and scans.pages_without_text == [2, 3]
    assert scans.page_image_shares[0] == 0.0 and scans.page_image_shares[1] == pytest.approx(1.0)
    assert policy.text_layer_coverage_reasons(scans.page_count, scans.pages_without_text) == ["pdf:pages_without_text:2/3"]


def test_the_reader_raises_nothing_for_a_blank_page_a_page_number_or_a_logo(tmp_path):
    plain = pdf.read_pdf(_write_pdf(tmp_path / "plain.pdf", [(TEXT_PAGE, LOGO), ([], None), (["Page 3 of 4"], None),
                                                              (["Page 4 of 4"], LOGO)]))
    assert plain.has_text_layer and plain.pages_without_text == []
    assert 0.0 < plain.page_image_shares[3] < pdf.MIN_SCAN_IMAGE_SHARE
    assert policy.text_layer_coverage_reasons(plain.page_count, plain.pages_without_text) == []


def test_the_policy_names_some_pages_but_not_all():
    assert policy.text_layer_coverage_reasons(3, [2, 3]) == ["pdf:pages_without_text:2/3"]
    assert policy.text_layer_coverage_reasons(3, []) == []
    assert policy.text_layer_coverage_reasons(3, [1, 2, 3]) == []  # no page has text: the document goes to OCR
    assert policy.text_layer_coverage_reasons(None, [1]) == []


def _pdf_text(pages_without_text: list[int], page_count: int = 3, has_text: bool = True) -> pdf.PdfText:
    return pdf.PdfText(path="synthetic.pdf", text="\n".join(TEXT_PAGE), lines=list(TEXT_PAGE), page_count=page_count,
                       has_text_layer=has_text, text_source="pdf" if has_text else None,
                       pages_without_text=pages_without_text)


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "p.sqlite"):
        source = tmp_path / "synthetic.pdf"
        source.write_bytes(b"%PDF-1.4 synthetic")
        yield source


def test_the_extraction_flow_raises_the_to_do(isolated):
    with patch("jav.pdf.read_pdf", return_value=_pdf_text([2, 3])), patch("jav.source_layer.save_from_pdftext", return_value="layer"):
        state = invoice_load(FlowState(doc_type="invoice_hu", source_path=str(isolated), case_id="t", arm="S"))
    assert state.needs_review and "pdf:pages_without_text:2/3" in state.review_reasons


def test_an_ordinary_document_and_a_scan_raise_nothing_here(isolated):
    with patch("jav.pdf.read_pdf", return_value=_pdf_text([])), patch("jav.source_layer.save_from_pdftext", return_value="layer"):
        state = invoice_load(FlowState(doc_type="invoice_hu", source_path=str(isolated), case_id="t", arm="S"))
    assert not state.needs_review and state.review_reasons == []
    with patch("jav.pdf.read_pdf", return_value=_pdf_text([1, 2, 3], has_text=False)):
        state = invoice_load(FlowState(doc_type="invoice_hu", source_path=str(isolated), case_id="t", arm="S"))
    assert state.review_reasons == []  # the whole document goes to OCR (ocr_pdf), which has its own to-dos


def test_the_detection_flow_raises_the_to_do_and_keeps_it_when_the_type_is_certain(isolated):
    from jav.detect import DetectResult

    with patch("jav.pdf.read_pdf", return_value=_pdf_text([2, 3])):
        state = detect_load(DetectState(source_path=str(isolated)))
    assert state.review_reasons == ["pdf:pages_without_text:2/3"]
    result = DetectResult.model_construct(doc_type="invoice_hu", confidence=0.99, issuer_hu=0.9, probabilities={},
                                          language="hu", parent=None, parent_prob=None)
    certain = state.model_copy(update={"doc_id": "d3", "run_id": "r1", "text_source": "pdf", "result": result,
                                       "uncertain": False})
    detect_save(certain)
    assert [r["reason"] for r in store.review_open_reasons("document", "d3")] == ["pdf:pages_without_text:2/3"]
