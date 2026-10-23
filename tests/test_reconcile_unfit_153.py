"""153 (review A3): a pairing that no longer fits its line or invoice is shown, blocks the approval and can be revoked.

An allocation is checked against the amounts when it is made. When an amount changes later (a correction on the review
page, a document read again), the engine ignores an allocation that would exceed it; before, it vanished from every view
while it stayed recorded (and came back if the amount did), and nothing blocked the approval. It is now listed in the
package's workspace (`unfit`), blocks the approval and can be revoked. A decision also fails when a scope changed
between its read and its write. Synthetic data, no paid calls.
"""

from __future__ import annotations

import pytest

from jav.app import work
from jav.core import store
from jav.domains.finance import reconcile, reconcile_package as rp
from tests import test_reconcile_k2_129 as k2

OWN_KEY = reconcile.account_key(k2.OWN)


@pytest.fixture
def package(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        rp.clear_cache()
        inv = k2._save("inv", k2._invoice())  # 100.00
        values = {**k2._statement(k2._line()), "account_no": k2.OWN}
        stmt = k2._save("stmt", values, doc_type="statement_cib", validation=k2.VERIFIED)
        [lid] = [ln["id"] for ln in reconcile.with_line_ids(stmt, [k2._line()])]
        wp_id = rp.create(name="April", accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30",
                          actor="reviewer")["workpackage_id"]
        yield {"wp": wp_id, "invoice": inv, "line": lid}
        rp.clear_cache()


def test_a_pairing_whose_invoice_amount_dropped_is_shown_and_blocks(package):
    [row] = rp.allocate(package["wp"], [{"invoice_doc_id": package["invoice"], "line_id": package["line"]}], note=None,
                        actor="reviewer")
    k2._save("inv", k2._invoice(amount="60.00"))  # a correction or a new reading lowers the invoice's amount
    ws = rp.workspace(package["wp"])
    [unfit] = ws["unfit"]
    assert unfit["ref"] == str(row["id"]) and unfit["invoice_id"] == package["invoice"]
    assert unfit["invoice_amount"] == "100.00" and unfit["invoice_total"] == "60.00"
    assert "allocation_no_longer_fits" in {b["code"] for b in ws["blockers"]}


def test_revoking_it_clears_the_list_and_the_blocker(package):
    [row] = rp.allocate(package["wp"], [{"invoice_doc_id": package["invoice"], "line_id": package["line"]}], note=None,
                        actor="reviewer")
    k2._save("inv", k2._invoice(amount="60.00"))
    rp.revoke(package["wp"], kind="allocation", ref=str(row["id"]), note="the invoice was corrected", actor="reviewer")
    ws = rp.workspace(package["wp"])
    assert ws["unfit"] == [] and "allocation_no_longer_fits" not in {b["code"] for b in ws["blockers"]}


def test_a_pairing_that_still_fits_is_not_listed(package):
    rp.allocate(package["wp"], [{"invoice_doc_id": package["invoice"], "line_id": package["line"]}], note=None,
                actor="reviewer")
    assert rp.workspace(package["wp"])["unfit"] == []


def test_a_scope_changed_between_the_read_and_the_write_is_a_conflict(package, monkeypatch):
    real_write = rp._write

    def scope_changed_meanwhile(state, fn, **kwargs):
        with store.connect() as c:
            c.execute("UPDATE workpackage_scopes SET revision = revision + 1 WHERE workpackage_id=?", (package["wp"],))
        return real_write(state, fn, **kwargs)

    monkeypatch.setattr(rp, "_write", scope_changed_meanwhile)
    with pytest.raises(work.RevisionConflict):
        rp.allocate(package["wp"], [{"invoice_doc_id": package["invoice"], "line_id": package["line"]}], note=None,
                    actor="reviewer")
