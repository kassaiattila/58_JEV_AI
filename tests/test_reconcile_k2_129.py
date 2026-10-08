"""129 (backlog F-reconciliation, K2): a person decides on a proposed invoice <-> statement line pair.

The owner's decisions of 2026-10-08 (DECISIONS 128, 129): the code proposes, a person confirms ("this line paid it") or
rejects with a reason ("not this one"); the decision belongs to the pair, closes its to-dos on both documents, is part
of the reviewed result and is frozen with the run's approval; a rejected pair never comes up again. The to-do stands on
the later processed document, in a worker run only. Synthetic documents and made-up accounts only; no AI call.
"""

from __future__ import annotations

import copy
import hashlib
import json
from decimal import Decimal

import pytest

from jav import corrections, datasets, policy, reconcile, store, work, work_views
from jav.models import CheckResult, FlowState, InvoiceHU
from jav.runtime import calls
from tests import test_api

env = test_api.env

NOW = "2026-10-08T10:00:00+00:00"
RUN = "run-000000000001"  # the service's run id pattern
OWN = "11112223-33334444-55556666"  # made up, wrong check digit (handoff 128 pitfall)
SUPPLIER = "99998887-77776666-55554444"
VERIFIED = [{"name": "closing_balance_check", "ok": True, "code": "closing.ok", "detail": None, "advisory": False},
            {"name": "totals_consistency", "ok": True, "code": "totals.ok", "detail": None, "advisory": False}]
CASES = {c["id"]: c for c in reconcile.golden_cases()}


def _id(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()


def _invoice(number="INV-0001", amount="100.00", **over):
    return {"invoice_number": number, "supplier_name": "Example Supplier Kft.", "payment_iban": SUPPLIER,
            "gross_total": amount, "currency": "HUF", "issue_date": "2026-04-01", "due_date": "2026-04-15", **over}


def _line(memo="INV-0001", amount="100.00", **over):
    return {"booking_date": "2026-04-10", "value_date": None, "direction": "debit", "amount": amount, "running_balance": None,
            "description": "Transfer", "counterparty_name": "Example Supplier", "counterparty_account": SUPPLIER, "memo": memo, **over}


def _statement(*lines):
    return {"statement_type": "bank_account", "account_no": OWN, "account_iban": None, "period_start": "2026-03-01",
            "period_end": "2026-06-30", "currency": "HUF", "opening_balance": None, "closing_balance": None,
            "total_debit": None, "total_credit": None, "transactions": list(lines) or [_line()]}


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield


def _run(run_id: str, names: list[str], *, approved: bool = False) -> None:
    items = [{"item_id": _id(n), "kind": "document", "source_path": f"C:/synthetic/{n}.pdf", "sha256": _id(n)} for n in names]
    with store.connect() as c:
        c.execute("INSERT OR IGNORE INTO workpackages(id, name, source_kind, created_at, updated_at) VALUES ('wp-1','synthetic','manual',?,?)",
                  (NOW, NOW))
        c.execute("INSERT INTO runs(run_id, workpackage_id, dedup_key, mode, assignment_revision, recipe_id, recipe_version, recipe_hash,"
                  " recipe, params, input, input_hash, status, approval, actor, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (run_id, "wp-1", run_id, "apply", 1, "processing", 1, "h", "{}", "{}", json.dumps({"items": items}), "h",
                   "needs_review", "approved" if approved else None, "t", NOW))
        for i in items:
            c.execute("INSERT INTO run_items(run_id, item_id, status, final_status, flow_run_id, updated_at) VALUES (?,?,?,?,?,?)",
                      (run_id, i["item_id"], "done", "done", work.flow_run_id(run_id, i["item_id"]), NOW))


def _save(name: str, fields: dict, *, run_id: str | None = None, doc_type: str = "invoice_hu", validation=None) -> str:
    doc = _id(name)
    flow = work.flow_run_id(run_id, doc) if run_id else f"cli-{name}"
    store.upsert_document(doc_id=doc, source_path=f"C:/synthetic/{name}.pdf", has_text=True, page_count=1, year=2026,
                          doc_type=doc_type, run_id=flow)
    store.insert_datapoints(run_id=flow, doc_id=doc, doc_type=doc_type, arm="G", datapoints=fields, field_conf={},
                            validation=validation or [], route="auto", review_reasons=[], final_status="done")
    return doc


