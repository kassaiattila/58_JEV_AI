"""265 (code review AI-12): a rerun of the type recognition closes the detail to-do it no longer has, and queues the
coverage reasons once.

When a rerun found no type (unknown), the earlier detailed-type to-do stayed open, and the coverage reasons (partial
OCR, pages without text) went both under the type recognition's to-do and under their own producer. Synthetic
documents in an empty store; no AI call.
"""

from __future__ import annotations

import pytest

from jav.core import store
from jav.flows import flow_detect


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "detect.sqlite"):
        yield tmp_path


def _open(doc_id: str) -> dict[str, list[str]]:
    with store.connect() as c:
        rows = c.execute("SELECT r.producer, r.reason FROM " + store.SUBJECT_REASONS
                         + " WHERE q.subject_kind='document' AND q.subject_id=? AND r.status='open'", (doc_id,)).fetchall()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["producer"], []).append(r["reason"])
    return out


def test_a_rerun_with_an_unknown_type(db) -> None:
    doc = "d" * 64
    store.review_enqueue(subject_kind="document", subject_id=doc, run_id="run-a", producer="detect_detail",
                         reasons=["detect_detail:gpt_failed:TypeError"])
    state = flow_detect.DetectState(source_path="x.pdf", run_id="run-b", doc_id=doc, text_source="ocr",
                                    review_reasons=["detect:no_result", "ocr:partial_pages:3"])
    with store.connect() as c:
        flow_detect._save(state, c)
    found = _open(doc)
    assert "detect_detail" not in found
    assert found["detect"] == ["detect:no_result"] and found["ocr_coverage"] == ["ocr:partial_pages:3"]
