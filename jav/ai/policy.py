"""Decision rules - the shared thresholds come from `configs/policy.json` (config as data), the logic is here.

224 (plan G-process-core P3c): a domain's own rules are in its own file, read by its own module: the email routes
(`configs/email.json`, `jav/domains/email/email_rules.py`), the duplicate search and the reconciliation's bands
(`configs/finance.json`, `jav/domains/finance/duplicates.py`, `jav/domains/finance/reconcile_rules.py`). They judge with the
bands here.

JEV's raw probabilities (`FieldPick.probabilities`, `JevVerdicts.flags`, `IntentResult.signals`) stay untouched in the
state; only their interpretation happens here. Changing a threshold (in the JSON, with a version bump) needs no re-run
if the questions and the evidence have not changed (the raw runs can be re-evaluated from `runs/*.jsonl`).

Type-dependent lists (required fields, high-stakes fields, scored fields) come from the type pack
(`configs/types/<type>.json`, `jav/ai/typepack.py`) according to `state.doc_type`; the thresholds (bands) are
type-independent and live here.
"""

from __future__ import annotations

from typing import Any, Literal

from jav.ai import checks
from jav.core import cfg, trace, type_roles
from jav.ai.models import CheckResult, FlowState
from jav.ai.typepack import get as get_pack
from jav.documents.ocr import quality_limits

# 227 (plan R3b): the rules are read through the config loader when they are applied, not copied when this module is
# loaded, so a reloaded `configs/policy.json` reaches every decision without a restart (`cfg.Section`)


def config_hash() -> str:
    """The fingerprint of `configs/policy.json` as it is loaded now (a data point's `config_hash` names it)."""
    return cfg.config_hash("policy")


# the none option's key is part of every S-path request: a change is a new request, measured and released (kept)
NONE_LABEL: str = cfg.load("policy")["none_label"]
DETECT_DETAIL = cfg.Section("policy", "detect_detail")  # 047 T1.2: threshold of the detailed-type code decision
DETECT_ISSUER = cfg.Section("policy", "detect_issuer")  # 090: the type / issuer cross-check
GPT_FIELD_CONFIDENCE = cfg.Section("policy", "gpt_field_confidence")  # 091: a GPT field's confidence without JEV

# --------------------------------------------------------------------------------------
# Bands (policy.json v1.1.0): named sets per call site, precedence by the length of the dotted prefix
# --------------------------------------------------------------------------------------

BANDS = cfg.Section("policy", "bands")
BAND_FOR = cfg.Section("policy", "band_for")
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


def band_keys(callsite: str, *fields: str) -> tuple[str, ...]:
    """218 (P3b): the `policy.json` keys a band decision of the call site reads, for the decision trace: the matched
    `band_for` key and each field's set (the named set's own value, or the `default` it inherits)."""
    parts = callsite.split(".")
    matched = next((".".join(parts[:n]) for n in range(len(parts), 0, -1) if ".".join(parts[:n]) in BAND_FOR), None)
    name = band_name(callsite)
    return ((f"band_for.{matched}",) if matched else ()) + tuple(
        f"bands.{name if field in BANDS.get(name, {}) else 'default'}.{field}" for field in fields)


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


def detail_direction(key: str | None, probabilities: dict[str, float] | None, direction: str | None) -> str | None:
    """149: whether the direction the own parties give an invoice settles its uncertain detailed type: `confirmed`
    (the type's side, `detect_detail.direction_sides`), `contradicted` (the side of the runner-up), or None when the
    uncertainty was not between an outgoing and an incoming pack, or the parties do not say."""
    sides = {k: side for side in ("outgoing", "incoming") for k in type_roles.types(f"direction:{side}")}
    if not key or key not in sides or not probabilities:
        return None
    rivals = sorted(((p, k) for k, p in probabilities.items() if k not in (key, "none")), reverse=True)
    if not rivals or sides.get(rivals[0][1]) in (None, sides[key]):
        return None
    if direction == sides[key]:
        return "confirmed"
    return "contradicted" if direction == sides[rivals[0][1]] else None


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


