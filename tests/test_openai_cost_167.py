"""167 (review AI-12): one OpenAI price rule for every caller.

The cost of an OpenAI answer was computed in six places with different behaviour for a model without its own price:
some charged the requested model's price, some recorded no cost at all. Now `jav.config.openai_cost` is the only rule:
the answering model's configured price, else the requested model's, else None (an unknown cost: the call log keeps
the reserved maximum committed). Money in Decimal. Stand-in answers only; no paid call.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic_ai.usage import RunUsage

from jav import config, store
from jav.config import OPENAI_MODEL, openai_cost, openai_priced_model

PRICE = config.OPENAI_USD_PER_MTOK[OPENAI_MODEL]


def _usage(i: int = 100, o: int = 40) -> SimpleNamespace:
    return SimpleNamespace(input_tokens=i, output_tokens=o)


def _expected(i: int = 100, o: int = 40, price: tuple[float, float] = PRICE) -> Decimal:
    exact = (Decimal(i) * Decimal(str(price[0])) + Decimal(o) * Decimal(str(price[1]))) / Decimal(1_000_000)
    return exact.quantize(Decimal("0.000001"))


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "c.sqlite"):
        yield tmp_path


def test_the_configured_model_is_charged_at_its_price_in_decimal():
    cost = openai_cost(_usage(), requested=OPENAI_MODEL, actual=OPENAI_MODEL)
    assert isinstance(cost, Decimal) and cost == _expected()


def test_a_dated_snapshot_and_an_unknown_name_are_charged_at_the_requested_price():
    assert openai_cost(_usage(), requested=OPENAI_MODEL, actual=f"{OPENAI_MODEL}-2026-03-17") == _expected()
    assert openai_cost(_usage(), requested=OPENAI_MODEL, actual="synthetic-unlisted-model") == _expected()
    assert openai_cost(_usage(), requested=OPENAI_MODEL, actual=None) == _expected()
    assert openai_priced_model(requested=OPENAI_MODEL, actual="synthetic-unlisted-model") == OPENAI_MODEL


def test_an_answering_model_with_its_own_price_is_charged_at_that_price(monkeypatch):
    monkeypatch.setitem(config.OPENAI_USD_PER_MTOK, "synthetic-priced-model", (2.0, 8.0))
    assert openai_cost(_usage(), requested=OPENAI_MODEL, actual="synthetic-priced-model") == _expected(price=(2.0, 8.0))
    assert openai_priced_model(requested=OPENAI_MODEL, actual="synthetic-priced-model") == "synthetic-priced-model"


def test_no_price_or_no_reported_usage_is_an_unknown_cost():
    assert openai_cost(_usage(), requested="synthetic-unpriced", actual="synthetic-unpriced-2026-01-01") is None
    assert openai_priced_model(requested="synthetic-unpriced", actual=None) is None
    assert openai_cost(RunUsage(), requested=OPENAI_MODEL, actual=OPENAI_MODEL) is None
    assert openai_cost(None, requested=OPENAI_MODEL, actual=OPENAI_MODEL) is None


def test_no_runtime_module_computes_an_openai_price_by_itself():
    """The price table is read by the shared rule only (the admin report lists it; experiments are not runtime)."""
    root = Path(config.PROJECT_ROOT) / "jav"
    readers = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.py")
                     if "experiments" not in p.parts and re.search(r"\bOPENAI_USD_PER_MTOK\b", p.read_text(encoding="utf-8")))
    assert readers == ["admin.py", "config.py"]


class _Agent:
    """A GPT stand-in whose answer names `model_name` as the answering model."""

    def __init__(self, model_name: str, output=None):
        self.model_name = model_name
        self.output = output

    def run_sync(self, prompt, **_kw):
        return SimpleNamespace(output=self.output, usage=_usage(),
                               response=SimpleNamespace(model_name=self.model_name, provider_details={}),
                               all_messages_json=lambda: b"[]")


def test_the_extraction_charges_an_unlisted_answering_model_at_the_requested_price(isolated):
    from jav import extract_llm
    from jav.typepack import get as get_pack
    from tests.test_no_jev_085 import GOOD

    pack = get_pack("invoice_hu")
    agent = _Agent("synthetic-unlisted-model", pack.llm_model().model_validate(GOOD))
    out = extract_llm._physical(agent, "synthetic", run_id="r-x", pack=pack, limited=False)
    assert out.cost_usd == _expected()
    assert store.ledger_for_run("r-x")[0]["cost_usd"] == pytest.approx(float(_expected()))


def test_the_provider_generation_charges_by_the_same_rule(isolated):
    from jav.provider_generation import generate

    raw = generate(_Agent("synthetic-unlisted-model", {"x": 1}), "synthetic", run_id="r-g", step="gen",
                   model_name=OPENAI_MODEL, config_hash="h")
    assert raw["model"] == "synthetic-unlisted-model"
    assert store.ledger_for_run("r-g")[0]["cost_usd"] == pytest.approx(float(_expected()))
