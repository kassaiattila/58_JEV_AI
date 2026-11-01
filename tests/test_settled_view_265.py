"""265 (code review DOM-05): a pairing decision reads the settled view, the same as the whole proposal gives it.

Every decision of a reconciliation package ran the whole proposal (its candidate search) only to read the confirmed
allocations, the allocations and marks that no longer fit, and the amounts allocated so far; on 1 000 lines and 500
invoices that took seconds per click. `reconcile.settled_view` gives just these, without the search. On every golden
case they are exactly what the proposal gives. Invented golden data; no AI.
"""

from __future__ import annotations

import pytest

from jav.domains.finance import reconcile

CASES = reconcile.golden_cases()


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_the_settled_view_is_the_proposals(case) -> None:
    full = reconcile.propose(case["snapshot"])
    view = reconcile.settled_view(case["snapshot"])
    assert view == {k: full[k] for k in ("confirmed", "unfit", "unfit_marks", "paid")}
