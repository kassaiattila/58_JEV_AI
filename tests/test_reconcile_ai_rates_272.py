"""272 (K4, the rest of DOM-08): the AI pairing proposal takes the exchange rates from the kept signal inputs.

265 (DOM-08) made the AI pairing proposal read the kept workspace instead of a deep copy, but it still built the
package's whole snapshot again (every invoice, statement and decision of the store) only for its exchange rates. The
reconciliation already keeps the store-wide inputs of its comparison, the rates among them, until any of its inputs
changes (`reconcile_package.signal_rates`, marked by the rates' last fetch too); the proposal reads them there, and
gets the same rates. Synthetic data; no AI call.
"""

from __future__ import annotations

from jav.domains.finance import reconcile_ai, reconcile_package as rp
from tests import test_reconcile_package_131 as p131
from tests.test_list_speed_140 import db, fresh_caches  # noqa: F401 - the shared fixtures


def test_the_ai_proposal_takes_the_kept_rates_not_a_second_snapshot(db, monkeypatch):  # noqa: F811
    p131._stmt("april", p131._line())
    wp = p131._package()
    expected = rp.scoped_snapshot(wp)[0].get("fx_rates") or {}
    rp.kept_workspace(wp)  # the workspace is built (and kept) once, from its own snapshot
    monkeypatch.setattr(rp, "scoped_snapshot", lambda *a, **k: (_ for _ in ()).throw(AssertionError("a second snapshot")))
    _lines, _items, rates = reconcile_ai._lines(wp)
    assert rates == expected == rp.signal_rates()