def issuer_mismatch_reason(doc_type: str | None, detail_type: str | None, issuer_hu: float | None, *, engine: str) -> str | None:
    """090 (backlog F-gpt-type-check): a code cross-check of a recognised type against the recogniser's own issuer
    judgement. A type or detailed type that presumes a Hungarian issuer (`detect_issuer.hungarian_types`) while
    P(issuer is Hungarian) is in the `no` band of `detect.issuer_is_hungarian.<engine>` contradicts itself: the to-do
    `detect:issuer_mismatch:<type>` (the detailed type named when it is the Hungarian one); the type is kept. Only for
    the engines in `detect_issuer.engines`. A foreign invoice with a Hungarian issuer is no contradiction: the form
    decides there (an Upwork invoice of a Hungarian freelancer is `invoice_foreign`)."""
    if engine not in DETECT_ISSUER["engines"] or issuer_hu is None:
        return None
    hungarian = set(type_roles.types("hungarian_issuer"))
    claimed = detail_type if detail_type in hungarian else doc_type if doc_type in hungarian else None
    if claimed and noul_band(issuer_hu, f"detect.issuer_is_hungarian.{engine}") == "no":
        return f"detect:issuer_mismatch:{claimed}"
    return None


def foreign_issuer_pack(broad: str, issuer_hu: float | None, *, engine: str) -> str | None:
    """122 (backlog Q-upwork-type, DECISIONS 083): the type pack for a category whose own packs presume a Hungarian
    issuer, when the recogniser's own issuer judgement says the issuer is not Hungarian (`detect_detail.
    foreign_issuer_pack`; the `no` band of `detect.issuer_is_hungarian[.gpt]`). A receipt of a foreign business is a
    foreign invoice by the registry; the only receipt pack is the Hungarian tax authority's. An uncertain or missing
    judgement routes nothing: the detailed-type question decides then."""
    pack = DETECT_DETAIL.get("foreign_issuer_pack", {}).get(broad)
    if pack is None or issuer_hu is None:
        return None
    callsite = "detect.issuer_is_hungarian" + (".gpt" if engine == "gpt" else "")
    return pack if noul_band(issuer_hu, callsite) == "no" else None


def gpt_field_confidence(token_p: dict[str, float | int] | None, status: str | None, *, failed_check: bool) -> float | None:
    """091 (backlog F-gpt-field-confidence): the confidence of a field GPT extracted, on the G path without JEV. The
    token probability of the value (`gpt_field_confidence.measure`) capped by the code's evidence: the source location's
    status (`evidence`: a value not printed on the document, or only next to another field's label) and a failed field
    check (`failed_check`); the weaker counts. Without a token probability only a cap below 1 is an estimate (a located
    value alone is not), otherwise None. What is shown; the to-do (092) is `apply_gpt_confidence_policy`."""
    caps = [float(GPT_FIELD_CONFIDENCE["evidence"][status])] if status in GPT_FIELD_CONFIDENCE["evidence"] else []
    if failed_check:
        caps.append(float(GPT_FIELD_CONFIDENCE["failed_check"]))
    token = token_p.get(GPT_FIELD_CONFIDENCE["measure"]) if token_p else None
    parts = caps + ([float(token)] if token is not None else [])
    return round(min(parts), 4) if parts else None


def parent_fallback(confidence: float, parent: str | None, parent_prob: float, callsite: str, probabilities: dict[str, float] | None = None) -> str | None:
    """Parent label: if the type / intent is uncertain (not the `auto` band) but the family's total probability
    reaches `parent_min_prob`, the family's name; otherwise None. Only a label for the review and the report; the
    route does not change."""
    if parent is None or choice_band(confidence, probabilities, callsite) == "auto":
        return None
    return parent if parent_prob >= band(callsite)["parent_min_prob"] else None


