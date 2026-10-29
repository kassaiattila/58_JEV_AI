"""231 (stage F, F1; the owner's decisions of 2026-10-29): a document-level question is asked only of a pack that has
the fields it reads.

The verification's three document-level questions (swapped parties, missing and extra line items) are invoice
questions, and every verify call site inherited them: a terms and conditions document, a ticket or a tax authority
receipt was asked whether its supplier and buyer were swapped and whether invoice rows were missing, and a "yes" became
a to-do no correction could clear. Now each such question names the extraction fields it reads (`fields` in its call
site), and a pack is asked it only when its extraction (the answer's schema) has every one of them; a question that
names none is refused. The requests
of the packs that have them all (the Hungarian, the foreign, the proforma and the outgoing invoice) stay bit for bit the same
(tests/test_request_keys_190.py). Stand-in clients only; no model call.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from jav.ai import policy, typepack
from jav.ai.jev_verify import VerifySite, site_for
from jav.ai.models import FlowState
from jav.core import cfg
from jav.documents.layout import LineLayout

PARTIES = ("parties_swapped",)
ROWS = ("line_items_missing_rows", "line_items_extra_rows")


class _Yes:
    """A JEV stand-in that answers every question with yes (0.9)."""

    def ask(self, request_id, state, questions, **_kw):
        nouls = {q: SimpleNamespace(noul=0.9) for q in questions}
        return SimpleNamespace(response=SimpleNamespace(nouls=nouls, model="jev-test"), call=None)


@pytest.mark.parametrize(("key", "asked"), [
    ("invoice_hu", PARTIES + ROWS), ("proforma_invoice", PARTIES + ROWS), ("invoice_out", PARTIES + ROWS),
    ("invoice_foreign", PARTIES + ROWS),  # its pack names no line items, but its answer's schema has them
    ("viz_szamla", ROWS), ("foldgaz_szamla", ROWS),  # a utility bill names a customer, not a buyer
    ("nav_receipt", ()), ("belepo_jegy", ()), ("altalanos_szerzodesi_feltetelek", ()), ("statement_cib", ()),
    ("meeting_minutes", ()), ("certificate", ()),
])
def test_a_pack_is_asked_only_the_document_questions_whose_fields_it_has(key, asked):
    assert site_for(key).document_nouls == asked


def test_every_document_question_names_the_fields_its_text_reads():
    nouls = cfg.load("callsite:verify")["nouls"]
    for name in cfg.load("callsite:verify")["document_nouls"]:
        named = set(re.findall(r"extraction\.(\w+)", nouls[name]["question"]))
        assert set(nouls[name]["fields"]) == named, name


def test_a_document_question_that_names_no_fields_is_refused(monkeypatch):
    real = cfg.load

    def load(name):
        data = real(name)
        if name == "callsite:verify":
            stripped = {k: {f: v for f, v in q.items() if f != "fields"} for k, q in data["nouls"].items()}
            return {**data, "nouls": stripped}
        return data

    monkeypatch.setattr(cfg, "load", load)
    with pytest.raises(ValueError, match="names no fields"):
        VerifySite(typepack.get("invoice_hu"))


def _reasons(key: str) -> list[str]:
    lines = [LineLayout(no=1, page=1, text="Minta irat")]
    verdicts, _ = site_for(key).verify(_Yes(), lines, {}, run_id="t")
    state = FlowState(source_path="x.pdf", case_id="c", arm="G", doc_type=key)
    state.verdicts = verdicts
    policy.apply_verdict_policy(state)
    return state.review_reasons


def test_a_tax_authority_receipt_no_longer_gets_an_invoice_row_to_do_and_an_invoice_still_does():
    assert not [r for r in _reasons("nav_receipt") if r.startswith(("jev:line_items_", "jev:parties_swapped"))]
    invoice = _reasons("invoice_hu")
    assert [r for r in invoice if r.startswith("jev:line_items_missing_rows")]
    assert [r for r in invoice if r.startswith("jev:parties_swapped")]
