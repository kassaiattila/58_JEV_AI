"""171 (plan 170, E0): characterisation tests. They pin what the code does today at six points that the coming refactors
rewrite (L1: the package's current result; E1-E7: the flow, check, decision and log registries), so that a change shows
up as a failing test instead of a silent difference:

1. the order of a decision's to-do reasons (the stored order is part of the result);
2. the reviewed version of a run (`corrections.review_version`): its parts and its exact digest;
3. the cache key and the fingerprint of a run's datasets (`datasets._key`, `datasets._run_fingerprint`);
4. the activity log ("My work today", `activity.entries`): its sources, order and row shape;
5. the worker's flow map: which flow module and which stages a recipe runs for an item;
6. the bytes of the email task proposal's output schema and request (part of the reuse key of earlier GPT answers).

A deliberate change updates the pinned value in the same commit and says so. Synthetic data only; no AI call, no
network.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import Decimal

import pytest

from jav import activity, activity_kinds, checks, corrections, datasets, duplicates, email_tasks, native_results, parties, policy, store, work
from jav.models import CheckResult, FlowState, InvoiceHU, JevVerdicts
from jav.runtime import calls, worker

RUN = "run-000000000171"
WP = "wp-000000000171"
NOW = "2026-10-08T10:00:00+00:00"
DAY = "2026-10-08"
ACTOR = "Reviewer One"


def _id(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()


DOC_A, DOC_B, DOC_C = _id("a"), _id("b"), _id("c")


@pytest.fixture
def db(tmp_path):
    from jav import mailbox, reconcile, statement_months  # noqa: F401  (their tables are registered on import)

    with store.use_store(tmp_path / "characterisation.sqlite"):
        yield


def _run(run_id: str = RUN, docs: tuple[str, ...] = (DOC_A, DOC_B), *, status: str = "needs_review",
         approved: bool = False) -> None:
    items = [{"item_id": d, "kind": "document", "source_path": f"C:/synthetic/{d[:8]}.pdf", "sha256": d} for d in docs]
    with store.connect() as c:
        c.execute("INSERT OR IGNORE INTO workpackages(id, name, source_kind, created_at, updated_at) VALUES (?,?,?,?,?)",
                  (WP, "synthetic", "manual", NOW, NOW))
        c.execute("INSERT INTO runs(run_id, workpackage_id, dedup_key, mode, assignment_revision, recipe_id, recipe_version,"
                  " recipe_hash, recipe, params, input, input_hash, status, approval, approved_by, approved_at, actor, created_at)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (run_id, WP, run_id, "apply", 1, "processing", 1, "h", "{}", "{}", json.dumps({"items": items}), "h", status,
                   "approved" if approved else None, ACTOR if approved else None, "2026-10-08T10:05:00+00:00" if approved else None,
                   ACTOR, "2026-10-08T10:01:00+00:00"))
        for d in docs:
            c.execute("INSERT INTO run_items(run_id, item_id, status, final_status, flow_run_id, updated_at) VALUES (?,?,?,?,?,?)",
                      (run_id, d, "done", "needs_review", work.flow_run_id(run_id, d), "2026-10-08T10:02:00+00:00"))


# --- 1. the order of a decision's to-do reasons ----------------------------------------------------------------------


@pytest.mark.parametrize(("arm", "expected"), [
    ("S", ["pick", "validation", "duplicate", "party", "statement", "no_invoice"]),
    ("G", ["verdict", "gpt_confidence", "validation", "duplicate", "party", "statement", "no_invoice"]),
])
def test_decide_applies_its_policies_in_a_fixed_order(monkeypatch, arm, expected) -> None:
    """Each policy step adds one marker reason; the markers come out in the order `policy.decide` calls the steps.
    175 (plan 170 E3): the steps are the decision and cross-document checks of the check registry (`jav/checks.py`);
    the cross-document ones run in a worker run only, so the decision runs in one. The pinned order is unchanged."""
    markers = {"pick": "pick", "verdict": "verdict", "gpt_confidence": "gpt_confidence", "validation": "validation",
               "duplicate": "duplicate", "own_tax": "party", "statement_overlap": "statement"}
    for check in checks.stage("decision"):
        marker = markers.pop(check.name)
        monkeypatch.setitem(checks._CHECKS, check.name,
                            replace(check, run=lambda state, m=marker: policy.require_review(state, m)))
    for check in checks.stage("cross_document"):
        marker = markers.pop(check.name)
        monkeypatch.setitem(checks._CHECKS, check.name, replace(check, run=lambda subject, m=marker: [m]))
    assert markers == {}  # every step of the decision is a check
    state = FlowState(source_path="synthetic.pdf", case_id="synthetic", arm=arm)
    with calls.use_run(budget_scope=RUN):
        assert policy.decide(state) == "human"
    assert state.review_reasons == expected


PIN_G_REASONS = [
    "source:not_found:supplier_name", "source:not_found:buyer_address", "llm:required_missing:buyer_name",
    "gpt:confidence_unavailable:supplier_name", "gpt:low_conf:invoice_number:0.50", "gpt:low_conf:gross_total:0.97",
    "validator:totals.mismatch", "validator:iban.checksum:payment_iban", f"duplicate:copy:{DOC_C}",
    "parties:own_tax_as_supplier",
]


def test_a_g_path_decision_without_jev_lists_its_reasons_in_this_order(monkeypatch) -> None:
    """The real policy steps on one G-path record without JEV; only the store readers of the cross-document checks
    (duplicates, own tax number) are stand-ins, and the decision runs in a worker run, the only place they run."""
    monkeypatch.setattr(duplicates, "review_reasons", lambda doc_id, doc_type, fields: [f"duplicate:copy:{DOC_C}"])
    monkeypatch.setattr(parties, "review_reasons", lambda doc_type, values: ["parties:own_tax_as_supplier"])
    state = FlowState(source_path="synthetic.pdf", case_id="synthetic", arm="G", jev=False, doc_type="invoice_hu",
                      doc_id=DOC_A)
    state.invoice = InvoiceHU(supplier_name="Example Supplier Kft.", invoice_number="INV-0001", currency="HUF",
                              gross_total=Decimal("1270.00"), payment_iban="HU00 0000 0000 0000 0000 0000 0000")
    state.verdicts = JevVerdicts(source="code", unsupported=["supplier_name", "buyer_address"])
    state.llm_token_p = {"invoice_number": {"joint": 0.5}, "currency": {"joint": 0.99}, "gross_total": {"joint": 0.97}}
    state.validation = [CheckResult(name="totals_consistency", ok=False, code="totals.mismatch"),
                        CheckResult(name="iban:payment_iban", ok=False, code="iban.checksum"),
                        CheckResult(name="vat_rate", ok=False, code="vat.unusual", advisory=True)]
    with calls.use_run(budget_scope=RUN):
        assert policy.decide(state) == "human"
    assert state.review_reasons == PIN_G_REASONS


# --- 2. the reviewed version of a run --------------------------------------------------------------------------------


def _review_version_steps(monkeypatch) -> list[str]:
    """The digest after each part is added in turn: none, corrections, task decisions, a native publication, a duplicate
    decision, a reconciliation decision, a statement choice."""
    _run()
    seen = [corrections.review_version(RUN)]
    with store.connect() as c:
        c.execute("INSERT INTO run_item_corrections(run_id, item_id, revision, fields, actor, created_at) VALUES (?,?,?,?,?,?)",
                  (RUN, DOC_A, 1, json.dumps({"invoice_number": "INV-0002"}), ACTOR, NOW))
        c.execute("INSERT INTO run_item_corrections(run_id, item_id, revision, fields, actor, created_at) VALUES (?,?,?,?,?,?)",
                  (RUN, DOC_A, 2, json.dumps({"invoice_number": "INV-0003"}), ACTOR, NOW))
    seen.append(corrections.review_version(RUN))
    with store.connect() as c:
        c.execute("INSERT INTO email_task_decisions(run_id, task_index, decision, actor, decided_at) VALUES (?,?,?,?,?)",
                  (f"{RUN}:{DOC_B}", 0, "accepted", ACTOR, NOW))
    seen.append(corrections.review_version(RUN))
    native = [{"item_id": DOC_B, "publication_id": "pub-1", "result_version": "rv-1"}]
    monkeypatch.setattr(native_results, "version_parts", lambda run_id, c: native if run_id == RUN else [])
    seen.append(corrections.review_version(RUN))
    with store.connect() as c:
        c.execute("INSERT INTO duplicate_decisions(pair_key, doc_id, other_doc_id, decision, actor, decided_at) VALUES (?,?,?,?,?,?)",
                  (f"{DOC_A}|{DOC_C}", DOC_A, DOC_C, "copy", ACTOR, NOW))
    seen.append(corrections.review_version(RUN))
    with store.connect() as c:
        c.execute("INSERT INTO reconcile_decisions(pair_key, invoice_doc_id, statement_doc_id, line_id, decision, actor, decided_at)"
                  " VALUES (?,?,?,?,?,?,?)", (f"{DOC_A}|line-1", DOC_A, DOC_C, "line-1", "paid_by", ACTOR, NOW))
    seen.append(corrections.review_version(RUN))
    with store.connect() as c:
        c.execute("INSERT INTO statement_choices(pair_key, keep_doc_id, actor, decided_at) VALUES (?,?,?,?)",
                  (f"{DOC_B}|{DOC_C}", DOC_B, ACTOR, NOW))
    seen.append(corrections.review_version(RUN))
    return seen


PIN_REVIEW_VERSIONS = ["4f53cda18c2baa0c", "3162c015768da350", "05922abd125306e1", "b0f22a550f220619",
                       "59faedec31ac0d46", "81ef156b36aa22c3", "d4d3b4dd41baaeb6"]


def test_the_reviewed_version_has_six_parts_and_each_changes_it(db, monkeypatch) -> None:
    seen = _review_version_steps(monkeypatch)
    assert seen[0] == hashlib.sha256(json.dumps([]).encode("utf-8")).hexdigest()[:16]  # no correction, no decision
    assert len(set(seen)) == len(seen)
    assert seen == PIN_REVIEW_VERSIONS


def test_the_reviewed_version_nests_its_parts_in_this_shape(db, monkeypatch) -> None:
    """The payload behind the final digest, rebuilt by hand: each part present wraps the earlier ones."""
    seen = _review_version_steps(monkeypatch)
    payload = {"checked": {"reviewed": {"result": {"review": {"corrections": [[DOC_A, 2]],
                                                              "tasks": [[f"{RUN}:{DOC_B}", 0, "accepted"]]},
                                                   "native": [{"item_id": DOC_B, "publication_id": "pub-1", "result_version": "rv-1"}]},
                                        "duplicates": [[f"{DOC_A}|{DOC_C}", DOC_A, "copy", NOW]]},
                           "reconcile": [[f"{DOC_A}|line-1", "paid_by", NOW]]},
               "statements": [[f"{DOC_B}|{DOC_C}", DOC_B, NOW]]}
    assert seen[-1] == hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest()[:16]


# --- 3. the cache key and the fingerprint of a run's datasets --------------------------------------------------------


# 172 (deliberate): a result table is a run's or the package's current result; for a run, `_result_fingerprint` is
# the run's own (`_run_fingerprint`, pinned below)
PIN_FINGERPRINTS = {
    "run_items": "_run_items_fingerprint", "emails": "result_fingerprint", "email_tasks": "result_fingerprint",
    "documents": "result_fingerprint", "datapoints": "result_fingerprint", "native_facts": "result_fingerprint",
    "line_items": "result_fingerprint", "utility_cost": "result_fingerprint", "utility_sources": "result_fingerprint",
    "file_names": "_run_fingerprint", "calls": "_calls_fingerprint",
}
# corrections (count, latest) | to-dos (count, open, latest id, latest close) | task decisions (count, digest) |
# items (count, latest update) | status | approval | native parts | duplicate decisions digest | left-out items digest
PIN_RUN_FINGERPRINT = ("1|2026-10-08T10:00:00+00:00|1|1|1|None|0|dc937b59892604f5|2|2026-10-08T10:02:00+00:00|needs_review"
                       "|None|[]|787f7d3a2ec11a26|dc937b59892604f5")


def test_a_run_dataset_is_cached_by_store_name_and_scope(db) -> None:
    assert datasets._key("documents", {"run_id": RUN}) == (str(store.active_path()), "documents", (("run_id", RUN),))
    assert datasets._key("run_items", {"run_id": RUN, "names": "content"}) == (
        str(store.active_path()), "run_items", (("names", "content"), ("run_id", RUN)))
    datasets.catalog()  # 185: complete with the domains' tables (`registrations.load_all`)
    assert {d.name: getattr(d.fingerprint, "__name__", None) for d in datasets.REGISTRY.values()
            if "run_id" in (*d.scope, *d.one_of)} == PIN_FINGERPRINTS


def test_the_run_fingerprint_is_this_string(db) -> None:
    _run()
    with store.connect() as c:
        c.execute("INSERT INTO run_item_corrections(run_id, item_id, revision, fields, actor, created_at) VALUES (?,?,?,?,?,?)",
                  (RUN, DOC_A, 1, json.dumps({"invoice_number": "INV-0002"}), ACTOR, NOW))
        c.execute("INSERT INTO duplicate_decisions(pair_key, doc_id, other_doc_id, decision, actor, decided_at) VALUES (?,?,?,?,?,?)",
                  (f"{DOC_A}|{DOC_C}", DOC_A, DOC_C, "copy", ACTOR, NOW))
    store.review_enqueue(subject_kind="document", subject_id=DOC_A, run_id=work.flow_run_id(RUN, DOC_A),
                         reasons=["validator:totals.mismatch"], producer="invoice")
    assert datasets._run_fingerprint({"run_id": RUN}) == PIN_RUN_FINGERPRINT
    assert datasets.result_fingerprint({"run_id": RUN}) == PIN_RUN_FINGERPRINT  # 172: a run's result table


def test_the_run_fingerprint_sees_reconciliation_decisions_and_statement_choices(db) -> None:
    """173 (deliberate, plan 170 K20 second half): a reconciliation decision or a statement choice on one of the run's
    documents changes the reviewed version, so the run's datasets are rebuilt after it too (until 172 they were not). A
    run without either keeps its earlier fingerprint (`test_the_run_fingerprint_is_this_string`)."""
    _run()
    before = datasets._run_fingerprint({"run_id": RUN})
    with store.connect() as c:
        c.execute("INSERT INTO reconcile_decisions(pair_key, invoice_doc_id, statement_doc_id, line_id, decision, actor, decided_at)"
                  " VALUES (?,?,?,?,?,?,?)", (f"{DOC_A}|line-1", DOC_A, DOC_C, "line-1", "paid_by", ACTOR, NOW))
    paid = datasets._run_fingerprint({"run_id": RUN})
    with store.connect() as c:
        c.execute("INSERT INTO statement_choices(pair_key, keep_doc_id, actor, decided_at) VALUES (?,?,?,?)",
                  (f"{DOC_B}|{DOC_C}", DOC_B, ACTOR, NOW))
    chosen = datasets._run_fingerprint({"run_id": RUN})
    assert len({before, paid, chosen}) == 3
    assert paid.startswith(before + "|") and chosen.startswith(before + "|")  # the earlier parts stay as they were


# --- 4. the activity log ---------------------------------------------------------------------------------------------


def test_the_activity_log_reads_these_sources() -> None:
    assert [s.code for s in activity_kinds.sources()] == [  # 175: the activity registry, in the same order
        "event", "recipe", "run_start", "run_approve", "correction", "reason_resolve", "task_decision", "task_done",
        "mailbox_pull",
        # 175 (deliberate, the owner's decision of 2026-10-19): a person's duplicate decisions, statement choices and
        # own workflow steps
        "duplicate_decision", "statement_choice", "workflow"]


PIN_ACTIVITY = [  # most recent first; another person's action is left out
    ("mailbox_pull", "inbox@example.com", None, None),
    ("task_done", None, RUN, WP),
    ("task_decision", "accepted", RUN, WP),
    ("run_approve", "approved", RUN, WP),
    ("reason_resolve", "validator:totals.mismatch", RUN, WP),
    ("correction", "invoice_number,net_total", RUN, WP),
    ("run_start", "apply", RUN, WP),
    ("recipe", "processing", None, WP),
    ("rename", None, None, WP),
]


def test_a_day_of_activity_in_this_order_and_shape(db) -> None:
    _run(approved=True)
    with store.connect() as c:
        c.execute("INSERT INTO workpackage_events(workpackage_id, action, actor, detail, created_at) VALUES (?,?,?,?,?)",
                  (WP, "rename", ACTOR, json.dumps({"name": "new"}), "2026-10-08T09:00:00+00:00"))
        c.execute("INSERT INTO recipe_assignments(workpackage_id, revision, recipe_id, recipe_version, recipe_hash, params, actor,"
                  " created_at) VALUES (?,?,?,?,?,?,?,?)", (WP, 1, "processing", 1, "h", "{}", ACTOR, "2026-10-08T09:30:00+00:00"))
        c.execute("INSERT INTO run_item_corrections(run_id, item_id, revision, fields, actor, created_at) VALUES (?,?,?,?,?,?)",
                  (RUN, DOC_A, 1, json.dumps({"net_total": "1000", "invoice_number": "INV-1"}), ACTOR, "2026-10-08T10:03:00+00:00"))
        c.execute("INSERT INTO review_queue(subject_kind, subject_id, run_id, reasons, created_at) VALUES (?,?,?,?,?)",
                  ("document", DOC_A, work.flow_run_id(RUN, DOC_A), "[]", NOW))
        review_id = c.execute("SELECT MAX(id) FROM review_queue").fetchone()[0]
        c.execute("INSERT INTO review_reasons(review_id, reason, producer, run_id, status, actor, created_at, closed_at)"
                  " VALUES (?,?,?,?,?,?,?,?)", (review_id, "validator:totals.mismatch", "invoice", work.flow_run_id(RUN, DOC_A),
                                                "resolved", ACTOR, NOW, "2026-10-08T10:04:00+00:00"))
        c.execute("INSERT INTO email_task_decisions(run_id, task_index, decision, actor, decided_at, done_by, done_at)"
                  " VALUES (?,?,?,?,?,?,?)", (f"{RUN}:{DOC_B}", 0, "accepted", ACTOR, "2026-10-08T10:06:00+00:00", ACTOR,
                                              "2026-10-08T10:07:00+00:00"))
        c.execute("INSERT INTO mailbox_pulls(id, request, actor, status, created_at) VALUES (?,?,?,?,?)",
                  ("pull-1", json.dumps({"mailbox": "inbox@example.com"}), ACTOR, "ok", "2026-10-08T10:08:00+00:00"))
        c.execute("INSERT INTO workpackage_events(workpackage_id, action, actor, detail, created_at) VALUES (?,?,?,?,?)",
                  (WP, "archive", "Someone Else", None, "2026-10-08T10:09:00+00:00"))
    rows = activity.entries(" reviewer  one ", DAY)  # the name is matched case- and space-insensitively
    assert [(r["action"], r["detail"], r["run_id"], r["workpackage_id"]) for r in rows] == PIN_ACTIVITY
    assert {tuple(r) for r in rows} == {("at", "action", "detail", "workpackage_id", "workpackage_name", "run_id")}


# --- 5. the worker's flow map ----------------------------------------------------------------------------------------


PIN_FLOW_MODULES = {  # flow name -> (module, Burr partition, terminal states)
    "invoice": ("jav.flow", "invoice", ["done", "needs_ocr", "needs_review"]),
    "doc_detect": ("jav.flow_detect", "doc_detect", ["done", "needs_ocr"]),
    "email": ("jav.flow_email", "email_intent", ["done"]),
    "native": ("jav.flow_native", "native", ["done", "needs_review"]),
    "statement_table": ("jav.flow_statement_table", "statement_table", ["done", "needs_review"]),
}


def test_each_flow_name_runs_this_module() -> None:
    names = ("invoice", "doc_detect", "email", "native", "statement_table")
    assert {n: (worker._flow_module(n).__name__, worker._flow_module(n).PARTITION, sorted(worker._flow_module(n).TERMINALS))
            for n in names} == PIN_FLOW_MODULES


_ITEMS = {
    "pdf": {"kind": "document", "source_path": "C:/synthetic/a.pdf"},
    "docx": {"kind": "document", "source_path": "C:/synthetic/a.docx"},
    "xlsx": {"kind": "document", "source_path": "C:/synthetic/a.xlsx"},
    "txt": {"kind": "document", "source_path": "C:/synthetic/a.txt"},
    "email": {"kind": "email", "source_path": "C:/synthetic/msg-1/message.json"},
    "statement_table": {"kind": "statement_table", "source_path": "C:/synthetic/export.csv"},
}


_OFFICE = ("docx", "xlsx", "txt")
PIN_ROUTES = {
    "processing": {"pdf": "document", **dict.fromkeys(_OFFICE, "document"), "email": "email",
                   "statement_table": "statement_table"},
    "multi-format-processing": {"pdf": "document", **dict.fromkeys(_OFFICE, "native")},
    "invoice-extraction": {"pdf": "invoice", **dict.fromkeys(_OFFICE, "invoice")},
    "document-processing": {"pdf": "document", **dict.fromkeys(_OFFICE, "document")},
    "email-intent": {"pdf": "document", **dict.fromkeys(_OFFICE, "document"), "email": "email"},
}


def test_each_recipe_routes_each_item_kind_to_this_flow() -> None:
    routed = {r["id"]: {k: work.flow_for(r, item) for k, item in _ITEMS.items() if item["kind"] in r["input_kinds"]}
              for r in work.recipes()}
    assert routed == PIN_ROUTES


_ALL = {"arm": "auto", "jev": "on", "jev_cache": "reuse", "tasks": "propose", "unknown_documents": "review"}
_DETECT_ON = ("doc_detect", {"jev": "on", "jev_cache": "reuse"})
_DETECT = ("doc_detect", {"jev_cache": "reuse"})
_MULTI = {k: v for k, v in _ALL.items() if k != "tasks"}
_INVOICE_HU = [("invoice", {"arm": "S", "jev_cache": "reuse", "doc_type": "invoice_hu"})]  # auto -> the pack's path
_DOCUMENT = [_DETECT, ("invoice", {"arm": "auto", "jev_cache": "reuse"})]
_EMAIL_DOCUMENT = [_DETECT, ("invoice", {"arm": "auto", "jev_cache": "reuse", "tasks": "propose"})]
PIN_STAGES = {
    **{f"processing:{k}": [_DETECT_ON, ("invoice", _ALL)] for k in ("pdf", *_OFFICE)},
    "processing:email": [("email", _ALL)],
    "processing:statement_table": [("statement_table", _ALL)],
    "multi-format-processing:pdf": [_DETECT_ON, ("invoice", _MULTI)],
    **{f"multi-format-processing:{k}": [("native", _MULTI)] for k in _OFFICE},
    **{f"invoice-extraction:{k}": _INVOICE_HU for k in ("pdf", *_OFFICE)},
    **{f"document-processing:{k}": _DOCUMENT for k in ("pdf", *_OFFICE)},
    **{f"email-intent:{k}": _EMAIL_DOCUMENT for k in ("pdf", *_OFFICE)},
    "email-intent:email": [("email", {"arm": "auto", "jev_cache": "reuse", "tasks": "propose"})],
}


def test_each_recipe_runs_these_stages() -> None:
    params = {"arm": "auto", "jev": "on", "jev_cache": "reuse", "tasks": "propose", "unknown_documents": "review"}
    stages = {}
    for r in work.recipes():
        for k, item in _ITEMS.items():
            if item["kind"] not in r["input_kinds"]:
                continue
            own = {p: v for p, v in params.items() if p in (r.get("params") or {})}
            if r["flow"] == "invoice":
                own["doc_type"] = "invoice_hu"
            stages[f"{r['id']}:{k}"] = worker._stages({**r, "flow": work.flow_for(r, item)}, own)
    assert stages == PIN_STAGES


def test_a_run_without_jev_takes_the_g_path_and_earlier_answers_are_the_default() -> None:
    recipe = next(r for r in work.recipes() if r["id"] == "invoice-extraction")
    assert worker._stages(recipe, {"arm": "S", "jev": "off", "doc_type": "invoice_hu"}) == [
        ("invoice", {"arm": "G", "jev": "off", "doc_type": "invoice_hu"})]
    assert worker.reuse_answers({}) is True
    assert worker.reuse_answers({"jev_cache": "live"}) is False


# --- 6. the email task proposal's schema and request bytes -----------------------------------------------------------


PIN_TASK_SCHEMA = "31a1ec7cf488ddf5171a31193deaf92376cabd0f929504f69a96e0cc256597bd"
PIN_TASK_REQUEST = "143ec7026f361d4037dee58105213ee11a4d11a96770d8ee15bb85203677c6c3"


def test_the_task_output_schema_bytes() -> None:
    schema = json.dumps(email_tasks.TaskOutput.model_json_schema(), ensure_ascii=False)
    assert hashlib.sha256(schema.encode("utf-8")).hexdigest() == PIN_TASK_SCHEMA


def test_the_task_request_bytes_for_a_synthetic_email() -> None:
    snap = email_tasks.snapshot(message_id="msg-1", subject="Quote request", body="Please send a quote by Friday.",
                                body_status="complete", attachments=[{"filename": "spec.pdf", "doc_type": "unknown"}])
    prompt = json.dumps(email_tasks.request_payload(snap, {"intent": "ajanlatkeres", "confidence": 0.9}),
                        ensure_ascii=False, sort_keys=True)
    assert hashlib.sha256(prompt.encode("utf-8")).hexdigest() == PIN_TASK_REQUEST
