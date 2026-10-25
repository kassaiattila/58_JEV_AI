"""145 (backlog F-reconciliation E3b): a reconciliation package's result - its statement, its approval as an unchangeable
version with a lock on its lines, reopening with a reason, accepting a command-line source, and the Excel download.

The owner's decisions (DECISIONS 131, 132, 133, 145): approval with open lines listed; every source from an approved run
or accepted by a person; an unverified statement or a month without a statement is a warning; reopening keeps the old
version as an earlier one; the download is an Excel workbook with two sheets. Synthetic documents and made-up accounts
only; no AI call, no network.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from jav.app import work, work_views
from jav.core import store
from jav.domains.finance import reconcile, reconcile_package as rp, reconcile_statement as rs
from tests import test_api
from tests import test_reconcile_k2_129 as k2
from tests.test_reconcile_package_131 import OWN_KEY, _ids, _line, _package, _stmt

env = test_api.env


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield


def _approved_sources(*names: str) -> None:
    k2._run(k2.RUN, list(names), approved=True)


def _world():
    """Four invoices and four lines of one approved run: a paid pair, a proposal, a line that needs no invoice and an
    incoming credit the code leaves out; one invoice has no payment in the covered period."""
    _approved_sources("paid", "proposed", "unpaid", "stmt")
    paid = k2._save("paid", k2._invoice(number="INV-0001"), run_id=k2.RUN)
    proposed = k2._save("proposed", k2._invoice(number="INV-0002", amount="200.00"), run_id=k2.RUN)
    unpaid = k2._save("unpaid", k2._invoice(number="INV-0003", amount="300.00", payment_iban=None, supplier_name="Nobody Kft."),
                      run_id=k2.RUN)
    lines = [_line(memo="INV-0001"), _line(amount="200.00", memo="INV-0002", day="2026-04-12"),
             _line(amount="15.00", memo="account fee", day="2026-04-20", counterparty_name="Bank", counterparty_account=None),
             _line(amount="50.00", memo="refund", day="2026-04-22", direction="credit", counterparty_name="Someone",
                   counterparty_account=None)]
    stmt = _stmt("stmt", *lines, run_id=k2.RUN)
    ids = _ids(stmt, *lines)
    wp_id = _package()
    pair = next(c for c in rp.workspace(wp_id)["lines"][0]["candidates"] if c["invoice_id"] == paid)
    rp.allocate(wp_id, [{"invoice_doc_id": pair["invoice_id"], "line_id": ids[0]}], note=None, actor="t")
    rp.mark(wp_id, [ids[2]], category="fee", note=None, actor="t")
    return wp_id, {"paid": paid, "proposed": proposed, "unpaid": unpaid}, ids


def _by(rows, key, value):
    return next(r for r in rows if r[key] == value)


# --- the statement -------------------------------------------------------------------------------------------------------


def test_the_statement_sorts_the_invoices_and_the_lines_by_their_result(db):
    wp_id, inv, ids = _world()
    view = rs.current(wp_id)
    st = view["statement"]
    assert (st["package"]["name"], st["period"], st["accounts"]) == ("April", ["2026-04-01", "2026-04-30"], [OWN_KEY])
    paid = _by(st["invoices"], "id", inv["paid"])
    assert (paid["result"], paid["allocated"], paid["rest"], paid["number"]) == ("paid", "100.00", "0.00", "INV-0001")
    assert [(p["line_id"], p["line_amount"], p["booking_date"]) for p in paid["paid_by"]] == [(ids[0], "100.00", "2026-04-10")]
    assert _by(st["invoices"], "id", inv["proposed"])["result"] == "undecided"  # a proposal is no decision
    assert _by(st["invoices"], "id", inv["unpaid"])["result"] == "no_payment_found"
    results = {ln["id"]: (ln["result"], ln["reason"]) for ln in st["lines"]}
    assert results == {ids[0]: ("paired", None), ids[1]: ("open", None), ids[2]: ("needs_no_invoice", "fee"),
                       ids[3]: ("left_out", "not_outgoing_payment")}
    assert _by(st["lines"], "id", ids[0])["pays"][0]["number"] == "INV-0001"
    assert st["counts"] == {"invoices": {"no_payment_found": 1, "paid": 1, "undecided": 1},
                            "lines": {"left_out": 1, "needs_no_invoice": 1, "open": 1, "paired": 1}, "open_lines": 1}
    assert view["blockers"] == [] and view["approval"]["active"] is None
    # the fingerprint is the content's: the same twice, another after a decision
    assert rs.current(wp_id)["fingerprint"] == view["fingerprint"]
    rp.mark(wp_id, [ids[1]], category="private", note=None, actor="t")
    assert rs.current(wp_id)["fingerprint"] != view["fingerprint"]


def test_an_unverified_statement_and_a_month_without_one_are_warnings_not_blockers(db):
    _approved_sources("inv", "stmt")
    k2._save("inv", k2._invoice(), run_id=k2.RUN)
    _stmt("stmt", _line(), run_id=k2.RUN, verified=False)
    wp_id = _package(end="2026-07-31")  # July has no statement
    ws = rp.workspace(wp_id)
    assert ws["blockers"] == [] and [w["code"] for w in ws["warnings"]] == ["statement_unverified"]
    warnings = rs.current(wp_id)["statement"]["warnings"]
    assert {(w["code"], w.get("month")) for w in warnings} == {("statement_unverified", None), ("month_without_statement", "2026-07")}


def test_another_partys_invoice_appears_only_when_a_line_of_the_scope_paid_it(db):
    from tests import test_parties_package_133 as p133

    home, _club = p133._parties()
    _mine, club_inv, _nobody, stmt = p133._docs()
    wp_id = rp.create(name="Home", accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30", actor="t",
                      party_id=home)["workpackage_id"]
    assert all(i["id"] != club_inv for i in rs.current(wp_id)["statement"]["invoices"])
    _first, second = _ids(stmt, _line(), _line(amount="250.00", memo="CLUB-77"))
    rp.allocate(wp_id, [{"invoice_doc_id": club_inv, "line_id": second}], note=None, actor="t")
    row = _by(rs.current(wp_id)["statement"]["invoices"], "id", club_inv)
    assert (row["result"], row["other_party"]) == ("paid", "Sporting Club")


# --- the approval, the lock and reopening --------------------------------------------------------------------------------


def test_the_approval_needs_the_sources_and_the_statement_the_person_saw(db):
    inv = k2._save("inv", k2._invoice())
    stmt = _stmt("stmt", _line())  # both from the command line: no run
    wp_id = _package()
    # the invoice belongs to no own party: it blocks once a line of the package paid it (DECISIONS 145)
    rp.allocate(wp_id, [{"invoice_doc_id": inv, "line_id": _ids(stmt, _line())[0]}], note=None, actor="t")
    view = rs.current(wp_id)
    assert {(b["code"], b["kind"]) for b in view["blockers"]} == {("source_no_run", "statement"), ("source_no_run", "invoice")}
    with pytest.raises(work.NotReady) as exc:
        rs.approve(wp_id, fingerprint=view["fingerprint"], actor="t")
    assert {b["code"] for b in exc.value.blockers} == {"source_no_run"}
    accepted = rs.accept_sources(wp_id, [b["doc_id"] for b in view["blockers"]], actor="Reviewer")
    assert accepted == 2
    view = rs.current(wp_id)
    assert view["blockers"] == []
    assert {i["source"] for i in view["statement"]["invoices"]} == {"accepted"}
    with pytest.raises(work.RevisionConflict):
        rs.approve(wp_id, fingerprint="0" * 64, actor="t")
    approved = rs.approve(wp_id, fingerprint=view["fingerprint"], actor="Reviewer")
    assert (approved["version"], approved["approved_by"], approved["fingerprint"]) == (1, "Reviewer", view["fingerprint"])
    assert rs.current(wp_id)["approval"]["active"]["version"] == 1
    view_ = work_views.workpackage_view(wp_id)
    assert view_["next"]["code"] == "reconcile_approved" and view_["case"]["pack"] == "reconciliation"  # 231 (C3a-2)
    with pytest.raises(rp.PackageError):
        rs.approve(wp_id, fingerprint=view["fingerprint"], actor="t")  # already approved
    assert stmt


def test_an_accepted_source_holds_for_its_result_only(db):
    inv = k2._save("inv", k2._invoice())
    stmt = _stmt("stmt", _line())
    wp_id = _package()
    rp.allocate(wp_id, [{"invoice_doc_id": inv, "line_id": _ids(stmt, _line())[0]}], note=None, actor="t")
    view = rs.current(wp_id)
    rs.accept_sources(wp_id, [b["doc_id"] for b in view["blockers"]], actor="t")
    assert rs.current(wp_id)["blockers"] == []
    store.insert_datapoints(run_id="cli-inv-again", doc_id=k2._id("inv"), doc_type="invoice_hu", arm="G",  # a new evaluation
                            datapoints=k2._invoice(), field_conf={}, validation=[], route="auto", review_reasons=[],
                            final_status="done")
    assert [b["kind"] for b in rs.current(wp_id)["blockers"]] == ["invoice"]
    with pytest.raises(rp.PackageError):
        rs.accept_sources(wp_id, ["not-a-blocker"], actor="t")


def test_an_approved_statement_locks_its_lines_in_every_package_until_reopened(db):
    wp_id, inv, ids = _world()
    version = rs.approve(wp_id, fingerprint=rs.current(wp_id)["fingerprint"], actor="t")
    other = _package(name="April again")
    for attempt in (
        lambda wp: rp.allocate(wp, [{"invoice_doc_id": inv["proposed"], "line_id": ids[1]}], note=None, actor="t"),
        lambda wp: rp.mark(wp, [ids[1]], category="private", note=None, actor="t"),
        lambda wp: rp.unmark(wp, [ids[2]], actor="t"),
        lambda wp: rp.reject(wp, inv["proposed"], ids[1], note="no", actor="t"),
    ):
        for wp in (wp_id, other):
            with pytest.raises(rp.Locked):
                attempt(wp)
    with pytest.raises(rp.Locked):
        rp.accept_proposed(wp_id, actor="t")
    assert rp.accept_proposed(other, actor="t") == 0  # another package skips the locked lines
    allocation = rp.workspace(wp_id)["lines"][0]["allocations"][0]["allocation_id"]
    with pytest.raises(rp.Locked):
        rp.revoke(other, kind="allocation", ref=str(allocation), actor="t")
    with pytest.raises(rp.Locked):
        rp.set_scope(wp_id, accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-05-31", expected_revision=1, actor="t")
    ws = rp.workspace(other)
    assert ws["lines"][0]["locked"] == {"workpackage_id": wp_id, "version": 1}
    assert rp.workspace(wp_id)["approval"]["active"]["version"] == version["version"]
    with pytest.raises(rp.PackageError):
        rs.reopen(wp_id, note=" ", actor="t")  # a reason is required
    rs.reopen(wp_id, note="a late invoice arrived", actor="Reviewer")
    rp.mark(other, [ids[1]], category="private", note=None, actor="t")  # unlocked again
    versions = rs.current(wp_id)["approval"]["versions"]
    assert [(v["version"], v["reopened_by"], v["reopen_note"]) for v in versions] == [(1, "Reviewer", "a late invoice arrived")]
    second = rs.approve(wp_id, fingerprint=rs.current(wp_id)["fingerprint"], actor="t")
    assert second["version"] == 2
    assert [v["version"] for v in rs.current(wp_id)["approval"]["versions"]] == [2, 1]
    assert rs.approved_version(wp_id, 1)["statement"]["counts"]["open_lines"] == 1  # the earlier version keeps its content
    assert rs.approved_version(wp_id, 2)["statement"]["counts"]["open_lines"] == 0


def test_an_approval_after_a_decision_recorded_meanwhile_conflicts(db):
    wp_id, _inv, ids = _world()
    seen = rs.current(wp_id)["fingerprint"]
    rp.mark(wp_id, [ids[1]], category="private", note=None, actor="t")
    with pytest.raises(work.RevisionConflict):
        rs.approve(wp_id, fingerprint=seen, actor="t")


# --- the download --------------------------------------------------------------------------------------------------------


def test_the_workbook_has_the_two_sheets_and_text_is_never_a_formula(db):
    wp_id, _inv, ids = _world()
    data, name = rs.xlsx(wp_id)
    assert name.endswith("-tervezet.xlsx")
    wb = load_workbook(io.BytesIO(data))
    assert wb.sheetnames == ["Számlák", "Tételek"]
    inv_sheet, line_sheet = wb["Számlák"], wb["Tételek"]
    texts = [c.value for row in inv_sheet.iter_rows(max_row=5) for c in row if c.value]
    assert "Tervezet — nem jóváhagyott" in texts and "April" in texts
    head = [c.value for c in next(r for r in inv_sheet.iter_rows() if r[0].value == "Számlaszám")]
    assert head[:3] == ["Számlaszám", "Szállító neve", "Szállító adószáma"]  # the field names of field_labels.json
    rows = [[c.value for c in r] for r in inv_sheet.iter_rows(min_row=inv_sheet.freeze_panes and int(inv_sheet.freeze_panes[1:]))]
    paid = next(r for r in rows if r[0] == "INV-0001")
    assert "Kifizetve" in paid and Decimal(str(paid[head.index("Összeg")])) == Decimal("100.00")
    line_rows = [[c.value for c in r] for r in line_sheet.iter_rows()]
    assert any("Banki díj vagy kamat" in r for r in line_rows)
    rs.approve(wp_id, fingerprint=rs.current(wp_id)["fingerprint"], actor="Reviewer")
    data, name = rs.xlsx(wp_id, version=1)
    assert name.endswith("-v1.xlsx")
    texts = [c.value for row in load_workbook(io.BytesIO(data))["Számlák"].iter_rows(max_row=5) for c in row if c.value]
    assert any(isinstance(t, str) and "1. változat" in t and "Reviewer" in t for t in texts)
    assert ids


def test_a_memo_that_looks_like_a_formula_is_written_as_text(db):
    _approved_sources("stmt")
    _stmt("stmt", _line(memo="=HYPERLINK(\"http://example.invalid\")"), run_id=k2.RUN)
    wp_id = _package()
    wb = load_workbook(io.BytesIO(rs.xlsx(wp_id)[0]))
    cells = [c for row in wb["Tételek"].iter_rows() for c in row if isinstance(c.value, str) and "HYPERLINK" in c.value]
    assert cells and all(c.data_type == "s" for c in cells)


def test_a_control_character_from_a_pdf_text_layer_does_not_fail_the_download(db):
    from jav.app.outputs import xlsx

    # found on the real store: a supplier's name read with a broken glyph; the workbook format refuses it (any download)
    assert xlsx.cell_value("Issued by: Spoti\x0bAB", None) == "Issued by: Spoti AB"
    _approved_sources("inv", "stmt")
    k2._save("inv", k2._invoice(supplier_name="Example\x07Supplier Kft."), run_id=k2.RUN)
    _stmt("stmt", _line(memo="INV-0001\x1f"), run_id=k2.RUN)
    wb = load_workbook(io.BytesIO(rs.xlsx(_package())[0]))
    texts = [c.value for ws in wb for row in ws.iter_rows() for c in row if isinstance(c.value, str)]
    assert "Example Supplier Kft." in texts and "INV-0001 " in texts


# --- the service ---------------------------------------------------------------------------------------------------------


def test_the_service_shows_approves_downloads_and_reopens(env):
    from tests.test_api import HUMAN

    c = env["client"]
    k2._save("inv", k2._invoice())
    _stmt("stmt", _line())
    wp_id = c.post("/api/reconcile/packages", headers=HUMAN, json={
        "name": "April", "accounts": [OWN_KEY], "period_start": "2026-04-01", "period_end": "2026-04-30"}).json()["workpackage"]["id"]
    view = c.get(f"/api/workpackages/{wp_id}/reconcile/statement").json()
    assert {b["code"] for b in view["blockers"]} == {"source_no_run"}
    r = c.post(f"/api/workpackages/{wp_id}/reconcile/approve", headers=HUMAN, json={"fingerprint": view["fingerprint"]})
    assert r.status_code == 409 and r.json()["error"] == "not_ready"
    r = c.post(f"/api/workpackages/{wp_id}/reconcile/accept-sources", headers=HUMAN,
               json={"doc_ids": [b["doc_id"] for b in view["blockers"]]})
    assert r.status_code == 200 and r.json()["blockers"] == []
    view = r.json()
    r = c.post(f"/api/workpackages/{wp_id}/reconcile/approve", headers=HUMAN, json={"fingerprint": "0" * 64})
    assert r.status_code == 409 and r.json()["error"] == "revision_conflict"
    r = c.post(f"/api/workpackages/{wp_id}/reconcile/approve", headers=HUMAN, json={"fingerprint": view["fingerprint"]})
    assert r.status_code == 200 and r.json()["approval"]["active"]["version"] == 1
    lid = c.get(f"/api/workpackages/{wp_id}/reconcile").json()["lines"][0]["id"]
    r = c.post(f"/api/workpackages/{wp_id}/reconcile/mark", headers=HUMAN, json={"line_ids": [lid], "category": "fee"})
    assert r.status_code == 422 and r.json()["error"] == "reconcile_locked"
    r = c.get(f"/api/workpackages/{wp_id}/reconcile/statement.xlsx", params={"version": 1})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert "attachment" in r.headers["content-disposition"]
    assert c.get(f"/api/workpackages/{wp_id}/reconcile/statement", params={"version": 7}).status_code == 404
    r = c.post(f"/api/workpackages/{wp_id}/reconcile/reopen", headers=HUMAN, json={"note": "a late invoice"})
    assert r.status_code == 200 and r.json()["approval"]["active"] is None
    assert c.post(f"/api/workpackages/{wp_id}/reconcile/mark", headers=HUMAN,
                  json={"line_ids": [lid], "category": "fee"}).status_code == 200
    assert reconcile.ENGINE_VERSION


def test_an_unassigned_invoice_blocks_the_approval_only_once_a_line_paid_it(db):
    # DECISIONS 145: an invoice of no own party is every package's own (133), but it blocks a package's approval only
    # when a line of the package paid it; an own party's invoice still blocks with a candidate
    from tests import test_parties_package_133 as p133

    home, _club = p133._parties()
    _approved_sources("stmt")
    mine = k2._save("mine", k2._invoice(buyer_name="Jane Example"))  # the home party's, by name; no run
    nobody = k2._save("nobody", k2._invoice(number="NB-5", amount="40.00"))  # no buyer: unassigned; no run
    stmt = _stmt("stmt", _line(), _line(amount="40.00", memo="NB-5", day="2026-04-12"), run_id=k2.RUN)
    wp_id = rp.create(name="Home", accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30", actor="t",
                      party_id=home)["workpackage_id"]
    ws = rp.workspace(wp_id)
    assert next(i for i in ws["invoices"] if i["id"] == nobody)["candidates"]  # it has a candidate ...
    assert [b["doc_id"] for b in ws["blockers"]] == [mine]  # ... but only the party's own invoice blocks
    _first, second = _ids(stmt, _line(), _line(amount="40.00", memo="NB-5", day="2026-04-12"))
    rp.allocate(wp_id, [{"invoice_doc_id": nobody, "line_id": second}], note=None, actor="t")
    assert {b["doc_id"] for b in rp.workspace(wp_id)["blockers"]} == {mine, nobody}  # paid by the package: it blocks


def test_an_invoice_paid_in_another_partys_package_does_not_block_this_one(db):
    # found on the real store: the household's electricity bills, paid in the household's package, blocked the club's
    from tests import test_parties_package_133 as p133
    from tests.test_reconcile_package_131 import OTHER

    home, club = p133._parties()
    _approved_sources("stmt", "club-stmt")
    _mine, club_inv, _nobody, _stmt_home = p133._docs()  # the club's invoice: no run
    club_line = _line(amount="250.00", memo="CLUB-77")
    club_stmt = _stmt("club-stmt", club_line, run_id=k2.RUN, account=OTHER)
    club_wp = rp.create(name="Club", accounts=[reconcile.account_key(OTHER)], period_start="2026-04-01",
                        period_end="2026-04-30", actor="t", party_id=club)["workpackage_id"]
    rp.allocate(club_wp, [{"invoice_doc_id": club_inv, "line_id": _ids(club_stmt, club_line)[0]}], note=None, actor="t")
    home_wp = rp.create(name="Home", accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30", actor="t",
                        party_id=home)["workpackage_id"]
    assert club_inv not in {b["doc_id"] for b in rp.workspace(home_wp)["blockers"]}
    assert club_inv in {b["doc_id"] for b in rp.workspace(club_wp)["blockers"]}
