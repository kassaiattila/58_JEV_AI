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

# each registered decision point and the test that shows its trace (a new point needs its own)
POINT_TESTS = {
    wf.BUDGET_GATE: "test_a_step_over_its_budget_traces_the_gate_with_the_wait",
    "detect.doc_type": "test_a_documents_type_and_detailed_type_are_traced_with_its_save",
    "detect.detail_type": "test_the_gpt_recognitions_contradiction_is_in_the_detailed_types_trace",
}


def test_every_decision_point_is_described_and_has_its_test():
    assert {p.code for p in trace.points()} == set(POINT_TESTS)
    for p in trace.points():
        assert p.what and p.not_for and p.owner and p.files and callable(p.rule), p.code
        assert all(cfg.CONFIG_DIR.joinpath(f).is_file() for f in p.files), p.code
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
