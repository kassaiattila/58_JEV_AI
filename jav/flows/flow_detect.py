"""M1 Burr flow: `load_pdf → detect → save → done`; a PDF without text → `ocr_pdf` (OCR text takes the same route) or
`needs_ocr`.

A separate, small graph (not part of the invoice flow): the category goes into the `documents` table, and the
type-specific M2 flow later starts from there. The `run_id` is the backbone here too; the JEV call goes through the
adapter (cache + ledger).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from burr.core import ApplicationBuilder, action, default, expr, when
from burr.core.application import Application
from burr.integrations.pydantic import PydanticTypingSystem
from pydantic import BaseModel, Field

from jav.ai import policy
from jav.core import store, trace
from jav.ai.detect import DetectResult
from jav.ai.detect_detail import DetailResult
from jav.ai.engine import with_engine
from jav.documents.layout import LineLayout

TERMINALS = ["done", "needs_ocr"]
PARTITION = "doc_detect"  # partition of the durable state store (066 Á08: the worker finds the saved state by it)
TRACKER_PROJECT = "jav_doc_detect"


class DetectState(BaseModel):
    source_path: str  # the original path: file name (part of the request), year hint and the stored path
    read_path: str | None = None  # where the bytes are read from (the source instance); None: `source_path`
    run_id: str = ""
    use_cache: bool = True
    jev: bool = True  # 086: False = processing without JEV, the type is recognised by GPT (`jav/ai/detect_gpt.py`)
    doc_id: str = ""
    text: str = ""
    lines: list[str] = Field(default_factory=list)
    layout: list[LineLayout] = Field(default_factory=list)
    page_count: int = 0
    has_text_layer: bool = False
    text_source: str | None = None  # "pdf" | "ocr" | None
    ocr_conf: float | None = None
    ocr_low_conf_ratio: float | None = None
    # 124: the digest of the kept original Azure recognition, when its text went on; the native reader takes it over
    ocr_recognition: str | None = None
    # 218 (plan P3 P3b): what the OCR escalation's decision read (`ocr.escalation_rule`), traced with the save
    ocr_escalation: dict[str, Any] | None = None
    year: int | None = None
    result: DetectResult | None = None
    detail: DetailResult | None = None  # 047 T1.2: detailed type within the coarse category
    detail_reasons: list[str] = Field(default_factory=list)
    uncertain: bool = False
    review_reasons: list[str] = Field(default_factory=list)  # additive; jev_unavailable:<reason> and ocr:* reasons
    final_status: str | None = None


def _year_hint(path: str) -> int | None:
    parts = Path(path).parts
    for part in reversed(parts[:-1]):  # a folder name (e.g. Bejövő/2023/...) takes precedence
        if re.fullmatch(r"20\d{2}", part):
            return int(part)
    m = re.search(r"(20\d{2})", Path(path).name)
    return int(m.group(1)) if m else None


@action.pydantic(reads=["source_path", "read_path", "review_reasons"],
                 writes=["text", "lines", "layout", "page_count", "has_text_layer", "text_source", "doc_id", "year",
                         "review_reasons"])
def load_pdf(state: DetectState) -> DetectState:
    from jav.documents import pdf_input

    pdf, state.doc_id, coverage = pdf_input.read_source(state.source_path, state.read_path)
    state.text, state.lines, state.layout = pdf.text, pdf.lines, pdf.layout
    state.page_count, state.has_text_layer, state.text_source = pdf.page_count, pdf.has_text_layer, pdf.text_source
    state.year = _year_hint(state.source_path)
    state.review_reasons = state.review_reasons + [r for r in coverage if r not in state.review_reasons]
    return state


@action.pydantic(reads=["source_path", "read_path", "doc_id", "page_count", "review_reasons"],
                 writes=["text", "lines", "layout", "text_source", "ocr_conf", "ocr_low_conf_ratio", "ocr_recognition",
                         "ocr_escalation", "review_reasons"])
def ocr_pdf(state: DetectState) -> DetectState:
    """PDF without text: OCR (jav/documents/ocr.py, cached) onto the same layout; no engine / no text -> `needs_ocr`."""
    from jav.documents import pdf_input
    from jav.documents.ocr import AZURE_PROVIDER, escalation_review_reasons

    recognised = pdf_input.recognise(state.source_path, state.read_path, state.doc_id, state.page_count)
    if recognised.pdf is None:
        state.review_reasons = state.review_reasons + [recognised.unavailable]
        return state
    pdf, signals = recognised.pdf, recognised.signals
    state.text, state.lines, state.layout, state.text_source = pdf.text, pdf.lines, pdf.layout, pdf.text_source
    state.ocr_conf, state.ocr_low_conf_ratio = signals.get("mean_conf"), signals.get("low_conf_ratio")
    state.ocr_escalation = signals.get("escalation")
    # 124: an Azure text cached before 123 has no kept original, so it names nothing and is not taken over
    state.ocr_recognition = signals.get("recognition_sha256") if signals.get("engine") == AZURE_PROVIDER else None
    if pdf.text_source is None:
        state.review_reasons = state.review_reasons + ["ocr:no_text"]
    state.review_reasons = state.review_reasons + [
        r for r in [*policy.ocr_coverage_reasons(state.page_count, signals.get("pages_ocr")), *escalation_review_reasons(signals)]
        if r not in state.review_reasons]
    return state


@action.pydantic(reads=["source_path", "text", "lines", "layout", "page_count", "run_id", "use_cache", "jev", "review_reasons"],
                 writes=["result", "uncertain", "review_reasons", "detail", "detail_reasons"])
def detect(state: DetectState) -> DetectState:
    from jav.ai.jev import JevUnavailableError, get_adapter
    from jav.ai.detect import detect as _detect
    from jav.documents.pdf import PdfText

    pdf = PdfText(path=state.source_path, text=state.text, lines=state.lines, layout=state.layout, page_count=state.page_count, has_text_layer=True)
    if not state.jev:
        return _detect_gpt(state, pdf)
    try:
        state.result = _detect(get_adapter(), pdf, state.source_path, run_id=state.run_id, use_cache=state.use_cache)
    except JevUnavailableError as exc:  # JEV unavailable (ledgered): no type, manual queue; a later scan reruns it
        state.result = None
        state.uncertain = True
        state.review_reasons = state.review_reasons + [f"jev_unavailable:{exc.reason}"]
        return state
    r = state.result
    state.uncertain = doc_type_rule(_type_inputs(state))["uncertain"]
    if r.doc_type != "unknown":
        _resolve_detail(state, get_adapter())
    return state


def _detect_gpt(state: DetectState, pdf) -> DetectState:
    """086: the type recognised by GPT (processing without JEV). A failed call (no budget, provider error) is a to-do,
    not the end of the item; an unmeasurable confidence makes the type uncertain. 160: a JEV question asked here
    anyway is refused (`jav/ai/engine.py`) and named as such."""
    from jav.ai.jev import JevUnavailableError
    from jav.ai.detect_gpt import choose_detail, detect as _detect

    try:
        state.result = _detect(pdf, state.source_path, run_id=state.run_id)
    except Exception as exc:  # noqa: BLE001 - an error is a to-do, not the end of the flow (as on the G path)
        state.result = None
        state.uncertain = True
        reason = f"jev_unavailable:{exc.reason}" if isinstance(exc, JevUnavailableError) else f"detect:gpt_failed:{type(exc).__name__}"
        state.review_reasons = state.review_reasons + [reason]
        return state
    r = state.result
    state.uncertain = doc_type_rule(_type_inputs(state))["uncertain"]
    if r.doc_type != "unknown":
        _resolve_detail(state, None, chooser=choose_detail)
    return state


# --- 218 (plan P3 P3b): the two decisions of the recognition as pure rules, traced with the document's save -----------

DOC_TYPE_POINT, DETAIL_TYPE_POINT = "detect.doc_type", "detect.detail_type"
_DETAIL_ERRORS = ("jev_unavailable:", "detect_detail:gpt_failed:")  # a question that failed, not a rule's to-do
_CHOICE_FIELDS = ("choice_human_max_conf", "choice_second_min_gap", "uncertain_review")


def _engine(state: DetectState) -> str:
    return "jev" if state.jev else "gpt"


def _type_inputs(state: DetectState) -> dict[str, Any]:
    r = state.result
    return {"engine": _engine(state), "doc_type": r.doc_type, "confidence": r.confidence, "probabilities": r.probabilities,
            "measured": r.measured}


def doc_type_rule(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Whether the recognised type waits for a person: an unknown type, a confidence the GPT answer could not give, or a
    confidence in the review band of the recogniser's call site (`detect.doc_type[.gpt]`). The type stays either way."""
    callsite = "detect.doc_type" + (".gpt" if inputs["engine"] == "gpt" else "")
    uncertain = (not inputs["measured"] or inputs["doc_type"] == "unknown"
                 or policy.choice_needs_review(inputs["confidence"], inputs["probabilities"], callsite))
    return {"doc_type": inputs["doc_type"], "uncertain": bool(uncertain)}


