"""265 (code review DOM-09): a document named by a prefix is found by a range on its key, not a substring.

A to-do names a document by the first characters of its id; the lookup compared a substring of every id, so it read
the whole table. A range on the key finds the same one (and none when two ids share the prefix). Invented ids; no AI.
"""

from __future__ import annotations

from jav.app import registrations
from jav.core import store
from jav.domains.finance import duplicates


def test_a_prefix_finds_its_one_document(tmp_path) -> None:
    registrations.load_all()
    with store.use_store(tmp_path / "p.sqlite"):
        for doc_id in ("abc123", "abc129", "abd000", "ab"):
            store.upsert_document(doc_id=doc_id, source_path=f"C:/invented/{doc_id}.pdf", page_count=1, has_text=True)
        assert duplicates.resolve_prefix("abc12") is None  # two share it
        assert duplicates.resolve_prefix("abc123") == "abc123"
        assert duplicates.resolve_prefix("abd") == "abd000"
        assert duplicates.resolve_prefix("abz") is None and duplicates.resolve_prefix("") is None
        with store.connect() as c:
            plan = " ".join(r[-1] for r in c.execute("EXPLAIN QUERY PLAN SELECT doc_id FROM documents WHERE doc_id >= ? AND"
                                                     " doc_id < ? LIMIT 2", ("abc", "abd")))
        assert "SEARCH" in plan
