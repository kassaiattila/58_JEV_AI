"""Burr state machine: processes one invoice-type document on the S (select) or G (generate+verify) path.

    load_pdf ─┬─ ocr_pdf ─── needs_ocr                       (no text layer; OCR unavailable / returned no text)
              │     ├─────────────────────────────┐          (OCR text: same route as a text layer)
              ├─ find_candidates → jev_select → normalize_picks ─┐        [S]
              └─ extract_llm ─┬─ jev_verify ──┬─ normalize_llm ──┤        [G]
                              ├─ code_verify ─┘                  │  (085: G without JEV)
                              └─ decide_route (LLM error)        │
                                                    validate ←───┘
                                                    decide_route → save ─┬─ done
                                                                         └─ needs_review

Typed Pydantic state (`FlowState`), `@action.pydantic` actions. Every AI call goes through the adapter layer
(`jav.adapters`); the `run_id` is the backbone: the ledger, datapoints and review_queue refer to it. The review latch
is additive.

The graph is type-independent: the type pack of `state.doc_type` (`jav/typepack.py`, `configs/types/<type>.json`)
supplies the field list, the candidate profile, the call sites, the prompt / schema, the validators and the required /
high-stakes fields. Every pack in `configs/types/` runs on it, e.g. `invoice_hu` (Hungarian invoice), `invoice_foreign`
(foreign invoice, ported on 2026-09-20) and the utility-bill packs.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from pathlib import Path

from burr.core import ApplicationBuilder, action, default, expr, when
from burr.core.application import Application
from burr.integrations.pydantic import PydanticTypingSystem

from jav import cfg, policy, store
from jav.config import TRACKER_PROJECTS
from jav.models import FlowState
from jav.typepack import DEFAULT_KEY, get as get_pack

TERMINALS = ["done", "needs_review", "needs_ocr"]
PARTITION = "invoice"  # partition of the durable state store (066 Á08: the worker finds the saved state by it)
TRACKER_PROJECT = TRACKER_PROJECTS.get("invoice_hu", "jav_invoice_hu")  # legacy; per type: `tracker_project(doc_type)`


def tracker_project(doc_type: str) -> str:
    return TRACKER_PROJECTS.get(doc_type, TRACKER_PROJECTS.get("invoice", "jav_invoice"))


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _year_hint(path: str) -> int | None:
    m = re.search(r"(20\d{2})", Path(path).name) or re.search(r"[\\/](20\d{2})[\\/]", path)
    return int(m.group(1)) if m else None


# --- actions ---------------------------------------------------------------------------


@action.pydantic(reads=["source_path", "read_path"], writes=["text", "lines", "page_count", "has_text_layer", "layout", "doc_id",
                                                             "text_source", "source_layer_id"])
def load_pdf(state: FlowState) -> FlowState:
    from jav import source_layer
    from jav.pdf import read_pdf

    pdf = read_pdf(state.read_path or state.source_path)
    state.text = pdf.text
    state.lines = pdf.lines
    state.layout = pdf.layout
    state.page_count = pdf.page_count
    state.has_text_layer = pdf.has_text_layer
    state.text_source = pdf.text_source
    state.doc_id = _sha256(state.read_path or state.source_path)
    if pdf.has_text_layer:  # for a PDF without text the OCR step saves the layer
        state.source_layer_id = source_layer.save_from_pdftext(state.doc_id, pdf)
    return state


@action.pydantic(
    reads=["source_path", "read_path", "page_count", "doc_id", "needs_review", "review_reasons"],
    writes=["text", "lines", "layout", "text_source", "ocr_conf", "ocr_low_conf_ratio", "ocr_engine", "ocr_escalated", "needs_review", "review_reasons",
            "source_layer_id"],
)
def ocr_pdf(state: FlowState) -> FlowState:
    """PDF without text: OCR (jav/ocr.py, with a disk cache) -> the same layout (lines, cells) as for a text layer.
    The OCR quality signals go into the state raw; weak OCR raises reviews per the policy's `ocr` thresholds. No
    engine / no usable text: `text_source` stays None -> `needs_ocr` terminal (the flow does not crash)."""
    from jav.ocr import OcrUnavailableError, azure_alias, escalation_review_reasons, ocr_with_escalation

    try:
        with azure_alias(state.source_path if state.read_path else None, state.doc_id):
            pdf, escalated = ocr_with_escalation(state.read_path or state.source_path, page_count=state.page_count)
    except OcrUnavailableError as exc:
        policy.require_review(state, f"ocr:unavailable:{type(exc).__name__}")
        return state
    state.text, state.lines, state.layout = pdf.text, pdf.lines, pdf.layout
    state.text_source = pdf.text_source
    signals = pdf.ocr or {}
    state.ocr_conf = signals.get("mean_conf")
    state.ocr_low_conf_ratio = signals.get("low_conf_ratio")
    state.ocr_engine = signals.get("engine")
    state.ocr_escalated = escalated
    from jav import source_layer

    state.source_layer_id = source_layer.save_from_pdftext(state.doc_id, pdf) if pdf.text_source else None
    if pdf.text_source is None:
        policy.require_review(state, "ocr:no_text")
    policy.require_review(state, *policy.ocr_review_reasons(state.ocr_conf, state.ocr_low_conf_ratio))
    policy.require_review(state, *policy.ocr_coverage_reasons(state.page_count, signals.get("pages_ocr")))
    policy.require_review(state, *escalation_review_reasons(signals))  # 075: Azure blocked by the budget
    return state


@action.pydantic(reads=["layout", "doc_type"], writes=["candidates"])
def find_candidates(state: FlowState) -> FlowState:
    from jav.candidates import find_all

    pack = get_pack(state.doc_type)
    state.candidates = find_all(state.layout, pack.candidate_profile, text_labels=pack.text_labels)
    return state


@action.pydantic(reads=["layout", "candidates", "run_id", "use_cache", "doc_type", "needs_review", "review_reasons"], writes=["picks", "jev_calls", "needs_review", "review_reasons"])
def jev_select(state: FlowState) -> FlowState:
    from jav.adapters.jev import JevUnavailableError, get_adapter
    from jav.jev_select import select_fields

    try:
        picks, calls = select_fields(get_adapter(), state.layout, state.candidates, run_id=state.run_id, use_cache=state.use_cache, pack=get_pack(state.doc_type))
    except JevUnavailableError as exc:  # JEV unavailable (ledgered): no picks, record to manual queue; flow survives
        picks, calls = {}, []
        policy.require_review(state, f"jev_unavailable:{exc.reason}")
    state.picks = picks
    state.jev_calls = state.jev_calls + calls
    return state


@action.pydantic(reads=["layout", "picks", "candidates", "doc_type", "needs_review", "review_reasons"], writes=["invoice", "needs_review", "review_reasons"])
def normalize_picks(state: FlowState) -> FlowState:
    from jav.jev_select import picks_to_invoice

    inv, reasons = picks_to_invoice(state.picks, state.candidates, pack=get_pack(state.doc_type), lines=state.layout)
    state.invoice = inv
    policy.require_review(state, *reasons)
    return state


@action.pydantic(reads=["text", "run_id", "doc_type", "needs_review", "review_reasons"], writes=["llm_output", "needs_review", "review_reasons"])
def extract_llm(state: FlowState) -> FlowState:
    from jav.extract_llm import extract

    try:
        state.llm_output = extract(state.text, run_id=state.run_id, pack=get_pack(state.doc_type))
    except Exception as exc:  # noqa: BLE001 - an error is a review reason, not the end of the flow
        state.llm_output = None
        policy.require_review(state, f"llm:failed:{type(exc).__name__}")
    return state


@action.pydantic(reads=["layout", "llm_output", "run_id", "use_cache", "doc_type", "needs_review", "review_reasons"], writes=["verdicts", "jev_calls", "needs_review", "review_reasons"])
def jev_verify(state: FlowState) -> FlowState:
    from jav.adapters.jev import JevUnavailableError, get_adapter
    from jav.jev_verify import code_verdicts, verify

    try:
        verdicts, call = verify(get_adapter(), state.layout, state.llm_output or {}, run_id=state.run_id, use_cache=state.use_cache, pack=get_pack(state.doc_type))
    except JevUnavailableError as exc:  # without verification the extract cannot be accepted automatically
        # 085: the code's own source check and the required fields still count (before 085 they were dropped too)
        state.verdicts = code_verdicts(state.layout or [], state.llm_output or {}, pack=get_pack(state.doc_type))
        policy.require_review(state, f"jev_unavailable:{exc.reason}")
        return state
    state.verdicts = verdicts
    state.jev_calls = state.jev_calls + [call]
    return state


@action.pydantic(reads=["layout", "llm_output", "doc_type"], writes=["verdicts"])
def code_verify(state: FlowState) -> FlowState:
    """085: the G path without JEV: only the code's own source check (every extracted value must be printed on the
    document); no JEV question, so the remaining checks are the pack's validators and its required fields."""
    from jav.jev_verify import code_verdicts

    state.verdicts = code_verdicts(state.layout or [], state.llm_output or {}, pack=get_pack(state.doc_type))
    return state


