"""265 (code review DOM-11): an invoice the pairing excludes cannot be paired by hand either.

The pairing excludes an invoice with a reason (an undecided duplicate, a confirmed copy, no issue date, a currency it
does not handle), but a person's allocation took any invoice of the snapshot: an undecided duplicate could be paid
twice. Now the allocation refuses an excluded invoice and points to the list of excluded ones. Synthetic data only;
no AI call.
"""

from __future__ import annotations

import pytest

from jav.domains.finance import reconcile_package as rp
from tests import test_reconcile_package_131 as p131
from tests.test_list_speed_140 import db, fresh_caches  # noqa: F401 - the shared fixtures
from tests.test_reconcile_k2_129 import _save


def test_an_excluded_invoice_is_refused_with_why(db):  # noqa: F811
    p131._stmt("april", p131._line())
    undated = _save("inv", {"invoice_number": "INV-0001", "supplier_name": "Example Supplier", "gross_total": "100.00",
                            "currency": "HUF"})  # no issue date: excluded from the pairing
    wp = p131._package()
    ws = rp.workspace(wp)
    line = next(ln for ln in ws["lines"] if ln["memo"] == "INV-0001")
    with pytest.raises(rp.PackageError, match="excluded from the pairing"):
        rp.allocate(wp, [{"invoice_doc_id": undated, "line_id": line["id"]}], note=None, actor="reviewer")
