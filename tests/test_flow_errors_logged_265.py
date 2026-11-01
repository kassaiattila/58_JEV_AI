"""265 (code review AI-05): an error a flow turns into a to-do is logged with its traceback.

The extraction's general error, the type recognition's and the detailed type choice's non-provider errors and the
native interpretation's boundary turned an exception into a to-do (`llm:failed:TypeError`) without a trace anywhere,
so a programming error looked like a model failure. They now log it with its traceback; the to-do stays as it was.
272 (K5): the extraction's and the type recognition's handlers are run, not read; the R5 fault (a handler that itself
failed) was a run's, which a reading of the source could not see.
"""

from __future__ import annotations

import inspect
import logging

from burr.integrations.pydantic import subset_model

from jav.ai import detect_gpt, extract_llm, native_processing
from jav.ai.models import FlowState
from jav.flows import flow, flow_detect


def _failing(*_a, **_k):
    raise TypeError("a synthetic programming error")


def test_the_extraction_s_failure_is_logged_with_its_traceback_and_is_its_to_do(monkeypatch, caplog) -> None:
    given = subset_model(FlowState, ["text", "run_id", "doc_type", "needs_review", "review_reasons"],
                         ["llm_output", "llm_token_p"], "extract_llm_input")
    monkeypatch.setattr(extract_llm, "extract_scored", _failing)
    with caplog.at_level(logging.ERROR):
        state = flow.extract_llm(given(text="Invoice number: A-1", run_id="run-x", doc_type="invoice_hu",
                                       needs_review=False, review_reasons=[]))
    assert "llm:failed:TypeError" in state.review_reasons
    [record] = [r for r in caplog.records if "the extraction failed" in r.getMessage()]
    assert record.exc_info and record.exc_info[0] is TypeError and "run-x" in record.getMessage()


def test_the_type_recognition_s_failure_is_logged_with_its_traceback(monkeypatch, caplog) -> None:
    monkeypatch.setattr(detect_gpt, "detect", _failing)
    state = flow_detect.DetectState(source_path="C:/invented/scan.pdf", run_id="run-x", jev=False)
    with caplog.at_level(logging.ERROR):
        flow_detect._detect_gpt(state, pdf=None)
    [record] = [r for r in caplog.records if "the type recognition failed" in r.getMessage()]
    assert record.exc_info and record.exc_info[0] is TypeError and "scan.pdf" in record.getMessage()


def test_the_other_boundaries_log_the_exception() -> None:
    assert 'exception("the detailed type choice failed' in inspect.getsource(flow_detect)
    assert 'exception("the native interpretation failed' in inspect.getsource(native_processing)