# Named thresholds (referenced by the flows, the measurements and tests) - read from the bands when asked (227), not
# separate data


def human_max_conf() -> float:
    """Below this, any scored field -> human (`invoice.pick`)."""
    return float(band("invoice.pick")["choice_human_max_conf"])


def auto_min_conf_high_stakes() -> float:
    """A high-stakes field's auto-accept (`invoice.pick.high_stakes`)."""
    return float(band("invoice.pick.high_stakes")["choice_human_max_conf"])


def review_flag_p() -> float:
    """G path: a Noul's P(yes) from which an error flag is a review (`invoice.verify`)."""
    return float(band("invoice.verify")["noul_yes_min"])


def detect_low_confidence() -> float:
    """M1: an uncertain type below it; still saved (`detect.doc_type`)."""
    return float(band("detect.doc_type")["choice_human_max_conf"])

# Type-dependent lists: from the named type's pack (202: no Hungarian invoice module constant)


def high_stakes_for(doc_type: str) -> frozenset[str]:
    return frozenset(get_pack(doc_type).high_stakes)


OCR_REVIEW_PRODUCER = "ocr"  # 066 Á01: producer of the no-text to-do (shared by M1 and M2); closed once there is text


def ocr_review_reasons(mean_conf: float | None, low_conf_ratio: float | None) -> list[str]:
    """Document with OCR text: weak mean word confidence or many weak words -> review reasons (the raw signals stay in
    the state). v1.6.0: the thresholds of `configs/policy.json` `ocr`, read by the OCR module (227)."""
    limits = quality_limits()
    out: list[str] = []
    if mean_conf is not None and mean_conf < limits.get("min_mean_conf", 0.0):
        out.append(f"ocr:low_confidence:{mean_conf:.2f}")
    if low_conf_ratio is not None and low_conf_ratio > limits.get("max_low_conf_ratio", 1.0):
        out.append(f"ocr:low_conf_words:{low_conf_ratio:.2f}")
    return out


def ocr_coverage_reasons(page_count: int | None, pages_ocr: int | None) -> list[str]:
    """Partial OCR (040 K1, F07): if fewer pages went through OCR than the document has, that is always a visible to-do
    (not a threshold but a fact) — so the data of the skipped pages cannot look complete, and it also stops approval."""
    if page_count is None or pages_ocr is None or pages_ocr >= page_count:
        return []
    return [f"ocr:partial_pages:{pages_ocr}/{page_count}"]


def reason_field(code: str, fields: set[str]) -> str | None:
    """083: the simple field a to-do is about, or None when it is about the document (or a line item). The field stands
    third in most codes (`pick:low_conf:payment_iban:0.53`) and first in a parse error (`meter_reading_start:unparseable`);
    only a simple field of the item's type pack counts. 160-D: here, so the eval report reads it too."""
    parts = code.split(":")
    for part in (parts[2] if len(parts) > 2 else None, parts[0]):
        if part in fields:
            return part
    return None


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


# --- 218 (plan P3 P3b): the extraction's decision as pure rules over its traced inputs. Each decision check of the
# registry applies its rule to the flow state (`apply_*`); the route's rule (`route_rule`) replays them in the registry's
# order, so the stored to-dos are the rule's value for the stored inputs. Ordered parts are lists (the trace stores its
# JSON with sorted keys). ------------------------------------------------------------------------------------------------

ROUTE_POINT = "extract.route"
_CHOICE_FIELDS = ("choice_human_max_conf", "choice_second_min_gap", "uncertain_review")
_NOUL_FIELDS = ("noul_no_max", "noul_yes_min", "uncertain_review")