@action.pydantic(reads=["layout", "llm_output", "doc_type", "needs_review", "review_reasons"], writes=["invoice", "needs_review", "review_reasons"])
def normalize_llm(state: FlowState) -> FlowState:
    from jav.dates import document_date_order
    from jav.numbers import document_convention

    # 081: a value GPT copied in the document's own notation ("28.000") is read with that notation, never as 28; 084: a
    # date GPT copied as printed ("04/12/2022") follows the document's own day/month order, or gets a to-do
    texts = [ln.text for ln in state.layout or []]
    convention = document_convention(texts)
    inv, reasons = get_pack(state.doc_type).normalize(state.llm_output or {}, convention=convention,
                                                      date_order=document_date_order(texts))
    state.invoice = inv
    policy.require_review(state, *reasons)
    return state


@action.pydantic(reads=["invoice", "doc_type"], writes=["validation"])
def validate(state: FlowState) -> FlowState:
    from jav.validators import run_all

    state.validation = run_all(state.invoice, get_pack(state.doc_type).validators) if state.invoice else []
    return state


@action.pydantic(
    reads=["arm", "picks", "verdicts", "validation", "invoice", "doc_type", "needs_review", "review_reasons"],
    writes=["route", "needs_review", "review_reasons"],
)
def decide_route(state: FlowState) -> FlowState:
    state.route = policy.decide(state)
    return state


