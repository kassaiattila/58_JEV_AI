"""M1 Burr-flow: `load_pdf → detect → save → done`, szöveg nélküli PDF → `ocr_pdf` (OCR-szöveg ugyanoda) vagy `needs_ocr`.

Külön, kicsi gráf (nem a számla-flow része): a kategória a `documents` táblába kerül, és később a típus szerinti
M2-flow onnan indul. A `run_id` itt is a gerinc; a Jev-hívás az adapteren megy (cache + ledger).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from burr.core import ApplicationBuilder, action, default, expr, when
from burr.core.application import Application
from burr.integrations.pydantic import PydanticTypingSystem
from pydantic import BaseModel, Field

from jav import policy, store
from jav.detect import DetectResult
from jav.detect_detail import DetailResult
from jav.models import LineLayout

TERMINALS = ["done", "needs_ocr"]
PARTITION = "doc_detect"  # a tartós állapotmentés partíciója (066 Á08: a feldolgozó ezzel keresi a mentett állapotot)
TRACKER_PROJECT = "jav_doc_detect"
LOW_CONFIDENCE = policy.DETECT_LOW_CONFIDENCE  # configs/policy.json `bands` (detect.doc_type): ez alatt a típus bizonytalan (review-jelölt), de mentjük


class DetectState(BaseModel):
    source_path: str
    run_id: str = ""
    use_cache: bool = True
    doc_id: str = ""
    text: str = ""
    lines: list[str] = Field(default_factory=list)
    layout: list[LineLayout] = Field(default_factory=list)
    page_count: int = 0
    has_text_layer: bool = False
    text_source: str | None = None  # "pdf" | "ocr" | None
    ocr_conf: float | None = None
    ocr_low_conf_ratio: float | None = None
    year: int | None = None
    result: DetectResult | None = None
    detail: DetailResult | None = None  # 047 T1.2: részletes típus a durva kategórián belül
    detail_reasons: list[str] = Field(default_factory=list)
    uncertain: bool = False
    review_reasons: list[str] = Field(default_factory=list)  # additív; ma: jev_unavailable:<ok>
    final_status: str | None = None


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _year_hint(path: str) -> int | None:
    parts = Path(path).parts
    for part in reversed(parts[:-1]):  # mappa-név (Bejövő/2023/...) elsőbbséget kap
        if re.fullmatch(r"20\d{2}", part):
            return int(part)
    m = re.search(r"(20\d{2})", Path(path).name)
    return int(m.group(1)) if m else None


@action.pydantic(reads=["source_path"], writes=["text", "lines", "layout", "page_count", "has_text_layer", "text_source", "doc_id", "year"])
def load_pdf(state: DetectState) -> DetectState:
    from jav.pdf import read_pdf

    pdf = read_pdf(state.source_path)
    state.text, state.lines, state.layout = pdf.text, pdf.lines, pdf.layout
    state.page_count, state.has_text_layer, state.text_source = pdf.page_count, pdf.has_text_layer, pdf.text_source
    state.doc_id = _sha256(state.source_path)
    state.year = _year_hint(state.source_path)
    return state


@action.pydantic(reads=["source_path", "page_count", "review_reasons"], writes=["text", "lines", "layout", "text_source", "ocr_conf", "ocr_low_conf_ratio", "review_reasons"])
def ocr_pdf(state: DetectState) -> DetectState:
    """Szöveg nélküli PDF: OCR (jav/ocr.py, gyorsítótárral) ugyanarra az elrendezésre; nincs motor / szöveg -> `needs_ocr`."""
    from jav.ocr import OcrUnavailableError, ocr_with_escalation

    try:
        pdf, _escalated = ocr_with_escalation(state.source_path, page_count=state.page_count)
    except OcrUnavailableError as exc:
        state.review_reasons = state.review_reasons + [f"ocr:unavailable:{type(exc).__name__}"]
        return state
    state.text, state.lines, state.layout, state.text_source = pdf.text, pdf.lines, pdf.layout, pdf.text_source
    signals = pdf.ocr or {}
    state.ocr_conf, state.ocr_low_conf_ratio = signals.get("mean_conf"), signals.get("low_conf_ratio")
    if pdf.text_source is None:
        state.review_reasons = state.review_reasons + ["ocr:no_text"]
    state.review_reasons = state.review_reasons + [
        r for r in policy.ocr_coverage_reasons(state.page_count, signals.get("pages_ocr")) if r not in state.review_reasons]
    return state


@action.pydantic(reads=["source_path", "text", "lines", "layout", "page_count", "run_id", "use_cache", "review_reasons"],
                 writes=["result", "uncertain", "review_reasons", "detail", "detail_reasons"])
def detect(state: DetectState) -> DetectState:
    from jav.adapters.jev import JevUnavailableError, get_adapter
    from jav.detect import detect as _detect
    from jav.pdf import PdfText

    pdf = PdfText(path=state.source_path, text=state.text, lines=state.lines, layout=state.layout, page_count=state.page_count, has_text_layer=True)
    try:
        state.result = _detect(get_adapter(), pdf, state.source_path, run_id=state.run_id, use_cache=state.use_cache)
    except JevUnavailableError as exc:  # a Jev nem elérhető (ledgerben): típus nélkül, kézi sorba; a bejárás később újrafuttatja
        state.result = None
        state.uncertain = True
        state.review_reasons = state.review_reasons + [f"jev_unavailable:{exc.reason}"]
        return state
    r = state.result
    state.uncertain = policy.choice_needs_review(r.confidence, r.probabilities, "detect.doc_type") or r.doc_type == "unknown"
    if r.doc_type != "unknown":
        _resolve_detail(state, get_adapter())
    return state


def _resolve_detail(state: DetectState, jev) -> None:
    """047 T1.2: a részletes típus (`jav/detect_detail.py`). Nyitva maradt vagy bizonytalan részletes típus teendő a
    felismerés saját okai mellett; a JEV kiesése itt sem állítja meg a folyamatot."""
    from jav.adapters.jev import JevUnavailableError
    from jav.detect_detail import resolve

    broad = state.result.doc_type
    try:
        d = resolve(broad, state.text, jev=jev, run_id=state.run_id, use_cache=state.use_cache)
    except JevUnavailableError as exc:
        d = DetailResult(broad=broad, key=None, method="no_jev")
        state.detail_reasons = [f"jev_unavailable:{exc.reason}"]
    state.detail = d
    if d.method == "no_candidate":  # 069: a kategóriához nincs típuscsomag (fizetési felszólítás, ismeretlen): nincs kinyerés
        state.detail_reasons = state.detail_reasons + [f"detect:no_type_pack:{broad}"]
        return
    if d.key is None:
        state.detail_reasons = state.detail_reasons + [f"detect:detail_open:{broad}"]
    elif d.method == "jev":
        reason = policy.choice_review_reason("detect_detail", d.key, d.confidence or 0.0, d.probabilities, "detect.detail_type")
        if reason:
            state.detail_reasons = state.detail_reasons + [reason]


@action.pydantic(reads=["doc_id", "source_path", "has_text_layer", "text_source", "page_count", "year", "result", "run_id", "uncertain",
                        "review_reasons", "detail", "detail_reasons"], writes=["final_status"])
def save(state: DetectState) -> DetectState:
    r, d = state.result, state.detail
    store.upsert_document(
        doc_id=state.doc_id, source_path=state.source_path, has_text=state.text_source is not None, page_count=state.page_count,
        year=state.year, doc_type=r.doc_type if r else None, type_conf=r.confidence if r else None,
        issuer_hu=r.issuer_hu if r else None, run_id=state.run_id,
        detail_type=d.key if d else None, detail_conf=d.confidence if d else None, detail_method=d.method if d else None,
    )
    store.review_close(subject_kind="document", subject_id=state.doc_id, producer=policy.OCR_REVIEW_PRODUCER, run_id=state.run_id)  # 066: most van szöveg
    # 047: a részletes típus saját felvevővel (a durva típus okaitól függetlenül zárul)
    if state.detail_reasons:
        store.review_enqueue(subject_kind="document", subject_id=state.doc_id, run_id=state.run_id, producer="detect_detail",
                             reasons=state.detail_reasons, payload={"detail": d.model_dump() if d else None})
    elif d is not None:
        store.review_close(subject_kind="document", subject_id=state.doc_id, producer="detect_detail", run_id=state.run_id)
    if state.uncertain and r is not None:
        store.review_enqueue(
            subject_kind="document", subject_id=state.doc_id, run_id=state.run_id, producer="detect",
            reasons=[f"detect:low_conf:{r.doc_type}:{r.confidence:.2f}"],
            payload={"probabilities": r.probabilities, "issuer_hu": r.issuer_hu, "language": r.language,
                     "parent": policy.parent_fallback(r.confidence, r.parent, r.parent_prob, "detect.doc_type", r.probabilities), "parent_prob": r.parent_prob},
        )
    elif r is None:
        store.review_enqueue(subject_kind="document", subject_id=state.doc_id, run_id=state.run_id, producer="detect",
                             reasons=list(state.review_reasons) or ["detect:no_result"])
    else:
        # újrafuttatás után már biztos a típus: a detect saját korábbi okai (hiba is) okafogyottak, másoké nyitva marad
        store.review_close(subject_kind="document", subject_id=state.doc_id, producer="detect", run_id=state.run_id)
    # Részleges OCR (F07): a típus lehet biztos, a kihagyott oldalak ettől még teendők; külön felvevő, hogy ne záródjon a detecttel.
    coverage = [x for x in state.review_reasons if x.startswith("ocr:partial_pages:")]
    if coverage:
        store.review_enqueue(subject_kind="document", subject_id=state.doc_id, run_id=state.run_id, producer="ocr_coverage", reasons=coverage)
    else:
        store.review_close(subject_kind="document", subject_id=state.doc_id, producer="ocr_coverage", run_id=state.run_id)
    state.final_status = "done" if r is not None else "jev_unavailable"
    return state


@action.pydantic(reads=[], writes=[])
def done(state: DetectState) -> DetectState:
    return state


@action.pydantic(reads=["doc_id", "source_path", "page_count", "year", "run_id", "review_reasons"], writes=["final_status"])
def needs_ocr(state: DetectState) -> DetectState:
    store.upsert_document(doc_id=state.doc_id, source_path=state.source_path, has_text=False, page_count=state.page_count, year=state.year, run_id=state.run_id)
    # 066 Á01: a szöveg nélküli irat teendő (a felvevő közös az M2-vel, szöveg esetén zárul)
    store.review_enqueue(subject_kind="document", subject_id=state.doc_id, run_id=state.run_id, producer=policy.OCR_REVIEW_PRODUCER,
                         reasons=[r for r in state.review_reasons if r.startswith("ocr:")] or ["ocr:no_text"])
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

CONTRACT = {  # a gráf deklarációja: FLOW.md + Mermaid + lint ebből (jav/contract.py, `python -m jav.cli flows`)
    "name": "doc_detect",
    "phases": ["load", "classify", "persist", "terminal"],
    "steps": [("load_pdf", "load"), ("ocr_pdf", "load"), ("detect", "classify"), ("save", "persist"), ("done", "terminal"), ("needs_ocr", "terminal")],
    "edges": [("load_pdf", "ocr_pdf", "nincs szövegréteg"), ("load_pdf", "detect"), ("ocr_pdf", "needs_ocr", "nincs OCR / nincs szöveg"), ("ocr_pdf", "detect", "OCR-szöveg"),
              ("detect", "save"), ("save", "done")],
    "step_meta": {
        "load_pdf": {"kind": "det", "note": "pdfplumber szó-szintű rekonstrukció, sha256 doc_id, év-hint a mappából; szövegréteg-teszt"},
        "ocr_pdf": {"kind": "det", "note": "szöveg nélküli PDF: OCR (jav/ocr.py: oldalkép + tesseract, natív / régi sidecar-kép, lemez-gyorsítótár) ugyanarra az elrendezésre; minőségjelek a state-ben"},
        "detect": {"kind": "jev", "note": "egy kérés, három ítélet: Choice doc_type (regiszter + unknown), Noul issuer_is_hungarian, Choice language; anchor-találatok feature-ként; 047: utána részletes típus a kategória csomagjai közül (jav/detect_detail.py: régi horgony-pontszám, szükség esetén JEV Choice)"},
        "save": {"kind": "store", "note": "documents tábla (047: részletes típus is; nyitva maradt részletes típus = detect_detail teendő; 069: a típuscsomag nélküli kategória is); conf < policy.detect.low_confidence -> review_queue (okonként, additív), különben a detect saját korábbi okai zárulnak"},
        "done": {"kind": "terminal", "note": "kategorizálva"},
        "needs_ocr": {"kind": "terminal", "note": "szöveg nélküli / törött szövegrétegű PDF, és az OCR sem adott szöveget (vagy nincs motor): documents has_text=0; 066: teendő (felvevő `ocr`, ocr:*), a szöveges mentés zárja"},
    },
    "terminals": TERMINALS,
    "doc_note": "M1 - a típus a documents táblába kerül; a típus szerinti M2-flow onnan indul. A run_id a gerinc, a Jev-hívás az adapteren megy (cache + ledger + config_hash).",
}


def build_app(source_path: str, *, tracker: bool = False, use_cache: bool = True, run_id: str | None = None,
              persister=None) -> Application:
    """`persister` (040 K1): tartós állapotmentés, ugyanazzal a `run_id`-vel folytatás; nélküle a korábbi viselkedés."""
    run_id = run_id or f"detect-{Path(source_path).stem[:24]}-{uuid.uuid4().hex[:8]}"
    initial = DetectState(source_path=source_path, run_id=run_id, use_cache=use_cache)
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
    return b.build()


def run_detect(source_path: str, *, tracker: bool = False, use_cache: bool = True, run_id: str | None = None) -> DetectState:
    """`run_id` (065): egy másik folyamatból hívva annak azonosítója alatt naplóz és vesz fel teendőt."""
    app = build_app(source_path, tracker=tracker, use_cache=use_cache, run_id=run_id)
    _, _, state = app.run(halt_after=TERMINALS)
    return state.data
