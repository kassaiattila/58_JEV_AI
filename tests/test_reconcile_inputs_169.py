"""169 (DECISIONS 169): a reconciliation package's inputs as an item list - the scope's statements and the invoices its
pairing may take, each with where it comes from; leaving a document out of this package only, with a reason, and
restoring it; the packages a file for it can be added to.

The owner's choice of 2026-10-18: "only from this reconciliation" - the document stays in its own package and in every
other reconciliation. Synthetic documents and made-up accounts only; no AI call, no network.
"""

from __future__ import annotations

import pytest

from jav import datasets, reconcile_package as rp, reconcile_statement as rs, store, work
from jav.tablequery import Query
from tests import test_api
from tests import test_reconcile_k2_129 as k2
from tests.test_reconcile_package_131 import OWN_KEY, _ids, _invoice_row, _line, _package, _stmt

env = test_api.env


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield


def _rows(wp_id: str, **scope: str) -> list[dict]:
    return datasets.query("reconcile_inputs", {"workpackage_id": wp_id, **scope}, Query(limit=500))["rows"]


def _two_invoices():
    inv = k2._save("inv", k2._invoice())
    other = k2._save("inv2", k2._invoice(number="INV-0002", amount="55.00"))
    stmt = _stmt("stmt", _line())
    return inv, other, stmt


# --- the item list -------------------------------------------------------------------------------------------------------


def test_the_inputs_are_the_scopes_statements_and_the_invoices_with_their_source(db):
    k2._run(k2.RUN, ["inv", "stmt"])
    inv = k2._save("inv", k2._invoice(), run_id=k2.RUN)
    stmt = _stmt("stmt", _line(), run_id=k2.RUN)
    wp_id = _package()
    ws = rp.workspace(wp_id)
    [st] = ws["statements"]
    assert (st["id"], st["file"], st["lines"], st["open_lines"], st["decided"], st["source"]) == (stmt, "stmt.pdf", 1, 1, 0, "not_approved")
    assert ws["counts"]["statements"] == 1 and ws["counts"]["own_invoices"] == 1 and ws["counts"]["left_out"] == 0
    rows = _rows(wp_id)
    assert [(r["kind"], r["name"]) for r in rows] == [("statement", "stmt.pdf"), ("incoming", "inv.pdf")]
    statement, invoice = rows
    # the source package and its live run, which an approval has not released yet
    assert (statement["package"], statement["source"], statement["_wp"], statement["_run"]) == ("synthetic", "live", "wp-1", k2.RUN)
    assert statement["date"] == "2026-03-01 – 06-30" and statement["open_lines"] == 1  # the same year once
    assert (invoice["subject"], invoice["partner"], invoice["amount"], invoice["pairing"]) == ("INV-0001", "Example Supplier Kft.", "100.00", "proposed")
    assert invoice["item_id"] == inv and invoice["blocks"] is None
    assert statement["blocks"] == "igen"  # an unapproved statement of the scope blocks the approval


def test_another_partys_invoices_show_only_on_request(db):
    from tests import test_parties_package_133 as p133

    home, _club = p133._parties()
    _mine, club_inv, _nobody, _stmt_id = p133._docs()
    wp_id = rp.create(name="Home", accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30", actor="t",
                      party_id=home)["workpackage_id"]
    assert club_inv not in {r["doc_id"] for r in _rows(wp_id)}
    others = {r["doc_id"]: r for r in _rows(wp_id, others="1")}
    assert others[club_inv]["party"] == "Sporting Club"


# --- leaving out and restoring -------------------------------------------------------------------------------------------


def test_a_left_out_invoice_leaves_this_package_only_and_comes_back(db):
    inv, other, stmt = _two_invoices()
    wp_id, second = _package(), _package(name="April again")
    assert rp.leave_out(wp_id, [inv], reason="  belongs to the other company ", actor="Reviewer") == 1
    ws = rp.workspace(wp_id)
    assert inv not in {r["id"] for r in ws["invoices"]} and other in {r["id"] for r in ws["invoices"]}
    [line] = ws["lines"]
    assert all(c["invoice_id"] != inv for c in line["candidates"])  # no longer proposed here
    [gone] = ws["left_out"]
    assert (gone["id"], gone["kind"], gone["reason"], gone["actor"], gone["number"]) == (inv, "invoice", "belongs to the other company", "Reviewer", "INV-0001")
    assert ws["counts"]["left_out"] == 1
    # the other package still pairs it
    assert inv in {r["id"] for r in rp.workspace(second)["invoices"]}
    with pytest.raises(rp.PackageError):
        rp.allocate(wp_id, [{"invoice_doc_id": inv, "line_id": _ids(stmt, _line())[0]}], note=None, actor="t")
    left = {r["doc_id"]: r for r in _rows(wp_id, left_out="1")}
    assert left[inv]["_left_out"] is True and left[inv]["left_out_reason"] == "belongs to the other company"
    assert inv not in {r["doc_id"] for r in _rows(wp_id)}
    assert rp.restore_left_out(wp_id, [inv], actor="Reviewer") == 1
    assert _invoice_row(rp.workspace(wp_id), inv)["state"] == "proposed"
    assert [e["action"] for e in work.workpackage_events(wp_id)][-2:] == ["reconcile_leave_out", "reconcile_restore"]


