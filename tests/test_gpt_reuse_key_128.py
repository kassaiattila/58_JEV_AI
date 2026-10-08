"""128 (backlog Q-gpt-key-narrowing): the reuse key of a GPT question is what GPT is sent, nothing more.

The GPT type detection and the GPT email intent passed their whole settings fingerprint into the reuse key, and that
fingerprint also covers the JEV call site and the registry descriptions only JEV reads. A JEV-only change therefore
made every earlier GPT answer unreachable, so re-running an old work package paid for GPT again although GPT was asked
exactly the same question. The key now holds the instructions, the output schema, the model settings, the output
limits and the document text; the settings fingerprint stays in the ledger.

Stand-in model only; no paid call.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from jav import gpt_choice, store
from jav.gpt_choice import Limits
from jav.runtime import calls
from tests.test_gpt_detect_086 import _factory, _tokens

FIELDS = {"kind": ["invoice", "other"]}
ANSWER = _tokens(('{"', 0.0, []), ("kind", 0.0, []), ('":"', 0.0, []), ("invoice", -0.05, [("other", -3.0)]), ('"}', 0.0, []))


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "k.sqlite"):
        yield tmp_path


def _counting_factory(counter: list[int]):
    inner = _factory(ANSWER)

    def factory(output_model, instructions):
        agent = inner(output_model, instructions)
        run_sync = agent.run_sync

        def counted(*a, **k):
            counter.append(1)
            return run_sync(*a, **k)

        agent.run_sync = counted
        return agent
    return factory


def _ask(run_id: str, limits: Limits, *, instructions: str = "Pick the kind.", prompt: str = "Document text"):
    calls.set_budget(run_id, "openai", Decimal("1"))
    with calls.use_run(budget_scope=run_id, reuse=True):
        return gpt_choice.ask("probe", instructions, prompt, FIELDS, run_id=run_id, limits=limits)


def test_a_settings_change_gpt_does_not_see_keeps_the_answer_reusable(isolated):
    asked: list[int] = []
    with gpt_choice.use_agent_factory(_counting_factory(asked)):
        first = _ask("run-a", Limits(config_hash="before-jev-change", max_output_tokens=200, top_logprobs=5))
        again = _ask("run-b", Limits(config_hash="after-jev-change", max_output_tokens=200, top_logprobs=5))
    assert len(asked) == 1
    assert again.values == first.values == {"kind": "invoice"}
    assert calls.journal("run-b")[0]["note"].startswith(calls.REUSED_NOTE)


@pytest.mark.parametrize("change", [
    {"limits": Limits(config_hash="h", max_output_tokens=300, top_logprobs=5)},
    {"limits": Limits(config_hash="h", max_output_tokens=200, top_logprobs=3)},
    {"instructions": "Pick the kind of the document."},
    {"prompt": "Another document"},
])
def test_a_change_to_what_gpt_is_sent_asks_again(isolated, change):
    asked: list[int] = []
    base = Limits(config_hash="h", max_output_tokens=200, top_logprobs=5)
    with gpt_choice.use_agent_factory(_counting_factory(asked)):
        _ask("run-a", base)
        _ask("run-b", change.get("limits", base), **{k: v for k, v in change.items() if k != "limits"})
    assert len(asked) == 2


def test_the_ledger_keeps_the_settings_fingerprint(isolated):
    with gpt_choice.use_agent_factory(_factory(ANSWER)):
        _ask("run-a", Limits(config_hash="fingerprint-1", max_output_tokens=200, top_logprobs=5))
    rows = [r for r in store.ledger_for_run("run-a") if r["provider"] == "openai"]
    assert rows and rows[0]["config_hash"] == "fingerprint-1"
