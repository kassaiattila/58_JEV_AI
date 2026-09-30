"""Partial OCR is always a visible to-do (040 K1, the F07 probe of 038). No real PDF and no model call."""

from pathlib import Path
from unittest.mock import patch

import pytest

from jav import policy, store
from jav.flow import ocr_pdf as invoice_ocr
from jav.flow_detect import DetectState, ocr_pdf as detect_ocr
from jav.models import FlowState
from jav.pdf import PdfText


def _partial(pages_ocr: int, page_count: int = 13) -> PdfText:
    return PdfText(path="synthetic.pdf", text="Synthetic OCR text", page_count=page_count, text_source="ocr",
                   ocr={"mean_conf": 0.99, "low_conf_ratio": 0.0, "engine": "native", "pages_ocr": pages_ocr})


def test_policy_coverage_reason():
    assert policy.ocr_coverage_reasons(13, 12) == ["ocr:partial_pages:12/13"]
    assert policy.ocr_coverage_reasons(12, 12) == [] and policy.ocr_coverage_reasons(None, 3) == []


def test_invoice_ocr_step_marks_partial_pages():
    with patch("jav.ocr.ocr_with_escalation", return_value=(_partial(12), False)):
        state = invoice_ocr(FlowState(source_path="synthetic.pdf", case_id="t", arm="S", page_count=13))
    assert state.needs_review and "ocr:partial_pages:12/13" in state.review_reasons


def test_detect_ocr_step_marks_partial_pages():
    with patch("jav.ocr.ocr_with_escalation", return_value=(_partial(12), False)):
        state = detect_ocr(DetectState(source_path="synthetic.pdf", page_count=13))
    assert "ocr:partial_pages:12/13" in state.review_reasons


def test_full_coverage_adds_nothing():
    with patch("jav.ocr.ocr_with_escalation", return_value=(_partial(13), False)):
        state = invoice_ocr(FlowState(source_path="synthetic.pdf", case_id="t", arm="S", page_count=13))
    assert not any(r.startswith("ocr:partial_pages") for r in state.review_reasons)


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "o.sqlite"):
        yield


def test_detect_save_keeps_coverage_reason_even_when_type_is_certain(isolated):
    """A certain type closes detect's own reasons, but the to-do for the skipped pages stays open."""
    from jav.flow_detect import save
    from jav.detect import DetectResult
    result = DetectResult.model_construct(doc_type="invoice_hu", confidence=0.99, issuer_hu=0.9, probabilities={}, language="hu",
                                          parent=None, parent_prob=None)
    state = DetectState(source_path="synthetic.pdf", doc_id="d13", page_count=13, run_id="r1", text_source="ocr",
                        result=result, uncertain=False, review_reasons=["ocr:partial_pages:12/13"])
    save(state)
    assert [r["reason"] for r in store.review_open_reasons("document", "d13")] == ["ocr:partial_pages:12/13"]
