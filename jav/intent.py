"""M3 - email intent recognition with JEV: one request, one Choice + Nouls + a Score.
Question set: `configs/callsites/email_intent.json`.

- Choice `intent` over the registered intents (`jav/intents.py` <- `configs/intents.json`; the axis is the sender's
  GOAL);
- Noul `requires_action`, `mentions_deadline`, `attachment_is_the_subject`, `multiple_requests`, `prompt_injection` and
  Score `urgency` (v1.1.0, replacing the former `tone_urgent` Noul) - routing and review signals, put into the state
  as raw probabilities; thresholds live only in `policy.py`.

State: subject, sender (+ domain), code-side features (automated sender, Re:/Fw:, amount / deadline / unsubscribe /
order-ID patterns, invoice and payment words), the attachments' names + M1 types (if M1 has run), and the first lines
of the CLEANED body, verbatim in Hungarian/English. The features are signals; the decision belongs to JEV.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, model_validator
from typesafe_sdk import Choice, Noul, Score

from jav import cfg
from jav.adapters.jev import JevAdapter
from jav.emails import EmailMessage, clean_body, sender_domain
from jav.intents import OTHER, PARENT_OF, choice_criteria
from jav.models import JevCall
from jav.registry import parent_summary

_CFG = cfg.load("callsite:email_intent")
CONFIG_HASH = cfg.config_hash("callsite:email_intent", "intents")
MAX_BODY_LINES: int = _CFG["state"]["max_body_lines"]
MAX_LINE_CHARS: int = _CFG["state"]["max_line_chars"]
NOUL_KEYS: tuple[str, ...] = tuple(k for k, q in _CFG["questions"].items() if q["kind"] == "noul")
SCORE_KEYS: tuple[str, ...] = tuple(k for k, q in _CFG["questions"].items() if q["kind"] == "score")  # v1.1.0: `urgency`

_AUTOMATED = re.compile(r"(?i)\b(no-?reply|donotreply|do-not-reply|notifications?|mailer|newsletter|billing|invoices?|alerts?|system|bounce)\b")
_REPLY = re.compile(r"(?i)^\s*(re|fw|fwd|aw|wg|vá|válasz)\s*:")
_AMOUNT = re.compile(r"(?i)\d[\d\s.,]*\s?(ft|huf|eur|€|usd|\$|gbp|£)\b|[€$£]\s?\d")
_DUE = re.compile(r"(?i)fizetési határid|esedékes|due date|payment due|határidő|deadline")
_UNSUB = re.compile(r"(?i)leiratkoz|unsubscribe|abmelden")
_ORDER_ID = re.compile(r"(?i)(rendelés|order|megrendelés)[^\n]{0,25}(#|azonosít|szám|id\b|number)[:\s]*[A-Z0-9-]{4,}")
_INVOICE_WORDS = re.compile(r"(?i)száml[aá]|díjbekérő|invoice|faktura|proforma")
_PAID_WORDS = re.compile(r"(?i)sikeres fizetés|payment (received|confirmation|successful)|receipt for|nyugta|jóváírás|refund|visszatérítés")


class ScoreSignal(BaseModel):
    """One Score signal, raw: the most likely level, the expected value (weighted mean), the concentration and the
    level distribution."""

    level: int  # argmax level (from 0)
    score: float  # JEV's `score` field: probability-weighted mean over the levels
    confidence: float
    probabilities: dict[str, float] = Field(default_factory=dict)  # level (str) -> P


class IntentResult(BaseModel):
    intent: str
    confidence: float
    probabilities: dict[str, float] = Field(default_factory=dict)
    signals: dict[str, float] = Field(default_factory=dict)  # Noul P(yes) per key
    scores: dict[str, ScoreSignal] = Field(default_factory=dict)  # Score signals per key (v1.1.0: urgency)
    parent: str | None = None  # family of the most likely intent (registry v2), aggregated in code
    parent_prob: float = 0.0  # total probability of the family - parent label at low confidence (the policy decides)
    body_clean: str = ""
    call: JevCall

    @model_validator(mode="after")
    def _fill_parent(self) -> "IntentResult":
        if self.parent is None and self.probabilities:
            self.parent, self.parent_prob = parent_summary(self.probabilities, PARENT_OF)
        return self


def _clip(lines: list[str]) -> list[str]:
    return [ln[:MAX_LINE_CHARS] for ln in lines]


def build_state(msg: EmailMessage) -> dict:
    body = clean_body(msg.body)
    lines = [ln for ln in body.split("\n") if ln.strip()][:MAX_BODY_LINES]
    text = f"{msg.subject}\n{body}"
    sender = msg.sender or ""
    features = {
        "automated_sender": bool(_AUTOMATED.search(sender.split("@")[0])) if sender else False,
        "reply_or_forward": bool(_REPLY.match(msg.subject or "")),
        "n_attachments": len(msg.attachments),
        "attachment_exts": sorted({a.ext for a in msg.attachments if a.ext}),
        "mentions_amount": bool(_AMOUNT.search(text)),
        "mentions_due": bool(_DUE.search(text)),
        "unsubscribe_link": bool(_UNSUB.search(msg.body)),
        "order_id_pattern": bool(_ORDER_ID.search(text)),
        "invoice_words": len(_INVOICE_WORDS.findall(text)),
        "paid_words": len(_PAID_WORDS.findall(text)),
        "body_chars": len(body),
        "body_truncated": len(msg.body) > len(body) + 50,
    }
    return {
        "subject": msg.subject,
        "sender": msg.sender,
        "sender_name": msg.sender_name,
        "sender_domain": sender_domain(msg.sender),
        "mailbox": msg.mailbox,
        "features": features,
        "attachments": [
            {"filename": a.filename, "doc_type": a.doc_type, "type_conf": None if a.type_conf is None else round(a.type_conf, 2)}
            for a in msg.attachments
        ],
        "body_lines": [f"L{i:02d}: {ln}" for i, ln in enumerate(_clip(lines), 1)],
    }


def build_questions(config: dict | None = None) -> dict[str, Choice | Noul]:
    """JSON question set -> SDK objects; the `registry:intents` criterion comes from the registry."""
    out: dict[str, Choice | Noul] = {}
    for key, q in (config or _CFG)["questions"].items():
        crit = q["criteria"]
        if crit == "registry:intents":
            crit = choice_criteria()
        if q["kind"] == "choice":
            out[key] = Choice(instructions=q["instructions"], criteria=crit)
        elif q["kind"] == "score":
            out[key] = Score(instructions=q["instructions"], criteria=list(crit))  # ordered level descriptions, from 0
        else:
            out[key] = Noul(instructions=q["instructions"], criteria=crit)
    return out


def _score_signal(answer: object) -> ScoreSignal:
    probs = {str(k): round(float(v), 4) for k, v in dict(answer.probabilities).items()}
    level = max(probs, key=lambda k: (probs[k], -int(k)))  # the most likely level; on a tie, the lower one
    return ScoreSignal(level=int(level), score=round(float(answer.score), 4), confidence=round(float(answer.confidence), 4), probabilities=probs)


def classify(jev: JevAdapter, msg: EmailMessage, *, run_id: str = "adhoc", use_cache: bool = True) -> IntentResult:
    state = build_state(msg)
    result = jev.ask("email_intent", state, build_questions(), run_id=run_id, use_cache=use_cache, config_hash=CONFIG_HASH)
    return decode_result(result.response, result.call, state)


def decode_result(r, call, state: dict) -> IntentResult:
    """Shared decoding for the production M3 path and the separate source-backed one."""
    ch = r.choices["intent"]
    return IntentResult(
        intent=ch.choice if ch.choice else OTHER,
        confidence=float(ch.confidence),
        probabilities={k: round(float(v), 4) for k, v in dict(ch.probabilities).items()},
        signals={k: round(float(r.nouls[k].noul), 4) for k in NOUL_KEYS},
        scores={k: _score_signal(r.scores[k]) for k in SCORE_KEYS},
        body_clean="\n".join(ln.split(": ", 1)[1] if ": " in ln else ln for ln in state["body_lines"]),
        call=call,
    )
