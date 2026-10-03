"""Offline provider adapters must preserve real reservation/replay behavior."""
from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace
import os

import pytest

from jav import store
from jav.config import OPENAI_MODEL
from jav.readers.interpretation import ProposedExtraction, ground
from jav.readers.pipeline import read_files
from jav.readers.providers import extract_gpt, select_jev, verify_jev
from jav.runtime import calls

pytest.importorskip("docx", reason="Native reader dependencies await integration")
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Job Object reader boundary")


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.txt"
    path.write_text("Order code: 0007\nQuantity: 3", encoding="utf-8")
    return read_files([path])


def proposed():
    return ProposedExtraction.model_validate_json('''{"facts":[{"entity":"order","property":"code","value":"0007",
      "state":"stated","citations":[{"occurrence_id":"o0","element_id":"e0","quote":"Order code: 0007"}]}]}''')


class FakeAgent:
    def __init__(self):
        self.calls = 0

    def run_sync(self, prompt, **kwargs):
        self.calls += 1
        return SimpleNamespace(output=proposed(), usage=SimpleNamespace(input_tokens=100, output_tokens=40),
                               response=SimpleNamespace(model_name=OPENAI_MODEL))


def test_gpt_uses_existing_reservation_and_replays_without_a_second_call(source, tmp_path):
    path = tmp_path / "trial.sqlite"
    agent = FakeAgent()
    with store.use_store(path), calls.measurement("native-synthetic", {"openai": Decimal("1")}):
        first = extract_gpt(source, run_id="trial", isolated_store=path, agent=agent)
        again = extract_gpt(source, run_id="trial", isolated_store=path, agent=agent)
        assert first == again
        with store.connect() as conn:
            assert conn.execute("SELECT count(*) FROM invocations WHERE status='succeeded'").fetchone()[0] == 1
    assert agent.calls == 1
    assert first.execution == "synthetic_test"


def test_gpt_refuses_missing_provider_budget_before_calling(source, tmp_path):
    agent = FakeAgent()
    path = tmp_path / "trial.sqlite"
    with store.use_store(path), calls.measurement("only-jev", {"jev": Decimal("0.1")}):
        with pytest.raises(ValueError, match="sub-budget"):
            extract_gpt(source, run_id="trial", isolated_store=path, agent=agent)
    assert agent.calls == 0


class FakeJev:
    def no_cache_write(self):
        return nullcontext()

    def ask(self, request_id, state, questions, **kwargs):
        answers = {key: SimpleNamespace(choice="c0", noul=0.8) for key in questions}
        return SimpleNamespace(response=SimpleNamespace(answers=answers, model="jev-test"), cached=False)


def test_jev_selection_and_support_are_distinct_from_correctness(source, tmp_path):
    path = tmp_path / "trial.sqlite"
    with store.use_store(path), calls.measurement("jev-arms", {"jev": Decimal("0.1")}):
        selected = select_jev(source, {"code": "order identifier"}, entity="order", run_id="trial",
                              isolated_store=path, adapter=FakeJev())
        assert selected.facts[0].proposal.value == "0007"
        initial = ground(source, proposed(), provider="offline", model="fixture", execution="synthetic_test")
        verified = verify_jev(source, initial, run_id="trial", isolated_store=path, adapter=FakeJev())
    assert verified.facts[0].semantic_support == 0.8
    assert verified.correctness == "not_established"
    assert verified.review_status == "not_reviewed"
