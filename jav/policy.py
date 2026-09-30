"""Döntési szabályok - a küszöbszámok és útvonalak a `configs/policy.json`-ból (konfig mint adat), a logika itt.

A Jev nyers valószínűségei (`FieldPick.probabilities`, `JevVerdicts.flags`, `IntentResult.signals`) érintetlenül
maradnak a state-ben; itt csak az értelmezésük történik. Egy küszöb módosítása (a JSON-ban, verzió-lépéssel) nem
igényel újrafuttatást, ha a kérdések és a bizonyítékok nem változtak (a nyers futások `runs/*.jsonl`-ből
újraértékelhetők).

Típus-függő listák (kötelező mezők, magas tétű mezők, pontozott mezők) a típus-csomagból (`configs/types/<típus>.json`,
`jav/typepack.py`) jönnek a `state.doc_type` szerint; a küszöbök (sávok) típus-függetlenek, itt.
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
DETECT_DETAIL: dict[str, Any] = dict(_CFG["detect_detail"])  # 047 T1.2: a részletes típus kód-döntésének küszöbe

# --------------------------------------------------------------------------------------
# Sávok (policy.json v1.1.0): nevesített készletek hívási helyenként, precedencia a pontozott előtag hossza szerint
# --------------------------------------------------------------------------------------

BANDS: dict[str, dict[str, Any]] = {name: dict(v) for name, v in _CFG["bands"].items()}
BAND_FOR: dict[str, str] = dict(_CFG["band_for"])
NoulBand = Literal["no", "uncertain", "yes"]
ChoiceBand = Literal["auto", "uncertain", "human"]


def band_name(callsite: str) -> str:
    """`invoice.pick.high_stakes.gross_total` -> a leghosszabb illeszkedő `band_for` kulcs készlete, különben `default`."""
    parts = callsite.split(".")
    for n in range(len(parts), 0, -1):
        key = ".".join(parts[:n])
        if key in BAND_FOR:
            return BAND_FOR[key]
    return "default"


def band(callsite: str) -> dict[str, Any]:
    """A hívási hely feloldott sáv-készlete: a nevesített készlet a `default` fölé merge-elve (hiányzó mező öröklődik)."""
    return {**BANDS["default"], **BANDS.get(band_name(callsite), {})}


def noul_band(p: float, callsite: str) -> NoulBand:
    """Kétoldali sáv egy Noul P(igen)-re: `no` (< no_max), `uncertain`, `yes` (>= yes_min)."""
    b = band(callsite)
    if p < b["noul_no_max"]:
        return "no"
    if p >= b["noul_yes_min"]:
        return "yes"
    return "uncertain"


def second_option_gap(probabilities: dict[str, float] | None) -> float | None:
    """A legvalószínűbb és a második opció valószínűségének különbsége; None, ha nincs két opció."""
    if not probabilities or len(probabilities) < 2:
        return None
    top = sorted(probabilities.values(), reverse=True)
    return round(top[0] - top[1], 4)


def choice_band(confidence: float, probabilities: dict[str, float] | None, callsite: str) -> ChoiceBand:
    """Choice-sáv: `human` a conf-küszöb alatt; `uncertain`, ha a második opció túl közel van; különben `auto`."""
    b = band(callsite)
    if confidence < b["choice_human_max_conf"]:
        return "human"
    gap = second_option_gap(probabilities)
    if gap is not None and gap < b["choice_second_min_gap"]:
        return "uncertain"
    return "auto"


def choice_needs_review(confidence: float, probabilities: dict[str, float] | None, callsite: str) -> bool:
    """`human` mindig; `uncertain` csak ha a készlet `uncertain_review: true`."""
    cb = choice_band(confidence, probabilities, callsite)
    return cb == "human" or (cb == "uncertain" and bool(band(callsite)["uncertain_review"]))


def choice_review_reason(prefix: str, key: str, confidence: float, probabilities: dict[str, float] | None, callsite: str) -> str | None:
    """Review-ok szöveg egy Choice-ítéletre, vagy None: `<prefix>:low_conf:<key>:<conf>` | `<prefix>:second_option:<key>:<rés>`."""
    cb = choice_band(confidence, probabilities, callsite)
    if cb == "human":
        return f"{prefix}:low_conf:{key}:{confidence:.2f}"
    if cb == "uncertain" and band(callsite)["uncertain_review"]:
        return f"{prefix}:second_option:{key}:{second_option_gap(probabilities):.2f}"
    return None


def noul_review_reason(prefix: str, key: str, p: float, callsite: str) -> str | None:
    """Review-ok szöveg egy Noul-jelre, vagy None: `<prefix>:<key>:<p>` (yes) | `<prefix>:uncertain:<key>:<p>` (ha engedélyezett)."""
    nb = noul_band(p, callsite)
    if nb == "yes":
        return f"{prefix}:{key}:{p:.2f}"
    if nb == "uncertain" and band(callsite)["uncertain_review"]:
        return f"{prefix}:uncertain:{key}:{p:.2f}"
    return None


def parent_fallback(confidence: float, parent: str | None, parent_prob: float, callsite: str, probabilities: dict[str, float] | None = None) -> str | None:
    """Szülő-címke: ha a típus / szándék bizonytalan (nem `auto` sáv), de a család összesített valószínűsége eléri a
    `parent_min_prob`-ot, a család neve; különben None. Csak címke a review-hoz és a riporthoz, a route nem változik."""
    if parent is None or choice_band(confidence, probabilities, callsite) == "auto":
        return None
    return parent if parent_prob >= band(callsite)["parent_min_prob"] else None


# Örökölt nevek (a flow-k és tesztek hivatkozzák) - a sávokból származnak, nem külön adat
HUMAN_MAX_CONF: float = band("invoice.pick")["choice_human_max_conf"]  # ez alatt bármely pontozott mező -> human
AUTO_MIN_CONF_HIGH_STAKES: float = band("invoice.pick.high_stakes")["choice_human_max_conf"]  # magas tétű mezők automatikus elfogadásához
REVIEW_FLAG_P: float = band("invoice.verify")["noul_yes_min"]  # G-kar: Noul P(igen) egy hiba-flagre, ettől review
DETECT_LOW_CONFIDENCE: float = band("detect.doc_type")["choice_human_max_conf"]  # M1: ez alatt a típus bizonytalan (review-jelölt), de mentjük

# Típus-függő listák: a típus-csomagból (a magyar számláé mint örökölt modul-konstans; más típusnál `high_stakes_for` / `required_for`)
HIGH_STAKES = frozenset(get_pack(DEFAULT_KEY).high_stakes)
REQUIRED = frozenset(get_pack(DEFAULT_KEY).required)  # a régi rules.json `required` listája


def high_stakes_for(doc_type: str | None) -> frozenset[str]:
    return frozenset(get_pack(doc_type or DEFAULT_KEY).high_stakes)


def required_for(doc_type: str | None) -> frozenset[str]:
    return frozenset(get_pack(doc_type or DEFAULT_KEY).required)


OCR: dict[str, float] = {k: float(v) for k, v in _CFG.get("ocr", {}).items()}  # v1.6.0: OCR-minőség küszöbök


OCR_REVIEW_PRODUCER = "ocr"  # 066 Á01: a szöveg nélküli irat teendőjének felvevője (M1 és M2 közös); szöveg esetén zárul


def ocr_review_reasons(mean_conf: float | None, low_conf_ratio: float | None) -> list[str]:
    """OCR-szövegű dokumentum: gyenge átlagos szó-bizalom vagy sok gyenge szó -> review-okok (a nyers jelek a state-ben maradnak)."""
    out: list[str] = []
    if mean_conf is not None and mean_conf < OCR.get("min_mean_conf", 0.0):
        out.append(f"ocr:low_confidence:{mean_conf:.2f}")
    if low_conf_ratio is not None and low_conf_ratio > OCR.get("max_low_conf_ratio", 1.0):
        out.append(f"ocr:low_conf_words:{low_conf_ratio:.2f}")
    return out


def ocr_coverage_reasons(page_count: int | None, pages_ocr: int | None) -> list[str]:
    """Részleges OCR (040 K1, F07): ha kevesebb oldal ment át OCR-en, mint amennyi az iratban van, az mindig látható
    teendő (nem küszöb, hanem tény) — így a kihagyott oldalak adata nem tűnhet teljesnek, és a jóváhagyást is megállítja."""
    if page_count is None or pages_ocr is None or pages_ocr >= page_count:
        return []
    return [f"ocr:partial_pages:{pages_ocr}/{page_count}"]


def ocr_should_escalate(mean_conf: float | None, low_conf_ratio: float | None) -> bool:
    """Gyenge helyi OCR (a policy `ocr.escalate_*` küszöbei alatt / fölött) -> a pontosabb, fizetős motorra (configs/ocr.json
    `escalation`) váltunk; a döntés adat, a jelek nyersen a state-ben maradnak."""
    if mean_conf is not None and mean_conf < OCR.get("escalate_min_mean_conf", 0.0):
        return True
    return low_conf_ratio is not None and low_conf_ratio > OCR.get("escalate_max_low_conf_ratio", 1.0)


def require_review(state: FlowState, *reasons: str) -> None:
    """Additív latch: `needs_review` csak False -> True irányban változik; az okok deduplikálva gyűlnek."""
    new = [r for r in reasons if r and r not in state.review_reasons]
    if new:
        state.review_reasons.extend(new)
        state.needs_review = True


def pick_policy_fields(pack) -> set[str]:
    """A sávvizsgálat mezői: a pontozott, a kötelező és a magas tétű mezők (066 Á04: a magas tétű, de nem pontozott
    mező, pl. a magyar számla fizetendő összege, eddig kimaradt)."""
    return set(pack.scored_fields) | set(pack.required) | set(pack.high_stakes)


def presence_probe_fields(pack) -> set[str]:
    """069 (Á11): jelölt nélkül is jelenlét-kérdést kapó mezők: a sávvizsgálat mezői, kivéve a kötelezőket (nekik jelölt
    nélkül is teendő jár) és a csak informatív mezőket (bizonytalanságuk nem küld kézi sorba)."""
    informational_only = set(pack.informational_fields) - set(pack.high_stakes)
    return pick_policy_fields(pack) - set(pack.required) - informational_only


def apply_pick_policy(state: FlowState) -> None:
    """S-kar: a pickek sávja (conf-küszöb, második-opció rés) és a kötelező mezők alapján review-okok (a csomag listái)."""
    pack = get_pack(state.doc_type)
    checked, required, high_stakes = pick_policy_fields(pack), set(pack.required), set(pack.high_stakes)
    informational = set(pack.informational_fields)
    for field, pick in state.picks.items():
        if field not in checked:
            continue
        if field in informational and field not in high_stakes:
            continue  # csak informatív mező (pl. cím): a régi szerződés nem pontozza, bizonytalansága nem küld kézi sorba (a magas tétű IBAN igen)
        if pick.n_options == 0:
            if field in required:
                require_review(state, f"pick:no_candidates:{field}")
            elif pick.present_p is not None and noul_band(pick.present_p, "invoice.pick.presence") == "yes":
                require_review(state, f"pick:present_no_candidates:{field}:{pick.present_p:.2f}")  # 069 Á11: a kód nem találta meg
            continue
        if pick.label is None and field in required:
            require_review(state, f"pick:none:{field}")
        if pick.present_p is not None:  # jelenlét-Noul a Choice mellett: ellentmondás = review-ok (kétoldali sáv, uncertain nem ok)
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
    """G-kar: evidencia nélküli értékek és a `yes` sávba eső Jev-flagek review-okok (uncertain csak ha engedélyezett)."""
    v = state.verdicts
    if v is None:
        return
    pack = get_pack(state.doc_type)
    skip = set(pack.informational_fields) - set(pack.high_stakes)  # csak informatív mezők (cím): a flagjük nem küld kézi sorba
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
        if not check.ok and not check.advisory:  # 053: a csak jelző ellenőrzés nem nyit teendőt
            require_review(state, f"validator:{check.code}")


def decide(state: FlowState) -> str:
    """'auto' vagy 'human'. A latch már tartalmaz minden okot; itt csak összegzünk."""
    if state.arm == "S":
        apply_pick_policy(state)
    else:
        apply_verdict_policy(state)
    apply_validation_policy(state)
    if state.invoice is None:
        require_review(state, "no_invoice")
    return "human" if state.needs_review else "auto"


# --------------------------------------------------------------------------------------
# M3: e-mail szándék -> next_flow (kód dönt; a Jev nyers intent + confidence + Noul-jelek a state-ben maradnak)
# --------------------------------------------------------------------------------------

INTENT_HUMAN_MAX_CONF: float = band("email.intent")["choice_human_max_conf"]  # intent-routing minta: ez alatt kézi sor, bármi is a címke
M2_TYPES = frozenset(_EMAIL["m2_types"])  # van / lesz M2-flow-ja
INTENT_ROUTE: dict[str, str] = dict(_EMAIL["intent_route"])  # csatolmány-független alapértelmezés szándékonként
EMAIL_JEV_UNAVAILABLE_ROUTE: str = _EMAIL["jev_unavailable_route"]  # a Jev nem válaszolt (adapter: JevUnavailableError) -> kézi sor


EMAIL_SIGNAL_REVIEW: tuple[str, ...] = tuple(_EMAIL.get("signal_review", ()))  # mely Noul-jel igen-sávja review-ok
EMAIL_SIGNAL_ROUTES: dict[str, str] = dict(_EMAIL.get("signal_routes", {}))  # jel igen-sávban -> útvonal (minden más elé)


def email_signal_reasons(signals: dict[str, float] | None) -> list[str]:
    """M3 Noul-jelek review-okai: `signal:<kulcs>:<p>` az `email.signal` sáv `yes` sávjában (uncertain csak ha engedélyezett)."""
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
    """Jel-vezérelt útvonal (pl. beszúrt utasítás -> `human:suspicious`), ha a jel az `email.signal` sáv `yes` sávjában van."""
    for key, route in EMAIL_SIGNAL_ROUTES.items():
        p = (signals or {}).get(key)
        if p is not None and noul_band(float(p), "email.signal") == "yes":
            return route
    return None


def email_next_flow(
    intent: str, confidence: float, attachments: list[Attachment], probabilities: dict[str, float] | None = None, signals: dict[str, float] | None = None
) -> str:
    """Determinisztikus útvonal: jel-útvonal (beszúrt utasítás) -> sáv (küszöb + második-opció rés) -> dokumentum-hordozó
    szándéknál a csatolmány típusa -> alapértelmezés."""
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
