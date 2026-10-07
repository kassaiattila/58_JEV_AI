"""126 (5th group, round A; backlog Q-money-request-size): the Hungarian and the foreign invoice's selection call sites
get the request-size budget the utility call site has had since 015.

Without a budget a request over JEV's token limit was neither trimmed nor retried: the money question of five Hungarian
invoices ended in a `jev_unavailable` to-do. With the budget, an oversized request is fitted, and a token error is
retried once with a tighter request (`jav/jev_budget.py`). A request within the budget is sent exactly as before, so
its cache key, and the stored answer, stay the same. Synthetic lines only; no AI call.
"""
from __future__ import annotations

import json

import pytest
from typesafe_sdk import Choice

from jav import candidates as cand, typepack
from jav.adapters.jev import JevUnavailableError
from jav.jev_select import site_for
from tests.test_ocr_utility import FakeJev, _line

UTILITY_BUDGET = json.loads(open("configs/callsites/select_utility.json", encoding="utf-8").read())["request_char_budget"]


def _invoice_lines(n_money: int) -> list:
    head = [_line(1, ("INVOICE", 20)), _line(2, ("Invoice number: INV-2026-001", 20), ("Date: 2026-09-01", 400)),
            _line(3, ("Seller: Example Trading Ltd", 20), ("VAT: HU12121216", 400)),
            _line(4, ("Buyer: Sample Services Ltd", 20), ("VAT: HU13570008", 400))]
    rows = [_line(5 + i, (f"Item {i} consulting service, monthly fee", 20), (f"{1000 + i},00 HUF", 400)) for i in range(n_money)]
    return head + rows + [_line(5 + n_money, ("Total: 1 270,00 HUF", 20))]  # line numbers 1..n, as the layout gives


@pytest.mark.parametrize("key", ["invoice_hu", "invoice_foreign"])
def test_the_invoice_selection_has_the_utility_request_budget(key):
    assert site_for(key).request_char_budget == UTILITY_BUDGET == 110000


@pytest.mark.parametrize("key", ["invoice_hu", "invoice_foreign"])
def test_a_request_within_the_budget_is_sent_unchanged(key):
    site = site_for(key)
    pack = typepack.get(key)
    lines = _invoice_lines(20)
    cands = cand.find_all(lines, pack.candidate_profile, text_labels=pack.text_labels)
    money = next(f for f, k in site.field_kind.items() if k == "money")
    questions = {money: site.build_choice(money, cands.get("money", []))}
    state = {"document": "x", "lines": [ln.model_dump() for ln in lines]}
    assert site._size(state, questions) < site.request_char_budget
    fitted_state, fitted_questions = site._fit_budget("money", state, questions, lines, cands, [money])
    assert fitted_state is state and fitted_questions is questions  # the same request: the same cache key


class _TokenLimitJev(FakeJev):
    def __init__(self, fail_times: int) -> None:
        super().__init__()
        self.fail_times = fail_times
        self.sizes: list[int] = []

    def ask(self, request_id, state, questions, **kw):
        self.sizes.append(len(json.dumps(state, ensure_ascii=False))
                          + sum(len(json.dumps(dict(q.criteria))) for q in questions.values() if isinstance(q, Choice)))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise JevUnavailableError("TypeSafeBadRequestError:400:max_tokens_exceeded")
        return super().ask(request_id, state, questions, **kw)


@pytest.mark.parametrize("key", ["invoice_hu", "invoice_foreign"])
def test_a_token_error_is_retried_once_with_a_tighter_request(key):
    pack = typepack.get(key)
    lines = _invoice_lines(400)
    cands = cand.find_all(lines, pack.candidate_profile, text_labels=pack.text_labels)
    jev = _TokenLimitJev(fail_times=1)
    picks, _calls = site_for(key).select_fields(jev, lines, cands, run_id="t")
    assert len(jev.sizes) >= 2 and jev.sizes[1] < jev.sizes[0]  # the failed request, then a smaller one
    assert picks  # the answer of the retried request is read
    with pytest.raises(JevUnavailableError):  # a second token error is not retried: it reaches the flow as a to-do
        site_for(key).select_fields(_TokenLimitJev(fail_times=2), lines, cands, run_id="t")


# --- Q-gpt-receipt-label: the attachment's type as processed ---------------------------------------------------------


def test_an_attachment_shows_the_type_it_was_processed_as(tmp_path):
    from jav import mailbox, store

    with store.use_store(tmp_path / "w.sqlite"):
        store.upsert_document(doc_id="d" * 64, source_path="C:/synthetic/receipt.pdf", has_text=True, doc_type="invoice_foreign")
        raw = {"intent": "szamlakuldes", "intent_conf": 0.9, "next_flow": "m1:detect", "signals": {},
               "attachments": [{"filename": "receipt.pdf", "doc_id": "d" * 64, "doc_type": "receipt", "status": "done"},
                               {"filename": "other.pdf", "doc_id": None, "doc_type": "contract", "status": "done"}]}
        res = mailbox.effective_email_result(raw, None)
    first, second = res["attachments"]
    assert (first["doc_type"], first["shown_type"]) == ("receipt", "invoice_foreign")  # recognised category kept for routing
    assert second["shown_type"] == "contract" and res["next_flow"] == "m1:detect"