def _pick_inputs(field: str, pick: Any) -> dict[str, Any]:
    """What the band reads of a pick: whether an option was chosen, its confidence, the two most likely options (the
    second-option gap), the options sent and the candidates found (a cut list) and the presence Noul."""
    top = sorted(pick.probabilities.items(), key=lambda kv: kv[1], reverse=True)[:2]
    return {"field": field, "chosen": pick.label is not None, "confidence": pick.confidence, "probabilities": dict(top),
            "n_options": pick.n_options, "n_candidates": pick.n_candidates, "present_p": pick.present_p}


def _verdict_inputs(v: Any) -> dict[str, Any] | None:
    if v is None:
        return None
    return {"source": v.source, "unsupported": list(v.unsupported), "omitted": list(v.omitted),
            "flags": [[f, [[flag, p] for flag, p in flags.items()]] for f, flags in v.flags.items()],
            "doc_flags": [[flag, p] for flag, p in v.doc_flags.items()]}


def decision_inputs(state: FlowState) -> dict[str, Any]:
    """What the extraction's decision reads of the flow state: the path and the type pack, the to-dos raised before it,
    the S path's picks, the G path's verification and token probabilities, the record's unset and empty fields, the
    failed record checks, and (filled in by `decide`) the cross-document checks' to-dos."""
    pack, rec = get_pack(state.doc_type), state.record
    values = rec.to_datapoints(pack.header_fields) if rec is not None else {}
    return {
        "arm": state.arm, "doc_type": state.doc_type, "jev": state.jev, "has_record": rec is not None,
        "earlier": list(state.review_reasons),
        "picks": [_pick_inputs(f, p) for f, p in state.picks.items()] if state.arm == "S" else [],
        "verdicts": _verdict_inputs(state.verdicts) if state.arm == "G" else None,
        "tokens": dict(state.llm_token_p or {}) if state.arm == "G" and not state.jev else {},
        "unset": [f for f in pack.record_fields if rec.get_field(f) is None] if rec is not None else [],
        "empty": [f for f in pack.header_fields if values.get(f) in (None, "", [])],
        "checks": [{"name": c.name, "code": c.code, "advisory": c.advisory} for c in state.validation if not c.ok],
        "cross_document": [],
    }


def pick_rule(inputs: dict[str, Any]) -> list[str]:
    """S path: the to-dos of the picks' band (confidence threshold, second-option gap, the high-stakes threshold), the
    presence Noul against the choice, a cut candidate list and the required fields (the pack's lists)."""
    pack = get_pack(inputs["doc_type"])
    checked, required, high_stakes = pick_policy_fields(pack), set(pack.required), set(pack.high_stakes)
    informational = set(pack.informational_fields)
    out: list[str] = []
    for pick in inputs["picks"]:
        field, present_p, conf, probs = pick["field"], pick["present_p"], pick["confidence"], pick["probabilities"]
        if field not in checked:
            continue
        if field in informational and field not in high_stakes:
            continue  # informational only (e.g. address): unscored, no manual queue; a high-stakes IBAN still counts
        if pick["n_options"] == 0:
            if field in required:
                out.append(f"pick:no_candidates:{field}")
            elif present_p is not None and noul_band(present_p, "invoice.pick.presence") == "yes":
                out.append(f"pick:present_no_candidates:{field}:{present_p:.2f}")  # 069 Á11: none found
            continue
        if not pick["chosen"] and field in required:
            out.append(f"pick:none:{field}")
        if not pick["chosen"] and pick["n_candidates"] is not None and pick["n_candidates"] > pick["n_options"]:
            # 076 (candidate-list cut): JEV saw only part of the candidates; the right one may have been cut off
            out.append(f"pick:none_on_cut_list:{field}:{pick['n_options']}/{pick['n_candidates']}")
        if present_p is not None:  # presence Noul vs Choice: a contradiction is a review reason (uncertain is not)
            nb = noul_band(present_p, "invoice.pick.presence")
            if pick["chosen"] and nb == "no":
                out.append(f"pick:absent_but_chosen:{field}:{present_p:.2f}")
            elif not pick["chosen"] and nb == "yes":
                out.append(f"pick:present_but_none:{field}:{present_p:.2f}")
        base = choice_review_reason("pick", field, conf, probs, "invoice.pick")
        if base:
            out.append(base)
        elif field in high_stakes and choice_band(conf, probs, "invoice.pick.high_stakes") == "human":
            out.append(f"pick:high_stakes_conf:{field}:{conf:.2f}")
    return out