@action.pydantic(reads=["arm", "doc_type", "source_layer_id", "picks", "candidates", "invoice", "verdicts"], writes=["provenance"])
def ground(state: FlowState) -> FlowState:
    """045: per-field source location on the word layer (code, no AI call). S path: the chosen candidate on its own
    line, plus the other candidates with their probabilities; G path: the value is searched for with its label context.
    An error here does not stop the process: the field goes on without a source location (`status=error`), the reason
    is logged."""
    from jav import grounding, source_layer

    pack = get_pack(state.doc_type)
    fields = {f: pack.kind(f) for f in pack.header_fields}
    values = state.invoice.to_datapoints(pack.header_fields) if state.invoice is not None else {}
    try:
        layer = source_layer.load(state.source_layer_id) if state.source_layer_id else None
        if state.arm == "S":
            from jav.jev_select import field_confidence

            conf = field_confidence(state.picks)
            state.provenance = grounding.ground_picks(layer, fields=fields, values=values, picks=state.picks,
                                                      candidates=state.candidates, confidence=conf)
        else:
            flags = state.verdicts.flags if state.verdicts else {}
            conf = {f: round(1 - max(d.values()), 4) for f, d in flags.items() if d}
            state.provenance = grounding.ground_values(layer, fields=fields, values=values, confidence=conf)
        if state.invoice is not None and pack.list_fields:  # 053: locations of the line-item list rows
            record = state.invoice.to_datapoints(pack.record_fields)
            lists = {f: record.get(f) or [] for f in pack.list_fields}
            state.provenance.update(grounding.ground_lists(layer, lists=lists, kinds={f: dict(v) for f, v in pack.list_fields.items()}))
    except Exception as exc:  # noqa: BLE001 - source location is auxiliary; saving the result must not depend on it
        logging.getLogger(__name__).warning("grounding failed for %s: %s", state.doc_id[:12], exc)
        state.provenance = {f: {"status": "error", "method": None, "error": f"{type(exc).__name__}"} for f in fields}
    return state


