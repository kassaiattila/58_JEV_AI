"""The decision trace (218, plan P3 P3b): which rule decided, with what, in which version.

Plain-language summary: every machine decision point is registered with what it decides, what it is not for, its owner,
the rule files it reads and its rule, a pure function whose value for the stored inputs is the stored outcome. Each
decision writes one trace row in the transaction that records its result: its inputs, its outcome, the rule files and
keys with their versions and fingerprints, and the calculation snapshot. When the trace cannot be written, the decision
is not written either. The first point is a workflow step's budget gate. Synthetic data, a temporary store, no paid
calls.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal

import pytest
from hypothesis import given, strategies as st

from jav.app import workflow_cases, workflows as wf
from jav.core import cfg, rulebook, store, trace
from jav.core.process import tasks
from tests.test_workflow_tasks_215 import _monthly
from tests.test_workflows_146 import _steps, db  # noqa: F401 - the fixture is used by name
from tests.test_process_rules_231 import test_an_approved_quote_and_its_letter_check_are_traced_decisions as quote_points_traced  # noqa: F401 - named by POINT_TESTS
from tests.test_rule_evaluation_231 import test_every_evaluation_is_traced_and_replays_the_same as rule_outcome_traced  # noqa: F401 - named by POINT_TESTS
from tests.test_rating_231 import test_the_calculation_is_traced_and_replays_the_same as premium_traced  # noqa: F401 - named by POINT_TESTS
from tests.test_field_check_231 import test_the_offered_facts_make_the_units_fill_what_is_missing_and_leave_a_conflict_to_the_person as claims_traced  # noqa: F401,E501 - named by POINT_TESTS
from tests.test_case_decisions_231 import test_risk_then_premium_with_another_person_above_the_limit as second_person_traced  # noqa: F401,E501 - named by POINT_TESTS

# each registered decision point and the test that shows its trace (a new point needs its own)
POINT_TESTS = {
    wf.BUDGET_GATE: "test_a_step_over_its_budget_traces_the_gate_with_the_wait",
    "detect.doc_type": "test_a_documents_type_and_detailed_type_are_traced_with_its_save",
    "detect.detail_type": "test_the_gpt_recognitions_contradiction_is_in_the_detailed_types_trace",
    "email.intent": "test_an_emails_intent_and_next_step_are_traced_with_its_save",
    "email.next_flow": "test_an_email_without_an_intent_traces_only_its_route",
    "extract.route": "test_an_s_path_records_route_and_to_dos_are_traced_with_its_save",
    "ocr.escalation": "test_a_blocked_escalation_is_traced_with_the_recognitions_save",
    "finance.duplicate": "test_a_duplicate_and_an_own_tax_number_are_traced_with_the_extractions_save",
    "parties.own_tax_as_supplier": "test_the_store_scans_trace_the_to_dos_they_open",
    "parties.detail_direction": "test_the_parties_direction_on_an_uncertain_detailed_type_is_traced",
    # 231 (B3): the quotes' points, shown in the process rules' tests (imported under a name pytest does not collect)
    "quote.amounts": "quote_points_traced",
    "quote.letter_check": "quote_points_traced",
    # 231 (stage D, D-c2): a product rule's outcome on an assessed unit
    "rules.outcome": "rule_outcome_traced",
    "rating.premium": "premium_traced",  # D-c3: a premium computed from a tariff
    "claims.offered": "claims_traced",  # D-d2: where a fact another step offers goes in a field check
    "decision.second_person": "second_person_traced",  # D-d4: whether a decision is another person's above a limit
}


def test_every_decision_point_is_described_and_has_its_test():
    assert {p.code for p in trace.points()} == set(POINT_TESTS)
    for p in trace.points():
        assert p.what and p.not_for and p.owner and p.files and callable(p.rule), p.code
        assert all(any(cfg.CONFIG_DIR.glob(f)) for f in p.files), p.code  # a file, or a pattern naming a family
        assert callable(globals()[POINT_TESTS[p.code]])


def test_an_unknown_point_or_a_rule_file_it_does_not_read_is_refused(db):  # noqa: F811
    with store.connect() as c:
        with pytest.raises(trace.UnknownPoint):
            trace.record_in(c, "no.such_point", subject=("x", "1"), inputs={}, outcome=None, keys={})
        with pytest.raises(trace.UnknownPoint, match="reads no rule file"):
            trace.record_in(c, wf.BUDGET_GATE, subject=("x", "1"), inputs={}, outcome=None, keys={"policy.json": ("a",)})


def test_a_step_over_its_budget_traces_the_gate_with_the_wait(db):  # noqa: F811
    wf_id = _monthly(db)
    rows = {r["subject_id"]: r for r in trace.rows(point=wf.BUDGET_GATE, case_id=wf_id)}
    over = rows[f"{wf_id}:invoices"]
    note = _steps(wf.view(wf_id))["invoices"]["note"]
    assert over["subject_kind"] == "workflow_step" and over["run_id"] is None
    assert over["inputs"] == {"estimate": note["estimate"], "budget": {}}
    assert over["outcome"] == {"over": note["over"], "decision": "needs_budget"} and over["outcome"]["over"]
    recipes = rulebook.current().files["recipes.json"]
    assert [(r["file"], r["version"], r["sha256"]) for r in over["rules"]] == [("recipes.json", recipes.version, recipes.sha256)]
    assert all(k.startswith("recipes[") for k in over["rules"][0]["keys"])
    assert over["snapshot_id"] == rulebook.current().snapshot_id
    assert trace.replay(over) == over["outcome"]
    # the statements are read by code: their estimate fits, so the run starts, named on the trace
    fits = rows[f"{wf_id}:statements"]
    assert fits["outcome"] == {"over": {}, "decision": "start"}
    assert fits["run_id"] == _steps(wf.view(wf_id))["statements"]["run_id"]
    with store.connect() as c:  # the stored inputs are exactly the text whose fingerprint is kept
        row = c.execute("SELECT inputs, inputs_sha FROM decision_trace WHERE id=?", (over["id"],)).fetchone()
    assert hashlib.sha256(row["inputs"].encode("utf-8")).hexdigest() == row["inputs_sha"]


def test_a_gate_whose_trace_cannot_be_written_records_no_wait_either(db, monkeypatch):  # noqa: F811
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("the trace could not be written")

    monkeypatch.setattr(trace, "record_in", broken)
    wf_id = _monthly(db)
    step = _steps(wf.view(wf_id))["invoices"]
    assert (step["state"], step["note"]) == ("failed", "the trace could not be written")  # a person starts it again
    assert tasks.get(tasks.task_id(workflow_cases.BUDGET_TASK, f"{wf_id}:invoices")) is None
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM decision_trace").fetchone()[0] == 0
        actions = [r[0] for r in c.execute("SELECT action FROM workflow_events WHERE workflow_id=? AND step='invoices'", (wf_id,))]
    assert "needs_budget" not in actions


AMOUNT = st.decimals(min_value=0, max_value=50, places=4).map(str)
PROVIDERS = st.sampled_from(["jev", "openai", "azure_di"])


@given(st.dictionaries(PROVIDERS, AMOUNT), st.dictionaries(PROVIDERS, AMOUNT))
def test_the_gate_is_over_exactly_where_an_estimate_is_over_its_budget_and_replays_the_same(estimate, budget):
    out = wf.budget_gate({"estimate": estimate, "budget": budget})
    assert set(out["over"]) == {p for p, v in estimate.items() if Decimal(v) > Decimal(budget.get(p, "0"))}
    assert out["decision"] == ("needs_budget" if out["over"] else "start")
    stored = json.loads(json.dumps({"inputs": {"estimate": estimate, "budget": budget}, "outcome": out}))
    assert wf.budget_gate(stored["inputs"]) == stored["outcome"]


def test_the_status_page_counts_the_trace_by_point(db):  # noqa: F811
    from jav.devtools import admin

    assert admin.trace_line() == "- decision trace (218): -"  # no decision yet
    _monthly(db)
    assert admin.trace_line() == f"- decision trace (218): {wf.BUDGET_GATE} 2"


# --- the recognition's two points (M1) ------------------------------------------------------------------------------


def _detect_jev(tmp_path, monkeypatch=None):
    from jav.ai import jev as jev_mod
    from jav.flows import flow_detect
    from tests.pdfgen import INVOICE_LINES, write_text_pdf
    from tests.test_runtime_worker import FakeClient

    adapter = jev_mod.JevAdapter(client=FakeClient(), cache_dir=tmp_path / "cache", model="jev-1.13.0")
    path = write_text_pdf(tmp_path / "invoice.pdf", INVOICE_LINES)
    with jev_mod.use_adapter(adapter):
        return flow_detect.run_detect(str(path), run_id="r-detect")


def test_a_documents_type_and_detailed_type_are_traced_with_its_save(db, tmp_path):  # noqa: F811
    from jav.flows import flow_detect

    st_ = _detect_jev(tmp_path)
    rows = {r["point"]: r for r in trace.rows(subject=("document", st_.doc_id))}
    kind = rows[flow_detect.DOC_TYPE_POINT]
    assert kind["run_id"] == "r-detect" and kind["inputs"]["engine"] == "jev"
    assert kind["inputs"]["doc_type"] == st_.result.doc_type and kind["inputs"]["confidence"] == st_.result.confidence
    assert kind["outcome"] == {"doc_type": st_.result.doc_type, "uncertain": st_.uncertain}
    keys = kind["rules"][0]["keys"]
    assert kind["rules"][0]["file"] == "policy.json" and any(k.startswith("band_for.detect") for k in keys)
    assert {k.rsplit(".", 1)[1] for k in keys if k.startswith("bands.")} == {
        "choice_human_max_conf", "choice_second_min_gap", "uncertain_review"}
    detail = rows[flow_detect.DETAIL_TYPE_POINT]
    assert detail["outcome"] == {"key": st_.detail.key, "reasons": st_.detail_reasons}
    assert detail["inputs"]["method"] == st_.detail.method and detail["inputs"]["errors"] == []
    for row in rows.values():
        assert trace.replay(row) == row["outcome"]


def test_the_gpt_recognitions_contradiction_is_in_the_detailed_types_trace(tmp_path, monkeypatch):
    from jav.ai import detect_detail, detect_gpt
    from jav.ai import jev as jev_mod
    from jav.flows import flow_detect
    from tests.pdfgen import INVOICE_LINES, write_text_pdf
    from tests.test_gpt_detect_086 import _NoJev
    from tests.test_gpt_type_check_090 import _contradicting

    monkeypatch.setattr(detect_detail, "anchor_score", lambda detect, text: (True, 1.0))
    path = write_text_pdf(tmp_path / "szamla.pdf", INVOICE_LINES)
    with store.use_store(tmp_path / "g.sqlite"), detect_gpt.use_agent_factory(_contradicting), jev_mod.use_adapter(_NoJev()):
        st_ = flow_detect.run_detect(str(path), run_id="r1", jev=False)
        row = trace.rows(point=flow_detect.DETAIL_TYPE_POINT, subject=("document", st_.doc_id))[0]
    assert row["inputs"]["engine"] == "gpt" and "detect:issuer_mismatch:invoice_hu" in row["outcome"]["reasons"]
    assert "detect_issuer.engines" in row["rules"][0]["keys"]
    assert trace.replay(row) == row["outcome"]


def test_a_recognition_whose_trace_cannot_be_written_saves_nothing(db, tmp_path, monkeypatch):  # noqa: F811
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("the trace could not be written")

    monkeypatch.setattr(trace, "record_in", broken)
    with pytest.raises(sqlite3.OperationalError):
        _detect_jev(tmp_path)
    with store.connect() as c:  # the document, its type and its to-dos are not written either
        assert c.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM review_reasons").fetchone()[0] == 0


# --- the email's two points (M3) -----------------------------------------------------------------------------------


def test_an_emails_intent_and_next_step_are_traced_with_its_save(db, monkeypatch):  # noqa: F811
    from jav.ai.models import JevCall
    from jav.domains.email import flow_email, intent as intent_mod
    from jav.domains.email.emails import Attachment, EmailMessage

    answer = intent_mod.IntentResult(intent="szamlakuldes", confidence=0.62, probabilities={"szamlakuldes": 0.62, "other": 0.38},
                                     signals={"injected_instruction": 0.01}, call=JevCall(request_id="x", n_questions=1, state_chars=1))
    monkeypatch.setattr(intent_mod, "classify", lambda *a, **kw: answer)  # an invented answer: no JEV call
    msg = EmailMessage(message_id="m-1", subject="Invoice", body="Please find the invoice attached.",
                       attachments=[Attachment(filename="invoice.pdf", doc_type="invoice_hu", status="done")])
    st_ = flow_email.run_email(message=msg, detect_attachments=False)
    rows = {r["point"]: r for r in trace.rows(subject=("email", "m-1"))}
    intent = rows[flow_email.INTENT_POINT]
    assert intent["inputs"]["intent"] == st_.result.intent and intent["outcome"]["uncertain"] == st_.uncertain
    assert set(intent["outcome"]["reasons"]) <= set(st_.review_reasons)
    route = rows[flow_email.NEXT_FLOW_POINT]
    assert route["outcome"] == {"next_flow": st_.next_flow}
    assert route["inputs"]["attachments"] == [{"filename": "invoice.pdf", "doc_type": "invoice_hu",
                                               "status": st_.message.attachments[0].status}]  # what the rule read
    assert route["rules"][0]["file"] == "email.json" and "signal_routes" in route["rules"][0]["keys"]  # 224: its own file
    assert route["rules"][1]["file"] == "policy.json" and "band_for.email.intent" in route["rules"][1]["keys"]
    for row in rows.values():
        assert trace.replay(row) == row["outcome"]


def test_an_email_without_an_intent_traces_only_its_route(db, tmp_path, monkeypatch):  # noqa: F811
    from jav.ai import jev as jev_mod
    from jav.domains.email import flow_email
    from jav.domains.email.emails import EmailMessage
    from tests.test_jev_adapter_v2 import _failing_adapter

    monkeypatch.setattr(jev_mod, "get_adapter", lambda: _failing_adapter(tmp_path))
    st_ = flow_email.run_email(message=EmailMessage(message_id="m-2", subject="?", body="?"), detect_attachments=False)
    rows = trace.rows(subject=("email", "m-2"))
    assert [r["point"] for r in rows] == [flow_email.NEXT_FLOW_POINT]
    assert rows[0]["outcome"] == {"next_flow": st_.next_flow} == {"next_flow": "human:jev_unavailable"}
    assert [(r["file"], r["keys"]) for r in rows[0]["rules"]] == [("email.json", ["jev_unavailable_route"])]


def test_an_email_whose_trace_cannot_be_written_saves_nothing(db, tmp_path, monkeypatch):  # noqa: F811
    from jav.ai import jev as jev_mod
    from jav.domains.email import flow_email
    from jav.domains.email.emails import EmailMessage
    from tests.test_jev_adapter_v2 import _failing_adapter

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("the trace could not be written")

    monkeypatch.setattr(jev_mod, "get_adapter", lambda: _failing_adapter(tmp_path))
    monkeypatch.setattr(trace, "record_in", broken)
    with pytest.raises(sqlite3.OperationalError):
        flow_email.run_email(message=EmailMessage(message_id="m-3", subject="?", body="?"), detect_attachments=False)
    with store.connect() as c:  # the email, its run's result and its to-do are not written either
        for table in ("emails", "email_results", "review_reasons"):
            assert c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table


# --- the extraction's point (M2) -----------------------------------------------------------------------------------


def _extract_s(tmp_path):
    from jav.ai import jev as jev_mod
    from jav.flows.flow import run_one
    from tests.pdfgen import INVOICE_LINES, write_text_pdf
    from tests.test_runtime_worker import FakeClient

    adapter = jev_mod.JevAdapter(client=FakeClient(), cache_dir=tmp_path / "cache", model="jev-1.13.0")
    path = write_text_pdf(tmp_path / "invoice.pdf", INVOICE_LINES)
    with jev_mod.use_adapter(adapter):
        return run_one(str(path), "c1", "S", tracker=False, doc_type="invoice_hu")


def _the_route_row(st_) -> dict:
    from jav.ai import policy

    (row,) = trace.rows(point=policy.ROUTE_POINT, subject=("document", st_.doc_id))
    assert row["run_id"] == st_.run_id
    # the to-dos raised before the decision and the ones it raised are the record's, in their stored order
    assert row["inputs"]["earlier"] + row["outcome"]["reasons"] == st_.review_reasons
    assert row["outcome"]["route"] == st_.route
    assert trace.replay(row) == row["outcome"]
    return row


def test_an_s_path_records_route_and_to_dos_are_traced_with_its_save(db, tmp_path):  # noqa: F811
    from jav.ai import typepack

    st_ = _extract_s(tmp_path)
    row = _the_route_row(st_)
    inputs = row["inputs"]
    assert (inputs["arm"], inputs["doc_type"], inputs["has_record"]) == ("S", "invoice_hu", True)
    assert [p["field"] for p in inputs["picks"]] == list(st_.picks)  # in the order the to-dos are raised
    for pick in inputs["picks"]:  # the two most likely options are all the band reads
        assert len(pick["probabilities"]) <= 2
        assert pick["confidence"] == st_.picks[pick["field"]].confidence
    snapshot = rulebook.current()
    files = {r["file"]: r for r in row["rules"]}
    assert set(files) == {"policy.json", "types/invoice_hu.json"}
    for name, r in files.items():
        assert (r["version"], r["sha256"]) == (snapshot.files[name].version, snapshot.files[name].sha256)
    assert "band_for.invoice.pick" in files["policy.json"]["keys"]
    assert {"required", "high_stakes", "scored_fields"} <= set(files["types/invoice_hu.json"]["keys"])
    assert typepack.get("invoice_hu").extends is None


def test_a_g_path_without_jev_traces_its_gpt_confidence_to_dos(tmp_path):
    from tests.test_no_jev_085 import GOOD, _run_g

    st_ = _run_g(tmp_path, GOOD, jev=False)
    with store.use_store(tmp_path / "f.sqlite"):
        row = _the_route_row(st_)
    inputs = row["inputs"]
    assert (inputs["arm"], inputs["jev"], inputs["verdicts"]["source"]) == ("G", False, "code")
    assert any(r.startswith("gpt:confidence_unavailable:") for r in row["outcome"]["reasons"])
    assert {"gpt_field_confidence.review_below", "gpt_field_confidence.measure"} <= set(row["rules"][0]["keys"])


def test_a_saved_state_decided_before_the_trace_is_saved_without_one(db, tmp_path):  # noqa: F811
    from jav.flows import flow

    st_ = _extract_s(tmp_path)
    old = st_.model_copy(update={"route_inputs": None, "run_id": "r-old"})
    flow.save(old)  # a run resumed at its save, decided by the code before the trace
    assert [r["run_id"] for r in trace.rows(subject=("document", st_.doc_id))] == [st_.run_id]
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM datapoints WHERE run_id='r-old'").fetchone()[0] == 1


def test_an_extraction_whose_trace_cannot_be_written_saves_nothing(db, tmp_path, monkeypatch):  # noqa: F811
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("the trace could not be written")

    monkeypatch.setattr(trace, "record_in", broken)
    with pytest.raises(sqlite3.OperationalError):
        _extract_s(tmp_path)
    with store.connect() as c:  # the document, its record and its to-dos are not written either
        for table in ("documents", "datapoints", "review_reasons"):
            assert c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table


_P = st.floats(min_value=0, max_value=1, allow_nan=False).map(lambda p: round(p, 4))
_FIELDS = ("supplier_name", "supplier_tax_id", "buyer_name", "invoice_number", "issue_date", "gross_total", "payment_iban",
           "supplier_address")


@st.composite
def _pick(draw, field: str):
    from jav.ai.models import FieldPick

    n = draw(st.integers(min_value=0, max_value=4))
    probs = {f"c{i}": draw(_P) for i in range(n)}
    chosen = draw(st.sampled_from(sorted(probs) + [None])) if probs else None
    return FieldPick(field=field, label=chosen, confidence=(max(probs.values()) if probs else None), probabilities=probs,
                     n_options=n, request_id="r", present_p=draw(st.none() | _P),
                     n_candidates=draw(st.none() | st.integers(min_value=n, max_value=n + 2)))


@st.composite
def _s_state(draw):
    from jav.ai.models import FlowState

    fields = draw(st.lists(st.sampled_from(_FIELDS), unique=True, max_size=len(_FIELDS)))
    earlier = draw(st.lists(st.sampled_from(["ocr:no_text", "pick:none:invoice_number"]), unique=True))
    state = FlowState(doc_type="invoice_hu", source_path="synthetic.pdf", case_id="h", arm="S", review_reasons=earlier,
                      needs_review=bool(earlier))  # the latch: a to-do raised before is a state waiting for a person
    state.picks = {f: draw(_pick(f)) for f in fields}
    return state


@st.composite
def _g_state(draw):
    from jav.ai.models import CheckResult, DocumentRecord, FlowState, JevVerdicts

    jev = draw(st.booleans())
    state = FlowState(doc_type="invoice_hu", source_path="synthetic.pdf", case_id="h", arm="G", jev=jev)
    if draw(st.booleans()):
        state.record = DocumentRecord(supplier_name=draw(st.none() | st.just("Example Supplier Kft.")),
                                      invoice_number=draw(st.none() | st.just("INV-1")), currency="HUF")
    flags = draw(st.dictionaries(st.sampled_from(_FIELDS), st.dictionaries(st.sampled_from(["off_target", "wrong_kind"]), _P)))
    state.verdicts = JevVerdicts(flags=flags, doc_flags=draw(st.dictionaries(st.just("parties_swapped"), _P)),
                                 unsupported=draw(st.lists(st.sampled_from(_FIELDS), unique=True)),
                                 source=draw(st.sampled_from(["jev", "code"])),
                                 omitted=draw(st.lists(st.just("line_items"), unique=True)))
    state.llm_token_p = draw(st.dictionaries(st.sampled_from(("supplier_name", "invoice_number", "currency")),
                                             st.fixed_dictionaries({"joint": _P, "min": _P})))
    state.validation = [CheckResult(name=n, ok=draw(st.booleans()), code="c.x", advisory=draw(st.booleans()))
                        for n in draw(st.lists(st.sampled_from(["totals_consistency", "iban:payment_iban",
                                                                "tax_id:supplier_tax_id"]), unique=True))]
    return state


@given(st.one_of(_s_state(), _g_state()))
def test_the_traced_rule_is_the_decision_the_flow_makes_and_replays_the_same(state):
    from jav.ai import policy

    before = list(state.review_reasons)
    route = policy.decide(state)  # outside a worker run: no cross-document check runs
    inputs = state.route_inputs
    assert inputs["earlier"] == before
    # as the trace stores it: JSON with sorted keys
    stored = json.loads(json.dumps({"inputs": inputs, "outcome": policy.route_rule(inputs)}, sort_keys=True))
    assert stored["outcome"] == {"route": route, "reasons": state.review_reasons[len(before):]}
    assert policy.route_rule(stored["inputs"]) == stored["outcome"]


# --- the recognition's escalation (OCR) ----------------------------------------------------------------------------


def _scan(tmp_path, *, mean_conf: float, low: float = 0.5, text: bool = True):
    """A PDF without a text layer, and a local OCR engine that reads it with `mean_conf` and a `low` share of weak
    words (the invoice's lines when `text`, nothing otherwise); the paid engine is blocked by the run's budget."""
    from dataclasses import replace

    from jav.documents import ocr
    from jav.documents.pdf import read_document
    from tests.pdfgen import INVOICE_LINES, write_text_pdf

    scan = write_text_pdf(tmp_path / "scan.pdf", [])
    printed = read_document(str(write_text_pdf(tmp_path / "printed.pdf", INVOICE_LINES)))
    signals = {"engine": "native", "mean_conf": mean_conf, "low_conf_ratio": low}

    def ocr_pdf(path, **kwargs):
        if kwargs.get("engine_name") == "azure_di":
            raise ocr.AzureBlocked("budget_exceeded")
        if not text:
            return ocr.PdfText(path=str(path), text="", page_count=1, ocr=dict(signals))
        return replace(printed, path=str(path), has_text_layer=False, text_source="ocr", ocr=dict(signals))

    return scan, ocr_pdf


def _escalating(monkeypatch, ocr_pdf):
    from jav.documents import ocr

    monkeypatch.delenv(ocr.ENGINE_ENV, raising=False)
    monkeypatch.setattr(ocr, "ESCALATION", {"enabled": True, "engine": "azure_di"})
    monkeypatch.setattr(ocr, "ocr_pdf", ocr_pdf)


def test_a_blocked_escalation_is_traced_with_the_recognitions_save(db, tmp_path, monkeypatch):  # noqa: F811
    from jav.ai import jev as jev_mod
    from jav.documents import ocr
    from jav.flows import flow_detect
    from tests.test_runtime_worker import FakeClient

    scan, ocr_pdf = _scan(tmp_path, mean_conf=0.5)
    _escalating(monkeypatch, ocr_pdf)
    adapter = jev_mod.JevAdapter(client=FakeClient(), cache_dir=tmp_path / "cache", model="jev-1.13.0")
    with jev_mod.use_adapter(adapter):
        st_ = flow_detect.run_detect(str(scan), run_id="r-scan")
    (row,) = trace.rows(point=ocr.ESCALATION_POINT, subject=("document", st_.doc_id))
    assert row["run_id"] == "r-scan" and row["inputs"]["first"] == {"engine": "native", "mean_conf": 0.5, "low_conf_ratio": 0.5}
    assert row["inputs"]["attempt"] == {"blocked": "budget_exceeded"}
    assert row["outcome"] == {"attempt": True, "text": "local", "reasons": ["ocr:escalation_blocked:budget_exceeded"]}
    assert "ocr:escalation_blocked:budget_exceeded" in st_.review_reasons
    assert {r["file"] for r in row["rules"]} == {"ocr.json", "policy.json"}
    assert trace.replay(row) == row["outcome"]


def test_the_recognition_keeps_the_to_do_of_a_blocked_escalation(db, tmp_path, monkeypatch):  # noqa: F811
    """222 (the owner's decision): a document whose type is recognised kept no to-do for an escalation the run's
    budget blocked; only the extraction stored it, so a document without one (an unknown type, an email's attachment)
    lost it. It is kept beside the pages OCR left out, and a later recognition without a block closes it."""
    from jav.ai import jev as jev_mod
    from jav.documents import ocr
    from jav.flows import flow_detect
    from tests.test_runtime_worker import FakeClient

    scan, ocr_pdf = _scan(tmp_path, mean_conf=0.5)
    _escalating(monkeypatch, ocr_pdf)
    adapter = jev_mod.JevAdapter(client=FakeClient(), cache_dir=tmp_path / "cache", model="jev-1.13.0")
    with jev_mod.use_adapter(adapter):
        st_ = flow_detect.run_detect(str(scan), run_id="r-scan")
        assert st_.result is not None
        opened = {r["reason"] for r in store.review_open_reasons("document", st_.doc_id)}
        assert "ocr:escalation_blocked:budget_exceeded" in opened
        monkeypatch.setattr(ocr, "ESCALATION", {"enabled": False, "engine": "azure_di"})  # nothing is blocked now
        flow_detect.run_detect(str(scan), run_id="r-scan-2")
    opened = {r["reason"] for r in store.review_open_reasons("document", st_.doc_id)}
    assert "ocr:escalation_blocked:budget_exceeded" not in opened


def test_a_document_ocr_could_not_read_is_traced_with_its_to_do_in_one_write(db, tmp_path, monkeypatch):  # noqa: F811
    from jav.documents import ocr
    from jav.flows.flow import run_one

    scan, ocr_pdf = _scan(tmp_path, mean_conf=0.99, low=0.0, text=False)
    _escalating(monkeypatch, ocr_pdf)
    st_ = run_one(str(scan), "c1", "S", tracker=False, doc_type="invoice_hu")
    assert st_.final_status == "needs_ocr"
    (row,) = trace.rows(point=ocr.ESCALATION_POINT, subject=("document", st_.doc_id))
    assert row["outcome"] == {"attempt": False, "text": "local", "reasons": []}  # good enough: no paid engine asked

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("the trace could not be written")

    monkeypatch.setattr(trace, "record_in", broken)
    with store.use_store(tmp_path / "second.sqlite"):
        with pytest.raises(sqlite3.OperationalError):
            run_one(str(scan), "c2", "S", tracker=False, doc_type="invoice_hu")
        with store.connect() as c:  # the document and its to-do are not written either
            for table in ("documents", "review_reasons"):
                assert c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table


_OUTCOME = st.one_of(st.none(), st.sampled_from(["off", "budget_exceeded", "uncertain_attempt", "unavailable"]), _P)


@given(_P, _P, st.sampled_from(["native", "azure_di"]), st.booleans(), st.booleans(), _OUTCOME)
def test_the_escalation_rule_is_what_the_recognition_does_and_replays_the_same(conf, ratio, engine, forced, enabled, then):
    """`then`: what the paid engine does when asked: blocked (a reason), reads with a confidence, or reads nothing."""
    import os
    from unittest.mock import patch

    from jav.documents import ocr

    first = ocr.PdfText(path="x.pdf", text="local", ocr={"engine": engine, "mean_conf": conf, "low_conf_ratio": ratio})

    def ocr_pdf(path, **kwargs):
        if kwargs.get("engine_name") != "azure_di":
            return ocr.PdfText(path="x.pdf", text="local", ocr=dict(first.ocr))
        if isinstance(then, str):
            raise (ocr.AzureBlocked(then) if then != "unavailable" else ocr.OcrUnavailableError("down"))
        return ocr.PdfText(path="x.pdf", text="paid", ocr=None if then is None else {"engine": "azure_di", "mean_conf": then})

    env = {ocr.ENGINE_ENV: "native"} if forced else {}
    with patch.object(ocr, "ocr_pdf", ocr_pdf), patch.object(ocr, "ESCALATION", {"enabled": enabled, "engine": "azure_di"}),             patch.dict(os.environ, env, clear=False):
        if not forced:
            os.environ.pop(ocr.ENGINE_ENV, None)
        pdf, escalated = ocr.ocr_with_escalation("x.pdf")
    inputs = pdf.ocr["escalation"]
    stored = json.loads(json.dumps({"inputs": inputs, "outcome": ocr.escalation_rule(inputs)}, sort_keys=True))
    out = stored["outcome"]
    assert out["text"] == ("escalated" if escalated else "local") and (pdf.text == "paid") == escalated
    assert out["reasons"] == ocr.escalation_review_reasons(pdf.ocr)
    assert ocr.escalation_rule(stored["inputs"]) == out


# --- the cross-document checks: a duplicate, an own tax number as the supplier's ----------------------------------


def _own_party(tax: str) -> None:
    from jav.app import parties

    parties.create("Example Buyer Kft.", identities=[("tax", parties.tax_key(tax), tax)], actor="tester")


def test_a_duplicate_and_an_own_tax_number_are_traced_with_the_extractions_save(db):  # noqa: F811
    from jav.ai.models import DocumentRecord, FlowState
    from jav.app import parties
    from jav.domains.finance import own_parties
    from jav.domains.finance import duplicates
    from jav.flows import flow
    from tests.test_duplicates_126 import A, _id, _in_run, _inv, _save

    earlier = _save("earlier", _inv())
    _own_party(A)  # the supplier's number is an own party's: the numbers are likely swapped
    state = FlowState(source_path="C:/synthetic/now.pdf", case_id="synthetic", arm="G", doc_type="invoice_hu",
                      doc_id=_id("now"), run_id="r-now")
    state.record = DocumentRecord(invoice_number="INV-2026/001", supplier_tax_id=A, supplier_name="Example Trading Ltd",
                                  issue_date="2026-09-02", gross_total=Decimal("1270.00"), currency="HUF")
    state = _in_run(lambda: flow.decide_route(state))  # the cross-document checks run in a worker run only
    flow.save(state)
    rows = {r["point"]: r for r in trace.rows(subject=("document", _id("now")))}
    dup = rows[duplicates.DUPLICATE_POINT]
    assert dup["run_id"] == "r-now" and [o["doc_id"] for o in dup["inputs"]["others"]] == [earlier]
    assert dup["outcome"]["reasons"] == [f"duplicate:variant:{earlier[:16]}"]
    assert dup["outcome"]["matches"] == [{"doc_id": earlier[:16], "kind": "variant", "differing": ["issue_date"],
                                          "missing": [], "decided": False}]
    own = rows[own_parties.OWN_TAX_POINT]
    assert own["inputs"]["supplier_tax"] == parties.tax_key(A) and own["inputs"]["own_party"]
    assert own["outcome"] == {"reasons": [own_parties.OWN_TAX_REASON]}
    route = rows["extract.route"]  # their to-dos are the route's inputs, in the order they ran
    assert route["inputs"]["cross_document"][:2] == [dup["outcome"]["reasons"], own["outcome"]["reasons"]]
    assert {r["reason"] for r in store.review_open_reasons("document", _id("now"))} >= {
        f"duplicate:variant:{earlier[:16]}", own_parties.OWN_TAX_REASON}
    for row in (dup, own, route):
        assert trace.replay(row) == row["outcome"]


def test_the_store_scans_trace_the_to_dos_they_open(db):  # noqa: F811
    from jav.app import work_runs
    from jav.domains.finance import own_parties
    from jav.domains.finance import duplicates, party_views
    from tests.test_duplicates_126 import A, _inv, _run, _save

    _own_party(A)
    _run("run-1", ["earlier", "now"])
    earlier = _save("earlier", {**_inv(), "supplier_tax_id": None}, run_id="run-1")
    now = _save("now", {**_inv(), "supplier_tax_id": A, "supplier_name": "Example Trading Ltd"}, run_id="run-1")
    assert duplicates.scan(write=True)["written"] == 1 and party_views.scan_own_tax(write=True)["written"] == 1
    flow_run = work_runs.flow_run_id("run-1", now)
    (dup,) = trace.rows(point=duplicates.DUPLICATE_POINT)
    assert (dup["subject_id"], dup["run_id"]) == (now, flow_run)
    assert dup["outcome"]["reasons"] == [f"duplicate:copy:{earlier[:16]}"]
    (own,) = trace.rows(point=own_parties.OWN_TAX_POINT)
    assert (own["subject_id"], own["run_id"], own["outcome"]) == (now, flow_run, {"reasons": [own_parties.OWN_TAX_REASON]})
    for row in (dup, own):
        assert trace.replay(row) == row["outcome"]
    duplicates.scan(write=True), party_views.scan_own_tax(write=True)  # nothing more to open: nothing more traced
    assert len(trace.rows(point=duplicates.DUPLICATE_POINT)) == len(trace.rows(point=own_parties.OWN_TAX_POINT)) == 1


# --- the detailed type by the own parties' direction ------------------------------------------------------------------


@pytest.mark.parametrize("buyer_is_own, verdict", [(True, "contradicted"), (False, "confirmed")])
def test_the_parties_direction_on_an_uncertain_detailed_type_is_traced(db, buyer_is_own, verdict):  # noqa: F811
    from jav.app import parties
    from jav.domains.finance import own_parties
    from tests.test_detail_direction_149 import OWN_TAX, SURE, _state, _uncertain

    parties.create("Sample Own Company", identities=[("tax", parties.tax_key(OWN_TAX), OWN_TAX)], actor="t")
    _uncertain()
    own, other = {"name": "Sample Own Company Kft.", "tax_id": OWN_TAX}, {"name": "Northwind Trading Ltd.", "tax_id": None}
    buyer, supplier = (own, other) if buyer_is_own else (other, own)
    own_parties.confirm_detail_by_direction(_state(supplier_name=supplier["name"], supplier_tax_id=supplier["tax_id"],
                                               buyer_name=buyer["name"], buyer_tax_id=buyer["tax_id"]))
    (row,) = trace.rows(point=own_parties.DIRECTION_POINT, subject=("document", "d1"))
    direction = "incoming" if buyer_is_own else "outgoing"
    assert row["inputs"] == {"doc_type": "invoice_out", "probabilities": SURE, "direction": direction}
    assert row["outcome"]["verdict"] == verdict and row["run_id"] == "run-a:item-1"
    opened = [r["reason"] for r in store.review_open_reasons("document", "d1")]
    assert ("detect_detail:low_conf:invoice_out:0.55" in opened) == (verdict == "contradicted")  # a match closes it
    assert set(row["outcome"]["reasons"]) <= set(opened)
    assert row["rules"][0]["keys"] == ["detect_detail.direction_sides"]
    assert trace.replay(row) == row["outcome"]