def apply_pick_policy(state: FlowState) -> None:
    """S path: the picks' to-dos (`pick_rule`)."""
    require_review(state, *dict.fromkeys(pick_rule(decision_inputs(state))))


def _required_missing(inputs: dict[str, Any]) -> list[str]:
    """175: the pack's required fields the record leaves unset, in the pack's order (a set's order depended on the
    process's hash seed)."""
    if inputs["verdicts"] is None or not inputs["has_record"]:
        return []
    unset = set(inputs["unset"])
    return [f for f in get_pack(inputs["doc_type"]).required if f in unset]


def verdict_rule(inputs: dict[str, Any]) -> list[str]:
    """G path: values without evidence, the lists left out of the verification, the `yes`-band JEV flags (uncertain
    only if enabled) and the required fields the record leaves unset (192: unless the pack only notes them)."""
    v = inputs["verdicts"]
    if v is None:
        return []
    pack = get_pack(inputs["doc_type"])
    skip = set(pack.informational_fields) - set(pack.high_stakes)  # informational only (address): flags not queued
    # 085: the code's own check alone names what it found (the JEV path keeps its earlier reason code)
    unsupported = "source:not_found" if v["source"] == "code" else "jev:unsupported"
    out = [f"{unsupported}:{f}" for f in v["unsupported"] if f not in skip]
    # 167 (AI-10): a list left out of the request to fit its size; its rows were never checked
    out += [f"jev:list_omitted:{f}" for f in v["omitted"]]
    for field, flags in v["flags"]:
        if field in skip:
            continue
        out += [r for flag, p in flags if (r := noul_review_reason("jev", f"{flag}:{field}", p, "invoice.verify"))]
    out += [r for flag, p in v["doc_flags"] if (r := noul_review_reason("jev", flag, p, "invoice.verify"))]
    if pack.required_review:
        out += [f"llm:required_missing:{f}" for f in _required_missing(inputs)]
    return out


def apply_verdict_policy(state: FlowState) -> None:
    """G path: the verification's to-dos (`verdict_rule`). 192: a pack read as one part of a whole judged elsewhere
    notes a missing required field as an advisory check instead (the gap is shown, but opens no to-do)."""
    inputs = decision_inputs(state)
    require_review(state, *dict.fromkeys(verdict_rule(inputs)))
    if not get_pack(state.doc_type).required_review:
        state.validation.extend(CheckResult(name=f"required:{f}", ok=False, code="required_missing", advisory=True)
                                for f in _required_missing(inputs))


def validation_rule(inputs: dict[str, Any]) -> list[str]:
    """A failed check opens a to-do. 090: a field check (its name is `<check>:<field>`) names the field third, so the
    to-do stands at that field in Review and the field's tick closes it; a check of the whole record keeps its code.
    053: an advisory-only check opens no to-do."""
    out = []
    for check in inputs["checks"]:
        if not check["advisory"]:
            field = check["name"].split(":", 1)[1] if ":" in check["name"] else None
            out.append(f"validator:{check['code']}:{field}" if field else f"validator:{check['code']}")
    return out


def apply_validation_policy(state: FlowState) -> None:
    """The failed record checks' to-dos (`validation_rule`)."""
    require_review(state, *dict.fromkeys(validation_rule(decision_inputs(state))))


