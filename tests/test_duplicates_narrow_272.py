"""272 (K4, the rest of DOM-09): a decision and a document's pairs read only the documents they show.

265 (DOM-09) found a document named by a prefix through a range on its key. A person's duplicate decision and a
document's review page still read every invoice-like document of the store (its counted result, every package) to
compare two of them, and a run's marks looked up each document's file name one by one. The loader now takes the
documents asked for (`documents(doc_ids=...)`, the same counted results), the decision and the pairs ask for theirs,
and the marks read the file names at once. The duplicate check of a document being processed still compares it with
every other one, which it must. Invented documents; no AI.
"""

from __future__ import annotations

import pytest

from jav.core import store
from jav.domains.finance import duplicates
from tests import test_duplicates_126 as d126


@pytest.fixture()
def db(tmp_path):
    with store.use_store(tmp_path / "w.sqlite"):
        yield


def test_the_loader_reads_only_the_documents_asked_for(db) -> None:
    earlier, now = d126._pair_in_run()
    every = {d.doc_id: d for d in duplicates.documents()}
    assert duplicates.documents(doc_ids=[now]) == [every[now]]
    assert duplicates.documents(doc_ids=[]) == []


def test_a_decision_and_a_document_s_pairs_ask_only_for_their_documents(db, monkeypatch) -> None:
    earlier, now = d126._pair_in_run()
    asked: list[object] = []
    real = duplicates.documents
    monkeypatch.setattr(duplicates, "documents", lambda *a, **k: asked.append(k.get("doc_ids")) or real(*a, **k))
    [pair] = duplicates.item_pairs(now, store.review_open_reasons("document", now))
    duplicates.decide("run-1", now, earlier, decision="variant", actor="reviewer", expected_state=pair["decision_state"])
    assert asked and all(ids is not None and set(ids) <= {now, earlier} for ids in asked)


def test_the_marks_read_the_file_names_once(db, monkeypatch) -> None:
    earlier, now = d126._pair_in_run()
    reasons = {now: [r["reason"] for r in store.review_open_reasons("document", now)]}
    expected = duplicates.marks(reasons)
    calls: list[list[str]] = []
    real = store.file_names
    monkeypatch.setattr(store, "file_names", lambda ids: calls.append(list(ids)) or real(ids))
    assert duplicates.marks(reasons) == expected and expected[now]["status"] == "suspected"
    assert len(calls) == 1
