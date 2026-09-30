"""M3 Burr-flow: `load_message → classify_attachments → intent → route → tasks → save → done`.

- `load_message`: inbox-mappából (`message.json` + fájlok) VAGY kész `EmailMessage`-ből (golden).
- `classify_attachments`: minden fájlként meglévő PDF-en lefut az M1 detect (saját Burr-gráf, a levél run_id-je alatt: `<run_id>-doc_detect`, 065), az
  eredmény (doc_id, doc_type, conf) a csatolmányra kerül és a `documents` táblába (source_email hivatkozással).
  Csak névvel ismert csatolmány (régi golden) -> `name_only`; kép -> `unsupported` (OCR = B5 bővítés).
- `intent`: egy Jev-kérés (Choice + 4 Noul) az adapteren át (cache + ledger).
- `route`: `policy.email_next_flow` - kód dönt az intentből, confidence-ből és a csatolmány-típusokból.
- `save`: `emails` tábla (levelenként a legutóbbi) és `email_results` (a futás saját sora, a levél szövegéből látott
  résszel, 058 K5.1); bizonytalan intent -> review_queue (okonként, additív), biztos -> a saját korábbi okai zárulnak.
"""

from __future__ import annotations

import uuid

from burr.core import ApplicationBuilder, action
from burr.core.application import Application
from burr.integrations.pydantic import PydanticTypingSystem
from pydantic import BaseModel, Field

from jav import policy, store
from jav.emails import DOC_EXTS, EmailMessage, body_coverage, load_message_dir
from jav.intent import IntentResult

TERMINALS = ["done"]
PARTITION = "email_intent"  # a tartós állapotmentés partíciója (066 Á08: a feldolgozó ezzel keresi a mentett állapotot)
TRACKER_PROJECT = "jav_email_intent"


class EmailState(BaseModel):
    source_dir: str | None = None
    run_id: str = ""
    use_cache: bool = True
    detect_attachments: bool = True
    message: EmailMessage | None = None
    result: IntentResult | None = None
    next_flow: str = ""
    uncertain: bool = False
    review_reasons: list[str] = Field(default_factory=list)  # additív; ma: jev_unavailable:<ok>
    final_status: str | None = None
    propose_tasks: bool = False  # 058 K5.3: a recept kéri-e a feladatjavaslatot (alapból nem: GPT-költség)
    tasks: dict | None = None  # a javaslat a kapu után: {status, tasks, rejected} (None = nem kértük)


@action.pydantic(reads=["source_dir", "message"], writes=["message"])
def load_message(state: EmailState) -> EmailState:
    if state.message is None:
        if not state.source_dir:
            raise ValueError("either source_dir or message is required")
        state.message = load_message_dir(state.source_dir)
    return state


@action.pydantic(reads=["message", "run_id", "use_cache", "detect_attachments"], writes=["message"])
def classify_attachments(state: EmailState) -> EmailState:
    msg = state.message
    assert msg is not None
    for att in msg.attachments:
        if att.path is None:
            att.status = "name_only"
            continue
        if att.ext not in DOC_EXTS:
            att.status = "unsupported"
            continue
        if att.ext != ".pdf":
            att.status = "unsupported"  # kép: OCR nélkül nem olvasható (B5)
            continue
        if not state.detect_attachments:
            att.status = "skipped"
            continue
        from jav.flow_detect import run_detect

        # 065: a levél futásazonosítója alatt, különben a csatolmány teendője és költsége a futáson kívülre kerül
        st = run_detect(att.path, use_cache=state.use_cache, run_id=f"{state.run_id}-doc_detect")
        att.doc_id, att.status = st.doc_id, st.final_status
        if st.result is not None:
            att.doc_type, att.type_conf, att.issuer_hu = st.result.doc_type, st.result.confidence, st.result.issuer_hu
        store.upsert_document(doc_id=st.doc_id, source_path=att.path, source_email=msg.message_id, run_id=state.run_id)
    return state


@action.pydantic(reads=["message", "run_id", "use_cache", "review_reasons"], writes=["result", "uncertain", "review_reasons"])
def intent(state: EmailState) -> EmailState:
    from jav.adapters.jev import JevUnavailableError, get_adapter
    from jav.intent import classify

    assert state.message is not None
    try:
        state.result = classify(get_adapter(), state.message, run_id=state.run_id, use_cache=state.use_cache)
    except JevUnavailableError as exc:  # a Jev nem elérhető (ledgerben): szándék nélkül, kézi sorba; a flow nem dől el
        state.result = None
        state.uncertain = True
        state.review_reasons = state.review_reasons + [f"jev_unavailable:{exc.reason}"]
        return state
    state.uncertain = policy.choice_needs_review(state.result.confidence, state.result.probabilities, "email.intent")
    # M3 jelek (v1.1.0): a beszúrt utasítás igen-sávja review-ok (additív, a policy dönti el, mely jel)
    state.review_reasons = state.review_reasons + [r for r in policy.email_signal_reasons(state.result.signals) if r not in state.review_reasons]
    return state