def _save_statement(name: str, *lines, run_id: str | None = None, verified: bool = True) -> str:
    return _save(name, _statement(*lines), run_id=run_id, doc_type="statement_cib", validation=VERIFIED if verified else [])


def _in_run(fn):
    calls.set_budget("run-now", "jev", Decimal("0.01"))
    with calls.use_run(budget_scope="run-now"):
        return fn()


def _line_id(statement: str, line: dict | None = None) -> str:
    return reconcile.with_line_ids(statement, [line or _line()])[0]["id"]


# --- the pure core: a person's decision settles the pair -----------------------------------------------------------


def _with(case_id: str, *decisions):
    snap = copy.deepcopy(CASES[case_id]["snapshot"])
    snap["decisions"] = [{"invoice_id": i, "line_id": t, "decision": d} for i, t, d in decisions]
    return reconcile.propose(snap)


def _status(result):
    return {s["invoice_id"]: s["status"] for s in result["invoices"]}


def test_a_rejected_pair_is_never_proposed_and_the_other_one_is_no_longer_ambiguous():
    result = _with("ambiguous", ("i1", "t1", "not_this"))
    assert [[c["line_id"], c["invoice_id"], c["proposed"], c["multiple_candidates"]] for c in result["candidates"]] == [["t1", "i2", True, False]]
    assert _status(result) == {"i1": "no_payment_found", "i2": "proposed"}


def test_a_confirmed_pair_takes_the_line_and_the_invoice_out_of_every_other_proposal():
    result = _with("ambiguous", ("i2", "t1", "paid_by"))
    assert result["candidates"] == []
    assert _status(result) == {"i1": "no_payment_found", "i2": "confirmed"}
    assert result["confirmed"] == [{"invoice_id": "i2", "line_id": "t1", "statement_id": "s1"}]
    assert result["unpaired_line_ids"] == []


def test_a_decision_on_a_line_that_is_gone_changes_nothing():
    result = _with("one_payment", ("i1", "t9", "paid_by"), ("i1", "t8", "not_this"))
    assert _status(result) == {"i1": "proposed"} and result["confirmed"] == []


def test_the_golden_set_has_decision_cases():
    assert {"decision_rejects_one_of_two", "decision_confirms_pair", "decision_on_a_missing_line"} <= set(CASES)
    for case_id in ("decision_rejects_one_of_two", "decision_confirms_pair", "decision_on_a_missing_line"):
        assert reconcile.check_case(CASES[case_id]) == []


def test_the_to_do_names_the_invoice_and_the_line():
    code = reconcile.reason(_id("inv"), "0123456789abcdef:0a1b2c3d4e5f:0")
    assert code == f"reconcile:proposed:{_id('inv')[:16]}:0123456789abcdef:0a1b2c3d4e5f:0"
    assert reconcile.parse_reason(code) == (_id("inv")[:16], "0123456789abcdef:0a1b2c3d4e5f:0")
    assert reconcile.parse_reason("duplicate:copy:0123456789abcdef") is None
    assert reconcile.parse_reason("reconcile:proposed:abc") is None


# --- the store: only in a worker run, on the later processed document ----------------------------------------------


def test_outside_a_worker_run_the_store_is_not_read(db):
    _save("inv", _invoice())
    assert reconcile.review_reasons(_id("stmt"), "statement_cib", _statement(), VERIFIED) == []


def test_a_statement_processed_after_the_invoice_gets_the_to_do(db):
    inv = _save("inv", _invoice())
    stmt = _id("stmt")
    reasons = _in_run(lambda: reconcile.review_reasons(stmt, "statement_cib", _statement(), VERIFIED))
    assert reasons == [reconcile.reason(inv, _line_id(stmt))]


