"""090: the code cross-check of the type recognised by GPT (backlog F-gpt-type-check, the owner's decision of
2026-10-02). A type or detailed type that presumes a Hungarian issuer, while the recogniser itself says the issuer is
not Hungarian, contradicts itself: a to-do, the type is kept. GPT's type errors are confident, so the confidence band
cannot catch them; the saved measurement had one such case (a foreign receipt as a Hungarian tax-authority receipt).

Synthetic documents and a stand-in model only; no paid call.
"""

import pytest

from jav import detect_detail, detect_gpt, flow_detect, policy, store
from jav.adapters import jev as jev_mod
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_gpt_detect_086 import DETAIL_TOKENS, _FakeAgent, _NoJev, _tokens

# {"doc_type":"invoice_hu","issuer_is_hungarian":"no","language":"en"}: a Hungarian type, a non-Hungarian issuer
CONTRADICTING_TOKENS = _tokens(
    ('{"', 0.0, []), ("doc", 0.0, []), ("_type", 0.0, []), ('":"', 0.0, []),
    ("invoice", -0.01, [("utility", -5.0)]), ("_h", -0.01, [("_foreign", -5.0)]), ('u', 0.0, []),
    ('","', 0.0, []), ("issuer", 0.0, []), ("_is", 0.0, []), ("_h", 0.0, []), ("ungarian", 0.0, []), ('":"', 0.0, []),
    ("no", -0.01, [("yes", -5.0)]), ('","', 0.0, []), ("language", 0.0, []), ('":"', 0.0, []),
    ("en", -0.02, [("hu", -4.0)]), ('"}', 0.0, []),
)


@pytest.mark.parametrize(("doc_type", "detail", "issuer_hu", "expected"), [
    ("invoice_hu", "invoice_hu", 0.01, "detect:issuer_mismatch:invoice_hu"),
    ("receipt", "nav_receipt", 0.0, "detect:issuer_mismatch:nav_receipt"),  # the measured case: the detailed type
    ("utility_bill_hu", None, 0.1, "detect:issuer_mismatch:utility_bill_hu"),
    ("invoice_hu", "invoice_hu", 0.5, None),  # an uncertain issuer is the confidence's business, not a contradiction
    ("invoice_hu", "invoice_hu", 0.99, None),
    ("receipt", None, 0.0, None),  # a receipt can come from anywhere
    ("invoice_foreign", "invoice_foreign", 1.0, None),  # no contradiction: the form decides (an Upwork invoice)
    ("invoice_hu", "invoice_hu", None, None),
])
def test_a_hungarian_type_with_a_non_hungarian_issuer_is_a_to_do(doc_type, detail, issuer_hu, expected):
    assert policy.issuer_mismatch_reason(doc_type, detail, issuer_hu, engine="gpt") == expected


def test_the_cross_check_applies_to_gpt_only():
    """The owner's decision: JEV's types were right on all 102 sample documents; there it would only add noise."""
    assert policy.DETECT_ISSUER["engines"] == ["gpt"]
    assert policy.issuer_mismatch_reason("invoice_hu", "invoice_hu", 0.0, engine="jev") is None


def test_the_gpt_issuer_band_is_its_own():
    assert policy.band_name("detect.issuer_is_hungarian.gpt") == "gpt_detect"
    assert policy.band_name("detect.issuer_is_hungarian.jev") == policy.band_name("detect.issuer_is_hungarian")


def _contradicting(output_model, instructions):
    return _FakeAgent(output_model, DETAIL_TOKENS if "detail_type" in output_model.model_fields else CONTRADICTING_TOKENS)


def test_the_detection_flow_queues_the_contradiction_and_keeps_the_type(tmp_path, monkeypatch):
    monkeypatch.setattr(detect_detail, "anchor_score", lambda detect, text: (True, 1.0))
    path = write_text_pdf(tmp_path / "szamla.pdf", INVOICE_LINES)
    with store.use_store(tmp_path / "f.sqlite"), detect_gpt.use_agent_factory(_contradicting), jev_mod.use_adapter(_NoJev()):
        st = flow_detect.run_detect(str(path), run_id="r1", jev=False)
        open_reasons = [r["reason"] for r in store.review_open_reasons("document", st.doc_id)]
    assert st.result.doc_type == "invoice_hu" and st.result.issuer_hu < 0.3
    assert st.detail.key == "invoice_hu"
    assert "detect:issuer_mismatch:invoice_hu" in st.detail_reasons
    assert "detect:issuer_mismatch:invoice_hu" in open_reasons
