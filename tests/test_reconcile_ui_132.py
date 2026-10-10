"""132 (backlog F-reconciliation E2): what the two-list pairing page needs from the reconciliation package.

- 'Needs no invoice' for several selected lines in one step, all or none (DECISIONS 132: a real statement is mostly
  lines without an invoice).
- A step that settles every line and invoice it touches needs no reason, even when it combines several lines or
  invoices (instalments that add up); a step that leaves a rest on a side it touches still does.
- Where a document opens: the package, run and item of its work run, and its page count.
- Where a statement line stands on its page: found in the statement's word layer by its amount and booking date.

Synthetic documents and made-up accounts only; no AI call, no network.
"""

from __future__ import annotations

import json

import pytest

from jav import reconcile, reconcile_package as rp, source_layer, store, work
from tests import test_api
from tests import test_reconcile_k2_129 as k2
from tests import test_reconcile_package_131 as e1

env = test_api.env
db = e1.db


# --- several lines marked at once --------------------------------------------------------------------------------------


def test_several_lines_need_no_invoice_in_one_step(db):
    first, second = e1._line(memo="coffee", amount="3.00"), e1._line(memo="lunch", amount="9.00", day="2026-04-11")
    stmt = e1._stmt("stmt", first, second)
    l1, l2 = e1._ids(stmt, first, second)
    wp_id = e1._package()
    marks = rp.mark(wp_id, [l1, l2], category="private", note=None, actor="reviewer")
    assert sorted(m["line_id"] for m in marks) == sorted([l1, l2])
    ws = rp.workspace(wp_id)
    assert {e1._line_row(ws, lid)["state"] for lid in (l1, l2)} == {"marked"}
    [event] = [e for e in work.workpackage_events(wp_id) if e["action"] == "reconcile_mark"]
    detail = json.loads(event["detail"])
    assert len(detail["marks"]) == 2 and detail["category"] == "private"


def test_marking_several_lines_is_all_or_none(db):
    inv = k2._save("inv", k2._invoice())
    other = e1._line(memo="coffee", amount="3.00")
    stmt = e1._stmt("stmt", e1._line(), other)
    paid, free = e1._ids(stmt, e1._line(), other)
    wp_id = e1._package()
    rp.allocate(wp_id, [{"invoice_doc_id": inv, "line_id": paid}], note=None, actor="t")
    with pytest.raises(rp.PackageError):
        rp.mark(wp_id, [free, paid], category="fee", note=None, actor="t")
    assert e1._line_row(rp.workspace(wp_id), free)["state"] != "marked"
    with pytest.raises(rp.PackageError):
        rp.mark(wp_id, [], category="fee", note=None, actor="t")


# --- the reason of a step ------------------------------------------------------------------------------------------------


def test_instalments_that_settle_the_invoice_need_no_reason(db):
    inv = k2._save("inv", k2._invoice())
    first, second = e1._line(amount="40.00"), e1._line(amount="60.00", day="2026-04-12")
    stmt = e1._stmt("stmt", first, second)
    l1, l2 = e1._ids(stmt, first, second)
    wp_id = e1._package()
    rows = rp.allocate(wp_id, [{"invoice_doc_id": inv, "line_id": l1}, {"invoice_doc_id": inv, "line_id": l2}],
                       note=None, actor="t")
    assert sorted(r["line_amount"] for r in rows) == ["40.00", "60.00"] and all(r["note"] is None for r in rows)
    assert e1._invoice_row(rp.workspace(wp_id), inv)["state"] == "confirmed"


def test_a_step_that_leaves_a_rest_still_needs_a_reason(db):
    a = k2._save("a", k2._invoice(number="INV-0001", amount="40.00"))
    b = k2._save("b", k2._invoice(number="INV-0002", amount="50.00"))
    stmt = e1._stmt("stmt", e1._line(memo="INV-0001 INV-0002"))
    [lid] = e1._ids(stmt, e1._line(memo="INV-0001 INV-0002"))
    wp_id = e1._package()
    pairs = [{"invoice_doc_id": a, "line_id": lid}, {"invoice_doc_id": b, "line_id": lid}]
    with pytest.raises(rp.PackageError):  # 40 + 50 of a 100 line: 10 is left on the line
        rp.allocate(wp_id, pairs, note=None, actor="t")
    rp.allocate(wp_id, pairs, note="the bank fee is in the same transfer", actor="t")
    assert e1._line_row(rp.workspace(wp_id), lid)["rest"] == "10.00"


# --- where a document opens ----------------------------------------------------------------------------------------------


def test_the_workspace_says_where_each_document_opens(db):
    k2._run(k2.RUN, ["inv", "stmt"])
    inv = k2._save("inv", k2._invoice(), run_id=k2.RUN)
    stmt = e1._stmt("stmt", e1._line(), run_id=k2.RUN)
    cli = k2._save("cli", k2._invoice(number="INV-0002", amount="7.00"))
    ws = rp.workspace(e1._package())
    assert ws["open"][inv] == {"workpackage_id": "wp-1", "run_id": k2.RUN, "item_id": inv, "pages": 1}
    assert ws["open"][stmt]["item_id"] == stmt
    assert cli not in ws["open"]  # an evaluation on the command line has no package to open it from


