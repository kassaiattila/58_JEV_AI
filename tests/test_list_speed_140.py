"""140 (backlog Q-filter-slowness; DECISIONS 140): the package list and the reconciliation workspace are kept until their
inputs change.

Measured on a copy of the store: every query of the work package list took 1.5-3.1 s, at each filter change and each
10 s refresh, because the list rebuilt the reconciliation workspace of every reconciliation package (about 1 s each).
Both are now kept with a mark of what they read (`store.table_marks`): a filter on unchanged data is served from the
kept rows, and any change of an input (a document's data, a correction, an approval, a decision, a mark, a statement
choice, an AI answer, a rate, a party) builds them again. Synthetic data only; no AI call.
"""

from __future__ import annotations

import pytest

from jav.app import datasets, parties, work, work_views
from jav.core import store
from jav.domains.finance import reconcile, reconcile_package as rp
from jav.app.tablequery import Filter, Query
from tests import test_reconcile_package_131 as p131
from tests.test_reconcile_k2_129 import _save

db = p131.db


@pytest.fixture(autouse=True)
def fresh_caches():
    datasets.clear_cache()
    rp.clear_cache()
    yield
    datasets.clear_cache()
    rp.clear_cache()


# --- the marks of the tables ----------------------------------------------------------------------------------------------


def test_a_tables_mark_follows_inserts_and_the_given_changes_in_place(db):
    with store.connect() as c:
        c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, revoked_at TEXT)")
        spec = {"t": "COUNT(revoked_at)", "missing_table": None}
        empty = store.table_marks(c, spec)
        c.execute("INSERT INTO t(revoked_at) VALUES (NULL)")
        one = store.table_marks(c, spec)
        c.execute("UPDATE t SET revoked_at='2026-10-10'")
        revoked = store.table_marks(c, spec)
    assert empty[1] is None  # a table the store does not have
    assert len({str(empty), str(one), str(revoked)}) == 3


# --- the reconciliation workspace ------------------------------------------------------------------------------------------


def _counting(monkeypatch) -> list[int]:
    calls: list[int] = []
    real = reconcile.propose

    def propose(snap):
        calls.append(1)
        return real(snap)

    monkeypatch.setattr(reconcile, "propose", propose)
    return calls


def _workspace_package():
    statement = p131._stmt("april", p131._line(), p131._line(amount="250.00", memo="INV-0002"))
    invoice = _save("inv", {"invoice_number": "INV-0001", "supplier_name": "Example Supplier", "gross_total": "100.00",
                            "currency": "HUF", "issue_date": "2026-04-01"})
    return p131._package(), statement, invoice


def test_the_workspace_is_kept_until_an_input_changes(db, monkeypatch):
    calls = _counting(monkeypatch)
    wp, statement, invoice = _workspace_package()
    first = rp.workspace(wp)
    again = rp.workspace(wp)
    assert len(calls) == 1 and again == first
    line = next(ln for ln in first["lines"] if ln["memo"] == "INV-0001")
    rp.allocate(wp, [{"invoice_doc_id": invoice, "line_id": line["id"]}], note=None, actor="reviewer")
    after = rp.workspace(wp)
    assert len(calls) > 1  # built again after the allocation
    assert next(ln for ln in after["lines"] if ln["id"] == line["id"])["state"] == "allocated"


def test_a_kept_workspace_is_not_changed_by_its_reader(db, monkeypatch):
    wp, _statement, _invoice = _workspace_package()
    first = rp.workspace(wp)
    first["lines"].clear()
    assert rp.workspace(wp)["lines"]


@pytest.mark.parametrize("change", ["new_document", "party", "mark"])
def test_each_kind_of_input_builds_the_workspace_again(db, monkeypatch, change):
    calls = _counting(monkeypatch)
    wp, statement, _invoice = _workspace_package()
    first = rp.workspace(wp)
    if change == "new_document":
        _save("inv2", {"invoice_number": "INV-0002", "supplier_name": "Example Supplier", "gross_total": "250.00",
                       "currency": "HUF", "issue_date": "2026-04-02"})
    elif change == "party":
        parties.create("Example Home", identities=[("account", p131.OWN_KEY, "own account")], actor="reviewer")
    else:
        line = next(ln for ln in first["lines"] if ln["memo"] == "INV-0002")
        rp.mark(wp, [line["id"]], category="private", note=None, actor="reviewer")
    rp.workspace(wp)
    assert len(calls) >= 2


