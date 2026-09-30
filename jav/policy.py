"""Decision rules - thresholds and routes come from `configs/policy.json` (config as data), the logic is here.

JEV's raw probabilities (`FieldPick.probabilities`, `JevVerdicts.flags`, `IntentResult.signals`) stay untouched in the
state; only their interpretation happens here. Changing a threshold (in the JSON, with a version bump) needs no re-run
if the questions and the evidence have not changed (the raw runs can be re-evaluated from `runs/*.jsonl`).

Type-dependent lists (required fields, high-stakes fields, scored fields) come from the type pack
(`configs/types/<type>.json`, `jav/typepack.py`) according to `state.doc_type`; the thresholds (bands) are
type-independent and live here.
"""

from __future__ import annotations

from typing import Any, Literal

from jav import cfg
from jav.emails import Attachment
from jav.intents import DOCUMENT_BEARING
from jav.models import FlowState
from jav.typepack import DEFAULT_KEY, get as get_pack

_CFG = cfg.load("policy")
_EMAIL = _CFG["email"]
CONFIG_HASH = cfg.config_hash("policy")

NONE_LABEL: str = _CFG["none_label"]
DETECT_DETAIL: dict[str, Any] = dict(_CFG["detect_detail"])  # 047 T1.2: threshold of the detailed-type code decision

# --------------------------------------------------------------------------------------
# Bands (policy.json v1.1.0): named sets per call site, precedence by the length of the dotted prefix
# --------------------------------------------------------------------------------------

BANDS: dict[str, dict[str, Any]] = {name: dict(v) for name, v in _CFG["bands"].items()}
BAND_FOR: dict[str, str] = dict(_CFG["band_for"])
NoulBand = Literal["no", "uncertain", "yes"]
ChoiceBand = Literal["auto", "uncertain", "human"]


def band_name(callsite: str) -> str:
    """`invoice.pick.high_stakes.gross_total` -> the set of the longest matching `band_for` key, otherwise `default`."""
    parts = callsite.split(".")
    for n in range(len(parts), 0, -1):
        key = ".".join(parts[:n])
        if key in BAND_FOR:
            return BAND_FOR[key]
    return "default"


def band(callsite: str) -> dict[str, Any]:
    """The call site's resolved band set: the named set merged over `default` (a missing field is inherited)."""
    return {**BANDS["default"], **BANDS.get(band_name(callsite), {})}


def noul_band(p: float, callsite: str) -> NoulBand:
    """Two-sided band for a Noul's P(yes): `no` (< no_max), `uncertain`, `yes` (>= yes_min)."""
    b = band(callsite)
    if p < b["noul_no_max"]:
        return "no"
    if p >= b["noul_yes_min"]:
        return "yes"
    return "uncertain"


def second_option_gap(probabilities: dict[str, float] | None) -> float | None:
    """The probability gap between the most likely and the second option; None if there are not two options."""
    if not probabilities or len(probabilities) < 2:
        return None
    top = sorted(probabilities.values(), reverse=True)
    return round(top[0] - top[1], 4)


def choice_band(confidence: float, probabilities: dict[str, float] | None, callsite: str) -> ChoiceBand:
    """Choice band: `human` below the conf threshold; `uncertain` if the second option is too close; else `auto`."""
    b = band(callsite)
    if confidence < b["choice_human_max_conf"]:
        return "human"
    gap = second_option_gap(probabilities)
    if gap is not None and gap < b["choice_second_min_gap"]:
        return "uncertain"
    return "auto"


def choice_needs_review(confidence: float, probabilities: dict[str, float] | None, callsite: str) -> bool:
    """`human` always; `uncertain` only if the set has `uncertain_review: true`."""
    cb = choice_band(confidence, probabilities, callsite)
    return cb == "human" or (cb == "uncertain" and bool(band(callsite)["uncertain_review"]))