def test_a_left_out_statement_leaves_the_scope_with_its_lines(db):
    _inv, _other, stmt = _two_invoices()
    wp_id = _package()
    rp.leave_out(wp_id, [stmt], reason="a duplicate download", actor="t")
    ws = rp.workspace(wp_id)
    assert ws["lines"] == [] and ws["statements"] == [] and ws["coverage"][0]["statements"] == 0
    assert [(g["kind"], g["account"]) for g in ws["left_out"]] == [("statement", k2.OWN)]
    assert ws["blockers"] == []  # its source no longer blocks the approval


def test_leaving_out_needs_a_reason_and_an_input_of_the_package(db):
    inv, _other, _stmt_id = _two_invoices()
    wp_id = _package()
    with pytest.raises(rp.PackageError):
        rp.leave_out(wp_id, [inv], reason="   ", actor="t")
    with pytest.raises(rp.PackageError):
        rp.leave_out(wp_id, ["f" * 64], reason="why", actor="t")
    with pytest.raises(rp.PackageError):
        rp.leave_out(wp_id, [], reason="why", actor="t")
    with pytest.raises(rp.PackageError):
        rp.restore_left_out(wp_id, [inv], actor="t")  # it is not left out


def test_a_pairing_on_the_document_has_to_be_revoked_first(db):
    inv, _other, stmt = _two_invoices()
    wp_id = _package()
    [row] = rp.allocate(wp_id, [{"invoice_doc_id": inv, "line_id": _ids(stmt, _line())[0]}], note=None, actor="t")
    for doc in (inv, stmt):
        with pytest.raises(rp.PackageError) as exc:
            rp.leave_out(wp_id, [doc], reason="why", actor="t")
        assert exc.value.template == "pairings or marks of this package rest on {{files}}; revoke them first"
    rp.revoke(wp_id, kind="allocation", ref=str(row["id"]), actor="t")
    assert rp.leave_out(wp_id, [inv, stmt], reason="why", actor="t") == 2


def test_an_approved_package_takes_no_change_of_its_inputs(db):
    k2._run(k2.RUN, ["inv", "stmt"], approved=True)
    inv = k2._save("inv", k2._invoice(), run_id=k2.RUN)
    _stmt("stmt", _line(), run_id=k2.RUN)
    wp_id = _package()
    rp.leave_out(wp_id, [k2._save("spare", k2._invoice(number="SP-1", amount="9.00"), run_id=k2.RUN)], reason="why", actor="t")
    view = rs.current(wp_id)
    rs.approve(wp_id, fingerprint=view["fingerprint"], actor="t")
    with pytest.raises(rp.Locked):
        rp.leave_out(wp_id, [inv], reason="why", actor="t")
    with pytest.raises(rp.Locked):
        rp.restore_left_out(wp_id, [k2._id("spare")], actor="t")
    # the version records what was left out
    [gone] = rs.approved_version(wp_id, 1)["statement"]["left_out"]
    assert (gone["kind"], gone["reason"]) == ("invoice", "why")


def test_a_package_without_left_out_documents_keeps_its_statement_unchanged(db):
    _two_invoices()
    wp_id = _package()
    assert "left_out" not in rs.current(wp_id)["statement"]


# --- where files are added -----------------------------------------------------------------------------------------------


def test_files_go_to_a_documents_or_statement_package_givers_first(db):
    k2._run(k2.RUN, ["inv", "stmt"])
    k2._save("inv", k2._invoice(), run_id=k2.RUN)
    _stmt("stmt", _line(), run_id=k2.RUN)
    wp_id = _package()
    found = rp.targets(wp_id)
    assert found["documents"][0]["id"] == "wp-1" and found["documents"][0]["inputs"] == 2
    assert wp_id not in {d["id"] for d in found["documents"]}
    assert found["statements"] == []


# --- the local service ---------------------------------------------------------------------------------------------------


def test_the_service_leaves_out_restores_and_lists_targets(env):
    c = env["client"]
    inv, _other, _stmt_id = _two_invoices()
    wp_id = _package()
    who = test_api.HUMAN
    assert c.post(f"/api/workpackages/{wp_id}/reconcile/leave-out", json={"doc_ids": [inv], "reason": ""}, headers=who).status_code == 422
    res = c.post(f"/api/workpackages/{wp_id}/reconcile/leave-out", json={"doc_ids": [inv], "reason": "not ours"}, headers=who)
    assert res.status_code == 200 and [g["id"] for g in res.json()["left_out"]] == [inv]
    res = c.post(f"/api/workpackages/{wp_id}/reconcile/restore-left-out", json={"doc_ids": [inv]}, headers=who)
    assert res.status_code == 200 and res.json()["left_out"] == []
    assert set(c.get(f"/api/workpackages/{wp_id}/reconcile/targets").json()) == {"documents", "statements"}
