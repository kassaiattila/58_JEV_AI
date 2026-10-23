"""153 (review B5): the readers that only read the reconciliation workspace use the kept one, without a copy.

The deep copy of the kept workspace was 85-93 % of the warm package list, quick review and sure-pairs time. The next
step, the quick review, the sure pairs and the service's JSON answers now read the kept workspace; this test makes sure
none of them changes it. Synthetic data, no AI call.
"""

import json

from jav.domains.finance import reconcile_package as rp, reconcile_review
from tests.test_list_speed_140 import _workspace_package, db, fresh_caches  # noqa: F401 - the shared fixtures


def test_the_readers_leave_the_kept_workspace_as_it_was(db):  # noqa: F811
    wp, _statement, _invoice = _workspace_package()
    kept = rp.kept_workspace(wp)
    before = json.dumps(kept, sort_keys=True, default=str)
    rp.package_view(wp)
    rp.proposed_pairs(wp)
    reconcile_review.review(wp)
    assert rp.kept_workspace(wp) is kept and json.dumps(kept, sort_keys=True, default=str) == before


def test_a_caller_that_changes_gets_its_own_copy(db):  # noqa: F811
    wp, _statement, _invoice = _workspace_package()
    mine = rp.workspace(wp)
    mine["lines"].clear()
    assert rp.kept_workspace(wp)["lines"]