@action.pydantic(reads=["message", "result"], writes=["next_flow"])
def route(state: EmailState) -> EmailState:
    assert state.message is not None
    if state.result is None:
        state.next_flow = policy.EMAIL_JEV_UNAVAILABLE_ROUTE
        return state
    state.next_flow = policy.email_next_flow(
        state.result.intent, state.result.confidence, state.message.attachments, state.result.probabilities, state.result.signals
    )
    return state


@action.pydantic(reads=["message", "result", "next_flow", "run_id", "propose_tasks", "review_reasons"], writes=["tasks", "review_reasons"])
def tasks(state: EmailState) -> EmailState:
    """058 K5.3: feladatjavaslat (GPT, a régi email-actions utasítása) + kódos bizonyíték-kapu. Csak ha a recept kéri, és a
    levél nem archiválandó (kód dönt). Hiba nem dönti el a folyamatot: teendő lesz belőle. Javaslat esetén teendő, mert a
    javaslatot csak ember fogadja el."""
    if not state.propose_tasks:
        return state
    from jav import email_tasks
    from jav.runtime.queue import JobCancelled

    msg = state.message
    assert msg is not None
    skip = email_tasks.skip_reason(state.next_flow, signals=state.result.signals if state.result else None,
                                   has_intent=state.result is not None)
    if skip:
        state.tasks = {"status": "skipped", "reason": skip, "tasks": [], "rejected": []}
        return state
    snap = email_tasks.snapshot(message_id=msg.message_id, subject=msg.subject, body=msg.body, body_status=body_coverage(msg)["status"],
                                attachments=[a.model_dump(exclude={"path"}) for a in msg.attachments])
    hint = {"intent_key": state.result.intent, "confidence": round(state.result.confidence, 3)} if state.result else None
    try:
        raw = email_tasks.extract(snap, intent_hint=hint, run_id=state.run_id)
    except JobCancelled:
        raise
    except Exception as exc:  # noqa: BLE001 - OpenAI / keret / séma hiba: teendő, a szándék-eredmény megmarad
        state.tasks = {"status": "error", "error": type(exc).__name__, "tasks": [], "rejected": []}
        state.review_reasons = state.review_reasons + [f"tasks:failed:{type(exc).__name__}"]
        return state
    accepted, rejected = email_tasks.gate(snap, raw)
    state.tasks = {"status": "proposed", "tasks": accepted, "rejected": rejected, "config_hash": email_tasks.CONFIG_HASH}
    if accepted:
        state.review_reasons = state.review_reasons + [f"tasks:proposed:{len(accepted)}"]
    return state


@action.pydantic(reads=["message", "result", "next_flow", "uncertain", "run_id", "review_reasons", "tasks"], writes=["final_status"])
def save(state: EmailState) -> EmailState:
    msg, r = state.message, state.result
    assert msg is not None
    store.upsert_email(
        message_id=msg.message_id, mailbox=msg.mailbox, sender=msg.sender, subject=msg.subject, received_at=msg.received_at,
        body_excerpt=(r.body_clean if r else msg.body)[:600],
        attachments=[a.model_dump(exclude={"path"}) for a in msg.attachments],
        intent=r.intent if r else None, intent_conf=r.confidence if r else None,
        # a `signals` JSON: Noul-jelek + `scores` (Score-jelek: szint, várható érték, conf, eloszlás) egy oszlopban
        signals=({**r.signals, "scores": {k: s.model_dump() for k, s in r.scores.items()}} if r else None),
        next_flow=state.next_flow, run_id=state.run_id,
    )
    # 058 K5.1: a futás saját eredménysora (az `emails` sor levelenként a legutóbbi marad); a levél szövegéből látott rész
    store.upsert_email_result(
        run_id=state.run_id, message_id=msg.message_id, intent=r.intent if r else None, intent_conf=r.confidence if r else None,
        signals=({**r.signals, "scores": {k: s.model_dump() for k, s in r.scores.items()}} if r else None),
        next_flow=state.next_flow, attachments=[a.model_dump(exclude={"path"}) for a in msg.attachments],
        body=body_coverage(msg), tasks=state.tasks,
    )
    if r is None:
        store.review_enqueue(subject_kind="email", subject_id=msg.message_id, run_id=state.run_id, producer="email_intent",
                             reasons=list(state.review_reasons) or ["intent:no_result"])
    elif state.uncertain or state.review_reasons:
        reasons = ([f"intent:low_conf:{r.intent}:{r.confidence:.2f}"] if state.uncertain else []) + list(state.review_reasons)
        store.review_enqueue(
            subject_kind="email", subject_id=msg.message_id, run_id=state.run_id, reasons=reasons, producer="email_intent",
            payload={"probabilities": r.probabilities, "signals": r.signals, "scores": {k: s.model_dump() for k, s in r.scores.items()},
                     "next_flow": state.next_flow,
                     "parent": policy.parent_fallback(r.confidence, r.parent, r.parent_prob, "email.intent", r.probabilities), "parent_prob": r.parent_prob},
        )
    else:
        store.review_close(subject_kind="email", subject_id=msg.message_id, producer="email_intent", run_id=state.run_id)
    # 048 T2: a feldolgozó a tétel állapotát ebből veszi; bizonytalan szándék = teendő
    state.final_status = "jev_unavailable" if r is None else ("needs_review" if state.uncertain or state.review_reasons else "done")
    return state


