"""M3 Burr flow: `load_message → classify_attachments → intent → route → tasks → save → done`.

- `load_message`: from an inbox folder (`message.json` + files) OR from a ready `EmailMessage` (golden set).
- `classify_attachments`: M1 detect runs on every PDF present as a file (its own Burr graph, under the email's run_id:
  `<run_id>-doc_detect`, 065); the result (doc_id, doc_type, conf) goes onto the attachment and into the `documents`
  table (with a source_email reference). An attachment known by name only (legacy golden set) -> `name_only`; image ->
  `unsupported` (OCR = extension B5); a PDF the reader cannot read -> `unreadable` + an email to-do (078).
- `intent`: one JEV request (Choice + 4 Nouls) through the adapter (cache + ledger); without JEV (089) the same
  questions in one GPT request (`jav/domains/email/intent_gpt.py`), its confidence from the answer's token log-probabilities.
- `route`: `policy.email_next_flow` - code decides from the intent, the confidence and the attachment types.
- 149: a sent message (`folder = 'sent'`) is not asked about its intent (the question reads the sender's aim, and the
  call is paid): its attachments still run and decide the route (`policy.email_sent_route`), no task proposal is made,
  and without a problem it leaves no to-do.
- `save`: `emails` table (the latest per email) and `email_results` (the run's own row, with the part of the email text
  that was seen, 058 K5.1); uncertain intent -> review_queue (per reason, additive), certain -> its own earlier reasons
  are closed.
- 190 (plan 189 A2f, the owner's decision of 2026-10-21): when the route is a data extraction (`m2:<type>`) whose type
  pack reads text (the quote request) and the recipe's `email_text` setting asks for it, `route` names a follow-up:
  the extraction flow on the email's own text (`emails.document_text`), which the worker runs as the item's next stage;
  `save` ties that document (its id is the text's digest) to the email.
- 192 (plan F-quote-package B6c, the owner's decision): when that type pack reads tables too, `route` also names a
  follow-up on each of the email's table attachments (an Excel or CSV request list, `table_follow_ups`), read as a part
  of the email's request in stages `invoice-a<n>`, not as an item of its own.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from burr.core import ApplicationBuilder, action
from burr.core.application import Application
from burr.integrations.pydantic import PydanticTypingSystem
from pydantic import BaseModel, Field

from jav.ai import policy, typepack
from jav.documents import text_document
from jav.core import store
from jav.domains.email.emails import DOC_EXTS, EmailMessage, body_coverage, document_text, load_message_dir
from jav.ai.engine import with_engine
from jav.domains.email.intent import IntentResult

log = logging.getLogger("jav.domains.email.flow_email")

TERMINALS = ["done"]
PARTITION = "email_intent"  # partition of the durable state persistence (066 Á08: the worker looks up the saved state with it)
TRACKER_PROJECT = "jav_email_intent"


class EmailState(BaseModel):
    source_dir: str | None = None
    run_id: str = ""
    use_cache: bool = True
    detect_attachments: bool = True
    jev: bool = True  # 086: False = processing without JEV: GPT recognises the intent (089), the attachments are not recognised here
    message: EmailMessage | None = None
    result: IntentResult | None = None
    next_flow: str = ""
    uncertain: bool = False
    review_reasons: list[str] = Field(default_factory=list)  # additive: jev_unavailable:<reason>, attachment:unreadable:<why>, ...
    final_status: str | None = None
    propose_tasks: bool = False  # 058 K5.3: whether the recipe asks for task proposals (off by default: GPT cost)
    tasks: dict | None = None  # the proposal after the gate: {status, tasks, rejected} (None = not requested)
    # an attachment's resolved path -> its verified source instance (the worker supplies it for the attachments that are
    # items of the package); such an attachment is read from the instance, any other from its path
    attachment_reads: dict[str, str] = Field(default_factory=dict)
    # 190: whether the recipe asks for the email's own text to be extracted when its route is a text-reading type pack,
    # and the follow-up stage named for the worker: {"flow": <flow>, "params": {"doc_type", "source_text"}}
    extract_text: bool = False
    follow_up: dict | None = None
    # 192 (B6c): the follow-ups on the email's table attachments (an Excel or CSV request list), each read by the same
    # type pack as a part of the email's request: [{"flow", "stage", "source_path", "name", "params": {"doc_type"}}]
    attachment_follow_ups: list[dict] = Field(default_factory=list)


@action.pydantic(reads=["source_dir", "message"], writes=["message"])
def load_message(state: EmailState) -> EmailState:
    if state.message is None:
        if not state.source_dir:
            raise ValueError("either source_dir or message is required")
        state.message = load_message_dir(state.source_dir)
    return state


@action.pydantic(reads=["message", "run_id", "use_cache", "detect_attachments", "review_reasons", "attachment_reads"],
                 writes=["message", "review_reasons"])
def classify_attachments(state: EmailState) -> EmailState:
    """078: an attachment the PDF reader cannot read (corrupt, over the reader's time or memory limit, over an input
    limit) is marked `unreadable` and gives the email an `attachment:unreadable:<why>` to-do; the other attachments and
    the intent still run. Until 078 the error failed the whole email item. Any other error still fails it.
    An attachment that is an item of the package is read from its source instance (`attachment_reads`), the same bytes
    its document item is processed from."""
    from jav.documents.isolated_pdf import PdfReaderError, PdfReaderLimit
    from jav.documents.pdf import DocumentTooLarge

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
            att.status = "unsupported"  # image: unreadable without OCR (B5)
            continue
        if not state.detect_attachments:
            att.status = "skipped"
            continue
        from jav.flows.flow_detect import run_detect

        # 065: under the email's run ID, otherwise the attachment's to-do and cost would fall outside the run
        try:
            st = run_detect(att.path, use_cache=state.use_cache, run_id=f"{state.run_id}-doc_detect",
                            read_path=state.attachment_reads.get(str(Path(att.path).resolve())))
        except (PdfReaderError, PdfReaderLimit, DocumentTooLarge) as exc:
            why = exc.reason if isinstance(exc, PdfReaderLimit) else type(exc).__name__
            log.warning("email %s: a PDF attachment is unreadable: %s", msg.message_id, why)  # no file name in the log
            att.status = "unreadable"
            if f"attachment:unreadable:{why}" not in state.review_reasons:
                state.review_reasons = state.review_reasons + [f"attachment:unreadable:{why}"]
            continue
        att.doc_id, att.status = st.doc_id, st.final_status
        if st.result is not None:
            att.doc_type, att.type_conf, att.issuer_hu = st.result.doc_type, st.result.confidence, st.result.issuer_hu
        store.upsert_document(doc_id=st.doc_id, source_path=att.path, source_email=msg.message_id, run_id=state.run_id)
    return state


@action.pydantic(reads=["message", "run_id", "use_cache", "jev", "review_reasons"], writes=["result", "uncertain", "review_reasons"])
def intent(state: EmailState) -> EmailState:
    from jav.ai.jev import JevUnavailableError, get_adapter
    from jav.domains.email.intent import classify

    assert state.message is not None
    if state.message.folder == "sent":  # 149: no sender's aim to recognise in a message we sent
        state.result, state.uncertain = None, False
        return state
    if not state.jev:  # 089 (the owner's decision of 2026-10-02): without JEV, GPT recognises the intent
        return _intent_gpt(state)
    try:
        state.result = classify(get_adapter(), state.message, run_id=state.run_id, use_cache=state.use_cache)
    except JevUnavailableError as exc:  # JEV unavailable (in the ledger): no intent, to the manual queue; the flow does not fail
        state.result = None
        state.uncertain = True
        state.review_reasons = state.review_reasons + [f"jev_unavailable:{exc.reason}"]
        return state
    state.uncertain = policy.choice_needs_review(state.result.confidence, state.result.probabilities, "email.intent")
    # M3 signals (v1.1.0): the yes band of an injected instruction is a review reason (additive, the policy decides
    # which signal)
    state.review_reasons = state.review_reasons + [r for r in policy.email_signal_reasons(state.result.signals) if r not in state.review_reasons]
    return state


def _intent_gpt(state: EmailState) -> EmailState:
    """089: the intent recognised by GPT (processing without JEV). A failed call (no budget, provider error) is a to-do,
    not the end of the item; an unmeasurable confidence makes the intent uncertain. The signals act as with JEV."""
    from jav.domains.email.intent_gpt import classify

    assert state.message is not None
    try:
        state.result = classify(state.message, run_id=state.run_id)
    except Exception as exc:  # noqa: BLE001 - an error is a to-do, not the end of the flow (as with the GPT type)
        state.result = None
        state.uncertain = True
        state.review_reasons = state.review_reasons + [f"intent:gpt_failed:{type(exc).__name__}"]
        return state
    r = state.result
    reasons = [] if r.measured else ["intent:confidence_unavailable"]
    state.uncertain = not r.measured or policy.choice_needs_review(r.confidence, r.probabilities, "email.intent.gpt")
    reasons += [x for x in policy.email_signal_reasons(r.signals) if x not in state.review_reasons]
    state.review_reasons = state.review_reasons + reasons
    return state


@action.pydantic(reads=["message", "result", "extract_text"], writes=["next_flow", "follow_up", "attachment_follow_ups"])
def route(state: EmailState) -> EmailState:
    assert state.message is not None
    if state.message.folder == "sent":  # 149: its attachments decide
        state.next_flow = policy.email_sent_route(state.message.attachments)
        return state
    if state.result is None:
        state.next_flow = policy.EMAIL_JEV_UNAVAILABLE_ROUTE
        return state
    state.next_flow = policy.email_next_flow(
        state.result.intent, state.result.confidence, state.message.attachments, state.result.probabilities, state.result.signals
    )
    state.follow_up = text_follow_up(state.message, state.next_flow) if state.extract_text else None
    state.attachment_follow_ups = table_follow_ups(state.message, state.next_flow) if state.extract_text else []
    return state


def text_follow_up(msg: EmailMessage, next_flow: str) -> dict | None:
    """190: the extraction of the email's own text, when its route is a data extraction whose type pack reads text and
    the email has text of its own; None otherwise (an invoice's route extracts its attachment, not the email)."""
    kind, _, key = next_flow.partition(":")
    if kind != "m2" or key not in typepack.keys() or "text" not in typepack.get(key).inputs:
        return None
    text = document_text(msg)
    return {"flow": "invoice", "params": {"doc_type": key, "source_text": text}} if text else None


def table_follow_ups(msg: EmailMessage, next_flow: str) -> list[dict]:
    """192 (B6c, the owner's decision): the extraction of each of the email's table attachments (an Excel or CSV
    request list), when its route is a data extraction whose type pack reads tables; read as a part of the email's
    request, not as an item of its own. Each names its stage (`invoice-a<n>`, after the text's `invoice`)."""
    kind, _, key = next_flow.partition(":")
    if kind != "m2" or key not in typepack.keys() or "table" not in typepack.get(key).inputs:
        return []
    tables = [a for a in msg.attachments if a.path and text_document.input_kind(a.path) == "table"]
    return [{"flow": "invoice", "stage": f"invoice-a{n}", "source_path": a.path, "name": a.filename,
             "params": {"doc_type": key}} for n, a in enumerate(tables, 1)]


@action.pydantic(reads=["message", "result", "next_flow", "run_id", "propose_tasks", "review_reasons"], writes=["tasks", "review_reasons"])
def tasks(state: EmailState) -> EmailState:
    """058 K5.3: task proposal (GPT, the legacy email-actions instruction) + code evidence gate. Only if the recipe asks
    for it and the email is not one to archive (code decides). An error does not fail the process: it becomes a to-do. A
    proposal also becomes a to-do, because only a person accepts a proposal."""
    if not state.propose_tasks:
        return state
    from jav.domains.email import email_tasks
    from jav.core.queue import JobCancelled

    msg = state.message
    assert msg is not None
    skip = "sent_message" if msg.folder == "sent" else email_tasks.skip_reason(
        state.next_flow, signals=state.result.signals if state.result else None, has_intent=state.result is not None)
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
    except Exception as exc:  # noqa: BLE001 - OpenAI / budget / schema error: a to-do, the intent result is kept
        state.tasks = {"status": "error", "error": type(exc).__name__, "tasks": [], "rejected": []}
        state.review_reasons = state.review_reasons + [f"tasks:failed:{type(exc).__name__}"]
        return state
    accepted, rejected = email_tasks.gate(snap, raw)
    state.tasks = {"status": "proposed", "tasks": accepted, "rejected": rejected, "config_hash": email_tasks.CONFIG_HASH}
    if accepted:
        state.review_reasons = state.review_reasons + [f"tasks:proposed:{len(accepted)}"]
    return state


@action.pydantic(reads=["message", "result", "next_flow", "uncertain", "run_id", "review_reasons", "tasks", "jev", "follow_up",
                         "source_dir"], writes=["final_status"])
def save(state: EmailState) -> EmailState:
    msg, r = state.message, state.result
    assert msg is not None
    if state.follow_up:  # 190: the email's own text as a document of the email (the extraction fills in the rest)
        text = state.follow_up["params"]["source_text"]
        store.upsert_document(doc_id=text_document.text_digest(text), source_email=msg.message_id, run_id=state.run_id,
                              source_path=str(Path(state.source_dir) / "message.json") if state.source_dir else msg.message_id)
    store.upsert_email(
        message_id=msg.message_id, mailbox=msg.mailbox, sender=msg.sender, subject=msg.subject, received_at=msg.received_at,
        body_excerpt=(r.body_clean if r else msg.body)[:600],
        attachments=[a.model_dump(exclude={"path"}) for a in msg.attachments],
        intent=r.intent if r else None, intent_conf=r.confidence if r else None,
        # the `signals` JSON: Noul signals + `scores` (Score signals: level, expected value, conf, distribution) in one
        # column
        signals=({**r.signals, "scores": {k: s.model_dump() for k, s in r.scores.items()}} if r else None),
        next_flow=state.next_flow, run_id=state.run_id,
    )
    # 058 K5.1: the run's own result row (the `emails` row stays the latest per email); the part of the email text seen
    store.upsert_email_result(
        run_id=state.run_id, message_id=msg.message_id, intent=r.intent if r else None, intent_conf=r.confidence if r else None,
        signals=({**r.signals, "scores": {k: s.model_dump() for k, s in r.scores.items()}} if r else None),
        next_flow=state.next_flow, attachments=[a.model_dump(exclude={"path"}) for a in msg.attachments],
        body=body_coverage(msg), tasks=state.tasks, folder=msg.folder,
    )
    sent = msg.folder == "sent"  # 149: no intent was asked, so a missing one is no to-do
    if r is None and not (sent and not state.review_reasons):
        store.review_enqueue(subject_kind="email", subject_id=msg.message_id, run_id=state.run_id, producer="email_intent",
                             reasons=list(state.review_reasons) or ["intent:no_result"])
    elif r is not None and (state.uncertain or state.review_reasons):
        reasons = ([f"intent:low_conf:{r.intent}:{r.confidence:.2f}"] if state.uncertain else []) + list(state.review_reasons)
        store.review_enqueue(
            subject_kind="email", subject_id=msg.message_id, run_id=state.run_id, reasons=reasons, producer="email_intent",
            payload={"probabilities": r.probabilities, "signals": r.signals, "scores": {k: s.model_dump() for k, s in r.scores.items()},
                     "next_flow": state.next_flow,
                     "parent": policy.parent_fallback(r.confidence, r.parent, r.parent_prob, _band(r), r.probabilities), "parent_prob": r.parent_prob},
        )
    else:
        store.review_close(subject_kind="email", subject_id=msg.message_id, producer="email_intent", run_id=state.run_id)
    # 048 T2: the worker takes the item's status from this; an uncertain intent = a to-do
    if sent:
        state.final_status = "needs_review" if state.review_reasons else "done"
    elif r is None:  # 089: without JEV a missing intent means GPT could not answer (as for the GPT type)
        state.final_status = "jev_unavailable" if state.jev else "gpt_unavailable"
    else:
        state.final_status = "needs_review" if state.uncertain or state.review_reasons else "done"
    return state


def _band(r: IntentResult) -> str:
    return "email.intent.gpt" if r.engine == "gpt" else "email.intent"


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

CONTRACT = {  # the graph declaration: FLOW.md + Mermaid + lint come from it (jav/flows/contract.py, `python -m jav.cli flows`)
    "name": "email_intent",
    "phases": ["load", "attachments", "classify", "route", "tasks", "persist", "terminal"],
    "steps": [("load_message", "load"), ("classify_attachments", "attachments"), ("intent", "classify"), ("route", "route"),
              ("tasks", "tasks"), ("save", "persist"), ("done", "terminal")],
    "edges": [("load_message", "classify_attachments"), ("classify_attachments", "intent"), ("intent", "route"), ("route", "tasks"),
              ("tasks", "save"), ("save", "done")],
    "step_meta": {
        "load_message": {"kind": "det", "note": "inbox/<mailbox>/<msgid>/message.json + fájlok, vagy kész EmailMessage (golden)"},
        "classify_attachments": {"kind": "flow", "note": "minden PDF-csatolmányon az M1 doc_detect gráf (a levél run_id-je alatt: <run_id>-doc_detect), eredmény a csatolmányra + documents.source_email; kép -> unsupported, névből ismert -> name_only; olvashatatlan PDF -> unreadable + teendő (attachment:unreadable), a levél tovább fut"},
        "intent": {"kind": "jev", "note": "egy kérés: Choice intent (11 szándék, a küldő célja) + 4 Noul jel; tisztított törzs + kód-oldali feature-ök a state-ben. Without JEV: the same questions to GPT in one structured request, the confidence from the answer's token log-probabilities (jav/domains/email/intent_gpt.py); a failed call is an intent:gpt_failed to-do (and no attachment recognition in this flow: the attachments are recognised as items of their own). A sent message (folder = sent, 149) is not asked: no call, no to-do"},
        "route": {"kind": "det", "note": "policy.email_next_flow: conf küszöb -> csatolmány M1-típusa -> szándékonkénti alapértelmezés. A sent message (149): policy.email_sent_route, its attachments' types, else archive:sent. 190: a route to a type pack that reads text (the quote request), with the recipe's email_text setting on, names the follow-up stage: the extraction flow on the email's own text; 192: and one on each table attachment when the pack reads tables"},
        "tasks": {"kind": "llm", "note": "feladatjavaslat (GPT, a régi email-actions v1.3.0 utasítása) + kódos bizonyíték-kapu; csak ha a recept kéri, archiválandó levélen nem; javaslat -> teendő (ember fogadja el). Not for a sent message (149)"},
        "save": {"kind": "store", "note": "emails + email_results (a futás sora, a feladatjavaslat is); bizonytalan intent / javaslat -> review_queue (additív), különben a korábbi tétel zárul; 190: the email's own text as a document tied to the email (documents.source_email), when a follow-up extracts it"},
        "done": {"kind": "terminal", "note": "szándék + next_flow mentve"},
    },
    "terminals": TERMINALS,
    "doc_note": "M3 - a bemenet a régi outlook_bridge.ps1 -> jav/domains/email/ingest_server.py -> inbox-mappa; a next_flow kódban dől el, nem Jev-kérdés.",
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
    attachment_reads: dict[str, str] | None = None,
    jev: bool = True,
    extract_text: bool = False,
) -> Application:
    """`run_id` + `persister` (048 T2): when run from the worker, durable state persistence and resumption under the
    same ID. `attachment_reads`: the source instances to read the package's attachment items from. `jev=False` (086,
    089): GPT recognises the intent, and there is no attachment recognition here: the PDF attachments are items of the
    package and are recognised there, by GPT. `extract_text` (190): the recipe's `email_text` setting is on, so a route to
    a text-reading type pack names the extraction of the email's own text as the follow-up stage."""
    stem = (message.message_id if message else source_dir or "email").replace(":", "-").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1][:32]
    run_id = run_id or f"email-{stem}-{uuid.uuid4().hex[:8]}"
    initial = EmailState(source_dir=source_dir, message=message, run_id=run_id, use_cache=use_cache,
                         detect_attachments=detect_attachments and jev, jev=jev,
                         propose_tasks=propose_tasks, attachment_reads=attachment_reads or {}, extract_text=extract_text)
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
    return with_engine(b, jev_on=jev).build()  # 160: without JEV, a JEV question is refused


def run_email(
    source_dir: str | None = None,
    *,
    message: EmailMessage | None = None,
    tracker: bool = False,
    use_cache: bool = True,
    detect_attachments: bool = True,
    jev: bool = True,
) -> EmailState:
    """`jev=False` (089): GPT recognises the intent (paid OpenAI call)."""
    app = build_app(source_dir=source_dir, message=message, tracker=tracker, use_cache=use_cache, detect_attachments=detect_attachments,
                    jev=jev)
    _, _, state = app.run(halt_after=TERMINALS)
    return state.data
