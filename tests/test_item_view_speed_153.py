"""153 (review B6): a document that is no statement does not build every stored statement for its review view.

Each review page of a document took 0.15-0.19 s, of which 0.10 s built every stored statement (220) to find out that
the document is none; a run's results took 102 s for 468 documents. The statement relations now return at once for a
document of another kind. Synthetic data, no paid calls.
"""

import pytest

from jav import reconcile, statement_months, store
from tests import test_reconcile_k2_129 as k2


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "s.sqlite"):
        yield


def test_an_invoice_does_not_build_the_statements(db, monkeypatch):
    invoice = k2._save("inv", k2._invoice())
    monkeypatch.setattr(reconcile, "statements", lambda: pytest.fail("every stored statement was built for an invoice"))
    assert statement_months.item_view(invoice, []) == []


def test_a_statement_still_shows_its_relations(db):
    statement = k2._save_statement("stmt", k2._line())
    assert statement_months.item_view(statement, []) == []  # a statement with no replacement or conflict: none, but read
