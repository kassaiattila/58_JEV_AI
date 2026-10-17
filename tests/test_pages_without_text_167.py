"""167 (review AI-3): pages without a text layer of their own are a visible to-do.

The text-layer test looked at the whole document. When one page has text (for example an electronically signed cover
page) and the others are scans, the document passed as text: the scanned pages never went to OCR, and nothing said
that their content was not read. Now each page gets the same test; when some pages (not all) fail it in a document
that has a text layer, both the detection and the extraction raise `pdf:pages_without_text:<n>/<total>`. Per-page OCR
of those pages is a later step. Synthetic word boxes only; no real PDF and no model call.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from jav import pdf, policy, store
from jav.flow import load_pdf as invoice_load
from jav.flow_detect import DetectState, load_pdf as detect_load, save as detect_save
from jav.models import FlowState

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


def _read(tmp_path: Path, pages: list[list[str]]) -> pdf.PdfText:
    """`read_pdf` over synthetic pages (the isolated reader's answer stands in for pdfplumber)."""
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"%PDF-1.4 synthetic")
    raw = [_words(p) for p in pages]
    with patch("jav.isolated_pdf.run", return_value=(len(pages), [(595.0, 842.0)] * len(pages), raw)):
        return pdf.read_pdf(source)


def test_each_page_gets_the_text_layer_test(tmp_path):
    signed_cover_then_scans = _read(tmp_path, [TEXT_PAGE, [], []])
    assert signed_cover_then_scans.has_text_layer  # the whole document still counts as text, as before
    assert signed_cover_then_scans.pages_without_text == [2, 3]
    assert _read(tmp_path, [TEXT_PAGE, TEXT_PAGE]).pages_without_text == []
    assert _read(tmp_path, [TEXT_PAGE]).pages_without_text == []


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
        state = invoice_load(FlowState(source_path=str(isolated), case_id="t", arm="S"))
    assert state.needs_review and "pdf:pages_without_text:2/3" in state.review_reasons


def test_an_ordinary_document_and_a_scan_raise_nothing_here(isolated):
    with patch("jav.pdf.read_pdf", return_value=_pdf_text([])), patch("jav.source_layer.save_from_pdftext", return_value="layer"):
        state = invoice_load(FlowState(source_path=str(isolated), case_id="t", arm="S"))
    assert not state.needs_review and state.review_reasons == []
    with patch("jav.pdf.read_pdf", return_value=_pdf_text([1, 2, 3], has_text=False)):
        state = invoice_load(FlowState(source_path=str(isolated), case_id="t", arm="S"))
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