# --- where a line stands on its statement page ---------------------------------------------------------------------------


def _layer(doc_id: str, rows: list[tuple[int, str]]) -> source_layer.SourceLayer:
    """A word layer with one text line per row: (page, text); words split on spaces, 10 points high."""
    pages: list[list[dict]] = [[], []]
    for n, (page, text) in enumerate(rows):
        x = 10.0
        for word in text.split(" "):
            pages[page - 1].append({"text": word, "x0": x, "x1": x + 6 * len(word), "top": 20.0 + 12 * n,
                                    "bottom": 30.0 + 12 * n, "line_no": n + 1})
            x += 6 * len(word) + 4
    layer = source_layer.build(doc_id, pages, [(600.0, 800.0), (600.0, 800.0)], text_source="pdf", engine="test")
    assert layer is not None
    return layer


# 138 (Q-line-locator reuse): the pairing page places a line with the review page's row locator (grounding.locate_rows)


def _lines(*lines):
    return reconcile.with_line_ids("s" * 64, list(lines))


def test_a_line_is_found_by_its_amount_and_date_on_the_same_text_line():
    [line] = _lines(e1._line(amount="12345.00", day="2026-04-10", memo="INV-0001"))
    layer = _layer("s" * 64, [(1, "Opening balance 12 345,00"), (1, "2026.04.09 Card fee 12 345,00"),
                              (2, "2026.04.10 Example Supplier INV-0001 -12 345,00")])
    page, box = rp.place(layer, "statement_cib", [line], line["id"])
    assert page == 2 and box is not None and box[1] < box[3]


def test_identical_lines_are_told_apart_by_their_order():
    fee = e1._line(amount="5.00", day="2026-04-10", memo="fee", counterparty_name="Bank", description="Fee")
    lines = _lines(fee, fee)
    layer = _layer("s" * 64, [(1, "2026.04.10 Bank fee 5,00"), (1, "2026.04.10 Bank fee 5,00")])
    (_p1, first), (_p2, second) = (rp.place(layer, "statement_cib", lines, ln["id"]) for ln in lines)
    assert first is not None and second is not None and first[1] < second[1]


def test_a_line_whose_amount_is_not_printed_is_not_located():
    layer = _layer("s" * 64, [(1, "2026.04.10 Something else 7,00")])
    [line] = _lines(e1._line(amount="100.00"))
    assert rp.place(layer, "statement_cib", [line], line["id"]) == (None, None)


def test_the_package_locates_a_line_on_its_statements_word_layer(db):
    k2._run(k2.RUN, ["stmt"])
    line = e1._line()
    stmt = e1._stmt("stmt", line, run_id=k2.RUN)
    layer = _layer(stmt, [(1, "2026.04.10 Example Supplier INV-0001 100,00")])
    source_layer.save(layer)
    with store.connect() as c:
        c.execute("UPDATE datapoints SET source_layer_id=? WHERE doc_id=?", (layer.layer_id, stmt))
    [lid] = e1._ids(stmt, line)
    wp_id = e1._package()
    found = rp.locate(wp_id, lid)
    assert (found["statement_id"], found["page"], found["open"]["item_id"]) == (stmt, 1, stmt) and found["box"] is not None
    other = e1._stmt("other", e1._line(), account=e1.OTHER)
    with pytest.raises(rp.PackageError):
        rp.locate(wp_id, e1._ids(other, e1._line())[0])


def test_a_line_of_a_statement_without_a_work_run_has_nothing_to_open(db):
    stmt = e1._stmt("stmt", e1._line())
    found = rp.locate(e1._package(), e1._ids(stmt, e1._line())[0])
    assert (found["open"], found["page"], found["box"]) == (None, None, None)


# --- the service ---------------------------------------------------------------------------------------------------------


def test_the_service_marks_several_lines_and_locates_one(env):
    from tests.test_api import HUMAN

    c = env["client"]
    first, second = e1._line(memo="coffee", amount="3.00"), e1._line(memo="lunch", amount="9.00", day="2026-04-11")
    stmt = e1._stmt("stmt", first, second)
    l1, l2 = e1._ids(stmt, first, second)
    wp_id = e1._package()
    r = c.post(f"/api/workpackages/{wp_id}/reconcile/mark", headers=HUMAN,
               json={"line_ids": [l1, l2], "category": "private"})
    assert r.status_code == 200, r.text
    assert {ln["state"] for ln in r.json()["lines"]} == {"marked"}
    r = c.get(f"/api/workpackages/{wp_id}/reconcile/locate", params={"line_id": l1})
    assert r.status_code == 200, r.text
    assert r.json()["statement_id"] == stmt and r.json()["open"] is None
    assert c.get(f"/api/workpackages/{wp_id}/reconcile/locate", params={"line_id": "nope"}).status_code == 422
    assert reconcile.ENGINE_VERSION