def test_an_invoice_processed_after_the_statement_gets_the_to_do(db):
    stmt = _save_statement("stmt")
    inv = _id("inv")
    assert _in_run(lambda: reconcile.review_reasons(inv, "invoice_hu", _invoice(), [])) == [reconcile.reason(inv, _line_id(stmt))]
    assert _in_run(lambda: reconcile.review_reasons(inv, "nav_receipt", _invoice(), [])) == []  # not a payable type


def test_the_current_values_replace_the_documents_stored_ones(db):
    _save_statement("stmt")
    inv = _save("inv", _invoice(amount="999.00"))  # an earlier, misread result of the same document
    assert _in_run(lambda: reconcile.review_reasons(inv, "invoice_hu", _invoice(), [])) != []


def test_the_policy_step_opens_the_to_do_on_a_statement(db):
    inv = _save("inv", _invoice())
    stmt = _id("stmt")
    values = _statement()
    state = FlowState(source_path="synthetic.pdf", case_id="synthetic", arm="G", doc_type="statement_cib", doc_id=stmt)
    state.invoice = InvoiceHU(currency="HUF", extra={k: v for k, v in values.items() if k != "currency"})
    state.validation = [CheckResult(**v) for v in VERIFIED]
    policy.apply_reconcile_policy(state)
    assert state.review_reasons == []  # outside a worker run
    _in_run(lambda: policy.apply_reconcile_policy(state))
    assert state.review_reasons == [reconcile.reason(inv, _line_id(stmt))] and state.needs_review


# --- the person's decision ------------------------------------------------------------------------------------------


def _pair_in_run(*, approved=False, extra=()):
    _run(RUN, ["inv", "stmt", *extra], approved=approved)
    inv = _save("inv", _invoice(), run_id=RUN)
    stmt = _save_statement("stmt", run_id=RUN)
    line = _line_id(stmt)
    store.review_enqueue(subject_kind="document", subject_id=stmt, run_id=work.flow_run_id(RUN, stmt),
                         reasons=[reconcile.reason(inv, line)], producer="m2:G")
    return inv, stmt, line


def test_a_confirmation_closes_the_pair_and_is_part_of_the_reviewed_result(db):
    inv, stmt, line = _pair_in_run()
    before = corrections.review_version(RUN)
    d = reconcile.decide(RUN, stmt, inv, line, decision="paid_by", actor="reviewer")
    assert (d["invoice_doc_id"], d["statement_doc_id"], d["line_id"], d["decision"], d["actor"]) == (inv, stmt, line, "paid_by", "reviewer")
    assert json.loads(d["signals"]) == ["invoice_number", "supplier_account", "supplier_name"] and d["amount_relation"] == "equal"
    assert store.review_open_reasons("document", stmt) == []
    assert corrections.review_version(RUN) != before
    changed = corrections.review_version(RUN)
    reconcile.decide(RUN, inv, inv, line, decision="not_this", actor="other", note="paid in cash")  # from the invoice side
    assert corrections.review_version(RUN) != changed
    assert _in_run(lambda: reconcile.review_reasons(stmt, "statement_cib", _statement(), VERIFIED)) == []  # never again


def test_a_rejection_needs_a_reason_and_a_decision_needs_the_pair(db):
    inv, stmt, line = _pair_in_run(extra=["other"])
    with pytest.raises(reconcile.DecisionError):
        reconcile.decide(RUN, stmt, inv, line, decision="not_this", actor="t", note="  ")
    with pytest.raises(reconcile.DecisionError):
        reconcile.decide(RUN, stmt, inv, line, decision="maybe", actor="t")
    other = _save("other", _invoice(number="INV-0002"), run_id=RUN)
    with pytest.raises(reconcile.DecisionError):
        reconcile.decide(RUN, other, inv, line, decision="paid_by", actor="t")  # the item is neither side of the pair
    with pytest.raises(KeyError):
        reconcile.decide(RUN, stmt, inv, f"{stmt[:16]}:000000000000:0", decision="paid_by", actor="t")  # no such line
    with pytest.raises(KeyError):
        reconcile.decide(RUN, _id("not-in-run"), inv, line, decision="paid_by", actor="t")