@action.pydantic(reads=[], writes=[])
def done(state: EmailState) -> EmailState:
    return state


TRANSITIONS = [
    ("load_message", "classify_attachments"),
    ("classify_attachments", "intent"),
    ("intent", "route"),
    ("route", "tasks"),
    ("tasks", "save"),
    ("save", "done"),
]

CONTRACT = {  # a gráf deklarációja: FLOW.md + Mermaid + lint ebből (jav/contract.py, `python -m jav.cli flows`)
    "name": "email_intent",
    "phases": ["load", "attachments", "classify", "route", "tasks", "persist", "terminal"],
    "steps": [("load_message", "load"), ("classify_attachments", "attachments"), ("intent", "classify"), ("route", "route"),
              ("tasks", "tasks"), ("save", "persist"), ("done", "terminal")],
    "edges": [("load_message", "classify_attachments"), ("classify_attachments", "intent"), ("intent", "route"), ("route", "tasks"),
              ("tasks", "save"), ("save", "done")],
    "step_meta": {
        "load_message": {"kind": "det", "note": "inbox/<mailbox>/<msgid>/message.json + fájlok, vagy kész EmailMessage (golden)"},
        "classify_attachments": {"kind": "flow", "note": "minden PDF-csatolmányon az M1 doc_detect gráf (a levél run_id-je alatt: <run_id>-doc_detect), eredmény a csatolmányra + documents.source_email; kép -> unsupported, névből ismert -> name_only"},
        "intent": {"kind": "jev", "note": "egy kérés: Choice intent (11 szándék, a küldő célja) + 4 Noul jel; tisztított törzs + kód-oldali feature-ök a state-ben"},
        "route": {"kind": "det", "note": "policy.email_next_flow: conf küszöb -> csatolmány M1-típusa -> szándékonkénti alapértelmezés"},
        "tasks": {"kind": "llm", "note": "058 K5.3: feladatjavaslat (GPT, a régi email-actions v1.3.0 utasítása) + kódos bizonyíték-kapu; csak ha a recept kéri, archiválandó levélen nem; javaslat -> teendő (ember fogadja el)"},
        "save": {"kind": "store", "note": "emails + email_results (a futás sora, K5.3: a javaslat is); bizonytalan intent / javaslat -> review_queue (additív), különben a korábbi tétel zárul"},
        "done": {"kind": "terminal", "note": "szándék + next_flow mentve"},
    },
    "terminals": TERMINALS,
    "doc_note": "M3 - a bemenet a régi outlook_bridge.ps1 -> jav/ingest_server.py -> inbox-mappa; a next_flow kódban dől el, nem Jev-kérdés.",
}


def build_app(
    *,
    source_dir: str | None = None,
    message: EmailMessage | None = None,
    tracker: bool = False,
    use_cache: bool = True,
    detect_attachments: bool = True,
    run_id: str | None = None,
    persister=None,
    propose_tasks: bool = False,
) -> Application:
    """`run_id` + `persister` (048 T2): a feldolgozóból futtatva tartós állapotmentés, ugyanazzal az azonosítóval folytatás."""
    stem = (message.message_id if message else source_dir or "email").replace(":", "-").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1][:32]
    run_id = run_id or f"email-{stem}-{uuid.uuid4().hex[:8]}"
    initial = EmailState(source_dir=source_dir, message=message, run_id=run_id, use_cache=use_cache, detect_attachments=detect_attachments,
                         propose_tasks=propose_tasks)
    b = (
        ApplicationBuilder()
        .with_typing(PydanticTypingSystem(EmailState))
        .with_actions(load_message, classify_attachments, intent, route, tasks, save, done)
        .with_transitions(*TRANSITIONS)
        .with_identifiers(app_id=run_id, partition_key=PARTITION if persister is not None else None)
    )
    if persister is not None:
        b = (b.initialize_from(persister, resume_at_next_action=True, default_state=initial.model_dump(),
                               default_entrypoint="load_message").with_state_persister(persister))
    else:
        b = b.with_state(initial).with_entrypoint("load_message")
    if tracker:
        b = b.with_tracker("local", project=TRACKER_PROJECT)
    return b.build()


def run_email(
    source_dir: str | None = None,
    *,
    message: EmailMessage | None = None,
    tracker: bool = False,
    use_cache: bool = True,
    detect_attachments: bool = True,
) -> EmailState:
    app = build_app(source_dir=source_dir, message=message, tracker=tracker, use_cache=use_cache, detect_attachments=detect_attachments)
    _, _, state = app.run(halt_after=TERMINALS)
    return state.data
