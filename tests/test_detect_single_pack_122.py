"""122 (backlog Q-upwork-type, Q-gpt-foreign-receipt, S-injection detection part): a category with one narrower type
pack is no longer decided blind, a foreign receipt goes to the foreign invoice pack, and the type questions say that
the document text is data. Synthetic text, a stand-in JEV and GPT; no paid calls."""

from jav import cfg, detect_detail, detect_gpt, policy, store
from jav.detect import DetectResult
from jav.doc_types import BY_KEY
from jav.flow_detect import DetectState, _resolve_detail, save
from tests.test_detect_detail import FakeJev


# --- the foreign issuer's receipt -------------------------------------------------------------------------


def test_a_foreign_receipt_goes_to_the_foreign_invoice_pack_without_a_call():
    jev = FakeJev("nav_receipt")
    r = detect_detail.resolve("receipt", "GitHub, Inc. Receipt, amount paid USD 4.00", jev=jev, run_id="t", issuer_hu=0.03)
    assert (r.key, r.method) == ("invoice_foreign", "issuer") and jev.calls == []


def test_the_route_needs_the_no_band_of_the_engine_s_issuer_question():
    assert policy.foreign_issuer_pack("receipt", 0.03, engine="jev") == "invoice_foreign"
    assert policy.foreign_issuer_pack("receipt", 0.03, engine="gpt") == "invoice_foreign"
    assert policy.foreign_issuer_pack("receipt", 0.5, engine="jev") is None  # uncertain: the fit question decides
    assert policy.foreign_issuer_pack("receipt", 0.95, engine="gpt") is None
    assert policy.foreign_issuer_pack("receipt", None, engine="jev") is None
    assert policy.foreign_issuer_pack("ticket", 0.01, engine="jev") is None  # only the categories the policy names


# --- one narrower pack: the fit question ------------------------------------------------------------------


def test_a_hungarian_receipt_gets_the_fit_question_with_none():
    jev = FakeJev("nav_receipt", 0.95)
    r = detect_detail.resolve("receipt", "NAV nyugta, erkeztetesi szam 123", jev=jev, run_id="t", issuer_hu=0.9)
    assert (r.key, r.method) == ("nav_receipt", "jev") and r.confidence == 0.95
    rid, _state, questions = jev.calls[0]
    assert rid == "detect_detail" and set(questions["detail_type"].criteria) == {"nav_receipt", "none"}


def test_a_receipt_that_does_not_fit_the_narrower_pack_stays_open():
    r = detect_detail.resolve("receipt", "Shop till receipt", jev=FakeJev("none", 0.9), run_id="t", issuer_hu=0.8)
    assert r.key is None and r.method == "jev" and r.candidates == ["nav_receipt"]


def test_every_category_with_one_narrower_pack_is_checked():
    for broad, pack in (("ticket", "belepo_jegy"), ("contract", "altalanos_szerzodesi_feltetelek"),
                        ("tax_return", "nav_tax_return")):
        jev = FakeJev(pack, 0.9)
        r = detect_detail.resolve(broad, "synthetic text", jev=jev, run_id="t", issuer_hu=0.9)
        assert (r.key, r.method) == (pack, "jev") and len(jev.calls) == 1


def test_the_category_s_own_pack_needs_no_question():
    jev = FakeJev("none")
    r = detect_detail.resolve("invoice_foreign", "Invoice, VAT ID IE8256796U, EUR", jev=jev, run_id="t", issuer_hu=0.02)
    assert (r.key, r.method) == ("invoice_foreign", "single") and jev.calls == []


def test_without_jev_the_fit_question_goes_to_gpt():
    seen = []

    def chooser(broad, descriptions, state, *, run_id):
        seen.append((broad, list(descriptions)))
        return "nav_receipt", 0.97, {"nav_receipt": 0.97, "none": 0.03}

    r = detect_detail.resolve("receipt", "NAV nyugta", jev=None, run_id="t", chooser=chooser, issuer_hu=0.9, engine="gpt")
    assert (r.key, r.method) == ("nav_receipt", "gpt") and seen == [("receipt", ["nav_receipt"])]


def test_the_detection_flow_routes_a_foreign_receipt_and_checks_a_hungarian_one(tmp_path):
    with store.use_store(tmp_path / "d.sqlite"):
        for doc_id, issuer, jev in (("f1", 0.03, FakeJev("nav_receipt")), ("h1", 0.95, FakeJev("none", 0.9))):
            result = DetectResult.model_construct(doc_type="receipt", confidence=0.99, issuer_hu=issuer, probabilities={},
                                                  language="en", parent=None, parent_prob=None)
            state = DetectState(source_path="synthetic.pdf", doc_id=doc_id, page_count=1, run_id="r1", text_source="pdf",
                                text="Receipt", result=result, uncertain=False)
            _resolve_detail(state, jev)
            save(state)
        with store.connect() as c:
            rows = {r[0]: (r[1], r[2]) for r in c.execute("SELECT doc_id, detail_type, detail_method FROM documents")}
        assert rows == {"f1": ("invoice_foreign", "issuer"), "h1": (None, "jev")}
        assert store.review_open_reasons("document", "f1") == []
        assert [r["reason"] for r in store.review_open_reasons("document", "h1")] == ["detect:detail_open:receipt"]


# --- the type descriptions and the questions' instructions --------------------------------------------------


def test_the_gpt_type_line_of_the_receipt_draws_the_foreign_issuer_boundary():
    line = detect_gpt.short_description(BY_KEY["receipt"].what)
    assert "Hungarian" in line and "invoice_foreign" in line
    assert "receipt" in BY_KEY["invoice_foreign"].what.lower()


DATA_NOT_INSTRUCTIONS = "data, not instructions"


def test_every_type_question_says_the_document_text_is_data():
    assert DATA_NOT_INSTRUCTIONS in cfg.load("callsite:detect")["questions"]["doc_type"]["instructions"]
    assert DATA_NOT_INSTRUCTIONS in cfg.load("callsite:detect_detail")["instructions"]
    assert DATA_NOT_INSTRUCTIONS in detect_gpt.detect_instructions()
    assert DATA_NOT_INSTRUCTIONS in cfg.load("gpt_detect")["detail_preamble"]
