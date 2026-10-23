"""190 (plan 189 A2d): the verification's questions are named by the call site, and the GPT request's source words by
the pack.

Every verification asked three invoice questions (swapped parties, missing and extra line items), whatever the
document, and every GPT request called its text an invoice PDF. Now a call site names its document-level questions
(`document_nouls`) and the questions asked of each of the pack's list fields (`list_nouls`), and a pack names the words
before its source text (`source_prefix`). Without these keys, every existing call site and pack asks exactly what it
asked (pinned in tests/test_request_keys_190.py). Stand-in clients only; no model call.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jav import extract_llm, policy, typepack
from jav.core import cfg
from jav.jev_verify import VerifySite, site_for
from jav.models import FlowState, JevVerdicts, LineLayout

INVOICE_DOCUMENT_NOULS = ("parties_swapped", "line_items_missing_rows", "line_items_extra_rows")  # verify.json's, inherited
LIST_NOULS = {
    "missing_rows": {"question": "Is a row of `list_field` printed but absent?", "true": "a row is missing", "false": "none is"},
    "extra_rows": {"question": "Is a row of `list_field` not printed?", "true": "a row is extra", "false": "none is"},
}


def _site(monkeypatch, **changes) -> VerifySite:
    """The meeting minutes' call site with `changes` (its `nouls` extended by the list questions)."""
    real = cfg.load

    def load(name):
        data = real(name)
        if name == "callsite:verify_meeting_minutes":
            return {**data, **changes}
        if name == "callsite:verify":
            return {**data, "nouls": {**data["nouls"], **LIST_NOULS}}
        return data

    monkeypatch.setattr(cfg, "load", load)
    return VerifySite(typepack.get("meeting_minutes"))


def test_every_call_site_before_the_quote_request_asks_the_three_invoice_questions_and_none_per_list():
    for key in (k for k in typepack.keys() if k != "quote_request"):  # 190 (A2e): its own questions
        site = site_for(key)
        assert site.document_nouls == INVOICE_DOCUMENT_NOULS and site.list_nouls == (), key


def test_a_call_site_names_its_own_document_and_list_questions(monkeypatch):
    site = _site(monkeypatch, document_nouls=[], list_nouls=["missing_rows", "extra_rows"])
    questions = site.build_questions({"organization_name": None}, {})
    lists = typepack.get("meeting_minutes").list_fields
    assert sorted(q for q in questions if "__" in q and q.split("__")[0] in lists) == sorted(
        f"{f}__{n}" for f in lists for n in ("extra_rows", "missing_rows"))
    assert not set(INVOICE_DOCUMENT_NOULS) & set(questions)
    sent = questions["resolutions__missing_rows"].instructions
    assert sent["list_field"] == "resolutions" and sent["question"] == LIST_NOULS["missing_rows"]["question"]


def test_a_question_without_its_text_is_refused(monkeypatch):
    with pytest.raises(ValueError, match="no question text"):
        _site(monkeypatch, list_nouls=["invented_question"])


def test_a_list_flag_is_a_to_do_at_the_list_field():
    state = FlowState(source_path="x.pdf", case_id="c", arm="G", doc_type="meeting_minutes")
    state.verdicts = JevVerdicts(flags={"resolutions": {"missing_rows": 0.97, "extra_rows": 0.02}})
    policy.apply_verdict_policy(state)
    assert state.review_reasons == ["jev:missing_rows:resolutions:0.97"]


def test_the_verification_answers_a_list_question_as_a_flag_of_the_list(monkeypatch):
    site = _site(monkeypatch, document_nouls=["parties_swapped"], list_nouls=["missing_rows"])

    class Jev:
        def ask(self, request_id, state, questions, **_kw):
            nouls = {q: SimpleNamespace(noul=0.9 if q.endswith("__missing_rows") else 0.1) for q in questions}
            return SimpleNamespace(response=SimpleNamespace(nouls=nouls, model="jev-test"), call=None)

    lines = [LineLayout(no=1, page=1, text="Jegyzokonyv")]
    verdicts, _ = site.verify(Jev(), lines, {"organization_name": None, "resolutions": []}, run_id="t")
    assert verdicts.flags["resolutions"] == {"missing_rows": 0.9}
    assert verdicts.doc_flags == {"parties_swapped": 0.1}


def test_the_source_words_are_the_packs_own_or_the_invoice_pdfs():
    pack = typepack.get("meeting_minutes")
    assert extract_llm.source_prefix(pack) == extract_llm.USER_PREFIX
    own = pack.model_copy(update={"source_prefix": "SOURCE TEXT of the request:\n\n"})
    assert extract_llm.source_prefix(own) == "SOURCE TEXT of the request:\n\n"
    assert all(typepack.get(k).source_prefix is None for k in typepack.keys() if k != "quote_request")
