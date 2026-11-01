"""265 (code review DOM-07): a line's statement for its page comes from the valid statements, not the whole snapshot.

Every page image of a reconciliation line built the store's whole snapshot (the invoices, the decisions, the exchange
rates) only to find the line's statement. The valid statements alone (`reconcile_store.live_statements`) are exactly
the snapshot's, a replaced one left out the same way. Invented data; no AI.
"""

from __future__ import annotations

from jav.domains.finance import reconcile_store
from tests.test_own_approval_224 import db  # noqa: F401 (the fixture)
from tests.test_reconcile_statement_145 import _world


def test_the_valid_statements_are_the_snapshots(db) -> None:  # noqa: F811
    _world()
    live = reconcile_store.live_statements()
    assert live and live == reconcile_store.snapshot()["statements"]
