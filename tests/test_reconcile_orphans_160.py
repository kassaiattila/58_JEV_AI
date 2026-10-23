"""160 (review M-1): a pairing or a "needs no invoice" mark that lost its invoice or its line is shown with the reason,
blocks the approval and can be revoked.

A pairing counts only while its invoice takes part in the pairing and its line is on its statement. When the invoice
left the pairing (its amount corrected to zero, its issue date removed, a second copy of it arrived) or the line got a
new identity (a correction or a new reading changed its content), the engine skipped the pairing without a word: the
line was proposed again, could be paired twice, and the package could be approved. A mark on such a line vanished the
same way. They are now listed beside the pairings that no longer fit the amounts (153), with the reason. Synthetic
data, no paid calls.
"""

from __future__ import annotations

import pytest

from jav import work
from jav.core import store
from jav.domains.finance import reconcile, reconcile_package as rp, reconcile_statement as rs
from tests import test_reconcile_k2_129 as k2

OWN_KEY = reconcile.account_key(k2.OWN)


def _save_statement(*lines) -> str:
    return k2._save("stmt", {**k2._statement(*lines), "account_no": k2.OWN}, doc_type="statement_cib", validation=k2.VERIFIED)


@pytest.fixture
def package(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        rp.clear_cache()
        inv = k2._save("inv", k2._invoice())
        stmt = _save_statement(k2._line(), k2._line(memo="Bank fee", amount="5.00", counterparty_account=None,
                                                     counterparty_name="Own Bank"))
        lid, fee = [ln["id"] for ln in reconcile.with_line_ids(stmt, [k2._line(), k2._line(
            memo="Bank fee", amount="5.00", counterparty_account=None, counterparty_name="Own Bank")])]
        wp_id = rp.create(name="April", accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30",
                          actor="reviewer")["workpackage_id"]
        yield {"wp": wp_id, "invoice": inv, "line": lid, "fee": fee}
        rp.clear_cache()


def _pair(package) -> dict:
    [row] = rp.allocate(package["wp"], [{"invoice_doc_id": package["invoice"], "line_id": package["line"]}], note=None,
                        actor="reviewer")
    return row


def _codes(ws) -> set[str]:
    return {b["code"] for b in ws["blockers"]}


def _correct_the_lines():
    """The statement read again with the payment's memo changed: the payment line gets a new identity, and so does the
    fee line (another counterparty name)."""
    _save_statement(k2._line(memo="INV-0001 April"), k2._line(memo="Bank fee", amount="5.00", counterparty_account=None,
                                                              counterparty_name="Own Bank Zrt."))


@pytest.mark.parametrize(("change", "why"), [({"gross_total": "0.00"}, "non_positive_amount"),
                                             ({"issue_date": None}, "missing_issue_date")])
def test_a_pairing_whose_invoice_left_the_pairing_is_shown_with_the_reason_and_blocks(package, change, why):
    row = _pair(package)
    k2._save("inv", k2._invoice(**change))
    ws = rp.workspace(package["wp"])
    [unfit] = ws["unfit"]
    assert unfit["kind"] == "allocation" and unfit["ref"] == str(row["id"])
    assert unfit["reason"] == "invoice_left_out" and unfit["invoice_reason"] == why
    assert "allocation_invoice_left_out" in _codes(ws)


def test_a_pairing_whose_invoice_arrived_a_second_time_is_shown_and_blocks(package):
    _pair(package)
    k2._save("inv-copy", k2._invoice())  # the same invoice from another file, no duplicate decision yet
    ws = rp.workspace(package["wp"])
    [unfit] = ws["unfit"]
    assert unfit["reason"] == "invoice_left_out" and unfit["invoice_reason"] == "duplicate_undecided"


def test_a_pairing_whose_line_changed_is_shown_and_blocks(package):
    row = _pair(package)
    _correct_the_lines()
    ws = rp.workspace(package["wp"])
    [unfit] = ws["unfit"]
    assert unfit["kind"] == "allocation" and unfit["ref"] == str(row["id"]) and unfit["reason"] == "line_gone"
    assert "decision_line_gone" in _codes(ws)
    with pytest.raises(work.NotReady):
        rs.approve(package["wp"], fingerprint=rs.current(package["wp"])["fingerprint"], actor="reviewer")


def test_a_mark_whose_line_changed_is_shown_and_blocks(package):
    [mark] = rp.mark(package["wp"], [package["fee"]], category="fee", note=None, actor="reviewer")
    _correct_the_lines()
    ws = rp.workspace(package["wp"])
    [unfit] = ws["unfit"]
    assert unfit["kind"] == "mark" and unfit["ref"] == str(mark["id"]) and unfit["reason"] == "line_gone"
    assert unfit["category"] == "fee"
    assert "decision_line_gone" in _codes(ws)


def test_revoking_them_clears_the_list_and_the_blockers(package):
    row = _pair(package)
    [mark] = rp.mark(package["wp"], [package["fee"]], category="fee", note=None, actor="reviewer")
    _correct_the_lines()
    rp.revoke(package["wp"], kind="allocation", ref=str(row["id"]), note="the line was read again", actor="reviewer")
    rp.revoke(package["wp"], kind="mark", ref=str(mark["id"]), note="the line was read again", actor="reviewer")
    ws = rp.workspace(package["wp"])
    assert ws["unfit"] == [] and not {"decision_line_gone", "allocation_invoice_left_out"} & _codes(ws)


def test_a_pairing_that_still_counts_is_not_listed(package):
    _pair(package)
    rp.mark(package["wp"], [package["fee"]], category="fee", note=None, actor="reviewer")
    ws = rp.workspace(package["wp"])
    assert ws["unfit"] == [] and not {"decision_line_gone", "allocation_invoice_left_out"} & _codes(ws)


def test_the_engine_returns_the_lost_pairing_with_its_reason():
    case = next(c for c in reconcile.golden_cases() if c["id"] == "split_payment_rest_proposed")
    snapshot = {**case["snapshot"], "allocations": [{"id": 7, "invoice_id": "i1", "line_id": "gone", "line_amount": "40.00",
                                                      "invoice_amount": "40.00"}],
                "marks": [{"id": 8, "line_id": "gone-too", "category": "fee"}]}
    result = reconcile.propose(snapshot)
    assert [(u["id"], u["reason"]) for u in result["unfit"]] == [(7, "line_gone")]
    assert [(m["id"], m["reason"]) for m in result["unfit_marks"]] == [(8, "line_gone")]