def choice_review_reason(prefix: str, key: str, confidence: float, probabilities: dict[str, float] | None, callsite: str) -> str | None:
    """Review reason text for a Choice verdict, or None: `<prefix>:low_conf:<key>:<conf>` |
    `<prefix>:second_option:<key>:<gap>`."""
    cb = choice_band(confidence, probabilities, callsite)
    if cb == "human":
        return f"{prefix}:low_conf:{key}:{confidence:.2f}"
    if cb == "uncertain" and band(callsite)["uncertain_review"]:
        return f"{prefix}:second_option:{key}:{second_option_gap(probabilities):.2f}"
    return None


def noul_review_reason(prefix: str, key: str, p: float, callsite: str) -> str | None:
    """Review reason text for a Noul signal, or None: `<prefix>:<key>:<p>` (yes) |
    `<prefix>:uncertain:<key>:<p>` (if enabled)."""
    nb = noul_band(p, callsite)
    if nb == "yes":
        return f"{prefix}:{key}:{p:.2f}"
    if nb == "uncertain" and band(callsite)["uncertain_review"]:
        return f"{prefix}:uncertain:{key}:{p:.2f}"
    return None


def parent_fallback(confidence: float, parent: str | None, parent_prob: float, callsite: str, probabilities: dict[str, float] | None = None) -> str | None:
    """Parent label: if the type / intent is uncertain (not the `auto` band) but the family's total probability
    reaches `parent_min_prob`, the family's name; otherwise None. Only a label for the review and the report; the
    route does not change."""
    if parent is None or choice_band(confidence, probabilities, callsite) == "auto":
        return None
    return parent if parent_prob >= band(callsite)["parent_min_prob"] else None


# Legacy names (referenced by the flows and tests) - derived from the bands, not separate data
HUMAN_MAX_CONF: float = band("invoice.pick")["choice_human_max_conf"]  # below this, any scored field -> human
AUTO_MIN_CONF_HIGH_STAKES: float = band("invoice.pick.high_stakes")["choice_human_max_conf"]  # high-stakes auto-accept
REVIEW_FLAG_P: float = band("invoice.verify")["noul_yes_min"]  # G path: Noul P(yes) for an error flag, review from here
DETECT_LOW_CONFIDENCE: float = band("detect.doc_type")["choice_human_max_conf"]  # M1: uncertain below it; still saved

# Type-dependent lists: from the type pack (the Hungarian invoice's as a legacy module constant; for other types use
# `high_stakes_for` / `required_for`)
HIGH_STAKES = frozenset(get_pack(DEFAULT_KEY).high_stakes)
REQUIRED = frozenset(get_pack(DEFAULT_KEY).required)  # the legacy rules.json `required` list


def high_stakes_for(doc_type: str | None) -> frozenset[str]:
    return frozenset(get_pack(doc_type or DEFAULT_KEY).high_stakes)


def required_for(doc_type: str | None) -> frozenset[str]:
    return frozenset(get_pack(doc_type or DEFAULT_KEY).required)


OCR: dict[str, float] = {k: float(v) for k, v in _CFG.get("ocr", {}).items()}  # v1.6.0: OCR quality thresholds


OCR_REVIEW_PRODUCER = "ocr"  # 066 Á01: producer of the no-text to-do (shared by M1 and M2); closed once there is text


def ocr_review_reasons(mean_conf: float | None, low_conf_ratio: float | None) -> list[str]:
    """Document with OCR text: weak mean word confidence or many weak words -> review reasons (the raw signals stay in
    the state)."""
    out: list[str] = []
    if mean_conf is not None and mean_conf < OCR.get("min_mean_conf", 0.0):
        out.append(f"ocr:low_confidence:{mean_conf:.2f}")
    if low_conf_ratio is not None and low_conf_ratio > OCR.get("max_low_conf_ratio", 1.0):
        out.append(f"ocr:low_conf_words:{low_conf_ratio:.2f}")
    return out


