"""265 (code review DOM-12): the finance domain's small shared helpers.

- One table check (`store.has_table`) instead of a copy in three modules.
- One reader of documents' file names (`store.file_names`), asking in chunks; the duplicate check had its own copy that
  put every id into one query (over SQLite's parameter limit for a large set).
- Revoking an allocation or a mark by a malformed id is "not found" (`KeyError`), not an unnamed `ValueError`.

Synthetic documents and made-up accounts only; no AI call.
"""

from __future__ import annotations

import pytest

from jav.core import store
from jav.domains.finance import reconcile_package as rp
from tests.test_reconcile_review_147 import _setup


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "f.sqlite"):
        rp.clear_cache()
        yield
        rp.clear_cache()


def test_the_table_check_and_the_file_names_are_shared(db) -> None:
    with store.connect() as c:
        assert store.has_table(c, "documents") and not store.has_table(c, "no_such_table")
        c.executemany("INSERT INTO documents (doc_id, source_path, first_seen) VALUES (?, ?, '2026-11-01')",
                      [(f"d{n:04d}", f"C:/inbox/file {n}.pdf") for n in range(1200)])
    names = store.file_names([f"d{n:04d}" for n in range(1200)] + ["unknown"])
    assert len(names) == 1200 and names["d0999"] == "file 999.pdf" and "unknown" not in names


def test_revoking_by_a_malformed_id_is_not_found(db) -> None:
    wp_id, _ids, _inv = _setup()
    for kind in ("allocation", "mark"):
        with pytest.raises(KeyError):
            rp.revoke(wp_id, kind=kind, ref="12a", actor="anna")
        with pytest.raises(KeyError):
            rp.revoke(wp_id, kind=kind, ref="999999", actor="anna")
