"""167 (review AI-10): the verification request gets a last fitting step that leaves the lists out.

The request-size fitting of the G path only shortened the source lines. A long extracted list (line items, statement
transactions) stayed in the request, so both the request and its one tighter retry ended in `max_tokens_exceeded`, and
the whole verification became a `jev_unavailable` to-do. Now, only after both of those failed, one last request leaves
the source lines and the pack's list fields out; the header fields are still verified, and each list left out is its
own to-do (`jev:list_omitted:<field>`), so its rows are never taken as checked. An ordinary request is unchanged.
Stand-in JEV answers only; no model call.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from typesafe_sdk import Noul

from jav.ai import policy
from jav.ai.jev import JevUnavailableError
from jav.ai.jev_verify import site_for
from jav.ai.models import FlowState, JevVerdicts, LineLayout
from tests.test_no_jev_085 import GOOD

TOKEN_ERROR = "TypeSafeBadRequestError:400:max_tokens_exceeded"
ROWS = [{"description": f"Synthetic service row {i}", "quantity": "1", "unit_price": "100", "net_amount": "100"}
        for i in range(1, 61)]


def _lines() -> list[LineLayout]:
    texts = [f"{k}: {v}" for k, v in GOOD.items()] + [f"Synthetic service row {i}   1   100   100" for i in range(1, 61)]
    return [LineLayout(no=i, page=1, text=t) for i, t in enumerate(texts, 1)]


class _Jev:
    """A JEV stand-in: refuses with a token error while the extraction still carries a list (`refuse_lists`), or for
    the first `fail_times` requests; answers every Noul with 0.1 otherwise."""

    def __init__(self, *, refuse_lists: bool = False, fail_times: int = 0, reason: str = TOKEN_ERROR):
        self.refuse_lists, self.fail_times, self.reason = refuse_lists, fail_times, reason
        self.states: list[dict] = []
        self.questions: list[dict] = []

    def ask(self, request_id, state, questions, **_kw):
        self.states.append(state)
        self.questions.append(questions)
        if self.fail_times > 0 or (self.refuse_lists and state["extraction"].get("line_items")):
            self.fail_times -= 1
            raise JevUnavailableError(self.reason)
        nouls = {q: SimpleNamespace(noul=0.1) for q, v in questions.items() if isinstance(v, Noul)}
        return SimpleNamespace(response=SimpleNamespace(nouls=nouls, model="jev-test"),
                               call=SimpleNamespace(request_id=request_id, cached=False))


@pytest.fixture()
def site(monkeypatch):
    s = site_for("invoice_hu")
    monkeypatch.setattr(s, "request_char_budget", 10_000_000)  # the first request is not trimmed
    return s


def test_an_ordinary_request_is_unchanged(site):
    llm = {**GOOD, "line_items": ROWS}
    jev = _Jev()
    verdicts, _ = site.verify(jev, _lines(), llm, run_id="t")
    assert len(jev.states) == 1 and verdicts.omitted == []
    sent = jev.states[0]
    assert sent["extraction"] == llm and len(sent["source_lines"]) == len(_lines())
    assert set(sent) == {"document", "source_lines", "extraction", "evidence"}


@pytest.mark.parametrize(("with_rows", "expected"), [
    (True, "aceae562740faacea029344b498f937d94eb8bd01cf8f78ec8fe573686324d55"),
    (False, "5345634edb5c8d882ded2278b34b36031eeeeede6f5514112e0599e9a8b4fd34"),
])
def test_an_ordinary_request_keeps_its_cache_key(site, with_rows, expected):
    """The request hash (the JEV cache key) of an ordinary request, recorded on the code before 167. A deliberate
    change to the `verify` call site or the invoice pack changes it too, and needs a paid golden run anyway."""
    from jav.ai.jev import request_hash

    jev = _Jev()
    site.verify(jev, _lines(), {**GOOD, "line_items": ROWS} if with_rows else dict(GOOD), run_id="t")
    assert request_hash("jev-1.13.0", jev.states[0], jev.questions[0]) == expected


def test_a_list_too_long_for_both_attempts_is_left_out_of_a_last_request(site):
    llm = {**GOOD, "line_items": ROWS}
    jev = _Jev(refuse_lists=True)
    verdicts, _ = site.verify(jev, _lines(), llm, run_id="t")
    assert len(jev.states) == 3  # the request, its tighter retry, then the last resort
    last = jev.states[2]
    assert "source_lines" not in last and "line_items" not in last["extraction"]
    assert last["extraction"]["invoice_number"] == GOOD["invoice_number"]  # the header fields are still verified
    assert jev.questions[2] == jev.questions[0]  # the questions do not change
    assert verdicts.omitted == ["line_items"] and verdicts.flags


def test_the_left_out_list_is_a_to_do():
    state = FlowState(source_path="synthetic.pdf", case_id="t", arm="G", doc_type="invoice_hu",
                      verdicts=JevVerdicts(omitted=["line_items"]))
    policy.apply_verdict_policy(state)
    assert state.needs_review and "jev:list_omitted:line_items" in state.review_reasons


def test_without_a_list_to_leave_out_or_on_another_error_it_fails_as_before(site):
    with pytest.raises(JevUnavailableError):
        site.verify(_Jev(fail_times=2), _lines(), dict(GOOD), run_id="t")  # nothing left to leave out
    jev = _Jev(fail_times=1, reason="TypeSafeRateLimitError:429")
    with pytest.raises(JevUnavailableError):
        site.verify(jev, _lines(), {**GOOD, "line_items": ROWS}, run_id="t")
    assert len(jev.states) == 1  # not a size error: no retry, no last resort
    jev = _Jev(fail_times=3)
    with pytest.raises(JevUnavailableError):
        site.verify(jev, _lines(), {**GOOD, "line_items": ROWS}, run_id="t")
    assert len(jev.states) == 3  # the last resort is asked once
