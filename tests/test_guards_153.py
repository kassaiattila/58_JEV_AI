"""153 (review F3): rules that carry a decision, tested where they had no test.

The review found guards with no test: the approval's refusal of a run with an unfinished input item, the
reconciliation's money guards (an amount over what a side has left, a marked line, a side without a positive amount,
a split without a reason), and the reconciliation's pairing and rejection over the service. Synthetic data, no AI call.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jav import api, reconcile, reconcile_package as rp, store, work
from tests import test_reconcile_k2_129 as k2
from tests.test_supersede_runs_151 import runs  # noqa: F401 - the shared fixture: one package, an older and a newer live run

OWN_KEY = reconcile.account_key(k2.OWN)
HUMAN = {"X-Actor": "Teszt Elek"}


# --- the approval -------------------------------------------------------------------------------------------------------


def test_a_run_with_an_unfinished_input_item_is_not_approved(runs, monkeypatch):  # noqa: F811
    with store.use_store(runs["db"]):
        with store.connect() as c:
            c.execute("UPDATE review_reasons SET status='resolved'")
            c.execute("UPDATE run_items SET status='failed' WHERE run_id=? AND item_id=?", (runs["newer"], runs["items"][0]))
        monkeypatch.setattr(work, "refresh_run_status", lambda run_id: "done")  # as if its status said otherwise
        with pytest.raises(work.NotReady):
            work.approve_run(runs["newer"], actor="teszt.elek")
        assert work.get_run(runs["newer"])["approval"] is None


# --- the reconciliation's money guards -------------------------------------------------------------------------------------


@pytest.fixture
def package(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        rp.clear_cache()
        invoice = k2._save("inv", k2._invoice())  # 100.00
        statement = k2._save("stmt", {**k2._statement(k2._line()), "account_no": k2.OWN}, doc_type="statement_cib",
                             validation=k2.VERIFIED)
        [line] = [ln["id"] for ln in reconcile.with_line_ids(statement, [k2._line()])]
        wp = rp.create(name="April", accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30",
                       actor="reviewer")["workpackage_id"]
        yield {"wp": wp, "invoice": invoice, "line": line, "db": tmp_path / "r.sqlite"}
        rp.clear_cache()


def test_an_amount_over_what_a_side_has_left_is_refused(package):
    pair = {"invoice_doc_id": package["invoice"], "line_id": package["line"], "line_amount": "150.00", "invoice_amount": "150.00"}
    with pytest.raises(rp.PackageError, match="over what the line or the invoice has left"):
        rp.allocate(package["wp"], [pair], note="too much", actor="reviewer")


def test_a_split_needs_a_reason(package):
    pair = {"invoice_doc_id": package["invoice"], "line_id": package["line"], "line_amount": "40.00", "invoice_amount": "40.00"}
    with pytest.raises(rp.PackageError, match="needs a reason"):
        rp.allocate(package["wp"], [pair], note=None, actor="reviewer")
    assert rp.allocate(package["wp"], [pair], note="first instalment", actor="reviewer")[0]["line_amount"] == "40.00"


def test_a_marked_line_is_not_paired(package):
    rp.mark(package["wp"], [package["line"]], category="private", note=None, actor="reviewer")
    with pytest.raises(rp.PackageError, match="marked as needing no invoice"):
        rp.allocate(package["wp"], [{"invoice_doc_id": package["invoice"], "line_id": package["line"]}], note=None,
                    actor="reviewer")


def test_an_invoice_without_a_positive_amount_is_not_paired(package):
    zero = k2._save("inv0", k2._invoice(number="INV-0000", amount="0.00"))
    with pytest.raises((rp.PackageError, KeyError)):  # left out of the pairing, or refused as it has no positive amount
        rp.allocate(package["wp"], [{"invoice_doc_id": zero, "line_id": package["line"]}], note=None, actor="reviewer")


# --- the same over the service ----------------------------------------------------------------------------------------------


def test_pairing_and_rejecting_over_the_service(package):
    client = TestClient(api.create_app(store_path=package["db"]), base_url="http://127.0.0.1:8930")
    url = f"/api/workpackages/{package['wp']}/reconcile"
    refused = client.post(f"{url}/reject", headers=HUMAN, json={"invoice_doc_id": package["invoice"], "line_id": package["line"],
                                                                  "note": ""})
    assert refused.status_code == 422  # a rejection needs a reason
    r = client.post(f"{url}/allocate", headers=HUMAN, json={"pairs": [{"invoice_doc_id": package["invoice"], "line_id": package["line"]}]})
    assert r.status_code == 200, r.text
    line = next(ln for ln in r.json()["lines"] if ln["id"] == package["line"])
    assert line["state"] == "allocated"
    again = client.post(f"{url}/reject", headers=HUMAN, json={"invoice_doc_id": package["invoice"], "line_id": package["line"],
                                                                "note": "not this one"})
    assert again.status_code == 422 and "revoke the allocation first" in again.json()["message"]
