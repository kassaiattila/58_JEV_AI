"""265 (code review DOM-02): an approved statement's quick review shows its lines, not an error.

The quick review read its sure pairs through `proposed_pairs`, a decision path that refuses an approved package, so
the default tab of an approved statement showed a 422 error. It now reads them from the kept workspace itself.
Synthetic data only; no AI call.
"""

from __future__ import annotations

from jav.domains.finance import reconcile_package as rp, reconcile_review
from tests.test_list_speed_140 import _workspace_package, db, fresh_caches  # noqa: F401 - the shared fixtures


def test_the_quick_review_of_an_approved_package_reads(db, monkeypatch):  # noqa: F811
    wp, _statement, _invoice = _workspace_package()
    monkeypatch.setattr(rp, "active_versions", lambda *a, **k: {wp: {"version": 1, "line_ids": []}})
    view = reconcile_review.review(wp)
    assert "groups" in view