@action.pydantic(
    reads=["run_id", "doc_id", "doc_type", "arm", "source_path", "has_text_layer", "text_source", "page_count", "invoice", "picks", "verdicts",
           "validation", "route", "review_reasons", "needs_review", "provenance", "source_layer_id"],
    writes=[],
)
def save(state: FlowState) -> FlowState:
    """Durable save: documents + datapoints (+ review_queue if it goes to a person). Idempotent per run_id."""
    pack = get_pack(state.doc_type)
    store.upsert_document(
        doc_id=state.doc_id,
        source_path=state.source_path,
        has_text=state.text_source is not None,  # text layer OR OCR text
        page_count=state.page_count,
        year=_year_hint(state.source_path),
        doc_type=pack.parent or pack.key,  # 047: coarse (M1) category here; the detailed type is in datapoints
        run_id=state.run_id,
    )
    store.review_close(subject_kind="document", subject_id=state.doc_id, producer=policy.OCR_REVIEW_PRODUCER, run_id=state.run_id)  # 066: there is text now
    if state.invoice is not None:
        rec_conf = None
        evidence = None
        if state.arm == "S":
            from jav.jev_select import field_confidence, record_conf, site_for

            field_conf = field_confidence(state.picks)
            rec_conf = record_conf(state.picks)
            evidence = {f: {"line_no": p.line_no, "present_p": p.present_p} for f, p in state.picks.items() if p.n_options > 0}
            config_hash = site_for(pack.key).config_hash
        else:
            from jav.jev_verify import site_for as verify_site_for

            field_conf = {f: max(d.values()) for f, d in (state.verdicts.flags.items() if state.verdicts else [])}
            # 085: without a JEV verification the result rests on the pack (extraction, code checks), not on the call site
            code_only = state.verdicts is not None and state.verdicts.source == "code"
            config_hash = cfg.combine(pack.config_hash, "code_verify") if code_only else verify_site_for(pack.key).config_hash
        store.insert_datapoints(
            run_id=state.run_id,
            doc_id=state.doc_id,
            doc_type=state.doc_type,
            arm=state.arm,
            datapoints=state.invoice.to_datapoints(pack.record_fields),
            field_conf=field_conf,
            validation=[v.model_dump() for v in state.validation],
            route=state.route,
            review_reasons=state.review_reasons,
            final_status="needs_review" if state.needs_review else "done",
            config_hash=datapoint_config_hash(config_hash),
            record_conf=rec_conf,
            evidence=evidence,
            provenance=state.provenance or None,
            source_layer_id=state.source_layer_id,
        )
    if state.needs_review:
        store.review_enqueue(
            subject_kind="document",
            subject_id=state.doc_id,
            run_id=state.run_id,
            reasons=state.review_reasons,
            producer=f"m2:{state.arm}",
            payload={"arm": state.arm, "doc_type": state.doc_type, "datapoints": state.invoice.to_datapoints(pack.record_fields) if state.invoice else None},
        )
    return state


@action.pydantic(reads=[], writes=["final_status"])
def done(state: FlowState) -> FlowState:
    state.final_status = "done"
    return state


@action.pydantic(reads=[], writes=["final_status"])
def needs_review(state: FlowState) -> FlowState:
    state.final_status = "needs_review"
    return state


@action.pydantic(reads=["run_id", "doc_id", "source_path", "page_count", "doc_type", "review_reasons"], writes=["final_status", "route"])
def needs_ocr(state: FlowState) -> FlowState:
    state.final_status = "needs_ocr"
    state.route = "ocr"
    store.upsert_document(
        doc_id=state.doc_id, source_path=state.source_path, has_text=False, page_count=state.page_count,
        year=_year_hint(state.source_path), doc_type=get_pack(state.doc_type).parent or state.doc_type, run_id=state.run_id,
    )
    # 066 Á01: a document without text is a to-do, else the run would be "done" and approvable with nothing extracted
    store.review_enqueue(subject_kind="document", subject_id=state.doc_id, run_id=state.run_id, producer=policy.OCR_REVIEW_PRODUCER,
                         reasons=[r for r in state.review_reasons if r.startswith("ocr:")] or ["ocr:no_text"])
    return state


TRANSITIONS = [
    ("load_pdf", "ocr_pdf", when(has_text_layer=False)),
    ("load_pdf", "find_candidates", when(arm="S")),
    ("load_pdf", "extract_llm", when(arm="G")),
    ("ocr_pdf", "needs_ocr", expr("text_source != 'ocr'")),
    ("ocr_pdf", "find_candidates", when(arm="S")),
    ("ocr_pdf", "extract_llm", when(arm="G")),
    ("find_candidates", "jev_select"),
    ("jev_select", "normalize_picks"),
    ("normalize_picks", "validate"),
    ("extract_llm", "code_verify", expr("llm_output is not None and not jev")),
    ("extract_llm", "jev_verify", expr("llm_output is not None")),
    ("extract_llm", "decide_route", default),
    ("jev_verify", "normalize_llm"),
    ("code_verify", "normalize_llm"),
    ("normalize_llm", "validate"),
    ("validate", "decide_route"),
    ("decide_route", "ground"),
    ("ground", "save"),
    ("save", "done", when(route="auto")),
    ("save", "needs_review", default),
]

