"""157 (backlog Q-own-tax-afterwards): the own-tax to-do of 134 for the invoices already in the store.

The check of 134 runs only while a worker processes a document, so the invoices processed before it never got the
to-do (DECISIONS 134: 16 in the store). As with the duplicates of 126, a scan lists them read only, and with `write`
opens the same to-do once, under the flow run that produced the document, on runs not yet approved. Synthetic
documents and made-up tax numbers only; no AI call."""

from __future__ import annotations

import pytest

from jav import corrections, parties, store, work
from tests.test_duplicates_126 import _run, _save  # the scan follows the duplicates' scan

BUYER, RAIL = "12121216-2-42", "13570008-1-13"  # made up (data guard allow list)
REASON = "parties:own_tax_as_supplier"


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "t.sqlite"):
        parties.create("Example Buyer Kft.", identities=[("tax", parties.tax_key(BUYER), BUYER)], actor="tester")
        yield


def _tax(supplier, buyer=None):
    return {"supplier_tax_id": supplier, "buyer_tax_id": buyer}


def test_scan_opens_the_own_tax_to_do_once_on_runs_not_yet_approved(db):
    _run("run-1", ["s1", "s2", "s3", "s4"])
    _run("run-2", ["a1"], approved=True)
    s1 = _save("s1", _tax(BUYER), run_id="run-1")                  # the own number as the supplier's: opens
    _save("s2", _tax(RAIL, BUYER), run_id="run-1")                 # read right
    _save("s3", _tax(BUYER, BUYER), run_id="run-1")                # the same on both sides: the role-pair check's
    s4 = _save("s4", _tax(BUYER), run_id="run-1")                  # corrected by a person: no longer the own number
    corrections.save("run-1", s4, fields={"supplier_tax_id": RAIL}, expected_revision=0, actor="t")
    _save("a1", _tax(BUYER), run_id="run-2")                       # an approved run never reopens
    _save("c1", _tax(BUYER))                                       # from the command line: no work run to show it in
    _save("o1", _tax(BUYER), doc_type="invoice_out")               # an outgoing invoice is the own party's
    dry = parties.scan_own_tax()
    assert dry == {"documents": 6, "flagged": 3, "to_open": 1, "written": 0,
                   "skipped": {"approved_run": 1, "no_work_run": 1}}
    assert store.review_open_reasons("document", s1) == []
    assert parties.scan_own_tax(write=True)["written"] == 1
    [reason] = store.review_open_reasons("document", s1)
    assert reason["reason"] == REASON and reason["run_id"] == work.flow_run_id("run-1", s1)
    assert [r["reason"] for r in work.item_reasons("run-1", s1)["run"]] == [REASON]  # the run's own to-do
    again = parties.scan_own_tax(write=True)
    assert (again["to_open"], again["written"], again["skipped"]["already_open"]) == (0, 0, 1)
    assert len(store.review_open_reasons("document", s1)) == 1


def test_a_document_re_read_as_another_type_drops_out(db):
    _run("run-1", ["r1"])
    _save("r1", _tax(BUYER), run_id="run-1")
    _save("r1", _tax(BUYER), run_id="run-1", doc_type="invoice_out")  # its latest result is outgoing
    assert parties.scan_own_tax()["documents"] == 0


def test_the_scan_and_the_flow_share_one_check(db):
    assert parties.own_tax_reasons("invoice_hu", _tax(BUYER)) == [REASON]
    assert parties.own_tax_reasons("invoice_hu", _tax(BUYER, BUYER)) == []
    assert parties.own_tax_reasons("invoice_out", _tax(BUYER)) == []


def test_the_command_prints_counts_only(db, capsys):
    from jav import cli

    _run("run-1", ["s1"])
    _save("s1", _tax(BUYER), run_id="run-1")
    assert cli.main(["own-tax"]) == 0
    out = capsys.readouterr().out
    assert "to-dos to open: 1" in out and "to-dos written" not in out
    assert BUYER not in out and parties.tax_key(BUYER) not in out  # counts only, no values
    assert cli.main(["own-tax", "--write"]) == 0
    assert "to-dos written: 1" in capsys.readouterr().out
