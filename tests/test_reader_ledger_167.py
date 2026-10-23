"""167 (review R-8): the native reader's GPT calls go into the ledger, as every other AI call does, failures too.

They were written only to the call log (invocations), so the ledger-based cost and error views missed them.
"""
import os
from decimal import Decimal
from types import SimpleNamespace

import pytest

from jav.core import store
from jav.core.config import OPENAI_MODEL
from jav.readers.interpretation import ProposedExtraction
from jav.readers.pipeline import read_files
from jav.readers.providers import extract_gpt
from jav.readers.receipts import InterpretationRejected
from jav.core import calls

pytest.importorskip("docx", reason="Native reader dependencies await integration")
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Job Object reader boundary")


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.txt"
    path.write_text("Order code: 0007\nQuantity: 3", encoding="utf-8")
    return read_files([path])


class FakeAgent:
    def __init__(self, error: Exception | None = None):
        self.calls, self.error = 0, error

    def run_sync(self, prompt, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        proposal = ProposedExtraction.model_validate_json('''{"facts":[{"entity":"order","property":"code",
          "value":"0007","state":"stated","citations":[{"occurrence_id":"o0","element_id":"e0","quote":"Order code: 0007"}]}]}''')
        return SimpleNamespace(output=proposal, usage=SimpleNamespace(input_tokens=100, output_tokens=40),
                               response=SimpleNamespace(model_name=OPENAI_MODEL))


def _ledger() -> list[dict]:
    with store.connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM ledger ORDER BY id")]


def test_a_live_reader_call_is_written_to_the_ledger_once(source, tmp_path):
    path = tmp_path / "trial.sqlite"
    agent = FakeAgent()
    with store.use_store(path), calls.measurement("native-ledger", {"openai": Decimal("1")}):
        extract_gpt(source, run_id="trial", isolated_store=path, agent=agent)
        extract_gpt(source, run_id="trial", isolated_store=path, agent=agent)  # replayed from the receipt: no call
        rows = _ledger()
        invocation = calls.journal("trial")[0]
    assert agent.calls == 1
    assert len(rows) == 1
    row = rows[0]
    assert (row["run_id"], row["step"], row["provider"], row["model"]) == ("trial", "reader_gpt", "openai", OPENAI_MODEL)
    assert (row["input_tokens"], row["output_tokens"], row["cached"], row["error"]) == (100, 40, 0, None)
    assert Decimal(str(row["cost_usd"])) == Decimal(invocation["cost_usd"])
    assert row["config_hash"] and row["cache_key"] and row["seconds"] is not None


def test_a_failed_reader_call_is_written_to_the_ledger_with_its_error(source, tmp_path):
    path = tmp_path / "trial.sqlite"
    with store.use_store(path), calls.measurement("native-ledger", {"openai": Decimal("1")}):
        with pytest.raises(ConnectionRefusedError):
            extract_gpt(source, run_id="trial", isolated_store=path, agent=FakeAgent(ConnectionRefusedError("refused")))
        rows = _ledger()
    assert [(r["step"], r["provider"], r["cost_usd"], r["error"]) for r in rows] == [
        ("reader_gpt", "openai", None, "ConnectionRefusedError")]


def test_an_answer_that_fails_validation_is_in_the_ledger_with_its_cost_and_the_failure(source, tmp_path):
    from pydantic_ai import Agent, NativeOutput
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.usage import RequestUsage

    def respond(messages, info):
        return ModelResponse([TextPart('{"facts":[{"entity":"order"}]}')], usage=RequestUsage(input_tokens=100, output_tokens=40))

    agent = Agent(FunctionModel(respond, model_name=OPENAI_MODEL), output_type=NativeOutput(ProposedExtraction), retries=0)
    path = tmp_path / "trial.sqlite"
    with store.use_store(path), calls.measurement("native-invalid", {"openai": Decimal("1")}):
        with pytest.raises(InterpretationRejected):
            extract_gpt(source, run_id="trial", isolated_store=path, agent=agent)
        rows = _ledger()
    assert len(rows) == 1
    assert (rows[0]["input_tokens"], rows[0]["output_tokens"]) == (100, 40)
    assert rows[0]["cost_usd"] is not None and rows[0]["error"] == "UnexpectedModelBehavior"
