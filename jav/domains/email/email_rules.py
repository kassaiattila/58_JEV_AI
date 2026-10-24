"""The email flow's decision rules: an email's next step, and the to-dos of its signals (224, plan G-process-core P3c).

Plain-language summary: after an email's intent is recognised, code decides what happens next: a signal in its yes
band (an injected instruction) sends it to a person as suspicious; an intent the recogniser is unsure of goes to a
person; for an intent that brings a document, the attachment's type decides (its data extraction, or text or type
recognition still to do); otherwise the intent's own route (archive it, put it in a person's inbox, ...). A message
we sent goes by its attachments. The routes and the signals are the email domain's own rules (`configs/email.json`);
the bands the confidence and the signals are judged with are the shared ones (`configs/policy.json`, `jav/ai/policy.py`).
Until 224 these rules lived in the shared rule file and its module, which imported the email domain to apply them.

- `email_next_flow(intent, confidence, attachments, probabilities, signals)`, `email_sent_route(attachments)`.
- `email_signal_reasons(signals)`, `email_signal_route(signals)`.

Layer: the email domain's business module; it reads the shared bands (`jav.ai.policy`) and the type roles.
"""

from __future__ import annotations

from jav.ai import policy
from jav.core import cfg, type_roles
from jav.domains.email.emails import Attachment
from jav.domains.email.intents import DOCUMENT_BEARING

# 227 (plan R3b): `configs/email.json` is read through the config loader when a rule applies, not copied when this
# module is loaded, so a reloaded file reaches the routes without a restart (`cfg.Section`)
_CFG = cfg.Section("email")

INTENT_ROUTE = cfg.Section("email", "intent_route")  # attachment-independent default per intent
EMAIL_SIGNAL_ROUTES = cfg.Section("email", "signal_routes")  # yes-band signal -> route (overrides all)


def m2_types() -> frozenset[str]:
    """The types with an M2 flow an attachment goes to (`configs/email.json` `m2_types`, through the type roles)."""
    return frozenset(type_roles.types("email_extraction"))


def config_hash() -> str:
    """The fingerprint of `configs/email.json` as it is loaded now."""
    return cfg.config_hash("email")


def jev_unavailable_route() -> str:
    """JEV did not answer -> the manual queue."""
    return str(_CFG["jev_unavailable_route"])


def sent_route() -> str:
    """149: a message we sent, without a document attachment."""
    return str(_CFG["sent_route"])


def signal_review() -> tuple[str, ...]:
    """The signals whose yes band means a review."""
    return tuple(_CFG.get("signal_review", ()))


def email_signal_reasons(signals: dict[str, float] | None) -> list[str]:
    """Review reasons of the M3 Noul signals: `signal:<key>:<p>` in the `yes` band of `email.signal` (uncertain only
    if enabled)."""
    out: list[str] = []
    for key in signal_review():
        p = (signals or {}).get(key)
        if p is None:
            continue
        reason = policy.noul_review_reason("signal", key, float(p), "email.signal")
        if reason:
            out.append(reason)
    return out


def email_signal_route(signals: dict[str, float] | None) -> str | None:
    """Signal-driven route (e.g. injected instruction -> `human:suspicious`) if the signal is in the `yes` band of
    `email.signal`."""
    for key, route in EMAIL_SIGNAL_ROUTES.items():
        p = (signals or {}).get(key)
        if p is not None and policy.noul_band(float(p), "email.signal") == "yes":
            return route
    return None


def email_next_flow(
    intent: str, confidence: float, attachments: list[Attachment], probabilities: dict[str, float] | None = None, signals: dict[str, float] | None = None
) -> str:
    """Deterministic route: signal route (injected instruction) -> band (threshold + second-option gap) -> for a
    document-bearing intent, the attachment's type -> default."""
    signal_route = email_signal_route(signals)
    if signal_route:
        return signal_route
    if policy.choice_needs_review(confidence, probabilities, "email.intent"):
        return _CFG["low_conf_route"]
    if intent in DOCUMENT_BEARING:
        by_attachment = _attachment_route(attachments)
        if by_attachment:
            return by_attachment
    return INTENT_ROUTE.get(intent, _CFG["default_route"])


def _attachment_route(attachments: list[Attachment]) -> str | None:
    """The route an email's attachments give: the first attachment of a type with a data extraction, else text
    recognition or type recognition still to do; None if no attachment decides."""
    m2 = m2_types()
    typed = [a for a in attachments if a.doc_type in m2]
    if typed:
        return f"m2:{typed[0].doc_type}"
    if any(a.status == "needs_ocr" for a in attachments):
        return _CFG["needs_ocr_route"]
    if any(a.ext == ".pdf" and a.status in (None, "name_only", "skipped") for a in attachments):
        return _CFG["detect_route"]
    return None


def email_sent_route(attachments: list[Attachment]) -> str:
    """149: the route of a message we sent. It has no intent to ask about (the intent question reads the sender's aim),
    so its attachments decide, as for a document-bearing intent; without a deciding attachment it is archived."""
    return _attachment_route(attachments) or sent_route()


__all__ = ["EMAIL_SIGNAL_ROUTES", "INTENT_ROUTE", "config_hash", "email_next_flow", "email_sent_route",
           "email_signal_reasons", "email_signal_route", "jev_unavailable_route", "m2_types", "sent_route", "signal_review"]
