"""153 (review B3): a run's records keep each item's source locations until its machine result or its correction changes.

During a large run every finished item rebuilt every document's source locations (the word layer and its grounding
index: about 0.9 s of a 468-document run's 1.1 s on a copy of the store, 3 s apart while the run's page polls). The
records now read the to-dos once for the run and keep each item's locations by the version of its result and its
correction. Synthetic data, no paid calls.
"""

from jav.app import corrections, export
from jav.core import store


def test_an_items_locations_are_built_again_only_when_its_result_or_correction_changes(monkeypatch, tmp_path):
    built: list[str] = []
    monkeypatch.setattr(corrections, "layer_for", lambda dp: None)
    monkeypatch.setattr(corrections, "effective_provenance", lambda dp, corr, layer: built.append(corr["revision"]) or {"f": {"page": 1}})
    dp = {"run_id": "run-1:abc", "created_at": "2026-10-13T08:00:00+00:00"}
    with store.use_store(tmp_path / "a.sqlite"):
        first = export._item_provenance("run-1", "abc", dp, {"revision": 0, "created_at": None})
        again = export._item_provenance("run-1", "abc", dp, {"revision": 0, "created_at": None})
        corrected = export._item_provenance("run-1", "abc", dp, {"revision": 1, "created_at": "2026-10-13T09:00:00+00:00"})
        rerun = export._item_provenance("run-1", "abc", {**dp, "created_at": "2026-10-13T10:00:00+00:00"},
                                        {"revision": 1, "created_at": "2026-10-13T09:00:00+00:00"})
    with store.use_store(tmp_path / "b.sqlite"):  # another store keeps its own
        export._item_provenance("run-1", "abc", dp, {"revision": 0, "created_at": None})
    assert first == again == corrected == rerun == {"f": {"page": 1}}
    assert built == [0, 1, 1, 0]