def test_one_line_pays_one_invoice(db):
    inv, stmt, line = _pair_in_run()
    other = _save("other", _invoice(number="INV-0002"), run_id=RUN)
    reconcile.decide(RUN, stmt, inv, line, decision="paid_by", actor="t")
    with pytest.raises(reconcile.DecisionError):
        reconcile.decide(RUN, stmt, other, line, decision="paid_by", actor="t")
    reconcile.decide(RUN, stmt, other, line, decision="not_this", actor="t", note="another invoice")  # a rejection is fine


def test_a_confirmation_closes_the_other_proposals_of_its_line(db):
    inv, stmt, line = _pair_in_run(extra=["other"])
    other = _save("other", _invoice(number="INV-0002"), run_id=RUN)  # an equal invoice of the same supplier: ambiguous
    store.review_enqueue(subject_kind="document", subject_id=stmt, run_id=work.flow_run_id(RUN, stmt),
                         reasons=[reconcile.reason(inv, line), reconcile.reason(other, line)], producer="m2:G")  # the run's whole list
    assert len(store.review_open_reasons("document", stmt)) == 2
    reconcile.decide(RUN, stmt, inv, line, decision="paid_by", actor="t")
    assert store.review_open_reasons("document", stmt) == []  # one line pays one invoice
    assert _in_run(lambda: reconcile.review_reasons(other, "invoice_hu", _invoice(number="INV-0002"), [])) == []


def test_decisions_are_frozen_on_an_approved_run(db):
    inv, stmt, line = _pair_in_run(approved=True)
    with pytest.raises(work.RevisionConflict):
        reconcile.decide(RUN, stmt, inv, line, decision="paid_by", actor="t")


def test_a_run_without_reconcile_decisions_keeps_its_review_version(db):
    _pair_in_run()
    assert corrections.review_version(RUN) == hashlib.sha256(json.dumps([]).encode("utf-8")).hexdigest()[:16]


# --- what a person sees ----------------------------------------------------------------------------------------------


def test_the_review_page_shows_the_line_and_the_invoice_side_by_side(db):
    inv, stmt, line = _pair_in_run()
    reasons = store.review_open_reasons("document", stmt)
    [pair] = reconcile.item_pairs(stmt, reasons)
    assert (pair["invoice_doc_id"], pair["statement_doc_id"], pair["line_id"], pair["side"]) == (inv, stmt, line, "statement")
    assert (pair["invoice"]["number"], pair["invoice"]["amount"], pair["invoice"]["file"]) == ("INV-0001", "100.00", "inv.pdf")
    assert (pair["line"]["booking_date"], pair["line"]["amount"], pair["line"]["memo"], pair["line"]["file"]) == ("2026-04-10", "100.00", "INV-0001", "stmt.pdf")
    assert pair["signals"] == ["invoice_number", "supplier_account", "supplier_name"] and pair["amount_relation"] == "equal"
    assert pair["reason_id"] == reasons[0]["id"] and pair["decision"] is None and not pair["source_review_required"]
    assert (pair["other_run_id"], pair["other_item_id"], pair["other_workpackage_id"]) == (RUN, inv, "wp-1")
    reconcile.decide(RUN, stmt, inv, line, decision="paid_by", actor="reviewer")
    [pair] = reconcile.item_pairs(inv, [])  # the invoice side shows the decision too
    assert (pair["side"], pair["decision"], pair["decided_by"], pair["reason_id"]) == ("invoice", "paid_by", "reviewer", None)


def test_an_unverified_statement_asks_for_its_source_to_be_checked(db):
    _run(RUN, ["inv", "stmt"])
    inv = _save("inv", _invoice(), run_id=RUN)
    stmt = _save_statement("stmt", run_id=RUN, verified=False)
    [pair] = reconcile.item_pairs(stmt, [{"id": 1, "reason": reconcile.reason(inv, _line_id(stmt))}])
    assert pair["source_review_required"]