def _detail_inputs(state: DetectState, errors: list[str]) -> dict[str, Any]:
    d = state.detail
    return {"engine": _engine(state), "doc_type": state.result.doc_type, "issuer_hu": state.result.issuer_hu,
            "broad": d.broad, "key": d.key, "method": d.method, "confidence": d.confidence,
            "probabilities": d.probabilities, "scores": d.scores, "errors": errors}


def detail_type_rule(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """The detailed type's to-dos (047, 069, 086, 090): a failed question (`errors`), a category without a type pack,
    an open detailed type, a GPT answer without a confidence, a JEV or GPT answer in the review band of
    `detect.detail_type[.gpt]`, and the type / issuer cross-check in code (a type presuming a Hungarian issuer the
    recogniser judged foreign). The detailed type stays either way."""
    reasons = list(inputs["errors"])
    key, method, broad = inputs["key"], inputs["method"], inputs["broad"]
    if method == "no_candidate":  # 069: no type pack for the category (payment reminder, unknown): no extraction
        reasons.append(f"detect:no_type_pack:{broad}")
    elif key is None:
        reasons.append(f"detect:detail_open:{broad}")
    elif method == "gpt" and inputs["confidence"] is None:
        reasons.append(f"detect_detail:confidence_unavailable:{key}")
    elif method in ("jev", "gpt"):
        callsite = "detect.detail_type" if method == "jev" else "detect.detail_type.gpt"
        reason = policy.choice_review_reason("detect_detail", key, inputs["confidence"] or 0.0, inputs["probabilities"], callsite)
        if reason:
            reasons.append(reason)
    issuer = policy.issuer_mismatch_reason(inputs["doc_type"], key, inputs["issuer_hu"], engine=inputs["engine"])
    if issuer:  # 090: a contradiction is a to-do beside the detailed type's
        reasons.append(issuer)
    return {"key": key, "reasons": reasons}


def _detail_keys(inputs: Mapping[str, Any]) -> tuple[str, ...]:
    keys: tuple[str, ...] = ("detect_issuer.engines", "detect_issuer.hungarian_types")
    keys += policy.band_keys(f"detect.issuer_is_hungarian.{inputs['engine']}", "noul_no_max")
    if inputs["method"] == "issuer":
        keys += ("detect_detail.foreign_issuer_pack",)
    elif inputs["method"] == "anchors":
        keys += ("detect_detail.anchor_margin",)
    elif inputs["method"] in ("jev", "gpt"):
        keys += policy.band_keys("detect.detail_type" + (".gpt" if inputs["method"] == "gpt" else ""), *_CHOICE_FIELDS)
    return keys


def _trace(c: Any, state: DetectState) -> None:
    """The recognised type's and the detailed type's decisions, in the save's transaction (and the OCR escalation's of a
    document without a text layer)."""
    from jav.documents import ocr

    ocr.trace_escalation(c, state.ocr_escalation, doc_id=state.doc_id, run_id=state.run_id)
    if state.result is None:  # no answer: nothing was decided (the to-do names the failure)
        return
    subject = ("document", state.doc_id)
    inputs = _type_inputs(state)
    callsite = "detect.doc_type" + (".gpt" if inputs["engine"] == "gpt" else "")
    trace.record_in(c, DOC_TYPE_POINT, subject=subject, inputs=inputs, outcome=doc_type_rule(inputs),
                    keys={"policy.json": policy.band_keys(callsite, *_CHOICE_FIELDS)}, run_id=state.run_id)
    if state.detail is not None:
        inputs = _detail_inputs(state, [r for r in state.detail_reasons if r.startswith(_DETAIL_ERRORS)])
        trace.record_in(c, DETAIL_TYPE_POINT, subject=subject, inputs=inputs, outcome=detail_type_rule(inputs),
                        keys={"policy.json": _detail_keys(inputs)}, run_id=state.run_id)


trace.register(trace.Point(
    DOC_TYPE_POINT, owner=__name__, files=("policy.json",), rule=doc_type_rule,
    what="whether a document's recognised type waits for a person (unknown, unmeasured or in the review band)",
    not_for="which type the recogniser chose (its answer is an input) or the detailed type within it"))
trace.register(trace.Point(
    DETAIL_TYPE_POINT, owner=__name__, files=("policy.json",), rule=detail_type_rule,
    what="the to-dos of a document's detailed type: no type pack, still open, unmeasured, in the review band, or a "
         "type presuming a Hungarian issuer the recogniser judged foreign",
    not_for="how the detailed type was found (issuer, single pack, anchors or a question: its method is an input) or "
            "its later check against the own parties' direction"))


def _resolve_detail(state: DetectState, jev, chooser=None) -> None:
    """047 T1.2: the detailed type (`jav/ai/detect_detail.py`). An open or uncertain detailed type is a to-do alongside
    the detection's own reasons; a JEV outage does not stop the process here either. `chooser` (086): the GPT
    question for processing without JEV; its failure is a to-do too."""
    from jav.ai.jev import JevUnavailableError
    from jav.ai.detect_detail import resolve

    broad = state.result.doc_type
    try:
        # 122: the recogniser's own issuer judgement may route a foreign issuer's receipt to the foreign invoice pack
        d = resolve(broad, state.text, jev=jev, run_id=state.run_id, use_cache=state.use_cache, chooser=chooser,
                    issuer_hu=state.result.issuer_hu, engine="gpt" if chooser is not None else "jev")
    except JevUnavailableError as exc:
        d = DetailResult(broad=broad, key=None, method="no_jev")
        state.detail_reasons = [f"jev_unavailable:{exc.reason}"]
    except Exception as exc:  # noqa: BLE001 - only the GPT chooser gets here (no JEV): a to-do, the item goes on
        if chooser is None:
            raise
        d = DetailResult(broad=broad, key=None, method="gpt")
        state.detail_reasons = [f"detect_detail:gpt_failed:{type(exc).__name__}"]
    state.detail = d
    # 218 (P3b): the to-dos by the traced rule (090: the issuer cross-check is part of it)
    state.detail_reasons = detail_type_rule(_detail_inputs(state, list(state.detail_reasons)))["reasons"]


@action.pydantic(reads=["doc_id", "source_path", "has_text_layer", "text_source", "page_count", "year", "result", "run_id", "uncertain",
                        "review_reasons", "detail", "detail_reasons", "jev", "ocr_escalation"], writes=["final_status"])
def save(state: DetectState) -> DetectState:
    """The document's type, its to-dos and (218, P3b) the traces of both decisions in one write transaction: the
    store's own writes join it as savepoints (`store.session`), so a stop in between leaves none of them."""
    with store.session(), store.connect() as c:
        store.begin_immediate(c)
        _save(state, c)
    state.final_status = "done" if state.result is not None else ("jev_unavailable" if state.jev else "gpt_unavailable")
    return state


def _save(state: DetectState, c: Any) -> None:
    r, d = state.result, state.detail
    store.upsert_document(
        doc_id=state.doc_id, source_path=state.source_path, has_text=state.text_source is not None, page_count=state.page_count,
        year=state.year, doc_type=r.doc_type if r else None, type_conf=r.confidence if r else None,
        issuer_hu=r.issuer_hu if r else None, run_id=state.run_id,
        detail_type=d.key if d else None, detail_conf=d.confidence if d else None, detail_method=d.method if d else None,
    )
    store.review_close(subject_kind="document", subject_id=state.doc_id, producer=policy.OCR_REVIEW_PRODUCER, run_id=state.run_id)  # 066: there is text now
    # 047: the detailed type has its own producer (closed independently of the coarse type's reasons)
    if state.detail_reasons:
        store.review_enqueue(subject_kind="document", subject_id=state.doc_id, run_id=state.run_id, producer="detect_detail",
                             reasons=state.detail_reasons, payload={"detail": d.model_dump() if d else None})
    elif d is not None:
        store.review_close(subject_kind="document", subject_id=state.doc_id, producer="detect_detail", run_id=state.run_id)
    if state.uncertain and r is not None:
        # 086: a GPT answer without log-probabilities has no measured confidence: say so, do not report a low one
        reason = f"detect:low_conf:{r.doc_type}:{r.confidence:.2f}" if r.measured else f"detect:confidence_unavailable:{r.doc_type}"
        store.review_enqueue(
            subject_kind="document", subject_id=state.doc_id, run_id=state.run_id, producer="detect",
            reasons=[reason],
            payload={"probabilities": r.probabilities, "issuer_hu": r.issuer_hu, "language": r.language,
                     "parent": policy.parent_fallback(r.confidence, r.parent, r.parent_prob, "detect.doc_type", r.probabilities), "parent_prob": r.parent_prob},
        )
    elif r is None:
        store.review_enqueue(subject_kind="document", subject_id=state.doc_id, run_id=state.run_id, producer="detect",
                             reasons=list(state.review_reasons) or ["detect:no_result"])
    else:
        # after a rerun the type is certain: detect's own earlier reasons (errors too) are obsolete; others' stay open
        store.review_close(subject_kind="document", subject_id=state.doc_id, producer="detect", run_id=state.run_id)
    # Partial OCR (F07): the type may be certain, but the skipped pages are still to-dos; a separate producer so that
    # closing detect does not close it. 167 (AI-3): so are the pages without a text layer of their own. 222 (the owner's
    # decision): and an escalation the run's budget blocked (075), which only the extraction kept before
    coverage = [x for x in state.review_reasons
                if x.startswith(("ocr:partial_pages:", "pdf:pages_without_text:", "ocr:escalation_blocked:"))]
    if coverage:
        store.review_enqueue(subject_kind="document", subject_id=state.doc_id, run_id=state.run_id, producer="ocr_coverage", reasons=coverage)
    else:
        store.review_close(subject_kind="document", subject_id=state.doc_id, producer="ocr_coverage", run_id=state.run_id)
    _trace(c, state)


@action.pydantic(reads=[], writes=[])
def done(state: DetectState) -> DetectState:
    return state


@action.pydantic(reads=["doc_id", "source_path", "page_count", "year", "run_id", "review_reasons", "ocr_escalation"],
                 writes=["final_status"])
def needs_ocr(state: DetectState) -> DetectState:
    """218 (P3b): the document, its to-do and the OCR escalation's trace in one write transaction."""
    from jav.documents import ocr

    with store.session(), store.connect() as c:
        store.begin_immediate(c)
        store.upsert_document(doc_id=state.doc_id, source_path=state.source_path, has_text=False, page_count=state.page_count, year=state.year, run_id=state.run_id)
        # 066 Á01: a document without text is a to-do (producer shared with M2; closed once there is text)
        store.review_enqueue(subject_kind="document", subject_id=state.doc_id, run_id=state.run_id, producer=policy.OCR_REVIEW_PRODUCER,
                             reasons=[r for r in state.review_reasons if r.startswith("ocr:")] or ["ocr:no_text"])
        ocr.trace_escalation(c, state.ocr_escalation, doc_id=state.doc_id, run_id=state.run_id)
    state.final_status = "needs_ocr"
    return state


TRANSITIONS = [
    ("load_pdf", "ocr_pdf", when(has_text_layer=False)),
    ("load_pdf", "detect", default),
    ("ocr_pdf", "needs_ocr", expr("text_source != 'ocr'")),
    ("ocr_pdf", "detect", default),
    ("detect", "save"),
    ("save", "done"),
]

CONTRACT = {  # graph declaration: FLOW.md + Mermaid + lint come from it (jav/flows/contract.py, `python -m jav.cli flows`)
    "name": "doc_detect",
    "phases": ["load", "classify", "persist", "terminal"],
    "steps": [("load_pdf", "load"), ("ocr_pdf", "load"), ("detect", "classify"), ("save", "persist"), ("done", "terminal"), ("needs_ocr", "terminal")],
    "edges": [("load_pdf", "ocr_pdf", "no text layer"), ("load_pdf", "detect"), ("ocr_pdf", "needs_ocr", "no OCR / no text"), ("ocr_pdf", "detect", "OCR text"),
              ("detect", "save"), ("save", "done")],
    "step_meta": {
        "load_pdf": {"kind": "det", "note": "pdfplumber word-level reconstruction, sha256 doc_id, year hint from the folder; the text-layer test of the document and of each page (167: scanned pages without text of their own, images over 30 % of the page, are the pdf:pages_without_text to-do, kept open by the ocr_coverage producer)"},
        "ocr_pdf": {"kind": "det", "note": "a PDF without text: OCR (jav/documents/ocr.py: page images and tesseract, native or the legacy sidecar image, a disk cache) onto the same layout; the quality signals in the state"},
        "detect": {"kind": "jev", "note": "one request, three judgements: Choice doc_type (the registry and unknown), Noul issuer_is_hungarian, Choice language; anchor hits as features; then the detailed type among the category's packs (jav/ai/detect_detail.py: the legacy anchor score, a JEV Choice when needed). Without JEV: the same three questions to GPT in one structured request, the confidence from the answer's token log-probabilities (jav/ai/detect_gpt.py); a failed call is a detect:gpt_failed to-do"},
        "save": {"kind": "store", "note": "the documents table (the detailed type too; a detailed type left open is a detect_detail to-do; a category without a type pack too); conf < policy.detect.low_confidence -> review_queue (by reason, additive), otherwise the detect step's own earlier reasons close"},
        "done": {"kind": "terminal", "note": "typed"},
        "needs_ocr": {"kind": "terminal", "note": "a PDF without text or with a broken text layer, and OCR gave no text either (or there is no engine): documents has_text=0; a to-do (producer `ocr`, ocr:*), closed by a save with text; 218: one write transaction with the OCR escalation's trace (ocr.escalation)"},
    },
    "terminals": TERMINALS,
    "doc_note": "M1 - the type goes into the documents table; the M2 flow of the type starts from there. The run_id is the backbone; the JEV call goes through the adapter (cache, ledger, config_hash).",
}


def build_app(source_path: str, *, tracker: bool = False, use_cache: bool = True, run_id: str | None = None,
              persister=None, read_path: str | None = None, jev: bool = True) -> Application:
    """`persister` (040 K1): durable state persistence, resuming under the same `run_id`; without it, the earlier
    behaviour. `read_path`: the document's bytes are read from here (its source instance); everything else uses
    `source_path`. `jev=False` (086): the type is recognised by GPT, JEV is never asked."""
    run_id = run_id or f"detect-{Path(source_path).stem[:24]}-{uuid.uuid4().hex[:8]}"
    initial = DetectState(source_path=source_path, read_path=read_path, run_id=run_id, use_cache=use_cache, jev=jev)
    b = (
        ApplicationBuilder()
        .with_typing(PydanticTypingSystem(DetectState))
        .with_actions(load_pdf, ocr_pdf, detect, save, done, needs_ocr)
        .with_transitions(*TRANSITIONS)
        .with_identifiers(app_id=run_id, partition_key=PARTITION if persister is not None else None)
    )
    if persister is not None:
        b = (b.initialize_from(persister, resume_at_next_action=True, default_state=initial.model_dump(),
                               default_entrypoint="load_pdf").with_state_persister(persister))
    else:
        b = b.with_state(initial).with_entrypoint("load_pdf")
    if tracker:
        b = b.with_tracker("local", project=TRACKER_PROJECT)
    return with_engine(b, jev_on=jev).build()  # 160: without JEV, a JEV question is refused


def run_detect(source_path: str, *, tracker: bool = False, use_cache: bool = True, run_id: str | None = None,
               read_path: str | None = None, jev: bool = True) -> DetectState:
    """`run_id` (065): when called from another process, logs and records to-dos under that process's identifier.
    `read_path`: the bytes are read from here (a source instance); the file name and the stored path stay `source_path`.
    `jev=False` (086): GPT recognises the type."""
    app = build_app(source_path, tracker=tracker, use_cache=use_cache, run_id=run_id, read_path=read_path, jev=jev)
    _, _, state = app.run(halt_after=TERMINALS)
    return state.data
