"""265 (code review AI-01): a source read in several parts is asked only when the budget covers every part.

The interpretation splits a long source into parts, each reserving its own maximum, while the native item's budget
priced one request: the second part was refused after the first was paid for, and the paid part was thrown away. Now
the whole is checked before the first part (parts answered before count nothing when the run reuses answers), and a
budget too small for it spends nothing. Synthetic text and a stand-in model; no paid call.
"""
from decimal import Decimal

import pytest

from jav.core import calls, store
from jav.documents.readers import providers
from jav.documents.readers.pipeline import read_files
from tests.native_fixtures_109 import synthetic_gpt


@pytest.fixture
def isolated(tmp_path):
    with store.use_store(tmp_path / "native.sqlite"):
        yield tmp_path


def _reading(isolated):
    path = isolated / "source.txt"
    path.write_text("Order code: 0012", encoding="utf-8")
    return read_files([path])


def test_a_budget_for_one_part_spends_nothing_on_a_source_of_several(isolated, monkeypatch):
    reading = _reading(isolated)
    requests = synthetic_gpt(monkeypatch)
    real = providers.source_chunks
    monkeypatch.setattr(providers, "source_chunks", lambda view, fits: real(view, fits) * 40)  # a long source's parts
    calls.set_budget("native-small", "openai", Decimal("0.05"))  # one part, not forty
    with calls.use_run(budget_scope="native-small"), pytest.raises(calls.BudgetExceeded, match="nothing was asked"):
        providers.extract_gpt(reading, run_id="small", isolated_store=store.active_path())
    assert requests == [] and calls.budget_usage("native-small")["committed_usd"] == Decimal(0)


def test_a_budget_for_every_part_asks_them_all(isolated, monkeypatch):
    reading = _reading(isolated)
    requests = synthetic_gpt(monkeypatch)
    real = providers.source_chunks
    monkeypatch.setattr(providers, "source_chunks", lambda view, fits: real(view, fits) * 2)
    calls.set_budget("native-room", "openai", Decimal("5"))
    with calls.use_run(budget_scope="native-room"):
        providers.extract_gpt(reading, run_id="room", isolated_store=store.active_path())
    assert len(requests) >= 1  # (the two identical parts share one question)
