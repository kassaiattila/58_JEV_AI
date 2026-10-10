"""131 (backlog F-reconciliation E1): the reconciliation package - a scope of own accounts and a period over the
documents other packages processed, decisions per pair with an amount (split and combined payments), 'not this one',
'needs no invoice', revocation, and the blockers of the approval.

The owner's decisions of 2026-10-09 (DECISIONS 131). Synthetic documents and made-up accounts only; no AI call, no
network (the test setup refuses any MNB request).
"""

from __future__ import annotations

import pytest

from jav import reconcile, reconcile_package as rp, store, work, work_views
from tests import test_api
from tests import test_reconcile_k2_129 as k2

env = test_api.env
OWN_KEY = reconcile.account_key(k2.OWN)
OTHER = "22223334-44445555-66667777"  # a second own account, made up


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield


def _line(amount="100.00", day="2026-04-10", memo="INV-0001", **over):
    return k2._line(memo=memo, amount=amount, booking_date=day, **over)


def _stmt(name, *lines, run_id=None, verified=True, account=k2.OWN):
    values = {**k2._statement(*lines), "account_no": account}
    return k2._save(name, values, run_id=run_id, doc_type="statement_cib", validation=k2.VERIFIED if verified else [])


def _package(*, accounts=(OWN_KEY,), start="2026-04-01", end="2026-04-30", name="April"):
    return rp.create(name=name, accounts=list(accounts), period_start=start, period_end=end, actor="reviewer")["workpackage_id"]


def _ids(stmt, *lines):
    return [ln["id"] for ln in reconcile.with_line_ids(stmt, list(lines))]


def _line_row(ws, line_id):
    return next(ln for ln in ws["lines"] if ln["id"] == line_id)


def _invoice_row(ws, doc_id):
    return next(i for i in ws["invoices"] if i["id"] == doc_id)


# --- the scope ---------------------------------------------------------------------------------------------------------


def test_the_scope_is_chosen_from_the_stores_accounts_and_checked(db):
    _stmt("stmt", _line())
    [acct] = rp.accounts()
    assert (acct["key"], acct["statements"], acct["currencies"], acct["first"], acct["last"]) == (OWN_KEY, 1, ["HUF"], "2026-03-01", "2026-06-30")
    with pytest.raises(rp.PackageError):
        _package(accounts=["000000000000000000000000"])
    with pytest.raises(rp.PackageError):
        _package(start="2026-05-01", end="2026-04-01")
    wp_id = _package()
    view = work_views.workpackage_view(wp_id)
    assert view["workpackage"]["source_kind"] == "reconcile" and view["runs"] == 0
    assert view["reconcile"]["scope"]["accounts"] == [OWN_KEY]
    assert view["next"]["code"] == "reconcile_pair"