def gpt_review_fields(pack_key: str) -> list[str]:
    """092: the fields whose GPT confidence can open a to-do: the accounting fields (scored, not informational, and the
    high-stakes ones), in the pack's order. 164: less the pack's `gpt_field_confidence.info_only` fields, whose GPT
    confidence only shows (an outgoing invoice's buyer address)."""
    pack = get_pack(pack_key)
    scope = (set(pack.strict_scored) | set(pack.high_stakes)) - set(GPT_FIELD_CONFIDENCE.get("info_only", {}).get(pack_key, ()))
    return [f for f in pack.header_fields if f in scope]


def gpt_confidence_rule(inputs: dict[str, Any]) -> list[str]:
    """092 (the owner's decisions of 2026-10-02): on the G path without JEV, an accounting field GPT extracted with a
    token probability below `gpt_field_confidence.review_below` is a `gpt:low_conf:<field>:<p>` to-do. A field without
    a value, or whose check already failed (it has its to-do), adds nothing; a run with JEV never gets it (`jev`), not
    even when JEV does not answer and the code's own check stands in. 160 (review AI-6): a field without a token
    probability (an answer without log-probabilities) is a `gpt:confidence_unavailable:<field>` to-do; it used to pass
    unchecked."""
    threshold = GPT_FIELD_CONFIDENCE.get("review_below")
    if inputs["jev"] or inputs["arm"] != "G" or threshold is None or not inputs["has_record"]:
        return []
    measure = GPT_FIELD_CONFIDENCE["measure"]
    failed = {c["name"].split(":", 1)[1] for c in inputs["checks"] if ":" in c["name"]}
    empty = set(inputs["empty"])
    out = []
    for field in gpt_review_fields(inputs["doc_type"]):
        token = (inputs["tokens"].get(field) or {}).get(measure)
        if field in empty or field in failed:
            continue
        if token is None:
            out.append(f"gpt:confidence_unavailable:{field}")
        elif float(token) < float(threshold):
            out.append(f"gpt:low_conf:{field}:{float(token):.2f}")
    return out


def apply_gpt_confidence_policy(state: FlowState) -> None:
    """The G path without JEV: the GPT confidence's to-dos (`gpt_confidence_rule`)."""
    require_review(state, *dict.fromkeys(gpt_confidence_rule(decision_inputs(state))))


# --- the cross-document checks: they read the store, so the check registry runs them in a worker run only (175, plan
# 170 E3: `jav/ai/checks.py`); 180 (plan 170 E7): the finance domain registers them (`jav/domains/finance/__init__.py`) -----------

def apply_cross_document_checks(state: FlowState) -> list[list[str]]:
    """The cross-document stage on the record being processed: each check's to-dos in the registry's order, nothing
    outside a worker run. Returns them, one list per check that ran (218: an input of the route's trace); the traces of
    the checks that give one are kept for the save (`state.check_traces`)."""
    subject = checks.Subject(state.doc_id, state.doc_type, state.record, [v.model_dump() for v in state.validation])
    found = checks.cross_document_traced(subject)
    for reasons, _ in found:
        require_review(state, *reasons)
    state.check_traces = [{"point": t.point, "inputs": t.inputs, "keys": {f: list(k) for f, k in t.keys.items()}}
                          for _, t in found if t is not None]
    return [reasons for reasons, _ in found]


def decide(state: FlowState) -> str:
    """'auto' or 'human'. The latch already holds every earlier reason; here the decision's checks add theirs, in the
    check registry's order (175, `jav/ai/checks.py`): the path's own checks and the failed record checks, then the
    cross-document checks (in a worker run only); a result without a record is a to-do. 218 (P3b): what it read is
    kept as `state.route_inputs`, traced with the save (`route_rule` replays it)."""
    inputs = decision_inputs(state)
    for check in checks.stage("decision"):
        if not check.arms or state.arm in check.arms:
            check.run(state)
    inputs["cross_document"] = apply_cross_document_checks(state)
    if state.record is None:
        require_review(state, "no_invoice")
    state.route_inputs = inputs
    return "human" if state.needs_review else "auto"


