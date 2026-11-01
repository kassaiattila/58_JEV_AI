"""272 (K2, the check of the code review fixes): outside a run or a budgeted measurement no paid OpenAI call is made.

Since 265 (SEC-02, TOOL-03) the JEV adapter and the Azure branch answer only from earlier answers without a run
context, and GPT's paragraph and structured answer refuse. Three GPT paths still called OpenAI without a budget or the
call log when no context was set (the G path's extraction, the structured choice, the email tasks); no entry point
reaches them so today, but a new one would have spent unseen. They now refuse with `NoBudget`, as the others do; a
stand-in agent handed over by a test or a free demonstration (`use_agent_factory`) still answers. Offline.
"""

from __future__ import annotations

import pytest

from jav.ai import extract_llm, gpt_choice
from jav.ai.gpt_answer import NoBudget
from jav.ai.typepack import get as get_pack
from jav.core import calls
from jav.domains.email import email_tasks
from tests.test_no_jev_085 import _FakeAgent


class _Paid:
    """Stands for the real OpenAI agent: being built or run at all fails the test."""

    def __init__(self, *_a, **_k) -> None:
        raise AssertionError("the real OpenAI agent was built outside a budget")


def test_the_extraction_is_refused_outside_a_budget(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(extract_llm, "get_agent", _Paid)
    assert calls.current() is None
    with pytest.raises(NoBudget):
        extract_llm.extract_scored("Invoice number: A-1", pack=get_pack("invoice_hu"), run_id="t-272")


def test_the_structured_choice_is_refused_outside_a_budget(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(gpt_choice, "openai_chat_model", _Paid)
    with gpt_choice.use_agent_factory(None), pytest.raises(NoBudget):  # the real construction (the tests' guard off)
        gpt_choice.ask("detect", "Pick one.", "{}", {"doc_type": ["invoice_hu", "none"]}, run_id="t-272",
                       limits=gpt_choice.Limits(config_hash="t", max_output_tokens=50, top_logprobs=0))


def test_the_email_tasks_are_refused_outside_a_budget(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(email_tasks, "get_agent", _Paid)
    with pytest.raises(NoBudget):
        email_tasks.extract(email_tasks.snapshot(message_id="m-1", subject="s", body="b", body_status="complete",
                                                 attachments=[]), intent_hint=None, run_id="t-272")


def test_a_stand_in_agent_still_answers_outside_a_budget():
    pack = get_pack("invoice_hu")
    with extract_llm.use_agent_factory(lambda p: _FakeAgent(p, {"invoice_number": "A-1"})):
        out = extract_llm.extract_scored("Invoice number: A-1", pack=pack, run_id="t-272")
    assert out.output["invoice_number"] == "A-1"
