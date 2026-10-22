"""139 (DECISIONS 139): the valid statement in the store and in a reconciliation package.

An unchecked statement and a later code-read, checked one of the same account and period: the reconciliation sees the
second only, a pair made on a line of the first stands on the same line of the second and can still be revoked; when
the second lacks a line of the first, the pair is a conflict until a person lets the first go (154), and a mark on the
missing line is then left over (listed with a blocker, revocable); a person's choice keeps the first again. Synthetic documents and made-up accounts only; no AI call."""

from __future__ import annotations

import pytest

from jav import checks, corrections, reconcile, reconcile_package as rp, statement_months as sm, store, work, work_runs
from tests import test_reconcile_k2_129 as k2
from tests.test_reconcile_package_131 import OWN_KEY, _ids, _line, _line_row, _package, _stmt


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield


FEE = _line(amount="50.00", day="2026-04-20", memo="Fee", counterparty_name="Bank", counterparty_account=None)


def _checked(name: str, *lines) -> str:
    """The same account's statement read by code from the bank's export, checked by its balances."""
    values = {**k2._statement(*lines), "account_no": k2.OWN}
    return k2._save(name, values, doc_type="statement_table", validation=k2.VERIFIED)


def _choose(a: str, b: str, keep: str | None) -> None:
    with store.connect() as c:
        c.execute("INSERT INTO statement_choices(pair_key, keep_doc_id, actor, decided_at) VALUES (?,?,?,?)",
                  (sm.pair_key(a, b), keep, "reviewer", "2026-10-10T00:00:00+00:00"))


def test_the_better_statement_replaces_the_old_and_takes_its_decisions(db):
    inv = k2._save("inv", k2._invoice())
    old = _stmt("old", _line(), FEE, verified=False)
    old_pay, old_fee = _ids(old, _line(), FEE)
    wp_id = _package()
    [alloc] = rp.allocate(wp_id, [{"invoice_doc_id": inv, "line_id": old_pay}], note=None, actor="reviewer")
    [mark] = rp.mark(wp_id, [old_fee], category="fee", note=None, actor="reviewer")

    new = _checked("new", _line(memo="INV-0001 ref"))  # the same payment, its memo printed longer; no fee line
    [new_pay] = _ids(new, _line(memo="INV-0001 ref"))
    snap = reconcile.snapshot()  # 154: the rule does not drop the fee line, a person decides
    assert sorted(s["id"] for s in snap["statements"]) == sorted([old, new]) and snap["conflicts"] == [sorted([old, new])]
    _choose(old, new, new)
    snap = reconcile.snapshot()
    assert [s["id"] for s in snap["statements"]] == [new]
    assert snap["replaced"][old]["by"] == new and snap["replaced"][old]["how"] == "person"
    assert snap["line_map"] == {old_pay: new_pay}

    ws = rp.workspace(wp_id)
    line = _line_row(ws, new_pay)
    assert line["state"] == "allocated" and line["allocations"][0]["allocation_id"] == alloc["id"]
    [left] = ws["left_over"]
    assert (left["kind"], left["ref"], left["line_id"], left["replaced_by"], left["category"]) == ("mark", str(mark["id"]), old_fee, new, "fee")
    assert left["amount"] == "50.00" and left["file"] == "old.pdf" and left["replaced_by_file"] == "new.pdf"
    assert {"code": "decision_not_carried", "doc_id": old, "file": "old.pdf", "kind": "statement"} in ws["blockers"]

    rp.revoke(wp_id, kind="mark", ref=str(mark["id"]), actor="reviewer")  # the left-over mark
    rp.revoke(wp_id, kind="allocation", ref=str(alloc["id"]), actor="reviewer")  # the carried allocation
    ws = rp.workspace(wp_id)
    assert ws["left_over"] == [] and _line_row(ws, new_pay)["state"] == "proposed"


def test_a_persons_choice_keeps_the_old_statement_and_its_decisions(db):
    inv = k2._save("inv", k2._invoice())
    old = _stmt("old", _line(), verified=False)
    [old_pay] = _ids(old, _line())
    wp_id = _package()
    rp.allocate(wp_id, [{"invoice_doc_id": inv, "line_id": old_pay}], note=None, actor="reviewer")
    new = _checked("new", _line())
    _choose(old, new, old)
    snap = reconcile.snapshot()
    assert [s["id"] for s in snap["statements"]] == [old] and snap["replaced"][new]["how"] == "person"
    assert _line_row(rp.workspace(wp_id), old_pay)["state"] == "allocated"
    _choose(old, new, None)  # back to the rule
    assert [s["id"] for s in reconcile.snapshot()["statements"]] == [new]


def test_two_checked_statements_of_the_same_rank_both_stay_as_a_conflict(db):
    a = _checked("a", _line())
    b = _checked("b", _line(), FEE)
    snap = reconcile.snapshot()
    assert sorted(s["id"] for s in snap["statements"]) == sorted([a, b])
    assert snap["conflicts"] == [sorted([a, b])] and snap["replaced"] == {}