def ocr_coverage_reasons(page_count: int | None, pages_ocr: int | None) -> list[str]:
    """Partial OCR (040 K1, F07): if fewer pages went through OCR than the document has, that is always a visible to-do
    (not a threshold but a fact) — so the data of the skipped pages cannot look complete, and it also stops approval."""
    if page_count is None or pages_ocr is None or pages_ocr >= page_count:
        return []
    return [f"ocr:partial_pages:{pages_ocr}/{page_count}"]


def ocr_should_escalate(mean_conf: float | None, low_conf_ratio: float | None) -> bool:
    """Weak local OCR (below / above the policy's `ocr.escalate_*` thresholds) -> switch to the more accurate, paid
    engine (configs/ocr.json `escalation`); the decision is data, the signals stay raw in the state."""
    if mean_conf is not None and mean_conf < OCR.get("escalate_min_mean_conf", 0.0):
        return True
    return low_conf_ratio is not None and low_conf_ratio > OCR.get("escalate_max_low_conf_ratio", 1.0)


def require_review(state: FlowState, *reasons: str) -> None:
    """Additive latch: `needs_review` only changes False -> True; the reasons accumulate deduplicated."""
    new = [r for r in reasons if r and r not in state.review_reasons]
    if new:
        state.review_reasons.extend(new)
        state.needs_review = True


def pick_policy_fields(pack) -> set[str]:
    """The fields of the band check: the scored, the required and the high-stakes fields (066 Á04: a high-stakes but
    unscored field, e.g. the Hungarian invoice's amount payable, used to be left out)."""
    return set(pack.scored_fields) | set(pack.required) | set(pack.high_stakes)


def presence_probe_fields(pack) -> set[str]:
    """069 (Á11): fields that get a presence question even without candidates: the band check's fields, except the
    required ones (they get a to-do without candidates anyway) and the informational-only ones (their uncertainty does
    not send them to the manual queue)."""
    informational_only = set(pack.informational_fields) - set(pack.high_stakes)
    return pick_policy_fields(pack) - set(pack.required) - informational_only


def apply_pick_policy(state: FlowState) -> None:
    """S path: review reasons from the picks' band (confidence threshold, second-option gap) and the required fields
    (the pack's lists)."""
    pack = get_pack(state.doc_type)
    checked, required, high_stakes = pick_policy_fields(pack), set(pack.required), set(pack.high_stakes)
    informational = set(pack.informational_fields)
    for field, pick in state.picks.items():
        if field not in checked:
            continue
        if field in informational and field not in high_stakes:
            continue  # informational only (e.g. address): unscored, no manual queue; a high-stakes IBAN still counts
        if pick.n_options == 0:
            if field in required:
                require_review(state, f"pick:no_candidates:{field}")
            elif pick.present_p is not None and noul_band(pick.present_p, "invoice.pick.presence") == "yes":
                require_review(state, f"pick:present_no_candidates:{field}:{pick.present_p:.2f}")  # 069 Á11: none found
            continue
        if pick.label is None and field in required:
            require_review(state, f"pick:none:{field}")
        if pick.present_p is not None:  # presence Noul vs Choice: a contradiction is a review reason (uncertain is not)
            nb = noul_band(pick.present_p, "invoice.pick.presence")
            if pick.label is not None and nb == "no":
                require_review(state, f"pick:absent_but_chosen:{field}:{pick.present_p:.2f}")
            elif pick.label is None and nb == "yes":
                require_review(state, f"pick:present_but_none:{field}:{pick.present_p:.2f}")
        base = choice_review_reason("pick", field, pick.confidence, pick.probabilities, "invoice.pick")
        if base:
            require_review(state, base)
        elif field in high_stakes and choice_band(pick.confidence, pick.probabilities, "invoice.pick.high_stakes") == "human":
            require_review(state, f"pick:high_stakes_conf:{field}:{pick.confidence:.2f}")


