"""231 (stage D, D-c7a): the invented insurer's condition documents as PDFs, read as a rule proposal will read a file.

Each condition document is written as pages, every clause (its number, title and text) on the page it says; read back
by the text-layer reader, each of the 16 rules finds its quote on the page it cites. The single-page writer the probes
use writes the same bytes as before (their PDFs' fingerprints are cache keys). Invented data; no paid call.
"""

from __future__ import annotations

import hashlib
import re

import pytest

from jav.app import product_sets
from jav.documents import pdf
from jav.documents.synthetic_pdf import write_unicode_pdf, write_unicode_pdf_pages

SET = product_sets.load()
SAMPLE = ["Invented Ltd   Invoice   2026-10-26", "Árvíztűrő tükörfúrógép ŐŰ őű (a) \\ b", "word " * 46,
          "a   b   c   d   e   f   g"]


def _plain(text: str) -> str:
    """Words as a reader joins them: one space between them, a word broken at its hyphen joined again."""
    return re.sub(r"-\s+", "-", re.sub(r"\s+", " ", text)).strip()


@pytest.fixture(scope="module")
def read(tmp_path_factory):
    written = product_sets.write_documents(SET, tmp_path_factory.mktemp("documents"))
    return {ident: pdf.read_document(path, ocr=False) for ident, path in written.items()}


def _page(doc: pdf.PdfText, n: int) -> str:
    return _plain(" ".join(line.text for line in doc.layout if line.page == n))


def test_every_document_has_its_pages_and_a_text_layer(read) -> None:
    for ident, doc in read.items():
        pages = max(s.page or 1 for s in SET.documents[ident].content.sections)
        assert doc.has_text_layer and doc.page_count == pages, ident
        assert SET.documents[ident].content.title in _page(doc, 1), ident


@pytest.mark.parametrize("ident", sorted(SET.rules))
def test_every_rule_finds_its_quote_on_the_page_it_cites(read, ident) -> None:
    source = SET.rules[ident].source
    doc = read[source.document.split("@")[0]]
    page = _page(doc, source.page)
    assert _plain(source.quote) in page, (ident, source.page, page[:200])
    section = next(s for s in SET.documents[source.document.split("@")[0]].content.sections if s.clause == source.clause)
    assert f"{section.clause}. {section.title}" in page


def test_the_single_page_writer_writes_the_same_bytes_as_before(tmp_path) -> None:
    path = write_unicode_pdf(tmp_path / "sample.pdf", SAMPLE)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == "65756281910e3bfac26d2ef59977526a65b2e1fa63de73340d516cabe8f7fda3"
    again = write_unicode_pdf_pages(tmp_path / "pages.pdf", [SAMPLE])
    assert again.read_bytes() == path.read_bytes()


def test_a_pdf_has_at_least_one_page(tmp_path) -> None:
    with pytest.raises(ValueError):
        write_unicode_pdf_pages(tmp_path / "none.pdf", [])