# --- the package list ------------------------------------------------------------------------------------------------------


def _counting_list(monkeypatch) -> list[int]:
    calls: list[int] = []
    real = work_views.workpackage_list

    def listed(**kwargs):
        calls.append(1)
        return real(**kwargs)

    monkeypatch.setattr(work_views, "workpackage_list", listed)
    return calls


def test_a_filter_on_the_unchanged_list_does_not_build_it_again(db, monkeypatch, tmp_path):
    calls = _counting_list(monkeypatch)
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4 synthetic")
    wp = work.create_from_files([pdf], name="Files", owner="reviewer")
    datasets.query("workpackages", None, Query())
    page = datasets.query("workpackages", None, Query(filters=[Filter(col="source_kind", op="in", value=["manual"])]))
    assert len(calls) == 1 and page["matched"] == 1
    work.rename_workpackage(wp["id"], "Renamed", actor="reviewer")
    page = datasets.query("workpackages", None, Query())  # 153: the last rows at once, rebuilt behind
    assert page["refreshing"] is True and page["rows"][0]["name"] == "Files"
    datasets.wait_for_rebuilds()
    page = datasets.query("workpackages", None, Query())
    assert len(calls) == 2 and page["rows"][0]["name"] == "Renamed" and "refreshing" not in page


def test_a_reconciliation_change_shows_in_the_lists_next_step(db, monkeypatch):
    """231 (U2a; the owner's decision of 2026-10-28: one work list, the cases): a reconciliation is a case, outside the
    list of every document batch; its container's next step in the list of every package follows a change at once."""
    wp, _statement, _invoice = _workspace_package()

    def code() -> str:
        return next(r for r in work_views.workpackage_list() if r["id"] == wp)["next"]["code"]

    before = code()
    ws = rp.workspace(wp)
    for line in ws["lines"]:
        rp.mark(wp, [line["id"]], category="private", note=None, actor="reviewer")
    assert before == "reconcile_pair" and code() == "reconcile_result"
    assert all(r["id"] != wp for r in datasets.query("workpackages", None, Query())["rows"])


def test_an_ai_answer_replaced_within_the_same_second_builds_the_workspace_again(db):
    """Found by the full check: an answer is replaced in place, so its row count, rowid and time stay the same."""
    wp, _statement, _invoice = _workspace_package()
    line = next(ln for ln in rp.workspace(wp)["lines"] if ln["memo"] == "INV-0001")
    for kind in ("retail_purchase", "subscription"):
        with store.connect() as c:
            c.execute("INSERT INTO reconcile_ai_proposals(line_id, engine, statement_doc_id, workpackage_id, options, kind, config_hash,"
                      " measured, created_at) VALUES (?,?,?,?,?,?,'x',1,'2026-10-10T20:00:00+00:00') ON CONFLICT(line_id, engine)"
                      " DO UPDATE SET kind=excluded.kind", (line["id"], "jev", line["statement_id"], wp, "[]", kind))
        if kind == "retail_purchase":
            assert next(ln for ln in rp.workspace(wp)["lines"] if ln["id"] == line["id"])["ai"]["jev"]["kind"] == kind
    assert next(ln for ln in rp.workspace(wp)["lines"] if ln["id"] == line["id"])["ai"]["jev"]["kind"] == "subscription"


def test_nothing_is_kept_beyond_the_time_slot(db, monkeypatch):
    calls = _counting(monkeypatch)
    wp, _statement, _invoice = _workspace_package()
    rp.workspace(wp)
    now = rp.time.time()
    monkeypatch.setattr(rp.time, "time", lambda: now + rp.KEEP_SECONDS)
    rp.workspace(wp)
    assert len(calls) == 2