def test_the_month_view_counts_the_valid_statement_and_names_the_replaced(db):
    from datetime import date

    from jav import parties, party_views

    party = parties.create("Example Home", identities=[("account", OWN_KEY, k2.OWN)], actor="t")
    old = _stmt("old", _line(), verified=False)
    _checked("new", _line())
    view = party_views.months(party["id"], "2026-04", "2026-04", today=date(2026, 10, 10))
    [col] = view["columns"]
    [cell] = col["months"]
    assert cell["statements"] == 1 and cell["state"] != "unverified" and cell["flags"] == []
    assert cell["replaced"] == [old]


# --- an undecided pair: a to-do in a worker run, a person's choice ------------------------------------------------


def _pair_in_run(*, approved: bool = False) -> tuple[str, str]:
    k2._run(k2.RUN, ["a", "b"], approved=approved)
    a = k2._save("a", {**k2._statement(_line()), "account_no": k2.OWN}, run_id=k2.RUN, doc_type="statement_table",
                 validation=k2.VERIFIED)
    b = k2._save("b", {**k2._statement(_line(), FEE), "account_no": k2.OWN}, run_id=k2.RUN, doc_type="statement_table",
                 validation=k2.VERIFIED)
    store.review_enqueue(subject_kind="document", subject_id=b, run_id=work_runs.flow_run_id(k2.RUN, b), reasons=[sm.reason(a)],
                         producer="statement_table")
    return a, b


def test_an_undecided_overlap_is_a_todo_in_a_worker_run_only(db):
    a, b = _pair_in_run()
    current = sm.current(b, "statement_table", {**k2._statement(_line(), FEE), "account_no": k2.OWN}, k2.VERIFIED)
    assert checks.get("statement_overlap").reads_store and not checks.store_readable()  # outside a worker run (175)
    assert k2._in_run(lambda: sm.review_reasons(current)) == [f"statement:overlap:{a[:16]}"]
    assert sm.parse_reason(sm.reason(a)) == a[:16] and sm.parse_reason("duplicate:copy:abc") is None
    [view] = sm.item_view(b, store.review_open_reasons("document", b))
    assert (view["relation"], view["other_doc_id"], view["other_file"], view["rank"], view["other_rank"]) == (
        "conflict", a, "a.pdf", "code_checked", "code_checked")
    assert view["reason_id"] is not None and view["other_workpackage_id"] == "wp-1" and view["kept"] is None


def test_a_persons_choice_closes_the_todos_is_reviewed_and_frozen_after_approval(db):
    a, b = _pair_in_run()
    before = corrections.review_version(k2.RUN)
    row = sm.decide(k2.RUN, b, a, keep=a, actor="reviewer", note="the export is complete")
    assert (row["keep_doc_id"], row["actor"]) == (a, "reviewer")
    assert store.review_open_reasons("document", b) == []
    assert corrections.review_version(k2.RUN) != before
    assert [s["id"] for s in reconcile.snapshot()["statements"]] == [a]
    [view] = sm.item_view(b, [])
    assert (view["relation"], view["how"], view["kept"], view["carried"], view["left_over"]) == ("replaced_by", "person", a, 1, 1)
    assert k2._in_run(lambda: sm.review_reasons(sm.current(b, "statement_table", {**k2._statement(_line(), FEE),
                                                                                    "account_no": k2.OWN}, k2.VERIFIED))) == []
    sm.decide(k2.RUN, a, b, keep=None, actor="reviewer")  # back to the rule: a conflict again
    assert sorted(s["id"] for s in reconcile.snapshot()["statements"]) == sorted([a, b])
    with pytest.raises(sm.ChoiceError):
        sm.decide(k2.RUN, a, b, keep="somebody-else", actor="t")
    with pytest.raises(sm.ChoiceError):
        sm.decide(k2.RUN, a, a, keep=a, actor="t")
    with store.connect() as c:
        c.execute("UPDATE runs SET approval='approved' WHERE run_id=?", (k2.RUN,))
    with pytest.raises(work.RevisionConflict):
        sm.decide(k2.RUN, b, a, keep=a, actor="t")


def test_statements_of_different_days_cannot_be_chosen_between(db):
    k2._run(k2.RUN, ["a", "b"])
    a = _checked("a", _line())
    values = {**k2._statement(_line(day="2026-08-10")), "account_no": k2.OWN, "period_start": "2026-07-01", "period_end": "2026-08-31"}
    b = k2._save("b", values, run_id=k2.RUN, doc_type="statement_table", validation=k2.VERIFIED)
    with pytest.raises(sm.ChoiceError):
        sm.decide(k2.RUN, b, a, keep=a, actor="t")


def test_the_policy_step_opens_the_todo_for_an_extracted_statement(db):
    from jav import policy, typepack
    from jav.models import CheckResult, FlowState

    k2._save_statement("earlier", _line())  # an extracted CIB statement, checked
    values = {**k2._statement(_line(), FEE), "account_no": k2.OWN}
    record, _reasons = typepack.get("statement_cib").normalize(values)
    state = FlowState(source_path="synthetic.pdf", case_id="synthetic", arm="G", doc_type="statement_cib", doc_id=k2._id("now"))
    state.record = record
    state.validation = [CheckResult(**v) for v in k2.VERIFIED]
    policy.apply_cross_document_checks(state)
    assert state.review_reasons == []  # outside a worker run
    k2._in_run(lambda: policy.apply_cross_document_checks(state))
    assert state.review_reasons == [f"statement:overlap:{k2._id('earlier')[:16]}"] and state.needs_review