def test_the_scope_changes_with_its_revision(db):
    _stmt("stmt", _line())
    wp_id = _package()
    rp.set_scope(wp_id, accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-05-31", expected_revision=1, actor="t")
    with pytest.raises(work.RevisionConflict):
        rp.set_scope(wp_id, accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-06-30", expected_revision=1, actor="t")
    assert rp.scope(wp_id)["revision"] == 2 and work.get(wp_id)["source_ref"] == "2026-04-01..2026-05-31"


def test_a_processing_package_is_not_a_reconciliation_package(db):
    k2._run(k2.RUN, ["inv"])
    with pytest.raises(rp.PackageError):
        rp.workspace("wp-1")


# --- the workspace -----------------------------------------------------------------------------------------------------


def test_the_workspace_shows_the_periods_lines_the_invoices_and_the_blockers(db):
    inv = k2._save("inv", k2._invoice())
    stmt = _stmt("stmt", _line(), _line(amount="7.00", day="2026-05-20", memo="other"))
    k2._save("far", k2._invoice(number="FAR-1", issue_date="2025-01-01", due_date="2025-01-15"))
    ws = rp.workspace(_package())
    [line] = ws["lines"]  # the May line is outside the period
    assert (line["state"], line["rest"], line["file"], line["statement_verified"]) == ("proposed", "100.00", "stmt.pdf", True)
    assert line["candidates"][0]["invoice_id"] == inv and line["candidates"][0]["signals"] == ["invoice_number", "supplier_account", "supplier_name"]
    assert [i["id"] for i in ws["invoices"]] == [inv]  # an invoice whose window misses the period is not listed
    assert {(b["code"], b["kind"]) for b in ws["blockers"]} == {("source_no_run", "statement"), ("source_no_run", "invoice")}
    assert ws["coverage"] == [{"account": OWN_KEY, "month": "2026-04", "statements": 1, "verified": 1}]
    assert ws["counts"]["open_lines"] == 1 and ws["line_marks"][0] == "private"
    assert stmt


def test_an_approved_source_is_no_blocker_and_an_unverified_statement_is(db):
    k2._run(k2.RUN, ["inv", "stmt"], approved=True)
    k2._save("inv", k2._invoice(), run_id=k2.RUN)
    _stmt("stmt", _line(), run_id=k2.RUN, verified=False)
    ws = rp.workspace(_package())
    assert [b["code"] for b in ws["blockers"]] == ["statement_unverified"]


# --- allocations ---------------------------------------------------------------------------------------------------------


def test_an_exact_pair_is_allocated_without_a_reason_and_revoked(db):
    inv = k2._save("inv", k2._invoice())
    stmt = _stmt("stmt", _line())
    [lid] = _ids(stmt, _line())
    wp_id = _package()
    [row] = rp.allocate(wp_id, [{"invoice_doc_id": inv, "line_id": lid}], note=None, actor="reviewer")
    assert (row["line_amount"], row["invoice_amount"], row["workpackage_id"]) == ("100.00", "100.00", wp_id)
    ws = rp.workspace(wp_id)
    assert _line_row(ws, lid)["state"] == "allocated" and _invoice_row(ws, inv)["state"] == "confirmed"
    assert rp.next_step(ws)["code"] == "reconcile_result"
    rp.revoke(wp_id, kind="allocation", ref=str(row["id"]), actor="reviewer", note="wrong one")
    assert _line_row(rp.workspace(wp_id), lid)["state"] == "proposed"
    assert [e["action"] for e in work.workpackage_events(wp_id)] == ["reconcile_scope", "reconcile_allocate", "reconcile_revoke"]


def test_a_split_payment_needs_a_reason_and_its_rest_is_proposed(db):
    inv = k2._save("inv", k2._invoice())
    first, second = _line(amount="40.00"), _line(amount="60.00", day="2026-04-12")
    stmt = _stmt("stmt", first, second)
    l1, l2 = _ids(stmt, first, second)
    wp_id = _package()
    pair = {"invoice_doc_id": inv, "line_id": l1}
    with pytest.raises(rp.PackageError):
        rp.allocate(wp_id, [pair], note=None, actor="t")  # 40 of a 100 invoice: a split
    rp.allocate(wp_id, [pair], note="first instalment", actor="t")
    ws = rp.workspace(wp_id)
    assert (_invoice_row(ws, inv)["allocated"], _invoice_row(ws, inv)["rest"], _invoice_row(ws, inv)["state"]) == ("40.00", "60.00", "proposed")
    assert _line_row(ws, l2)["state"] == "proposed"
    assert rp.accept_proposed(wp_id, actor="t") == 1
    ws = rp.workspace(wp_id)
    assert _invoice_row(ws, inv)["state"] == "confirmed" and len(_invoice_row(ws, inv)["allocations"]) == 2


def test_one_line_pays_two_invoices_within_its_amount(db):
    a = k2._save("a", k2._invoice(number="INV-0001", amount="40.00"))
    b = k2._save("b", k2._invoice(number="INV-0002", amount="60.00"))
    stmt = _stmt("stmt", _line(memo="INV-0001 INV-0002"))
    [lid] = _ids(stmt, _line(memo="INV-0001 INV-0002"))
    wp_id = _package()
    with pytest.raises(rp.PackageError):  # 70 + 40 is over the line's 100
        rp.allocate(wp_id, [{"invoice_doc_id": a, "line_id": lid, "line_amount": "40.00"},
                            {"invoice_doc_id": b, "line_id": lid, "line_amount": "70.00"}], note="combined", actor="t")
    rp.allocate(wp_id, [{"invoice_doc_id": a, "line_id": lid}, {"invoice_doc_id": b, "line_id": lid}], note="combined", actor="t")
    ws = rp.workspace(wp_id)
    assert _line_row(ws, lid)["state"] == "allocated" and {i["id"]: i["state"] for i in ws["invoices"]} == {a: "confirmed", b: "confirmed"}
    with pytest.raises(rp.PackageError):
        rp.allocate(wp_id, [{"invoice_doc_id": a, "line_id": lid}], note=None, actor="t")  # nothing left


def test_in_one_currency_the_two_shares_are_one_amount(db):
    inv = k2._save("inv", k2._invoice())
    stmt = _stmt("stmt", _line())
    [lid] = _ids(stmt, _line())
    with pytest.raises(rp.PackageError):
        rp.allocate(_package(), [{"invoice_doc_id": inv, "line_id": lid, "line_amount": "50.00", "invoice_amount": "60.00"}],
                    note="x", actor="t")


def test_a_line_outside_the_scope_or_an_outgoing_invoice_is_refused(db):
    inv = k2._save("inv", k2._invoice())
    out = k2._save("out", k2._invoice(number="OUT-1"), doc_type="invoice_out")
    other = _stmt("other", _line(), account=OTHER)
    _stmt("stmt", _line())
    [lid] = _ids(other, _line())
    wp_id = _package()
    with pytest.raises(rp.PackageError):
        rp.allocate(wp_id, [{"invoice_doc_id": inv, "line_id": lid}], note=None, actor="t")
    with pytest.raises(rp.PackageError):
        rp.allocate(wp_id, [{"invoice_doc_id": out, "line_id": lid}], note=None, actor="t")


def test_an_allocation_from_another_account_still_pays_the_invoice(db):
    """The amounts allocated so far come from every statement, so an invoice paid from an account outside the scope
    is not shown as unpaid."""
    inv = k2._save("inv", k2._invoice())
    other = _stmt("other", _line(), account=OTHER)
    _stmt("stmt", _line(memo="unrelated", counterparty_name="Somebody", counterparty_account=None, amount="5.00"))
    [lid] = _ids(other, _line())
    wide = _package(accounts=[OWN_KEY, reconcile.account_key(OTHER)], name="both")
    rp.allocate(wide, [{"invoice_doc_id": inv, "line_id": lid}], note=None, actor="t")
    narrow = _package(name="own only")
    assert _invoice_row(rp.workspace(narrow), inv)["state"] == "confirmed"


def test_the_trial_confirmations_count_as_whole_allocations(db):
    inv, stmt, line = k2._pair_in_run()
    k2._decide(inv, stmt, line, run_id=k2.RUN)  # a decision of the retired review page panel (129-136)
    ws = rp.workspace(_package())
    [share] = _line_row(ws, line)["allocations"]
    assert (share["allocation_id"], share["line_amount"]) == (None, "100.00") and _line_row(ws, line)["state"] == "allocated"
    rp.revoke(ws["workpackage_id"], kind="decision", ref=reconcile.pair_key(inv, line), actor="t")
    assert _line_row(rp.workspace(ws["workpackage_id"]), line)["state"] == "proposed"


# --- a converted card pair ---------------------------------------------------------------------------------------------


def _card(amount="6700.00"):
    line = {"booking_date": "2026-04-03", "value_date": None, "direction": "debit", "amount": amount, "running_balance": None,
            "description": "EXAMPLE CLOUD", "counterparty_name": "EXAMPLE CLOUD", "counterparty_account": None, "memo": None}
    values = {"statement_type": "credit_card", "account_no": "4444555566667777", "account_iban": None, "period_start": "2026-03-01",
              "period_end": "2026-04-30", "currency": "HUF", "opening_balance": None, "closing_balance": None,
              "total_debit": None, "total_credit": None, "transactions": [line]}
    stmt = k2._save("card", values, doc_type="statement_cib", validation=k2.VERIFIED)
    return stmt, reconcile.with_line_ids(stmt, [line])[0]["id"]


def test_a_converted_pair_is_allocated_only_in_whole_and_without_a_rate_needs_a_reason(db):
    inv = k2._save("usd", {"invoice_number": "EC-1", "supplier_name": "Example Cloud Inc.", "gross_total": "20.00",
                           "currency": "USD", "issue_date": "2026-04-01"}, doc_type="invoice_foreign")
    _stmt_id, lid = _card()
    wp_id = _package(accounts=[reconcile.account_key("4444555566667777")])
    with pytest.raises(rp.PackageError):
        rp.allocate(wp_id, [{"invoice_doc_id": inv, "line_id": lid, "line_amount": "3000.00"}], note="part", actor="t")
    with pytest.raises(rp.PackageError):  # no stored rate: the pair is not checked, so a reason is needed
        rp.allocate(wp_id, [{"invoice_doc_id": inv, "line_id": lid}], note=None, actor="t")
    [row] = rp.allocate(wp_id, [{"invoice_doc_id": inv, "line_id": lid}], note="paid by card, see the receipt", actor="t")
    assert (row["line_amount"], row["invoice_amount"]) == ("6700.00", "20.00")


# --- rejection, marks, conflicts, deletion -------------------------------------------------------------------------------


def test_a_rejected_pair_is_not_offered_again_until_revoked(db):
    inv = k2._save("inv", k2._invoice())
    stmt = _stmt("stmt", _line())
    [lid] = _ids(stmt, _line())
    wp_id = _package()
    with pytest.raises(rp.PackageError):
        rp.reject(wp_id, inv, lid, note=" ", actor="t")
    d = rp.reject(wp_id, inv, lid, note="paid in cash", actor="t")
    assert (d["decision"], d["workpackage_id"], d["run_id"]) == ("not_this", wp_id, None)
    ws = rp.workspace(wp_id)
    assert _line_row(ws, lid)["state"] == "open" and _line_row(ws, lid)["rejected"] == [inv]
    rp.revoke(wp_id, kind="decision", ref=reconcile.pair_key(inv, lid), actor="t")
    assert _line_row(rp.workspace(wp_id), lid)["state"] == "proposed"


def test_a_line_that_needs_no_invoice_is_marked_with_its_reason(db):
    inv = k2._save("inv", k2._invoice())
    stmt = _stmt("stmt", _line())
    [lid] = _ids(stmt, _line())
    wp_id = _package()
    with pytest.raises(rp.PackageError):
        rp.mark(wp_id, [lid], category="holiday", note=None, actor="t")
    with pytest.raises(rp.PackageError):
        rp.mark(wp_id, [lid], category="other", note=None, actor="t")  # 'other' needs a note
    [m] = rp.mark(wp_id, [lid], category="private", note=None, actor="t")
    ws = rp.workspace(wp_id)
    assert _line_row(ws, lid)["state"] == "marked" and _line_row(ws, lid)["mark"]["category"] == "private"
    assert ws["counts"]["open_lines"] == 0
    with pytest.raises(rp.PackageError):
        rp.allocate(wp_id, [{"invoice_doc_id": inv, "line_id": lid}], note=None, actor="t")
    rp.revoke(wp_id, kind="mark", ref=str(m["id"]), actor="t")
    rp.allocate(wp_id, [{"invoice_doc_id": inv, "line_id": lid}], note=None, actor="t")
    with pytest.raises(rp.PackageError):
        rp.mark(wp_id, [lid], category="fee", note=None, actor="t")  # allocated: revoke it first


def test_a_decision_after_another_one_was_recorded_meanwhile_conflicts(db):
    inv = k2._save("inv", k2._invoice())
    stmt = _stmt("stmt", _line())
    [lid] = _ids(stmt, _line())
    wp_id = _package()
    stale = rp._decision_state()
    rp.mark(wp_id, [lid], category="private", note=None, actor="other")
    with pytest.raises(work.RevisionConflict):
        rp._write(stale, lambda c: None)
    assert inv


def test_a_package_with_decisions_is_only_hidden(db):
    stmt = _stmt("stmt", _line())
    [lid] = _ids(stmt, _line())
    empty = _package(name="empty")
    work.delete_workpackage(empty, actor="t")
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM reconcile_scopes").fetchone()[0] == 0
    used = _package(name="used")
    rp.mark(used, [lid], category="private", note=None, actor="t")
    with pytest.raises(work.NotReady):
        work.delete_workpackage(used, actor="t")


# --- the service ---------------------------------------------------------------------------------------------------------


def test_the_service_creates_the_package_and_records_the_decisions(env):
    from tests.test_api import HUMAN

    c = env["client"]
    inv = k2._save("inv", k2._invoice())
    stmt = _stmt("stmt", _line())
    [lid] = _ids(stmt, _line())
    assert c.get("/api/reconcile/accounts").json()["accounts"][0]["key"] == OWN_KEY
    r = c.post("/api/reconcile/packages", headers=HUMAN,
               json={"name": "April", "accounts": [OWN_KEY], "period_start": "2026-04-01", "period_end": "2026-04-30"})
    assert r.status_code == 201, r.text
    wp_id = r.json()["workpackage"]["id"]
    assert c.get(f"/api/workpackages/{wp_id}/reconcile").json()["lines"][0]["state"] == "proposed"
    bad = c.post(f"/api/workpackages/{wp_id}/reconcile/allocate", headers=HUMAN,
                 json={"pairs": [{"invoice_doc_id": inv, "line_id": lid, "line_amount": "1,5"}]})
    assert bad.status_code == 422  # a guessed separator is never accepted
    r = c.post(f"/api/workpackages/{wp_id}/reconcile/accept-proposed", headers=HUMAN, json={})
    assert r.status_code == 200, r.text
    assert r.json()["lines"][0]["state"] == "allocated"
    alloc = r.json()["lines"][0]["allocations"][0]["allocation_id"]
    r = c.post(f"/api/workpackages/{wp_id}/reconcile/revoke", headers=HUMAN, json={"kind": "allocation", "ref": str(alloc)})
    assert r.json()["lines"][0]["state"] == "proposed"
    r = c.post(f"/api/workpackages/{wp_id}/reconcile/mark", headers=HUMAN, json={"line_ids": [lid], "category": "fee"})
    assert r.json()["lines"][0]["state"] == "marked"
    assert c.post(f"/api/workpackages/{wp_id}/reconcile/mark", headers=HUMAN, json={"line_ids": [lid], "category": "nope"}).status_code == 422
    assert any(w["id"] == wp_id for w in c.get("/api/workpackages").json()["workpackages"])