def test_the_run_dataset_lists_the_invoices_and_the_lines(db):
    inv, stmt, line = _pair_in_run()
    assert "reconciliation" in work_views.result_tables(RUN)
    cols, rows = datasets.rows("reconciliation", {"run_id": RUN})
    by_kind = {r["kind"]: r for r in rows}
    assert {c.key for c in cols} >= {"kind", "file", "status", "date", "amount", "currency", "partner", "number", "paired_file", "signal_invoice_number", "decision"}
    assert (by_kind["invoice"]["status"], by_kind["invoice"]["paired_file"], by_kind["invoice"]["number"]) == ("proposed", "stmt.pdf", "INV-0001")
    assert (by_kind["line"]["status"], by_kind["line"]["paired_file"], by_kind["line"]["amount"]) == ("proposed", "inv.pdf", "100.00")
    assert (by_kind["line"]["signal_invoice_number"], by_kind["line"]["signal_supplier_account"]) == (True, True)
    reconcile.decide(RUN, stmt, inv, line, decision="paid_by", actor="t")
    _cols, rows = datasets.rows("reconciliation", {"run_id": RUN})
    assert {r["kind"]: (r["status"], r["decision"]) for r in rows} == {"invoice": ("confirmed", "paid_by"), "line": ("confirmed", "paid_by")}


def test_a_run_without_statements_or_matches_has_no_reconciliation_view(db):
    _run(RUN, ["inv"])
    _save("inv", _invoice(), run_id=RUN)
    assert "reconciliation" not in work_views.result_tables(RUN)


# --- the pairs already in the store ----------------------------------------------------------------------------------


def test_scan_opens_the_to_do_once_on_the_later_document_of_a_run_not_yet_approved(db):
    _run(RUN, ["inv", "stmt"])
    inv = _save("inv", _invoice(), run_id=RUN)
    stmt = _save_statement("stmt", run_id=RUN)
    _save("cli-inv", _invoice(number="INV-0007", amount="7.00"))  # from the command line: no work run to show it in
    _save_statement("cli-stmt", _line(memo="INV-0007", amount="7.00"))
    dry = reconcile.scan()
    assert (dry["proposed_pairs"], dry["to_open"], dry["written"], dry["skipped"]) == (2, 1, 0, {"no_work_run": 1})
    wrote = reconcile.scan(write=True)
    assert wrote["written"] == 1
    [reason] = store.review_open_reasons("document", stmt)
    assert reason["reason"] == reconcile.reason(inv, _line_id(stmt)) and reason["run_id"] == work.flow_run_id(RUN, stmt)
    again = reconcile.scan(write=True)
    assert (again["to_open"], again["written"], again["skipped"]) == (0, 0, {"already_open": 1, "no_work_run": 1})
    reconcile.decide(RUN, stmt, inv, _line_id(stmt), decision="not_this", actor="t", note="refund")
    assert reconcile.scan(write=True)["skipped"] == {"no_work_run": 1}  # a rejected pair is no longer a proposal


# --- end to end: the service records the decision ------------------------------------------------------------------


def test_the_service_shows_the_pair_and_records_the_decision(env):
    from tests.test_api import HUMAN

    c = env["client"]
    inv, stmt, line = _pair_in_run()
    view = c.get(f"/api/runs/{RUN}/items/{stmt}").json()
    [pair] = view["reconcile"]
    assert pair["invoice_doc_id"] == inv and pair["line_id"] == line and pair["decision"] is None
    url = f"/api/runs/{RUN}/items/{stmt}/reconcile/decision"
    bad = c.post(url, headers=HUMAN, json={"invoice_doc_id": inv, "line_id": line, "decision": "not_this"})
    assert bad.status_code == 422  # a rejection needs a reason
    r = c.post(url, headers=HUMAN, json={"invoice_doc_id": inv, "line_id": line, "decision": "paid_by"})
    assert r.status_code == 200, r.text
    assert r.json()["reconcile"][0]["decision"] == "paid_by"
    assert not [x for x in r.json()["open_reasons"] if x["reason"].startswith("reconcile:")]
    assert c.post(url, headers=HUMAN, json={"invoice_doc_id": inv, "line_id": "x", "decision": "paid_by"}).status_code == 422