CONTRACT = {  # graph declaration: FLOW.md + Mermaid + lint come from it (jav/contract.py, `python -m jav.cli flows`)
    "name": "invoice",
    "phases": ["load", "extract", "normalize", "decide", "persist", "terminal"],
    "steps": [
        ("load_pdf", "load"), ("ocr_pdf", "load"),
        ("find_candidates", "extract"), ("jev_select", "extract"), ("extract_llm", "extract"), ("jev_verify", "extract"), ("code_verify", "extract"),
        ("normalize_picks", "normalize"), ("normalize_llm", "normalize"),
        ("validate", "decide"), ("decide_route", "decide"),
        ("ground", "persist"), ("save", "persist"),
        ("done", "terminal"), ("needs_review", "terminal"), ("needs_ocr", "terminal"),
    ],
    "edges": [
        ("load_pdf", "ocr_pdf", "nincs szövegréteg"), ("load_pdf", "find_candidates", "S-kar"), ("load_pdf", "extract_llm", "G-kar"),
        ("ocr_pdf", "needs_ocr", "nincs OCR / nincs szöveg"), ("ocr_pdf", "find_candidates", "S-kar"), ("ocr_pdf", "extract_llm", "G-kar"),
        ("find_candidates", "jev_select"), ("jev_select", "normalize_picks"), ("normalize_picks", "validate"),
        ("extract_llm", "code_verify", "extract, without JEV"), ("extract_llm", "jev_verify", "van kivonat"),
        ("extract_llm", "decide_route", "LLM-hiba"),
        ("jev_verify", "normalize_llm"), ("code_verify", "normalize_llm"), ("normalize_llm", "validate"),
        ("validate", "decide_route"), ("decide_route", "ground"), ("ground", "save"),
        ("save", "done", "route auto"), ("save", "needs_review", "különben"),
    ],
    "step_meta": {
        "load_pdf": {"kind": "det", "note": "pdfplumber szó-szintű rekonstrukció, sha256 doc_id; szövegréteg-teszt; a szóréteg (szókeretek) mentése"},
        "ocr_pdf": {"kind": "det", "note": "szöveg nélküli PDF: oldalkép (pypdfium2) + tesseract szó-dobozok (natív / régi sidecar-kép) -> ugyanaz a sor- és cella-építés; a szóréteg mentése; lemez-gyorsítótár runs/ocr/; minőségjelek nyersen, gyenge OCR review-ok (policy ocr)"},
        "find_candidates": {"kind": "det", "note": "S-kar: determinisztikus, sorrendezett, maszkoló jelöltkeresők a csomag jelölt-profiljával (hu / intl): iban -> tax_id -> date -> invoice_number -> money; nevek/címek cellákon"},
        "jev_select": {"kind": "jev", "note": "S-kar: kötegelt Choice-kérések (parties / header / money) a csomag select-hívási helyéről, fókuszált state, none mindig opció, jelenlét-Noul mezőnként (jelölt nélkül is, a vizsgált nem kötelező mezőkre, csak meglévő kérésben)"},
        "extract_llm": {"kind": "llm", "note": "G-kar: gpt kivonat a csomag régi promptjával + sémájával (Pydantic AI), az egyetlen generatív lépés"},
        "jev_verify": {"kind": "jev", "note": "G-kar: evidencia-illesztés kódban (unsupported), majd Noul fan-out egy kérésben (off_target, wrong_kind, incomplete, absence_wrong, parties_swapped, tételsorok) a csomag verify-hívási helyéről"},
        "code_verify": {"kind": "det", "note": "085: the G path without JEV: the code's own source check only (every extracted value must be printed on the document, otherwise a source:not_found to-do); no JEV question"},
        "normalize_picks": {"kind": "det", "note": "S-kar: label -> típusos érték a csomag mező-fajtái szerint (Decimal, date), kód-oldali konzisztencia-okok"},
        "normalize_llm": {"kind": "det", "note": "G-kar: kivonat-szótár -> normalizált rekord a csomag mező-fajtái szerint"},
        "validate": {"kind": "det", "note": "a csomag validátor-listája (a régi rules.json): áfa-egyenlet, dátumsorrend, adószám-ellenőrzőszám, IBAN mod-97, formátum-regexek"},
        "decide_route": {"kind": "det", "note": "policy.decide: küszöbök (configs/policy.json), a csomag kötelező / magas tétű mezői, additív review-latch -> auto | human"},
        "ground": {"kind": "det", "note": "mezőnkénti forráshely a szórétegen (S: a kiválasztott jelölt sora + a többi jelölt; G: kódos keresés címkével, configs/grounding.json); hiba esetén forráshely nélkül tovább"},
        "save": {"kind": "store", "note": "documents + datapoints (mezőnkénti confidence, a hívási hely config_hash-e) + review_queue"},
        "done": {"kind": "terminal", "note": "auto - elfogadva"},
        "needs_review": {"kind": "terminal", "note": "human - review-sorban, okokkal"},
        "needs_ocr": {"kind": "terminal", "note": "szöveg nélküli PDF, és az OCR sem adott használható szöveget (vagy nincs OCR-motor): documents has_text=0; teendő (felvevő `ocr`, ocr:*), a szöveges mentés zárja"},
    },
    "terminals": TERMINALS,
    "doc_note": "M2 invoice - két kar egy gráfban (S = jelöltek + Jev Choice, G = gpt + Jev Noul); egyetértés = auto, eltérés = review. Típus-független: a típus-csomag (configs/types/<típus>.json: invoice_hu, invoice_foreign, a közmű-számlák) adja a mezőket, kérdéseket, promptot, validátorokat. Szöveg nélküli PDF-nél OCR-lépés (ocr_pdf) ugyanarra az elrendezésre. Minden AI-hívás az adapteren (cache + ledger + config_hash).",
}


