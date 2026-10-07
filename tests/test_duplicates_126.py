"""126 (backlog F-duplicate): the same invoice twice in the store, found by code from the extracted and corrected data.

The owner's decisions of 2026-10-07 (DECISIONS 124, 126): a to-do on the later processed document, compared with every
earlier document in the store; a confirmed copy stays, marked, and counts once; every invoice-like document, a pro forma
invoice never being a copy of a final invoice; the pairs already in the store get the same to-do once, on runs not yet
approved. Synthetic documents and made-up tax numbers only; no AI call.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal

import pytest

from jav import corrections, duplicates, export, policy, report_utility, store, work
from jav.models import FlowState, InvoiceHU
from jav.runtime import calls
from tests import test_api

env = test_api.env

A, A_EU, B = "12121216-2-42", "HU12121216", "13570008-1-13"  # made up (data guard allow list)
NOW = "2026-10-07T10:00:00+00:00"


def _id(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()


def _inv(number="INV-2026/001", tax=A, name="Example Trading Ltd", date="2026-09-01", gross="1270.00", currency="HUF"):
    return {"invoice_number": number, "supplier_tax_id": tax, "supplier_name": name, "issue_date": date,
            "gross_total": gross, "currency": currency}


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "w.sqlite"):
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


def _save(name: str, fields: dict, *, run_id: str | None = None, doc_type: str = "invoice_hu") -> str:
    doc = _id(name)
    flow = work.flow_run_id(run_id, doc) if run_id else f"cli-{name}"
    store.upsert_document(doc_id=doc, source_path=f"C:/synthetic/{name}.pdf", has_text=True, page_count=1, year=2026,
                          doc_type=doc_type, run_id=flow)
    store.insert_datapoints(run_id=flow, doc_id=doc, doc_type=doc_type, arm="S", datapoints=fields, field_conf={},
                            validation=[], route="auto", review_reasons=[], final_status="done")
    return doc


def _in_run(fn):
    calls.set_budget("run-now", "jev", Decimal("0.01"))
    with calls.use_run(budget_scope="run-now"):
        return fn()


# --- the key and the kind ------------------------------------------------------------------------------------


def test_the_invoice_number_compares_by_its_letters_and_digits():
    assert duplicates.number_key("INV-2026/001") == duplicates.number_key("inv 2026 001") == "INV2026001"
    assert duplicates.number_key("N/A") is None and duplicates.number_key("") is None and duplicates.number_key(None) is None


def test_a_copy_matches_on_date_amount_and_currency():
    kind, differing, missing = duplicates.classify(_inv(gross="1270"), _inv(gross="1270.00", currency="huf"))
    assert (kind, differing, missing) == ("copy", (), ())


def test_a_variant_names_the_differing_fields():
    assert duplicates.classify(_inv(), _inv(date="2026-09-02", gross="1300.00")) == ("variant", ("issue_date", "gross_total"), ())


def test_a_missing_compared_field_is_undecidable_unless_another_differs():
    assert duplicates.classify(_inv(), _inv(date=None)) == ("undecidable", (), ("issue_date",))
    assert duplicates.classify(_inv(gross="1"), _inv(date=None)) == ("variant", ("gross_total",), ("issue_date",))


def test_the_supplier_is_the_same_by_tax_number_else_by_name():
    assert duplicates.same_supplier(_inv(tax=A), _inv(tax=A_EU))  # the domestic and the EU form of one number
    assert not duplicates.same_supplier(_inv(tax=A), _inv(tax=B))
    assert duplicates.same_supplier(_inv(tax=None), _inv(tax=A, name="EXAMPLE TRADING LIMITED"))
    assert not duplicates.same_supplier(_inv(tax=None, name=None), _inv(tax=None, name=None))


def _doc(name, fields, doc_type="invoice_hu", seq=0):
    return duplicates.Document(_id(name), doc_type, fields, seq=seq)


@pytest.mark.parametrize("other,doc_type", [
    (_inv(tax=B, name="Other Supplier Ltd"), "invoice_hu"),  # the same number from another supplier
    (_inv(number="INV-2026/002"), "invoice_hu"),            # the same amount and date, another number
    (_inv(number="CN-2026/001", gross="-1270.00"), "invoice_hu"),  # a credit note under its own number
    (_inv(), "proforma_invoice"),                            # a pro forma invoice is never a copy of a final one
    (_inv(), "nav_receipt"),                                 # not an invoice-like type
])
def test_counter_examples_are_not_the_same_invoice(other, doc_type):
    assert duplicates.matches(_doc("now", _inv()), [_doc("earlier", other, doc_type)]) == []


def test_two_pro_forma_invoices_can_be_copies_and_types_of_one_family_match():
    pro = duplicates.matches(_doc("now", _inv(), "proforma_invoice"), [_doc("earlier", _inv(), "proforma_invoice")])
    assert [m.kind for m in pro] == ["copy"]
    utility = duplicates.matches(_doc("now", _inv(), "viz_szamla"), [_doc("earlier", _inv(), "invoice_hu")])
    assert [m.kind for m in utility] == ["copy"]  # one document read as two types of the family


def test_the_to_do_names_the_kind_and_the_other_document():
    [m] = duplicates.matches(_doc("now", _inv()), [_doc("earlier", _inv(gross="9"))])
    assert m.reason == f"duplicate:variant:{_id('earlier')[:16]}"
    assert duplicates.parse_reason(m.reason) == ("variant", _id("earlier")[:16])
    assert duplicates.parse_reason("pick:low_conf:invoice_number:0.5") is None


def test_every_family_type_is_a_type_pack():
    from jav import typepack

    for t in duplicates.family_types():
        assert typepack.get(t).key == t


# --- the store: only in a worker run, effective values, decided pairs --------------------------------------------


def test_outside_a_worker_run_the_store_is_not_read(db):
    _save("earlier", _inv())
    assert duplicates.review_reasons(_id("now"), "invoice_hu", _inv()) == []


def test_in_a_worker_run_an_earlier_copy_opens_a_to_do(db):
    _save("earlier", _inv())
    _save("now", _inv())  # the document's own earlier result never counts
    reasons = _in_run(lambda: duplicates.review_reasons(_id("now"), "invoice_hu", _inv()))
    assert reasons == [f"duplicate:copy:{_id('earlier')[:16]}"]


def test_the_latest_result_of_an_earlier_document_counts(db):
    _save("earlier", _inv())
    _save("earlier", {"issue_date": "2026-09-01"}, doc_type="nav_receipt")  # read again as another type: drops out
    assert _in_run(lambda: duplicates.review_reasons(_id("now"), "invoice_hu", _inv())) == []


def test_a_correction_of_an_earlier_document_is_its_value(db):
    _run("run-1", ["earlier"])
    _save("earlier", _inv(number="INV-2026/999"), run_id="run-1")  # misread number, corrected by a person
    assert _in_run(lambda: duplicates.review_reasons(_id("now"), "invoice_hu", _inv())) == []
    corrections.save("run-1", _id("earlier"), fields={"invoice_number": "INV-2026/001"}, expected_revision=0, actor="t")
    assert _in_run(lambda: duplicates.review_reasons(_id("now"), "invoice_hu", _inv())) == [f"duplicate:copy:{_id('earlier')[:16]}"]


def test_the_policy_step_opens_the_to_do_and_sends_the_document_to_a_person(db):
    _save("earlier", _inv())
    state = FlowState(source_path="synthetic.pdf", case_id="synthetic", arm="G", doc_type="invoice_hu", doc_id=_id("now"))
    state.invoice = InvoiceHU(invoice_number="INV-2026/001", supplier_tax_id=A, supplier_name="Example Trading Ltd",
                              issue_date="2026-09-01", gross_total=Decimal("1270.00"), currency="HUF")
    policy.apply_duplicate_policy(state)
    assert state.review_reasons == []  # outside a worker run
    _in_run(lambda: policy.apply_duplicate_policy(state))
    assert state.review_reasons == [f"duplicate:copy:{_id('earlier')[:16]}"] and state.needs_review


# --- the person's decision ---------------------------------------------------------------------------------------


def _pair_in_run(*, approved=False):
    _run("run-1", ["earlier", "now"], approved=approved)
    earlier = _save("earlier", _inv(), run_id="run-1")
    now = _save("now", _inv(date="2026-09-02"), run_id="run-1")
    store.review_enqueue(subject_kind="document", subject_id=now, run_id=work.flow_run_id("run-1", now),
                         reasons=[f"duplicate:variant:{earlier[:16]}"], producer="m2:S")
    return earlier, now


def test_a_decision_closes_the_pair_and_is_part_of_the_reviewed_result(db):
    earlier, now = _pair_in_run()
    before = corrections.review_version("run-1")
    d = duplicates.decide("run-1", now, earlier, decision="variant", actor="reviewer")
    assert (d["doc_id"], d["other_doc_id"], d["decision"], d["suggested"], d["actor"]) == (now, earlier, "variant", "variant", "reviewer")
    assert store.review_open_reasons("document", now) == []
    assert corrections.review_version("run-1") != before
    changed = corrections.review_version("run-1")
    duplicates.decide("run-1", now, earlier, decision="different", actor="reviewer")  # may change until approval
    assert corrections.review_version("run-1") != changed
    again = duplicates.decide("run-1", earlier, now, decision="copy", actor="other")  # changed from the other document
    assert (again["doc_id"], again["other_doc_id"], again["decision"]) == (now, earlier, "copy")  # the direction stays
    assert _in_run(lambda: duplicates.review_reasons(now, "invoice_hu", _inv(date="2026-09-02"))) == []  # never again


def test_a_run_without_duplicate_decisions_keeps_its_review_version(db):
    _pair_in_run()
    rows = []  # no corrections, no task decisions, no native items: the version of an empty correction list
    import hashlib as h

    assert corrections.review_version("run-1") == h.sha256(json.dumps(rows).encode("utf-8")).hexdigest()[:16]


def test_decisions_are_frozen_on_an_approved_run_and_checked(db):
    earlier, now = _pair_in_run(approved=True)
    with pytest.raises(work.RevisionConflict):
        duplicates.decide("run-1", now, earlier, decision="copy", actor="t")
    with store.connect() as c:
        c.execute("UPDATE runs SET approval=NULL WHERE run_id='run-1'")
    with pytest.raises(duplicates.DecisionError):
        duplicates.decide("run-1", now, earlier, decision="merge", actor="t")
    with pytest.raises(duplicates.DecisionError):
        duplicates.decide("run-1", now, now, decision="copy", actor="t")
    with pytest.raises(KeyError):
        duplicates.decide("run-1", _id("not-in-run"), earlier, decision="copy", actor="t")


# --- what a person sees: the pair side by side, the mark, the totals --------------------------------------------


def test_the_review_page_shows_both_documents_side_by_side(db):
    earlier, now = _pair_in_run()
    reasons = store.review_open_reasons("document", now)
    [pair] = duplicates.item_pairs(now, reasons)
    assert (pair["other_doc_id"], pair["other_file"], pair["kind"], pair["decision"]) == (earlier, "earlier.pdf", "variant", None)
    rows = {r["field"]: r for r in pair["fields"]}
    assert rows["issue_date"]["differs"] and (rows["issue_date"]["value"], rows["issue_date"]["other_value"]) == ("2026-09-02", "2026-09-01")
    assert not rows["gross_total"]["differs"] and pair["reason_id"] == reasons[0]["id"]
    duplicates.decide("run-1", now, earlier, decision="variant", actor="reviewer")
    [pair] = duplicates.item_pairs(now, [])
    assert (pair["decision"], pair["decided_by"], pair["reason_id"], pair["repeat"]) == ("variant", "reviewer", None, True)


def test_the_mark_is_a_suspicion_then_the_decision(db):
    earlier, now = _pair_in_run()
    code = f"duplicate:variant:{earlier[:16]}"
    assert duplicates.marks({now: [code], earlier: []}) == {
        now: {"status": "suspected", "kind": "variant", "other_doc_id": earlier, "other_file": "earlier.pdf", "different": []}}
    duplicates.decide("run-1", now, earlier, decision="copy", actor="t")
    assert duplicates.marks({now: [], earlier: []}) == {
        now: {"status": "copy", "other_doc_id": earlier, "other_file": "earlier.pdf", "different": []}}  # the original: no mark
    duplicates.decide("run-1", now, earlier, decision="different", actor="t")
    marks = duplicates.marks({now: [], earlier: []})
    assert marks == {now: {"different": [earlier]}, earlier: {"different": [now]}}


def _bill(item, amount="3266", **mark):
    fields = {"supplier_name": "MVM", "consumption_address": "1111 Budapest, Minta utca 11", "billing_period_start": "2026-01-01",
              "billing_period_end": "2026-01-31", "gross_total": amount, "invoice_number": "HU-123"}
    return {"item_id": item, "file": f"{item}.pdf", "doc_type": "mohu_szamla", "fields": fields, "pages": {"gross_total": 1},
            "corrected": [], "open_reasons": [], **({"duplicate": mark} if mark else {})}


def test_the_utility_report_counts_a_pair_once_until_a_person_says_they_differ():
    rep = report_utility.build([_bill("m1"), _bill("m2")])
    assert rep["grand_total"] == "3266.00" and [d["status"] for d in rep["duplicates"]] == ["suspected"]
    rep = report_utility.build([_bill("m1"), _bill("m2", status="copy", other_doc_id="m1", different=[])])
    assert rep["grand_total"] == "3266.00" and [d["status"] for d in rep["duplicates"]] == ["copy"]
    rep = report_utility.build([_bill("m1", different=["m2"]), _bill("m2", different=["m1"])])
    assert rep["grand_total"] == "6532.00" and rep["duplicates"] == []


def test_another_supplier_with_the_same_number_counts_separately_in_the_report():
    other = _bill("m2")
    other["fields"]["supplier_name"] = "Another Utility Company"
    assert report_utility.build([_bill("m1"), other])["grand_total"] == "6532.00"


def test_the_documents_table_shows_the_mark():
    record = {"item_id": "x", "file": "x.pdf", "doc_type": "invoice_hu", "arm": "S", "final_status": "done", "fields": {},
              "open_reasons": [], "duplicate": {"status": "copy", "other_file": "y.pdf", "different": []}}
    head, [row] = export.documents_table([record])
    assert head[: len(export.DOC_HEAD)] == export.DOC_HEAD
    assert (row[export.DOC_HEAD.index("Duplicate")], row[export.DOC_HEAD.index("Duplicate of")]) == ("copy", "y.pdf")
    record["duplicate"] = {"status": "suspected", "kind": "undecidable", "other_file": "y.pdf", "different": []}
    assert export.documents_table([record])[1][0][export.DOC_HEAD.index("Duplicate")] == "suspected:undecidable"
    record["duplicate"] = {"different": ["y"]}
    assert export.documents_table([record])[1][0][export.DOC_HEAD.index("Duplicate of")] is None


# --- the pairs already in the store ------------------------------------------------------------------------------


def test_scan_lists_the_pairs_and_opens_the_to_dos_once_on_runs_not_yet_approved(db):
    _run("run-1", ["a1", "a2"])
    _run("run-2", ["b1", "b2"], approved=True)
    a1 = _save("a1", _inv(), run_id="run-1")
    a2 = _save("a2", _inv(), run_id="run-1")
    _save("b1", _inv(number="X-7"), run_id="run-2")
    _save("b2", _inv(number="X-7"), run_id="run-2")
    _save("c1", _inv(number="Y-8"))
    _save("c2", _inv(number="Y-8", gross="5"))  # from the command line: no work run to show it in
    _save("solo", _inv(number="Z-9"))
    dry = duplicates.scan()
    assert (dry["groups"], dry["files"], dry["pairs"], dry["to_open"], dry["written"]) == (3, 6, {"copy": 2, "variant": 1}, 1, 0)
    assert dry["skipped"] == {"approved_run": 1, "no_work_run": 1}
    assert store.review_open_reasons("document", a2) == []
    wrote = duplicates.scan(write=True)
    assert wrote["written"] == 1
    [reason] = store.review_open_reasons("document", a2)
    assert reason["reason"] == f"duplicate:copy:{a1[:16]}" and reason["run_id"] == work.flow_run_id("run-1", a2)
    assert work.item_reasons("run-1", a2)["run"]  # the run's own to-do: it blocks the approval until decided
    again = duplicates.scan(write=True)
    assert len(store.review_open_reasons("document", a2)) == 1
    assert (again["to_open"], again["written"], again["skipped"]["already_open"]) == (0, 0, 1)  # counted as open, not to open
    duplicates.decide("run-1", a2, a1, decision="copy", actor="t")
    assert duplicates.scan(write=True)["skipped"] == {"approved_run": 1, "decided": 1, "no_work_run": 1}


# --- end to end: the worker opens the to-do, the service records the decision ------------------------------------


def test_the_worker_flags_a_second_copy_and_the_service_records_the_decision(env):
    from jav.runtime import worker
    from tests.pdfgen import INVOICE_LINES, write_text_pdf
    from tests.test_api import HUMAN, _ready_wp, _start

    c = env["client"]
    lines = [line.replace("Szamlaszam:", "Invoice number:") for line in INVOICE_LINES]  # a label the candidate finder knows
    write_text_pdf(env["folder"] / "szamla_1.pdf", lines)
    write_text_pdf(env["folder"] / "szamla_1_copy.pdf", lines + ["Sent again"])  # other bytes, the same invoice
    wp = _ready_wp(c, env["folder"])
    run_id = _start(c, wp["id"]).json()["run_id"]
    worker.run_worker(once=True)
    items = work.get_run(run_id)["input"]["items"]
    flagged = {i["item_id"]: [r["reason"] for r in work.item_reasons(run_id, i["item_id"], i)["run"] if r["reason"].startswith("duplicate:")]
               for i in items}
    [(repeat, [reason])] = [(k, v) for k, v in flagged.items() if v]
    kind, prefix = duplicates.parse_reason(reason)
    original = next(i["item_id"] for i in items if i["item_id"].startswith(prefix))
    from pathlib import Path

    assert {Path(i["source_path"]).name for i in items if i["item_id"] in (repeat, original)} == {"szamla_1.pdf", "szamla_1_copy.pdf"}
    view = c.get(f"/api/runs/{run_id}/items/{repeat}").json()
    [pair] = view["duplicates"]
    assert pair["other_doc_id"] == original and pair["decision"] is None and pair["kind"] == kind
    r = c.post(f"/api/runs/{run_id}/items/{repeat}/duplicates/{original}/decision", headers=HUMAN, json={"decision": "copy"})
    assert r.status_code == 200, r.text
    assert r.json()["duplicates"][0]["decision"] == "copy" and not [x for x in r.json()["open_reasons"] if x["reason"].startswith("duplicate:")]
    bad = c.post(f"/api/runs/{run_id}/items/{repeat}/duplicates/{original}/decision", headers=HUMAN, json={"decision": "merge"})
    assert bad.status_code == 422
    from jav import datasets

    _cols, rows = datasets.rows("documents", {"run_id": run_id})
    marks = {row["item_id"]: row.get("duplicate") for row in rows}
    assert marks[repeat] == "copy" and marks[original] is None