def route_rule(inputs: dict[str, Any]) -> dict[str, Any]:
    """The extraction's route: the decision checks' rules in the registry's order (those of the record's path), then
    the cross-document checks' to-dos and `no_invoice` for a result without a record; the to-dos it raised are the new
    ones, in order, once each. A record waits for a person (`human`) when any to-do was raised, before or here;
    otherwise it is accepted (`auto`)."""
    reasons = list(inputs["earlier"])
    for check in checks.stage("decision"):
        if not check.arms or inputs["arm"] in check.arms:
            _latch(reasons, *dict.fromkeys(check.rule(inputs)))  # type: ignore[misc] - `checks.register` requires it
    for found in inputs["cross_document"]:
        _latch(reasons, *found)
    if not inputs["has_record"]:
        _latch(reasons, "no_invoice")
    return {"route": "human" if reasons else "auto", "reasons": reasons[len(inputs["earlier"]):]}


def _latch(reasons: list[str], *found: str) -> None:
    """`require_review` on a reason list: the reasons not there before the call are added."""
    reasons.extend([r for r in found if r and r not in reasons])


def route_keys(inputs: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    """The rule keys the route's decision reads, by rule file: the bands of its path's checks in `policy.json` and the
    field roles of its type pack (with `extends`, the base pack's too: the lists are merged)."""
    pack = get_pack(inputs["doc_type"])
    if inputs["arm"] == "S":
        policy_keys = (*band_keys("invoice.pick", *_CHOICE_FIELDS), *band_keys("invoice.pick.high_stakes", "choice_human_max_conf"),
                       *band_keys("invoice.pick.presence", "noul_no_max", "noul_yes_min"))
        roles: tuple[str, ...] = ("scored_fields", "required", "high_stakes", "informational_fields")
    else:
        policy_keys = band_keys("invoice.verify", *_NOUL_FIELDS)
        roles = ("informational_fields", "high_stakes", "required", "required_review")
        if not inputs["jev"]:
            policy_keys += ("gpt_field_confidence.review_below", "gpt_field_confidence.measure", "gpt_field_confidence.info_only")
            roles += ("scored_fields",)
    keys = {"policy.json": policy_keys, f"types/{pack.key}.json": roles}
    if pack.extends:
        keys[f"types/_base/{pack.extends}.json"] = roles
    return keys


# The decision stage of the check registry (the S path's picks; the G path's verdicts and GPT confidence; the failed
# record checks), in the order they run, each with its pure rule. 180: the cross-document and after-save stages are the
# finance domain's.
checks.register(checks.Check("pick", "decision", apply_pick_policy, arms=("S",), rule=pick_rule))
checks.register(checks.Check("verdict", "decision", apply_verdict_policy, arms=("G",), rule=verdict_rule))
checks.register(checks.Check("gpt_confidence", "decision", apply_gpt_confidence_policy, arms=("G",), rule=gpt_confidence_rule))
checks.register(checks.Check("validation", "decision", apply_validation_policy, rule=validation_rule))

trace.register(trace.Point(
    ROUTE_POINT, owner=__name__, files=("policy.json", "types/*.json"), rule=route_rule,
    what="whether a document's extracted record is accepted or waits for a person, and the to-dos its decision raised: "
         "the picks' bands and presence (S), a value without a source, a verification flag or a missing required field "
         "(G), the GPT confidence without JEV, and the failed record checks",
    not_for="the extraction itself (the AI's answers are inputs), the to-dos raised before the decision (text, OCR, a "
            "failed question) or the cross-document checks (their to-dos are inputs)"))


# --------------------------------------------------------------------------------------
# M3: the email intent's band (224: its routes and signals are the email domain's, `jav/domains/email/email_rules.py`)
# --------------------------------------------------------------------------------------

def intent_human_max_conf() -> float:
    """M3: below it the manual queue, whatever the label (`email.intent`)."""
    return float(band("email.intent")["choice_human_max_conf"])