def apply_verdict_policy(state: FlowState) -> None:
    """G path: values without evidence and `yes`-band JEV flags are review reasons (uncertain only if enabled)."""
    v = state.verdicts
    if v is None:
        return
    pack = get_pack(state.doc_type)
    skip = set(pack.informational_fields) - set(pack.high_stakes)  # informational only (address): flags not queued
    for field in v.unsupported:
        if field not in skip:
            require_review(state, f"jev:unsupported:{field}")
    for field, flags in v.flags.items():
        if field in skip:
            continue
        for flag, p in flags.items():
            reason = noul_review_reason("jev", f"{flag}:{field}", p, "invoice.verify")
            if reason:
                require_review(state, reason)
    for flag, p in v.doc_flags.items():
        reason = noul_review_reason("jev", flag, p, "invoice.verify")
        if reason:
            require_review(state, reason)
    if state.invoice is not None:
        for field in required_for(state.doc_type):
            if state.invoice.get_field(field) is None:
                require_review(state, f"llm:required_missing:{field}")


def apply_validation_policy(state: FlowState) -> None:
    for check in state.validation:
        if not check.ok and not check.advisory:  # 053: an advisory-only check opens no to-do
            require_review(state, f"validator:{check.code}")


def decide(state: FlowState) -> str:
    """'auto' or 'human'. The latch already holds every reason; here we only sum up."""
    if state.arm == "S":
        apply_pick_policy(state)
    else:
        apply_verdict_policy(state)
    apply_validation_policy(state)
    if state.invoice is None:
        require_review(state, "no_invoice")
    return "human" if state.needs_review else "auto"


# --------------------------------------------------------------------------------------
# M3: email intent -> next_flow (code decides; JEV's raw intent + confidence + Noul signals stay in the state)
# --------------------------------------------------------------------------------------

INTENT_HUMAN_MAX_CONF: float = band("email.intent")["choice_human_max_conf"]  # below: manual queue, whatever the label
M2_TYPES = frozenset(_EMAIL["m2_types"])  # has / will have an M2 flow
INTENT_ROUTE: dict[str, str] = dict(_EMAIL["intent_route"])  # attachment-independent default per intent
EMAIL_JEV_UNAVAILABLE_ROUTE: str = _EMAIL["jev_unavailable_route"]  # JEV did not answer -> manual queue


EMAIL_SIGNAL_REVIEW: tuple[str, ...] = tuple(_EMAIL.get("signal_review", ()))  # signals whose yes band means review
EMAIL_SIGNAL_ROUTES: dict[str, str] = dict(_EMAIL.get("signal_routes", {}))  # yes-band signal -> route (overrides all)


def email_signal_reasons(signals: dict[str, float] | None) -> list[str]:
    """Review reasons of the M3 Noul signals: `signal:<key>:<p>` in the `yes` band of `email.signal` (uncertain only
    if enabled)."""
    out: list[str] = []
    for key in EMAIL_SIGNAL_REVIEW:
        p = (signals or {}).get(key)
        if p is None:
            continue
        reason = noul_review_reason("signal", key, float(p), "email.signal")
        if reason:
            out.append(reason)
    return out


def email_signal_route(signals: dict[str, float] | None) -> str | None:
    """Signal-driven route (e.g. injected instruction -> `human:suspicious`) if the signal is in the `yes` band of
    `email.signal`."""
    for key, route in EMAIL_SIGNAL_ROUTES.items():
        p = (signals or {}).get(key)
        if p is not None and noul_band(float(p), "email.signal") == "yes":
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
    if choice_needs_review(confidence, probabilities, "email.intent"):
        return _EMAIL["low_conf_route"]
    if intent in DOCUMENT_BEARING:
        typed = [a for a in attachments if a.doc_type in M2_TYPES]
        if typed:
            return f"m2:{typed[0].doc_type}"
        if any(a.status == "needs_ocr" for a in attachments):
            return _EMAIL["needs_ocr_route"]
        if any(a.ext == ".pdf" and a.status in (None, "name_only", "skipped") for a in attachments):
            return _EMAIL["detect_route"]
    return INTENT_ROUTE.get(intent, _EMAIL["default_route"])
