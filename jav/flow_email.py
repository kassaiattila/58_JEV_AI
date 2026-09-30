"""M3 Burr flow: `load_message → classify_attachments → intent → route → tasks → save → done`.

- `load_message`: from an inbox folder (`message.json` + files) OR from a ready `EmailMessage` (golden set).
- `classify_attachments`: M1 detect runs on every PDF present as a file (its own Burr graph, under the email's run_id:
  `<run_id>-doc_detect`, 065); the result (doc_id, doc_type, conf) goes onto the attachment and into the `documents`
  table (with a source_email reference). An attachment known by name only (legacy golden set) -> `name_only`; image ->
  `unsupported` (OCR = extension B5); a PDF the reader cannot read -> `unreadable` + an email to-do (078).
- `intent`: one JEV request (Choice + 4 Nouls) through the adapter (cache + ledger).
- `route`: `policy.email_next_flow` - code decides from the intent, the confidence and the attachment types.
- `save`: `emails` table (the latest per email) and `email_results` (the run's own row, with the part of the email text
  that was seen, 058 K5.1); uncertain intent -> review_queue (per reason, additive), certain -> its own earlier reasons
  are closed.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from burr.core import ApplicationBuilder, action
from burr.core.application import Application
from burr.integrations.pydantic import PydanticTypingSystem
from pydantic import BaseModel, Field

from jav import policy, store
from jav.emails import DOC_EXTS, EmailMessage, body_coverage, load_message_dir
from jav.intent import IntentResult

log = logging.getLogger("jav.flow_email")

TERMINALS = ["done"]
PARTITION = "email_intent"  # partition of the durable state persistence (066 Á08: the worker looks up the saved state with it)
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
    review_reasons: list[str] = Field(default_factory=list)  # additive: jev_unavailable:<reason>, attachment:unreadable:<why>, ...
    final_status: str | None = None
    propose_tasks: bool = False  # 058 K5.3: whether the recipe asks for task proposals (off by default: GPT cost)
    tasks: dict | None = None  # the proposal after the gate: {status, tasks, rejected} (None = not requested)
    # an attachment's resolved path -> its verified source instance (the worker supplies it for the attachments that are
    # items of the package); such an attachment is read from the instance, any other from its path
    attachment_reads: dict[str, str] = Field(default_factory=dict)


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
    from jav.isolated_pdf import PdfReaderError, PdfReaderLimit
    from jav.pdf import DocumentTooLarge

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
        from jav.flow_detect import run_detect

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


@action.pydantic(reads=["message", "run_id", "use_cache", "review_reasons"], writes=["result", "uncertain", "review_reasons"])
def intent(state: EmailState) -> EmailState:
    from jav.adapters.jev import JevUnavailableError, get_adapter
    from jav.intent import classify

    assert state.message is not None
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
    """058 K5.3: task proposal (GPT, the legacy email-actions instruction) + code evidence gate. Only if the recipe asks
    for it and the email is not one to archive (code decides). An error does not fail the process: it becomes a to-do. A
    proposal also becomes a to-do, because only a person accepts a proposal."""
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
    except Exception as exc:  # noqa: BLE001 - OpenAI / budget / schema error: a to-do, the intent result is kept
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
    # 048 T2: the worker takes the item's status from this; an uncertain intent = a to-do
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

CONTRACT = {  # the graph declaration: FLOW.md + Mermaid + lint come from it (jav/contract.py, `python -m jav.cli flows`)
    "name": "email_intent",
    "phases": ["load", "attachments", "classify", "route", "tasks", "persist", "terminal"],
    "steps": [("load_message", "load"), ("classify_attachments", "attachments"), ("intent", "classify"), ("route", "route"),
              ("tasks", "tasks"), ("save", "persist"), ("done", "terminal")],
    "edges": [("load_message", "classify_attachments"), ("classify_attachments", "intent"), ("intent", "route"), ("route", "tasks"),
              ("tasks", "save"), ("save", "done")],
    "step_meta": {
        "load_message": {"kind": "det", "note": "inbox/<mailbox>/<msgid>/message.json + fájlok, vagy kész EmailMessage (golden)"},
        "classify_attachments": {"kind": "flow", "note": "minden PDF-csatolmányon az M1 doc_detect gráf (a levél run_id-je alatt: <run_id>-doc_detect), eredmény a csatolmányra + documents.source_email; kép -> unsupported, névből ismert -> name_only; olvashatatlan PDF -> unreadable + teendő (attachment:unreadable), a levél tovább fut"},
        "intent": {"kind": "jev", "note": "egy kérés: Choice intent (11 szándék, a küldő célja) + 4 Noul jel; tisztított törzs + kód-oldali feature-ök a state-ben"},
        "route": {"kind": "det", "note": "policy.email_next_flow: conf küszöb -> csatolmány M1-típusa -> szándékonkénti alapértelmezés"},
        "tasks": {"kind": "llm", "note": "feladatjavaslat (GPT, a régi email-actions v1.3.0 utasítása) + kódos bizonyíték-kapu; csak ha a recept kéri, archiválandó levélen nem; javaslat -> teendő (ember fogadja el)"},
        "save": {"kind": "store", "note": "emails + email_results (a futás sora, a feladatjavaslat is); bizonytalan intent / javaslat -> review_queue (additív), különben a korábbi tétel zárul"},
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
    attachment_reads: dict[str, str] | None = None,
) -> Application:
    """`run_id` + `persister` (048 T2): when run from the worker, durable state persistence and resumption under the
    same ID. `attachment_reads`: the source instances to read the package's attachment items from."""
    stem = (message.message_id if message else source_dir or "email").replace(":", "-").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1][:32]
    run_id = run_id or f"email-{stem}-{uuid.uuid4().hex[:8]}"
    initial = EmailState(source_dir=source_dir, message=message, run_id=run_id, use_cache=use_cache, detect_attachments=detect_attachments,
                         propose_tasks=propose_tasks, attachment_reads=attachment_reads or {})
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
