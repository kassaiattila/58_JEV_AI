"""A reader change alone no longer makes the same document a new paid question (124, Q-native-reuse).

The text sent to the model carries only what the model reads: the source elements and
the reading gaps. The fingerprint of the frozen source bundle, which includes the reader
code and package versions, stays in the stored interpretation, where it binds the answer
to the reading it was grounded on.
"""
from decimal import Decimal

import pytest

from jav import store
from jav.readers import pipeline, providers
from jav.readers.pipeline import read_files
from jav.runtime import calls
from native_fixtures_109 import synthetic_gpt


@pytest.fixture
def isolated(tmp_path):
    with store.use_store(tmp_path / "native.sqlite"):
        yield tmp_path


def test_a_new_reader_version_reuses_the_answer_for_unchanged_text(isolated, monkeypatch):
    path = isolated / "source.txt"
    path.write_text("Order code: 0012", encoding="utf-8")
    first_reading = read_files([path])
    monkeypatch.setattr(pipeline, "implementation_version", lambda: "native-1:" + "f" * 64)
    second_reading = read_files([path])
    assert first_reading.bundle.digest() != second_reading.bundle.digest()
    requests = synthetic_gpt(monkeypatch)
    calls.set_budget("native-rerun", "openai", Decimal("1"))
    with calls.use_run(budget_scope="native-rerun", reuse=True):
        first = providers.extract_gpt(first_reading, run_id="first", isolated_store=store.active_path())
        rerun = providers.extract_gpt(second_reading, run_id="rerun", isolated_store=store.active_path())
    assert len(requests) == 1
    assert rerun.request_sha256 == first.request_sha256
    # The reused answer is grounded on, and bound to, the new reading.
    assert rerun.source_bundle_sha256 == second_reading.bundle.digest()
    assert [fact.grounding for fact in rerun.facts] == ["literal_match"]
