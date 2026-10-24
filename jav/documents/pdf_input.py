"""A PDF's way into a flow, shared by the type recognition and the data extraction (194, plan G-tidy R3).

Plain-language summary: both flows start a PDF the same way. They read its text layer from the frozen source copy
when there is one, know the document by the digest of its bytes, and note the pages that have no text layer of their
own. A PDF without text goes through OCR, escalated to Azure when the local result is weak. The two flows used to
write these steps out each; now each flow's step calls this module and keeps only what it does differently: the
extraction saves the source layer and judges the OCR quality, the recognition remembers the Azure reading's
fingerprint.

Layer: a flow's step → **this** → `jav.documents.pdf`, `jav.documents.ocr` (227, plan R3c: the pages-without-text
rule is this module's, until then the AI layer's decision rules).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jav.core.digest import file_sha256
from jav.documents.pdf import PdfText


@dataclass(frozen=True)
class Recognised:
    """The OCR of a PDF without text: its text (None when OCR could not run), whether it was escalated, its quality
    signals, and the to-do to raise when OCR could not run (`ocr:unavailable:<reason>`)."""

    pdf: PdfText | None
    escalated: bool = False
    signals: dict[str, Any] = field(default_factory=dict)
    unavailable: str | None = None


def text_layer_coverage_reasons(page_count: int | None, pages_without_text: list[int] | None) -> list[str]:
    """167 (review AI-3): in a document with a text layer, some pages (not all) are scans without text of their own,
    e.g. behind an electronically signed cover page (`pdf.pages_without_text`: no text and an image over most of the
    page). Those pages were neither read nor sent to OCR, so this is always a visible to-do, like partial OCR. With no
    page of text the whole document goes to OCR instead (`ocr_pdf`)."""
    n = len(pages_without_text or [])
    if not page_count or n == 0 or n >= page_count:
        return []
    return [f"pdf:pages_without_text:{n}/{page_count}"]


def read_source(source_path: str, read_path: str | None) -> tuple[PdfText, str, list[str]]:
    """The PDF's text layer (from the frozen copy `read_path` when given), its identity (the digest of the file read)
    and the to-dos of its pages without a text layer of their own (167, AI-3: those pages were neither read nor sent
    to OCR; none for a PDF without any text layer, which goes to OCR whole)."""
    from jav.documents.pdf import read_pdf

    path = read_path or source_path
    pdf = read_pdf(path)
    coverage = text_layer_coverage_reasons(pdf.page_count, pdf.pages_without_text) if pdf.has_text_layer else []
    return pdf, file_sha256(path), coverage


def recognise(source_path: str, read_path: str | None, doc_id: str, page_count: int | None) -> Recognised:
    """OCR of a PDF without text (`jav.documents.ocr`, cached), escalated to Azure on a weak local result within the run's
    budget. While the flow reads the frozen copy, which the legacy sidecar cannot see, the Azure call may use the
    unchanged original instead (`azure_alias`). No engine: no text and an `ocr:unavailable:<reason>` to-do; the flow
    goes on."""
    from jav.documents.ocr import OcrUnavailableError, azure_alias, ocr_with_escalation

    try:
        with azure_alias(source_path if read_path else None, doc_id):
            pdf, escalated = ocr_with_escalation(read_path or source_path, page_count=page_count)
    except OcrUnavailableError as exc:
        return Recognised(pdf=None, unavailable=f"ocr:unavailable:{type(exc).__name__}")
    return Recognised(pdf=pdf, escalated=escalated, signals=pdf.ocr or {})


__all__ = ["Recognised", "read_source", "recognise"]
