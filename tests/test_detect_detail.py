"""047 T1.2: detailed type within the coarse category (synthetic text, fake JEV; no paid calls)."""

from types import SimpleNamespace

from jav import detect_detail


class FakeJev:
    def __init__(self, choice, confidence=0.9):
        self.calls = []
        self.choice, self.confidence = choice, confidence

    def ask(self, request_id, state, questions, **kw):
        self.calls.append((request_id, state, questions))
        pick = SimpleNamespace(choice=self.choice, confidence=self.confidence, probabilities={self.choice: self.confidence})
        return SimpleNamespace(response=SimpleNamespace(choices={"detail_type": pick}), call=None)


def test_candidates_follow_parent_and_skip_pending_types():
    assert set(detect_detail.candidates("bank_statement")) == {"statement_cib", "statement_erste"}
    assert "invoice_out" in detect_detail.candidates("invoice_hu") and "invoice_hu" in detect_detail.candidates("invoice_hu")
    assert "meghivo" not in detect_detail.candidates("other")  # pending in the legacy project too: manual only
    assert detect_detail.candidates("payment_reminder") == []


def test_single_candidate_needs_no_call():
    jev = FakeJev("none")
    r = detect_detail.resolve("receipt", "NAV elfogadó nyugta, érkeztetési szám 123", jev=jev, run_id="t")
    assert (r.key, r.method) == ("nav_receipt", "single") and jev.calls == []


def test_anchors_decide_between_siblings_without_a_call():
    jev = FakeJev("none")
    text = "Fővárosi Csatornázási Művek Zrt. csatornadíj számla, szennyvíz elvezetés, elszámolási időszak"
    r = detect_detail.resolve("utility_bill_hu", text, jev=jev, run_id="t")
    assert r.key == "csatorna_szamla" and r.method == "anchors" and jev.calls == []


def test_several_qualifying_siblings_go_to_jev_choice():
    jev = FakeJev("statement_erste", 0.93)
    r = detect_detail.resolve("bank_statement", "Bankszámlakivonat, CIB Bank és Erste Bank átvezetés, nyitó egyenleg", jev=jev, run_id="t")
    assert r.key == "statement_erste" and r.method == "jev" and r.confidence == 0.93
    rid, state, questions = jev.calls[0]
    assert rid == "detect_detail" and set(questions["detail_type"].criteria) >= {"statement_cib", "statement_erste", "none"}


def test_jev_none_or_unavailable_leaves_detail_open():
    r = detect_detail.resolve("bank_statement", "kivonat: CIB Bank, Erste Bank", jev=FakeJev("none", 0.8), run_id="t")
    assert r.key is None and r.method == "jev"
    r2 = detect_detail.resolve("bank_statement", "kivonat: CIB Bank, Erste Bank", jev=None, run_id="t")
    assert r2.key is None and r2.method == "no_jev"


def test_default_pack_of_the_category_when_no_sibling_qualifies():
    r = detect_detail.resolve("invoice_hu", "Számla sorszám 2026/15, fizetési határidő", jev=FakeJev("none"), run_id="t")
    assert (r.key, r.method) == ("invoice_hu", "anchors")
    # the outgoing-invoice marker (BD serial number) also excludes the Hungarian invoice: small lead → JEV decides
    r2 = detect_detail.resolve("invoice_hu", "Számla BD123 Minta Kft.", jev=FakeJev("invoice_out", 0.95), run_id="t")
    assert (r2.key, r2.method) == ("invoice_out", "jev") and r2.scores["invoice_out"] > r2.scores["invoice_hu"]


def test_detect_flow_saves_detail_and_opens_task_when_undecided(tmp_path):
    """After detection the detailed type is saved to the document; a type left open is a to-do of its own (no JEV)."""
    from jav import store
    from jav.detect import DetectResult
    from jav.flow_detect import DetectState, _resolve_detail, save

    with store.use_store(tmp_path / "d.sqlite"):
        for doc_id, broad, text in (("d1", "receipt", "NAV nyugta"), ("d2", "bank_statement", "kivonat: CIB Bank, Erste Bank")):
            result = DetectResult.model_construct(doc_type=broad, confidence=0.99, issuer_hu=0.9, probabilities={}, language="hu",
                                                  parent=None, parent_prob=None)
            state = DetectState(source_path="synthetic.pdf", doc_id=doc_id, page_count=1, run_id="r1", text_source="pdf",
                                text=text, result=result, uncertain=False)
            _resolve_detail(state, None)
            save(state)
        with store.connect() as c:
            rows = dict(c.execute("SELECT doc_id, detail_type FROM documents").fetchall())
        assert rows == {"d1": "nav_receipt", "d2": None}
        assert [r["reason"] for r in store.review_open_reasons("document", "d2")] == ["detect:detail_open:bank_statement"]
        assert store.review_open_reasons("document", "d1") == []
