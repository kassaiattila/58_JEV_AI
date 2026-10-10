"""129 (backlog F-reconciliation, K2): a person decides on a proposed invoice <-> statement line pair.

The owner's decisions of 2026-10-08 (DECISIONS 128, 129): the code proposes, a person confirms ("this line paid it") or
rejects with a reason ("not this one"); the decision belongs to the pair and a rejected pair never comes up again.

137 (DECISIONS 137): the reconciliation package (131) does this work, so the processing no longer opens a to-do for a
pair on the documents, and the review page's panel, its service route, the run's reconciliation view and the command
line's `--write` are gone. The decisions made through the panel stay in the store: the core still honours them and they
stay part of the reviewed result of their run. The helpers here are shared by the later reconciliation tests.
Synthetic documents and made-up accounts only; no AI call.
"""

from __future__ import annotations

import copy
import hashlib
import json
from decimal import Decimal

import pytest

from jav import cli, corrections, datasets, policy, reconcile, store, work, work_views
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
    assert result["confirmed"] == [{"invoice_id": "i2", "line_id": "t1", "statement_id": "s1",
                                    "line_amount": "100.00", "invoice_amount": "100.00"}]  # 131: as a whole-amount allocation
    assert result["unpaired_line_ids"] == []


def test_a_decision_on_a_line_that_is_gone_changes_nothing():
    result = _with("one_payment", ("i1", "t9", "paid_by"), ("i1", "t8", "not_this"))
    assert _status(result) == {"i1": "proposed"} and result["confirmed"] == []


def test_the_golden_set_has_decision_cases():
    assert {"decision_rejects_one_of_two", "decision_confirms_pair", "decision_on_a_missing_line"} <= set(CASES)
    for case_id in ("decision_rejects_one_of_two", "decision_confirms_pair", "decision_on_a_missing_line"):
        assert reconcile.check_case(CASES[case_id]) == []


# --- shared helpers for the store ------------------------------------------------------------------------------------


def _pair_in_run(*, approved=False, extra=()):
    """An invoice and a statement of one run whose line pays it (the golden "one payment" shape)."""
    _run(RUN, ["inv", "stmt", *extra], approved=approved)
    inv = _save("inv", _invoice(), run_id=RUN)
    stmt = _save_statement("stmt", run_id=RUN)
    return inv, stmt, _line_id(stmt)


def _decide(invoice: str, statement: str, line: str, decision: str = "paid_by", *, run_id: str | None = None,
            note: str | None = None) -> None:
    """A decision row as the review page's panel wrote it from 129 to 136; the store keeps such rows."""
    with store.connect() as c:
        c.execute("INSERT INTO reconcile_decisions(pair_key, invoice_doc_id, statement_doc_id, line_id, decision, signals,"
                  " amount_relation, run_id, actor, note, decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (reconcile.pair_key(invoice, line), invoice, statement, line, decision, "[]", "equal", run_id,
                   "reviewer", note, NOW))


# --- 137: the reconciliation lives in its package only --------------------------------------------------------------


def test_the_processing_opens_no_reconciliation_to_do(db):
    _save("inv", _invoice())
    stmt = _id("stmt")
    values = _statement()
    state = FlowState(source_path="synthetic.pdf", case_id="synthetic", arm="G", doc_type="statement_cib", doc_id=stmt)
    state.invoice = InvoiceHU(currency="HUF", extra={k: v for k, v in values.items() if k != "currency"})
    state.validation = [CheckResult(**v) for v in VERIFIED]
    _in_run(lambda: policy.decide(state))
    assert not [r for r in state.review_reasons if r.startswith("reconcile:")]
    assert not hasattr(policy, "apply_reconcile_policy") and not hasattr(reconcile, "review_reasons")


def test_an_earlier_decision_still_settles_the_pair_and_stays_in_the_reviewed_version(db):
    inv, stmt, line = _pair_in_run()
    before = corrections.review_version(RUN)
    assert before == hashlib.sha256(json.dumps([]).encode("utf-8")).hexdigest()[:16]  # no decision: the plain version
    _decide(inv, stmt, line, run_id=RUN)
    result = reconcile.propose(reconcile.snapshot())
    assert _status(result) == {inv: "confirmed"} and result["candidates"] == []
    assert corrections.review_version(RUN) != before  # an approved run's version is the same as before 137


def test_a_run_has_no_reconciliation_view(db):
    _pair_in_run()
    assert "reconciliation" not in work_views.result_tables(RUN)
    with pytest.raises(datasets.UnknownDataset):
        datasets.rows("reconciliation", {"run_id": RUN})


def test_the_command_line_only_counts(db, capsys):
    _pair_in_run()
    summary = reconcile.scan()
    assert summary["proposed_pairs"] == 1 and not {"to_open", "written", "skipped"} & set(summary)
    with pytest.raises(TypeError):
        reconcile.scan(write=True)  # type: ignore[call-arg]
    with pytest.raises(SystemExit):
        cli.main(["reconcile", "--write"])
    capsys.readouterr()


def test_the_review_page_shows_no_pairs_and_the_route_is_gone(env):
    from tests.test_api import HUMAN

    c = env["client"]
    inv, stmt, line = _pair_in_run()
    _decide(inv, stmt, line, run_id=RUN)
    view = c.get(f"/api/runs/{RUN}/items/{stmt}").json()
    assert "reconcile" not in view and view["item_id"] == stmt
    r = c.post(f"/api/runs/{RUN}/items/{stmt}/reconcile/decision", headers=HUMAN,
               json={"invoice_doc_id": inv, "line_id": line, "decision": "paid_by"})
    assert r.status_code in (404, 405)