def datapoint_config_hash(site_hash: str) -> str:
    """067 (066 Á18): a saved data point's config hash combines the call site's (with pack and instruction) and the
    policy's: the bands and thresholds also shape the result (to-do, route)."""
    return cfg.combine(site_hash, policy.CONFIG_HASH)


def new_run_id(case_id: str, arm: str, run_no: int) -> str:
    return f"{case_id}-{arm}-r{run_no}-{uuid.uuid4().hex[:8]}"


def build_app(
    source_path: str, case_id: str, arm: str, run_no: int = 1, tracker: bool = True, use_cache: bool = True, doc_type: str = DEFAULT_KEY,
    *, run_id: str | None = None, persister=None, read_path: str | None = None, jev: bool = True,
) -> Application:
    """`persister` (040 K1, supplied by the worker): durable state persistence after every step; with the same `run_id`
    the run resumes at the next step. Without it, the earlier behaviour: a new identifier, no persistence.
    `read_path`: the document's bytes are read from here (its source instance); everything else uses `source_path`.
    `jev=False` (085): processing without JEV: only the G path, verified by the code alone (`code_verify`)."""
    pack = get_pack(doc_type)  # unknown type pack -> error right here, not in the middle of the graph
    if arm not in pack.arms:
        raise ValueError(f"a(z) {doc_type} típus-csomag csak ezekkel a karokkal fut: {', '.join(pack.arms)} (kért: {arm})")
    if not jev and arm != "G":
        raise ValueError(f"without JEV only the G path runs (requested: {arm})")
    run_id = run_id or new_run_id(case_id, arm, run_no)
    initial = FlowState(source_path=source_path, read_path=read_path, case_id=case_id, arm=arm, run_no=run_no, run_id=run_id,
                        use_cache=use_cache, doc_type=doc_type, jev=jev)
    builder = (
        ApplicationBuilder()
        .with_typing(PydanticTypingSystem(FlowState))
        .with_actions(
            load_pdf, ocr_pdf, find_candidates, jev_select, normalize_picks, extract_llm, jev_verify, code_verify, normalize_llm,
            validate, decide_route, ground, save, done, needs_review, needs_ocr,
        )
        .with_transitions(*TRANSITIONS)
        .with_identifiers(app_id=run_id, partition_key=PARTITION if persister is not None else None)
    )
    if persister is not None:
        builder = (builder.initialize_from(persister, resume_at_next_action=True, default_state=initial.model_dump(),
                                           default_entrypoint="load_pdf").with_state_persister(persister))
    else:
        builder = builder.with_state(initial).with_entrypoint("load_pdf")
    if tracker:
        builder = builder.with_tracker("local", project=tracker_project(doc_type))
    return builder.build()


def run_one(
    source_path: str, case_id: str, arm: str, run_no: int = 1, tracker: bool = True, use_cache: bool = True, doc_type: str = DEFAULT_KEY
) -> FlowState:
    app = build_app(source_path, case_id, arm, run_no=run_no, tracker=tracker, use_cache=use_cache, doc_type=doc_type)
    _, _, state = app.run(halt_after=TERMINALS)
    return state.data
