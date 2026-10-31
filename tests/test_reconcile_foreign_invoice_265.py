"""265 (code review DOM-03): a scope of forint bank accounts shows the invoices of another currency too.

A forint bank statement may pay an invoice of another currency at the bank's rate (149), but the pairing page listed
another currency's invoices only beside a card statement: in a scope of forint bank accounts only, a euro invoice was
missing from the page and could not be paired even by hand. Synthetic data only; no AI call.
"""

from __future__ import annotations

from jav.domains.finance import reconcile_package as rp
from tests import test_reconcile_package_131 as p131
from tests.test_list_speed_140 import db, fresh_caches  # noqa: F401 - the shared fixtures
from tests.test_reconcile_k2_129 import _save


def test_a_euro_invoice_is_on_a_forint_bank_statement_s_page(db):  # noqa: F811
    p131._stmt("april", p131._line(amount="39000.00", memo="Transfer EUR invoice"))
    euro = _save("inv-eur", {"invoice_number": "EU-7", "supplier_name": "Example GmbH", "gross_total": "100.00",
                             "currency": "EUR", "issue_date": "2026-04-02"})
    ws = rp.workspace(p131._package())
    assert euro in {i["id"] for i in ws["invoices"]}
