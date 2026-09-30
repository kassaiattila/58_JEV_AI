"""Burr állapotgép: egy számla-típusú dokumentum feldolgozása az S- (select) vagy G- (generate+verify) karon.

    load_pdf ─┬─ ocr_pdf ─── needs_ocr                       (nincs szövegréteg; OCR nem elérhető / nem adott szöveget)
              │     ├─────────────────────────────┐          (OCR-szöveg: ugyanoda, mint a szövegréteg)
              ├─ find_candidates → jev_select → normalize_picks ─┐        [S]
              └─ extract_llm ─┬─ jev_verify → normalize_llm ─────┤        [G]
                              └─ decide_route (LLM-hiba)         │
                                                    validate ←───┘
                                                    decide_route → save ─┬─ done
                                                                         └─ needs_review

Tipizált Pydantic állapot (`FlowState`), `@action.pydantic` akciók. Minden AI-hívás az adapter-rétegen megy
(`jav.adapters`), a `run_id` a gerinc: ledger, datapoints, review_queue erre hivatkozik. A review-latch additív.

A gráf típus-független: a `state.doc_type` típus-csomagja (`jav/typepack.py`, `configs/types/<típus>.json`) adja a
mezőlistát, a jelölt-profilt, a hívási helyeket, a promptot / sémát, a validátorokat és a kötelező / magas tétű mezőket.
Ma két csomag fut rajta: `invoice_hu` (magyar számla) és `invoice_foreign` (külföldi számla, 2026-09-20 portolás).
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
PARTITION = "invoice"  # a tartós állapotmentés partíciója (066 Á08: a feldolgozó ezzel keresi a mentett állapotot)
TRACKER_PROJECT = TRACKER_PROJECTS.get("invoice_hu", "jav_invoice_hu")  # örökölt név; típusonként: `tracker_project(doc_type)`


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


# --- akciók ----------------------------------------------------------------------------


@action.pydantic(reads=["source_path"], writes=["text", "lines", "page_count", "has_text_layer", "layout", "doc_id", "text_source",
                                                "source_layer_id"])
def load_pdf(state: FlowState) -> FlowState:
    from jav import source_layer
    from jav.pdf import read_pdf

    pdf = read_pdf(state.source_path)
    state.text = pdf.text
    state.lines = pdf.lines
    state.layout = pdf.layout
    state.page_count = pdf.page_count
    state.has_text_layer = pdf.has_text_layer
    state.text_source = pdf.text_source
    state.doc_id = _sha256(state.source_path)
    if pdf.has_text_layer:  # szöveg nélküli PDF-nél az OCR-lépés menti a réteget
        state.source_layer_id = source_layer.save_from_pdftext(state.doc_id, pdf)
    return state


@action.pydantic(
    reads=["source_path", "page_count", "doc_id", "needs_review", "review_reasons"],
    writes=["text", "lines", "layout", "text_source", "ocr_conf", "ocr_low_conf_ratio", "ocr_engine", "ocr_escalated", "needs_review", "review_reasons",
            "source_layer_id"],
)
def ocr_pdf(state: FlowState) -> FlowState:
    """Szöveg nélküli PDF: OCR (jav/ocr.py, lemez-gyorsítótárral) -> ugyanaz az elrendezés (sorok, cellák), mint a szövegrétegnél.
    Az OCR minőségjelei nyersen a state-be; a gyenge OCR review-ok a policy `ocr` küszöbei szerint. Ha nincs motor / nincs
    használható szöveg: `text_source` marad None -> `needs_ocr` terminális (a flow nem dől el)."""
    from jav.ocr import OcrUnavailableError, ocr_with_escalation

    try:
        pdf, escalated = ocr_with_escalation(state.source_path, page_count=state.page_count)
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
    except JevUnavailableError as exc:  # a Jev nem elérhető (ledgerben): nincs pick, a rekord kézi sorba megy, a flow nem dől el
        picks, calls = {}, []
        policy.require_review(state, f"jev_unavailable:{exc.reason}")
    state.picks = picks
    state.jev_calls = state.jev_calls + calls
    return state


@action.pydantic(reads=["picks", "candidates", "doc_type", "needs_review", "review_reasons"], writes=["invoice", "needs_review", "review_reasons"])
def normalize_picks(state: FlowState) -> FlowState:
    from jav.jev_select import picks_to_invoice

    inv, reasons = picks_to_invoice(state.picks, state.candidates, pack=get_pack(state.doc_type))
    state.invoice = inv
    policy.require_review(state, *reasons)
    return state


@action.pydantic(reads=["text", "run_id", "doc_type", "needs_review", "review_reasons"], writes=["llm_output", "needs_review", "review_reasons"])
def extract_llm(state: FlowState) -> FlowState:
    from jav.extract_llm import extract

    try:
        state.llm_output = extract(state.text, run_id=state.run_id, pack=get_pack(state.doc_type))
    except Exception as exc:  # noqa: BLE001 - a hiba review-ok, nem flow-halál
        state.llm_output = None
        policy.require_review(state, f"llm:failed:{type(exc).__name__}")
    return state


@action.pydantic(reads=["layout", "llm_output", "run_id", "use_cache", "doc_type", "needs_review", "review_reasons"], writes=["verdicts", "jev_calls", "needs_review", "review_reasons"])
def jev_verify(state: FlowState) -> FlowState:
    from jav.adapters.jev import JevUnavailableError, get_adapter
    from jav.jev_verify import verify

    try:
        verdicts, call = verify(get_adapter(), state.layout, state.llm_output or {}, run_id=state.run_id, use_cache=state.use_cache, pack=get_pack(state.doc_type))
    except JevUnavailableError as exc:  # ellenőrzés nélkül a kivonat nem fogadható el automatikusan
        state.verdicts = None
        policy.require_review(state, f"jev_unavailable:{exc.reason}")
        return state
    state.verdicts = verdicts
    state.jev_calls = state.jev_calls + [call]
    return state


@action.pydantic(reads=["llm_output", "doc_type", "needs_review", "review_reasons"], writes=["invoice", "needs_review", "review_reasons"])
def normalize_llm(state: FlowState) -> FlowState:
    inv, reasons = get_pack(state.doc_type).normalize(state.llm_output or {})
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
    """045: mezőnkénti forráshely a szórétegen (kód, AI-hívás nélkül). S-út: a kiválasztott jelölt a saját sorában, és a
    többi jelölt a valószínűségével; G-út: az érték keresése a címke-környezettel. Hiba itt nem állítja meg a folyamatot:
    a mező forráshely nélkül (`status=error`) megy tovább, az ok a naplóban."""
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
        if state.invoice is not None and pack.list_fields:  # 053: a tételes listák sorainak helye
            record = state.invoice.to_datapoints(pack.record_fields)
            lists = {f: record.get(f) or [] for f in pack.list_fields}
            state.provenance.update(grounding.ground_lists(layer, lists=lists, kinds={f: dict(v) for f, v in pack.list_fields.items()}))
    except Exception as exc:  # noqa: BLE001 - a forráshely segédadat; a kinyert eredmény mentése nem múlhat rajta
        logging.getLogger(__name__).warning("grounding failed for %s: %s", state.doc_id[:12], exc)
        state.provenance = {f: {"status": "error", "method": None, "error": f"{type(exc).__name__}"} for f in fields}
    return state


@action.pydantic(
    reads=["run_id", "doc_id", "doc_type", "arm", "source_path", "has_text_layer", "text_source", "page_count", "invoice", "picks", "verdicts",
           "validation", "route", "review_reasons", "needs_review", "provenance", "source_layer_id"],
    writes=[],
)
def save(state: FlowState) -> FlowState:
    """Tartós mentés: documents + datapoints (+ review_queue, ha emberhez megy). Idempotens run_id-ra."""
    pack = get_pack(state.doc_type)
    store.upsert_document(
        doc_id=state.doc_id,
        source_path=state.source_path,
        has_text=state.text_source is not None,  # szövegréteg VAGY OCR-szöveg
        page_count=state.page_count,
        year=_year_hint(state.source_path),
        doc_type=pack.parent or pack.key,  # 047: a documents.doc_type a durva (M1) kategória; a részletes típus a datapoints-ban
        run_id=state.run_id,
    )
    store.review_close(subject_kind="document", subject_id=state.doc_id, producer=policy.OCR_REVIEW_PRODUCER, run_id=state.run_id)  # 066: most van szöveg
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
            config_hash = verify_site_for(pack.key).config_hash
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
    # 066 Á01: a szöveg nélküli irat teendő, különben a futás „kész” lenne és jóváhagyható, pedig semmit nem nyert ki
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
    ("extract_llm", "jev_verify", expr("llm_output is not None")),
    ("extract_llm", "decide_route", default),
    ("jev_verify", "normalize_llm"),
    ("normalize_llm", "validate"),
    ("validate", "decide_route"),
    ("decide_route", "ground"),
    ("ground", "save"),
    ("save", "done", when(route="auto")),
    ("save", "needs_review", default),
]

CONTRACT = {  # a gráf deklarációja: FLOW.md + Mermaid + lint ebből (jav/contract.py, `python -m jav.cli flows`)
    "name": "invoice",
    "phases": ["load", "extract", "normalize", "decide", "persist", "terminal"],
    "steps": [
        ("load_pdf", "load"), ("ocr_pdf", "load"),
        ("find_candidates", "extract"), ("jev_select", "extract"), ("extract_llm", "extract"), ("jev_verify", "extract"),
        ("normalize_picks", "normalize"), ("normalize_llm", "normalize"),
        ("validate", "decide"), ("decide_route", "decide"),
        ("ground", "persist"), ("save", "persist"),
        ("done", "terminal"), ("needs_review", "terminal"), ("needs_ocr", "terminal"),
    ],
    "edges": [
        ("load_pdf", "ocr_pdf", "nincs szövegréteg"), ("load_pdf", "find_candidates", "S-kar"), ("load_pdf", "extract_llm", "G-kar"),
        ("ocr_pdf", "needs_ocr", "nincs OCR / nincs szöveg"), ("ocr_pdf", "find_candidates", "S-kar"), ("ocr_pdf", "extract_llm", "G-kar"),
        ("find_candidates", "jev_select"), ("jev_select", "normalize_picks"), ("normalize_picks", "validate"),
        ("extract_llm", "jev_verify", "van kivonat"), ("extract_llm", "decide_route", "LLM-hiba"),
        ("jev_verify", "normalize_llm"), ("normalize_llm", "validate"),
        ("validate", "decide_route"), ("decide_route", "ground"), ("ground", "save"),
        ("save", "done", "route auto"), ("save", "needs_review", "különben"),
    ],
    "step_meta": {
        "load_pdf": {"kind": "det", "note": "pdfplumber szó-szintű rekonstrukció, sha256 doc_id; szövegréteg-teszt; a szóréteg (szókeretek, 045) mentése"},
        "ocr_pdf": {"kind": "det", "note": "szöveg nélküli PDF: oldalkép (pypdfium2) + tesseract szó-dobozok (natív / régi sidecar-kép) -> ugyanaz a sor- és cella-építés; a szóréteg mentése (045); lemez-gyorsítótár runs/ocr/; minőségjelek nyersen, gyenge OCR review-ok (policy ocr)"},
        "find_candidates": {"kind": "det", "note": "S-kar: determinisztikus, sorrendezett, maszkoló jelöltkeresők a csomag jelölt-profiljával (hu / intl): iban -> tax_id -> date -> invoice_number -> money; nevek/címek cellákon"},
        "jev_select": {"kind": "jev", "note": "S-kar: kötegelt Choice-kérések (parties / header / money) a csomag select-hívási helyéről, fókuszált state, none mindig opció, jelenlét-Noul mezőnként (069: jelölt nélkül is, a vizsgált nem kötelező mezőkre, csak meglévő kérésben)"},
        "extract_llm": {"kind": "llm", "note": "G-kar: gpt kivonat a csomag régi promptjával + sémájával (Pydantic AI), az egyetlen generatív lépés"},
        "jev_verify": {"kind": "jev", "note": "G-kar: evidencia-illesztés kódban (unsupported), majd Noul fan-out egy kérésben (off_target, wrong_kind, incomplete, absence_wrong, parties_swapped, tételsorok) a csomag verify-hívási helyéről"},
        "normalize_picks": {"kind": "det", "note": "S-kar: label -> típusos érték a csomag mező-fajtái szerint (Decimal, date), kód-oldali konzisztencia-okok"},
        "normalize_llm": {"kind": "det", "note": "G-kar: kivonat-szótár -> normalizált rekord a csomag mező-fajtái szerint"},
        "validate": {"kind": "det", "note": "a csomag validátor-listája (a régi rules.json): áfa-egyenlet, dátumsorrend, adószám-ellenőrzőszám, IBAN mod-97, formátum-regexek"},
        "decide_route": {"kind": "det", "note": "policy.decide: küszöbök (configs/policy.json), a csomag kötelező / magas tétű mezői, additív review-latch -> auto | human"},
        "ground": {"kind": "det", "note": "045: mezőnkénti forráshely a szórétegen (S: a kiválasztott jelölt sora + a többi jelölt; G: kódos keresés címkével, configs/grounding.json); hiba esetén forráshely nélkül tovább"},
        "save": {"kind": "store", "note": "documents + datapoints (mezőnkénti confidence, a hívási hely config_hash-e) + review_queue"},
        "done": {"kind": "terminal", "note": "auto - elfogadva"},
        "needs_review": {"kind": "terminal", "note": "human - review-sorban, okokkal"},
        "needs_ocr": {"kind": "terminal", "note": "szöveg nélküli PDF, és az OCR sem adott használható szöveget (vagy nincs OCR-motor): documents has_text=0; 066: teendő (felvevő `ocr`, ocr:*), a szöveges mentés zárja"},
    },
    "terminals": TERMINALS,
    "doc_note": "M2 invoice - két kar egy gráfban (S = jelöltek + Jev Choice, G = gpt + Jev Noul); egyetértés = auto, eltérés = review. Típus-független: a típus-csomag (configs/types/<típus>.json: invoice_hu, invoice_foreign, a közmű-számlák) adja a mezőket, kérdéseket, promptot, validátorokat. Szöveg nélküli PDF-nél OCR-lépés (ocr_pdf) ugyanarra az elrendezésre. Minden AI-hívás az adapteren (cache + ledger + config_hash).",
}


def datapoint_config_hash(site_hash: str) -> str:
    """067 (066 Á18): a mentett adatpont azonosítója a hívási helyé (csomaggal, utasítással) és a policy-é együtt:
    a sávok és a küszöbök is az eredmény részei (teendő, útvonal)."""
    return cfg.combine(site_hash, policy.CONFIG_HASH)


def new_run_id(case_id: str, arm: str, run_no: int) -> str:
    return f"{case_id}-{arm}-r{run_no}-{uuid.uuid4().hex[:8]}"


def build_app(
    source_path: str, case_id: str, arm: str, run_no: int = 1, tracker: bool = True, use_cache: bool = True, doc_type: str = DEFAULT_KEY,
    *, run_id: str | None = None, persister=None,
) -> Application:
    """`persister` (040 K1, a feldolgozó adja): tartós állapotmentés lépésenként, ugyanazzal a `run_id`-vel a következő
    lépéstől folytatódik. Nélküle a korábbi viselkedés: új azonosító, mentés nélkül."""
    pack = get_pack(doc_type)  # ismeretlen típus-csomag -> hiba már itt, nem a gráf közepén
    if arm not in pack.arms:
        raise ValueError(f"a(z) {doc_type} típus-csomag csak ezekkel a karokkal fut: {', '.join(pack.arms)} (kért: {arm})")
    run_id = run_id or new_run_id(case_id, arm, run_no)
    initial = FlowState(source_path=source_path, case_id=case_id, arm=arm, run_no=run_no, run_id=run_id, use_cache=use_cache, doc_type=doc_type)
    builder = (
        ApplicationBuilder()
        .with_typing(PydanticTypingSystem(FlowState))
        .with_actions(
            load_pdf, ocr_pdf, find_candidates, jev_select, normalize_picks, extract_llm, jev_verify, normalize_llm,
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
