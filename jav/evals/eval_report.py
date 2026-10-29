"""Shared eval module (framework layer): a uniform list of judgments from the flows' raw runs (`runs/*.jsonl`), and a
report built from it.

Flow-independent: the input is the four golden formats (invoice S / G, doc_detect, email_intent), the verifier and
injection probes, and the determinism files; the file-name pattern tells which flow. A **judgment** (`Judgment`) = one
JEV question for one case: Choice (label, confidence, top prob, second option) or Noul (P(yes)); where the truth is
known, also `expected` + `correct`. Every number is computed without calls, for $0; the bands come from the `bands`
sets of `configs/policy.json` (`jav/ai/policy.py`).

Sections: per-question accuracy and band distribution (with per-band accuracy), calibration curve (per bin P vs. hit
rate, ECE) by top prob and by confidence, top prob vs. confidence gap, policy-band re-evaluation (how many cases would
change band with the `uncertain_review` switch), determinism (per-question spread, flips).

Wiring in a new flow: an extractor `_from_<flow>(row) -> list[Judgment]` + the file-name pattern in `FLOW_PATTERNS`.

160-D (measurements without JEV): the GPT measurements (`*_gpt.jsonl`, `*_G_nojev.jsonl` and their determinism files)
are flows of their own, named `<flow>_gpt`. Their judgments use the GPT call sites (`.gpt`), so the bands are the ones
the flows apply without JEV. A GPT field's confidence is a judgment of the `field` kind: the probability that the
extracted value is the document's, its truth the field's score, its band `auto` at or above the policy's
`gpt_field_confidence.review_below` and a to-do below it. The silent errors section counts the wrong answers the
recorded run left without a to-do (`Judgment.flagged`), for every flow whose rows record their to-dos.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal

from jav.ai import policy
from jav.core import values
from jav.core.config import RUNS_DIR

LEGACY_DOC_TYPE = "invoice_hu"
"""202: the type of the first reference flow, for old data only. Rows, raw runs and file names saved before the type was
recorded name no type, and all of them were Hungarian invoices. Never a processing default: the shared code always
takes the type explicitly. 229 (plan structure stage 1, MD2): the measurement's, which alone reads such rows (until
then the type pack registry's, `jav/ai/typepack.py`)."""

# score: conf / top_prob read as for a Choice, the label is the level; field (160-D): a GPT field's confidence
Kind = Literal["choice", "noul", "score", "field"]

# file-name pattern -> flow name (the determinism files belong to the same flow, several rows per case)
# 160-D: the GPT patterns come first, since the JEV detection determinism pattern would take their files too
FLOW_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"_detect_golden_gpt(_keys)?\.jsonl$|_detect_determinism_gpt\.jsonl$", "doc_detect_gpt"),
    (r"_email_golden_gpt\.jsonl$|_email_determinism_gpt\.jsonl$", "email_intent_gpt"),
    (r"_email_injection_probe_gpt\.jsonl$", "email_injection_probe_gpt"),
    (r"_(golden|synthetic)_G_nojev\.jsonl$|_determinism_G_n\d+_nojev\.jsonl$", "invoice_G_gpt"),
    (r"_golden_S\.jsonl$|_determinism_S_n\d+\.jsonl$", "invoice_S"),
    (r"_golden_G\.jsonl$|_determinism_G_n\d+\.jsonl$", "invoice_G"),
    (r"_detect_golden\.jsonl$|_detect_determinism.*\.jsonl$", "doc_detect"),
    (r"_email_golden\.jsonl$|_email_determinism.*\.jsonl$", "email_intent"),
    (r"_verifier_probe\.jsonl$", "invoice_verify_probe"),
    (r"_email_injection_probe\.jsonl$", "email_injection_probe"),
)
DEFAULT_GLOBS: tuple[str, ...] = ("*_golden_S.jsonl", "*_golden_G.jsonl", "*_detect_golden.jsonl", "*_email_golden.jsonl",
                                  "*_determinism_S_n*.jsonl", "*_determinism_G_n*.jsonl", "*_detect_determinism.jsonl", "*_email_determinism.jsonl",
                                  "*_verifier_probe.jsonl", "*_email_injection_probe.jsonl",
                                  "*_detect_golden_gpt.jsonl", "*_email_golden_gpt.jsonl", "*_golden_G_nojev.jsonl",
                                  "*_detect_determinism_gpt.jsonl", "*_email_determinism_gpt.jsonl",
                                  "*_determinism_G_n*_nojev.jsonl", "*_email_injection_probe_gpt.jsonl")
CAL_BIN_EDGES: tuple[float, ...] = (0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0)
# 160-D: GPT confidences crowd near 1 and the field threshold is 0.98, so the GPT flows get finer bins there
GPT_CAL_BIN_EDGES: tuple[float, ...] = (0.0, 0.5, 0.8, 0.9, 0.95, 0.98, 0.99, 1.0)


@dataclass
class Judgment:
    flow: str
    case_id: str
    question: str  # field (S), flag name (G), question ID (detect / email)
    kind: Kind
    callsite: str  # policy-band call site (configs/policy.json band_for)
    label: str | None
    expected: str | None
    correct: bool | None
    confidence: float | None  # Choice confidence (concentration)
    top_prob: float | None  # probability of the chosen option
    second_prob: float | None  # probability of the second option (None if there is none)
    p: float | None  # Noul P(yes)
    route_recorded: str | None  # the route recorded in the run (route / next_flow), if any
    run_no: int = 1
    field: str | None = None  # G path: which field the flag refers to
    parent: str | None = None  # registry v2: family of the most probable option (from the run row)
    parent_prob: float | None = None  # combined probability of the family
    parent_correct: bool | None = None  # family of the expected label == parent (where the truth is known)
    flagged: bool | None = None  # 160-D: the recorded run left a to-do on it (None: the row does not record to-dos)


# --- file -> judgments ---------------------------------------------------------------------------


def flow_of(path: Path | str) -> str | None:
    name = Path(path).name
    for pattern, flow in FLOW_PATTERNS:
        if re.search(pattern, name):
            return flow
    return None


def is_determinism(path: Path | str) -> bool:
    return "determinism" in Path(path).name


def load_rows(path: Path | str) -> list[dict[str, Any]]:
    return values.json_lines(path)


def _budget_skipped(row: dict[str, Any]) -> bool:
    reasons = row.get("review_reasons") or ()
    return (str(row.get("error") or "").startswith("BudgetExceeded")
            or any(r.endswith(":BudgetExceeded") or r == "jev_unavailable:budget_exceeded" for r in reasons))


def budget_skips(rows: list[dict[str, Any]]) -> list[str]:
    """The cases a measurement budget left without a result (123): a provider call whose worst-case reservation did
    not fit. A blocked Azure escalation is not one: measurements give Azure no budget, and the document is read."""
    return [str(r.get("case_id")) for r in rows if _budget_skipped(r)]


def report_budget_skips(rows: list[dict[str, Any]]) -> int:
    """Print a warning for the cases the budget skipped and return their number; nothing when there are none."""
    skipped = budget_skips(rows)
    if skipped:
        print(f"\n**Skipped for the budget: {len(skipped)} of {len(rows)} cases** ({', '.join(skipped)}). They have no "
              "result, so the figures above are not comparable. A call reserves its worst case before it starts; "
              "rerun these cases with enough budget left (saved answers are reused).")
    return len(skipped)


def _top2(probs: dict[str, float] | None) -> tuple[float | None, float | None]:
    if not probs:
        return None, None
    vals = sorted((float(v) for v in probs.values()), reverse=True)
    return vals[0], (vals[1] if len(vals) > 1 else None)


def _from_invoice_S(row: dict[str, Any]) -> list[Judgment]:
    out = []
    scores = row.get("scores") or {}
    expected_present = row.get("expected_present") or {}
    flow = row.get("flow_label") or "invoice_S"  # a separate flow per type pack (invoice_S = Hungarian, invoice_foreign_S = foreign invoice)
    high_stakes = policy.high_stakes_for(row.get("doc_type") or LEGACY_DOC_TYPE)  # a row before the type was recorded
    for field, pick in (row.get("picks") or {}).items():
        top, second = _top2(pick.get("top3"))
        if pick.get("confidence") is None:  # 069 (Á11): no candidates means no Choice judgment, only (possibly) a presence judgment
            out.extend(_presence_judgment(row, flow, field, pick, expected_present))
            continue
        out.append(Judgment(
            flow=flow, case_id=row["case_id"], question=field, kind="choice",
            callsite="invoice.pick.high_stakes" if field in high_stakes else "invoice.pick",
            label=pick.get("label"), expected=None, correct=scores.get(field), confidence=float(pick["confidence"]),
            top_prob=top, second_prob=second, p=None, route_recorded=row.get("route"), run_no=int(row.get("run_no", 1)),
            field=field, flagged=_field_flagged(row, field),
        ))
        out.extend(_presence_judgment(row, flow, field, pick, expected_present))
    return out


def _presence_judgment(row: dict[str, Any], flow: str, field: str, pick: dict[str, Any],
                       expected_present: dict[str, Any]) -> list[Judgment]:
    """Presence Noul (select.json v1.1.0): truth = the golden expected value is not None."""
    p = pick.get("present_p")
    if p is None:
        return []
    exp = expected_present.get(field)
    expected = None if exp is None else ("yes" if exp else "no")
    label = "yes" if p >= 0.5 else "no"
    return [Judgment(
        flow=flow, case_id=row["case_id"], question=f"{field}.present", kind="noul", callsite="invoice.pick.presence",
        label=label, expected=expected, correct=None if expected is None else label == expected, confidence=None, top_prob=None,
        second_prob=None, p=float(p), route_recorded=row.get("route"), run_no=int(row.get("run_no", 1)), field=field,
    )]


def _from_invoice_G(row: dict[str, Any]) -> list[Judgment]:
    out = []
    v = row.get("verdicts")
    if not v:
        return out
    scores = row.get("scores") or {}
    flow = row.get("flow_label") or "invoice_G"

    def noul(question: str, p: float, field: str | None) -> Judgment:
        # truth: for a scored field the flag must fire if the field is wrong; the label is p >= 0.5
        expected = None if field is None or field not in scores or scores[field] is None else ("no" if scores[field] else "yes")
        label = "yes" if p >= 0.5 else "no"
        return Judgment(flow=flow, case_id=row["case_id"], question=question, kind="noul", callsite="invoice.verify",
                        label=label, expected=expected, correct=None if expected is None else label == expected,
                        confidence=None, top_prob=None, second_prob=None, p=float(p), route_recorded=row.get("route"),
                        run_no=int(row.get("run_no", 1)), field=field)

    for field, flags in (v.get("flags") or {}).items():
        for flag, p in flags.items():
            out.append(noul(flag, p, field))
    for flag, p in (v.get("doc_flags") or {}).items():
        out.append(noul(flag, p, None))
    return out


def _from_invoice_G_gpt(row: dict[str, Any]) -> list[Judgment]:
    """160-D: the G path without JEV. Each field with a measured GPT confidence is a `field` judgment; its truth is the
    field's score (None when the golden set does not score it). A field without a measured confidence has no judgment:
    the flow makes it a to-do of its own (`gpt:confidence_unavailable`), and a budget-skipped case has none."""
    out = []
    scores = row.get("scores") or {}
    flow = (row.get("flow_label") or "invoice_G") + "_gpt"
    # 164: a field outside the pack's to-do fields (an address, `gpt_field_confidence.info_only`) only shows its value
    to_do = set(policy.gpt_review_fields(row["doc_type"])) if row.get("doc_type") else None
    for field, conf in (row.get("field_confidence") or {}).items():
        if conf is None:
            continue
        callsite = "invoice.gpt_field" if to_do is None or field in to_do else "invoice.gpt_field.info"
        out.append(Judgment(
            flow=flow, case_id=row["case_id"], question=field, kind="field", callsite=callsite,
            label=None, expected=None, correct=scores.get(field), confidence=float(conf), top_prob=float(conf),
            second_prob=None, p=None, route_recorded=row.get("route"), run_no=int(row.get("run_no", 1)), field=field,
            flagged=_field_flagged(row, field),
        ))
    return out


def _field_flagged(row: dict[str, Any], field: str) -> bool | None:
    """Whether the recorded run left a to-do on the field (`policy.reason_field`); None when the row has no to-dos."""
    if "review_reasons" not in row:
        return None
    return any(policy.reason_field(r, {field}) == field for r in row["review_reasons"] or ())


def _item_flagged(row: dict[str, Any]) -> bool | None:
    """Whether the recorded run left any to-do on the item (a type or an intent is one answer per item)."""
    return bool(row["review_reasons"]) if "review_reasons" in row else None


def _band_flag(j: Judgment, row: dict[str, Any], *, unknown: bool = False) -> Judgment:
    """A type's or an intent's own low-confidence to-do is not among the row's reasons: the flow adds it at its end,
    from the band (`policy.choice_needs_review`), for an unmeasured confidence and for an unknown type. So a judgment
    in the to-do band counts as flagged too."""
    if j.flagged is not None:
        j.flagged = (j.flagged or unknown or j.confidence is None
                     or policy.choice_needs_review(j.confidence, row.get("top3"), j.callsite))
    return j


def _gpt(callsite: str, gpt: bool) -> str:
    return callsite + ".gpt" if gpt else callsite


def _measured(row: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    """The confidence, the top and the second probability of a Choice row; 160-D: a GPT answer without
    log-probabilities (`measured` false) has none, so it falls into the to-do band and out of the calibration."""
    if row.get("measured") is False:
        return None, None, None
    top, second = _top2(row.get("top3"))
    return float(row["confidence"]), top, second


def _parent_fields(row: dict[str, Any], parent_of: dict[str, str]) -> dict[str, Any]:
    parent, prob = row.get("parent"), row.get("parent_prob")
    exp = row.get("expected")
    correct = None if parent is None or exp is None or exp not in parent_of else parent_of[exp] == parent
    return {"parent": parent, "parent_prob": prob, "parent_correct": correct}


def _from_detect(row: dict[str, Any], *, gpt: bool = False) -> list[Judgment]:
    from jav.ai.doc_types import PARENT_OF

    if row.get("got") is None:
        return []
    flow = "doc_detect_gpt" if gpt else "doc_detect"
    confidence, top, second = _measured(row)
    out = [Judgment(flow=flow, case_id=row["case_id"], question="doc_type", kind="choice", callsite=_gpt("detect.doc_type", gpt),
                    label=row["got"], expected=row.get("expected"), correct=None if row.get("expected") is None else row["got"] == row["expected"],
                    confidence=confidence, top_prob=top, second_prob=second, p=None, route_recorded=row.get("status"),
                    run_no=int(row.get("run_no", 1)), flagged=_item_flagged(row), **_parent_fields(row, PARENT_OF))]
    _band_flag(out[0], row, unknown=row["got"] == "unknown")
    if row.get("issuer_hu") is not None:
        out.append(Judgment(flow=flow, case_id=row["case_id"], question="issuer_is_hungarian", kind="noul",
                            callsite=_gpt("detect.issuer_is_hungarian", gpt),
                            label="yes" if row["issuer_hu"] >= 0.5 else "no", expected=None, correct=None, confidence=None, top_prob=None,
                            second_prob=None, p=float(row["issuer_hu"]), route_recorded=None, run_no=int(row.get("run_no", 1))))
    return out


def _from_email(row: dict[str, Any], *, gpt: bool = False) -> list[Judgment]:
    from jav.domains.email.intents import PARENT_OF

    if row.get("got") is None:
        return []
    flow = "email_intent_gpt" if gpt else "email_intent"
    confidence, top, second = _measured(row)
    out = [Judgment(flow=flow, case_id=row["case_id"], question="intent", kind="choice", callsite=_gpt("email.intent", gpt),
                    label=row["got"], expected=row.get("expected"), correct=None if row.get("expected") is None else row["got"] == row["expected"],
                    confidence=confidence, top_prob=top, second_prob=second, p=None, route_recorded=row.get("next_flow"),
                    run_no=int(row.get("run_no", 1)), flagged=_item_flagged(row), **_parent_fields(row, PARENT_OF))]
    _band_flag(out[0], row)
    for key, p in (row.get("signals") or {}).items():
        out.append(Judgment(flow=flow, case_id=row["case_id"], question=key, kind="noul", callsite=_gpt("email.signal", gpt),
                            label="yes" if p >= 0.5 else "no", expected=None, correct=None, confidence=None, top_prob=None, second_prob=None,
                            p=float(p), route_recorded=None, run_no=int(row.get("run_no", 1)), flagged=_item_flagged(row)))
    for key, s in (row.get("scores") or {}).items():  # v1.1.0: Score signal (urgency) - label = level, conf + level probabilities
        top, second = _top2(s.get("probabilities"))
        out.append(Judgment(flow=flow, case_id=row["case_id"], question=key, kind="score", callsite=_gpt(f"email.{key}", gpt),
                            label=str(s.get("level")), expected=None, correct=None, confidence=float(s.get("confidence") or 0.0),
                            top_prob=top, second_prob=second, p=None, route_recorded=None, run_no=int(row.get("run_no", 1))))
    return out


def _from_verify_probe(row: dict[str, Any]) -> list[Judgment]:
    """Verifier probe: with known truth. For a faulty variant the truth of the expected flag is `yes`; for the perfect
    extract the truth of every flag of the fields covered by the golden set is `no` (there the probe's `p` is the
    highest such flag). The other flags have no truth."""
    out: list[Judgment] = []
    variant, target = row["variant"], row["target"]
    t_flag, _, t_field = target.partition(":")
    case_id = f"{row['case_id']}/{variant}"
    doc_type = row.get("doc_type", LEGACY_DOC_TYPE)
    flow = "invoice_verify_probe" if doc_type == LEGACY_DOC_TYPE else f"{doc_type}_verify_probe"  # the earlier flow name

    def noul(question: str, p: float, field: str | None, expected: str | None) -> Judgment:
        label = "yes" if p >= 0.5 else "no"
        return Judgment(flow=flow, case_id=case_id, question=question, kind="noul", callsite="invoice.verify",
                        label=label, expected=expected, correct=None if expected is None else label == expected,
                        confidence=None, top_prob=None, second_prob=None, p=float(p), route_recorded=None,
                        run_no=int(row.get("run_no", 1)), field=field)

    perfect_fields = set(row.get("perfect_fields") or [])
    for field, flags in (row.get("flags") or {}).items():
        for flag, p in flags.items():
            if variant == "perfect":
                expected = "no" if field in perfect_fields else None
            else:
                expected = "yes" if (flag == t_flag and field == t_field) else None
            out.append(noul(flag, p, field, expected))
    for flag, p in (row.get("doc_flags") or {}).items():
        if variant == "perfect":
            expected = "no" if flag == "parties_swapped" else None
        else:
            expected = "yes" if (flag == t_flag and not t_field) else None
        out.append(noul(flag, p, None, expected))
    return out


def _from_email_injection(row: dict[str, Any], *, gpt: bool = False) -> list[Judgment]:
    """Injected-instruction probe: like the email golden set, but the truth of the `prompt_injection` Noul is known
    (clean -> no, tampered -> yes), the case is `<case>/<variant>`; the truth of the intent is the golden expected
    intent (for the tampered variant too - a flip is an error)."""
    out = _from_email(row, gpt=gpt)
    variant = row.get("variant", "clean")
    for j in out:
        j.flow = "email_injection_probe_gpt" if gpt else "email_injection_probe"
        j.case_id = f"{row['case_id']}/{variant}"
        if j.kind == "noul" and j.question == "prompt_injection":
            j.expected = "no" if variant == "clean" else "yes"
            j.correct = j.label == j.expected
    return out


EXTRACTORS: dict[str, Callable[[dict[str, Any]], list[Judgment]]] = {
    "invoice_S": _from_invoice_S, "invoice_G": _from_invoice_G, "doc_detect": _from_detect, "email_intent": _from_email,
    "invoice_verify_probe": _from_verify_probe, "email_injection_probe": _from_email_injection,
    "doc_detect_gpt": lambda row: _from_detect(row, gpt=True), "email_intent_gpt": lambda row: _from_email(row, gpt=True),
    "email_injection_probe_gpt": lambda row: _from_email_injection(row, gpt=True), "invoice_G_gpt": _from_invoice_G_gpt,
}


def judgments_from_file(path: Path | str) -> list[Judgment]:
    flow = flow_of(path)
    if flow is None:
        raise ValueError(f"an unknown run file (no flow pattern): {path}")
    extract = EXTRACTORS[flow]
    out: list[Judgment] = []
    seen: dict[str, int] = defaultdict(int)  # determinism file without run_no (email): numbered per case
    for row in load_rows(path):
        js = extract(row)
        if js and "run_no" not in row:
            # by the judgment's case_id (the probe's variants are separate cases: `<case>/<variant>`), not by the raw
            # row
            key = js[0].case_id
            seen[key] += 1
            for j in js:
                j.run_no = seen[key]
        out.extend(js)
    if "_synthetic_" in Path(path).name:  # 160-D: the invented cases, apart from the golden set's flow
        for j in out:
            j.flow = f"{j.flow} (synthetic)"
    return out


# --- bands and summaries -------------------------------------------------------------------------


def band_of(j: Judgment) -> str:
    if j.kind == "noul":
        return policy.noul_band(j.p or 0.0, j.callsite)
    if j.kind == "field":  # 160-D: below the review threshold the flow leaves a to-do on the field (164: not on .info)
        if j.callsite.endswith(".info"):
            return "auto"
        return "auto" if j.confidence is not None and j.confidence >= policy.GPT_FIELD_CONFIDENCE["review_below"] else "human"
    probs = None
    if j.top_prob is not None:
        probs = {"_top": j.top_prob, "_second": j.second_prob} if j.second_prob is not None else {"_top": j.top_prob}
    return policy.choice_band(j.confidence or 0.0, probs, j.callsite)


def _acc(js: list[Judgment]) -> float | None:
    scored = [j for j in js if j.correct is not None]
    return round(sum(j.correct for j in scored) / len(scored), 4) if scored else None


def _first_runs(js: list[Judgment]) -> list[Judgment]:
    return [j for j in js if j.run_no == 1]


def per_question(js: list[Judgment]) -> list[dict[str, Any]]:
    """Flow × question: n, accuracy, conf/p mean and spread, band distribution, per-band accuracy (1st run only)."""
    groups: dict[tuple[str, str, str], list[Judgment]] = defaultdict(list)
    for j in _first_runs(js):
        groups[(j.flow, j.question, j.kind)].append(j)
    rows = []
    for (flow, q, kind), items in sorted(groups.items()):
        vals = [j.p if kind == "noul" else j.confidence for j in items]
        vals = [v for v in vals if v is not None]
        bands: dict[str, int] = defaultdict(int)
        by_band: dict[str, list[Judgment]] = defaultdict(list)
        for j in items:
            b = band_of(j)
            bands[b] += 1
            by_band[b].append(j)
        scored = [j for j in items if j.correct is not None]
        rows.append({
            "flow": flow, "question": q, "kind": kind, "n": len(items), "n_scored": len(scored),
            "correct": sum(j.correct for j in scored), "accuracy": _acc(items),
            "mean": round(statistics.mean(vals), 4) if vals else None, "std": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0,
            "bands": dict(sorted(bands.items())), "acc_by_band": {b: _acc(bj) for b, bj in sorted(by_band.items()) if _acc(bj) is not None},
        })
    return rows


def calibration(js: list[Judgment], *, key: str = "top_prob", edges: tuple[float, ...] = CAL_BIN_EDGES) -> dict[str, Any]:
    """Choice (and 160-D: GPT field) judgments with truth: mean P vs. hit rate per bin, ECE (n-weighted |acc - P|)."""
    items = [j for j in _first_runs(js) if j.kind in ("choice", "field") and j.correct is not None and getattr(j, key) is not None]
    bins = []
    n_total = len(items)
    ece = 0.0
    for lo, hi in zip(edges, edges[1:]):
        last = hi == edges[-1]
        inb = [j for j in items if (lo <= getattr(j, key) < hi) or (last and getattr(j, key) == hi)]
        if not inb:
            bins.append({"lo": lo, "hi": hi, "n": 0, "mean_p": None, "hit_rate": None})
            continue
        mean_p = statistics.mean(getattr(j, key) for j in inb)
        hit = sum(j.correct for j in inb) / len(inb)
        ece += len(inb) / n_total * abs(hit - mean_p)
        bins.append({"lo": lo, "hi": hi, "n": len(inb), "mean_p": round(mean_p, 4), "hit_rate": round(hit, 4)})
    return {"key": key, "n": n_total, "ece": round(ece, 4), "bins": bins}


def top_prob_vs_confidence(js: list[Judgment]) -> list[dict[str, Any]]:
    """Per flow: the mean / largest gap between confidence and top prob, and for how many judgments top prob would give
    a different band."""
    groups: dict[str, list[Judgment]] = defaultdict(list)
    for j in _first_runs(js):
        if j.kind == "choice" and j.top_prob is not None and j.confidence is not None:
            groups[j.flow].append(j)
    rows = []
    for flow, items in sorted(groups.items()):
        diffs = [abs(j.confidence - j.top_prob) for j in items]
        differs = 0
        for j in items:
            thr = policy.band(j.callsite)["choice_human_max_conf"]
            if (j.confidence < thr) != (j.top_prob < thr):
                differs += 1
        rows.append({"flow": flow, "n": len(items), "mean_abs_diff": round(statistics.mean(diffs), 4), "max_abs_diff": round(max(diffs), 4),
                     "band_differs": differs})
    return rows


def policy_reeval(js: list[Judgment]) -> list[dict[str, Any]]:
    """Per case: whether there is a `human` judgment (review already now), and whether there is ONLY `uncertain` (it
    would be reviewed with `uncertain_review: true`).

    The accuracy of the `uncertain_only` cases tells whether the switch is worth turning on: if they are inaccurate, the
    band is a good signal; if they are accurate, the switch would only add needless manual work.
    """
    by_flow_case: dict[str, dict[str, list[Judgment]]] = defaultdict(lambda: defaultdict(list))
    for j in _first_runs(js):
        by_flow_case[j.flow][j.case_id].append(j)
    rows = []
    for flow, cases in sorted(by_flow_case.items()):
        n_human = n_unc = 0
        unc_scored: list[bool] = []
        noul_unc = 0
        for _, items in cases.items():
            bands = {band_of(j) for j in items if j.kind in ("choice", "field")}
            noul_unc += sum(1 for j in items if j.kind == "noul" and band_of(j) == "uncertain")
            if "human" in bands:
                n_human += 1
            elif "uncertain" in bands:
                n_unc += 1
                unc_scored += [bool(j.correct) for j in items if j.kind == "choice" and band_of(j) == "uncertain" and j.correct is not None]
        rows.append({
            "flow": flow, "cases": len(cases), "cases_human": n_human, "cases_uncertain_only": n_unc,
            "uncertain_only_accuracy": round(sum(unc_scored) / len(unc_scored), 4) if unc_scored else None,
            "noul_uncertain": noul_unc,
        })
    return rows


def parent_fallback_summary(js: list[Judgment]) -> list[dict[str, Any]]:
    """Parent label (registry v2): for how many of the non-auto-band Choice judgments the family is usable
    (`policy.parent_fallback`), and for how many it matches the family of the expected label."""
    groups: dict[str, list[Judgment]] = defaultdict(list)
    for j in _first_runs(js):
        if j.kind == "choice" and j.parent is not None:
            groups[j.flow].append(j)
    rows = []
    for flow, items in sorted(groups.items()):
        non_auto = [j for j in items if band_of(j) != "auto"]
        usable = [j for j in non_auto if policy.parent_fallback(j.confidence or 0.0, j.parent, j.parent_prob or 0.0, j.callsite,
                                                                {"_top": j.top_prob, "_second": j.second_prob} if j.second_prob is not None else None)]
        rows.append({
            "flow": flow, "n": len(items), "human": sum(1 for j in non_auto if band_of(j) == "human"), "uncertain": sum(1 for j in non_auto if band_of(j) == "uncertain"),
            "parent_usable": len(usable), "parent_correct": sum(1 for j in usable if j.parent_correct),
            "parent_correct_all": sum(1 for j in items if j.parent_correct), "parent_scored": sum(1 for j in items if j.parent_correct is not None),
        })
    return rows


def silent_errors(js: list[Judgment], *, examples: int = 10) -> list[dict[str, Any]]:
    """160-D: per flow, the judgments with a known truth (1st run) whose row records its to-dos: how many were wrong,
    how many of those the recorded run flagged with a to-do, and how many passed without one (silent errors), with the
    first silent cases (`<case> <question>`). Without JEV this is the number the field threshold has to keep low."""
    groups: dict[str, list[Judgment]] = defaultdict(list)
    for j in _first_runs(js):
        if j.correct is not None and j.flagged is not None:
            groups[j.flow].append(j)
    rows = []
    for flow, items in sorted(groups.items()):
        wrong = [j for j in items if not j.correct]
        silent = [j for j in wrong if not j.flagged]
        rows.append({"flow": flow, "scored": len(items), "wrong": len(wrong), "flagged": len(wrong) - len(silent),
                     "silent": len(silent), "silent_cases": [f"{j.case_id} {j.question}" for j in silent[:examples]]})
    return rows


def determinism_summary(js: list[Judgment]) -> list[dict[str, Any]]:
    """Several runs per case: per question the mean and maximum spread of conf / p, and the number of label flips."""
    groups: dict[tuple[str, str], dict[tuple[str, str | None], list[Judgment]]] = defaultdict(lambda: defaultdict(list))
    for j in js:
        groups[(j.flow, j.question)][(j.case_id, j.field)].append(j)  # G path: case × field is the unit of a run series
    rows = []
    for (flow, q), cases in sorted(groups.items()):
        multi = {c: items for c, items in cases.items() if len(items) > 1}
        if not multi:
            continue
        stds, flips = [], 0
        for items in multi.values():
            vals = [(j.p if j.kind == "noul" else j.confidence) for j in items]
            vals = [v for v in vals if v is not None]
            if len(vals) > 1:
                stds.append(statistics.pstdev(vals))
            if len({j.label for j in items}) > 1:
                flips += 1
        rows.append({"flow": flow, "question": q, "cases": len(multi), "runs": max(len(i) for i in multi.values()),
                     "std_mean": round(statistics.mean(stds), 4) if stds else 0.0, "std_max": round(max(stds), 4) if stds else 0.0, "flips": flips})
    return rows


# --- report --------------------------------------------------------------------------------------


def default_inputs() -> list[Path]:
    """The latest runs/*.jsonl per pattern."""
    out = []
    for g in DEFAULT_GLOBS:
        files = sorted(RUNS_DIR.glob(g))
        if files:
            out.append(files[-1])
    return out


def _f(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def report_markdown(paths: list[Path | str]) -> str:
    paths = [Path(p) for p in paths]
    golden = [p for p in paths if not is_determinism(p)]
    det = [p for p in paths if is_determinism(p)]
    js = [j for p in golden for j in judgments_from_file(p)]
    jd = [j for p in det for j in judgments_from_file(p)]
    L = [f"# Eval report ({datetime.now():%Y-%m-%d %H:%M}) — without calls, from the raw runs", "",
         f"Bands: `configs/policy.json` v{policy.cfg.version('policy')} (`bands` / `band_for`); a Choice band = a confidence threshold and a gap to the second option, a Noul band is two-sided.", "",
         "## Sources", ""]
    for p in paths:
        n = len(load_rows(p))
        L.append(f"- `{p.name}` → {flow_of(p)}{' (determinism)' if is_determinism(p) else ''}, {n} row(s)")
    L += ["", "## By question (run 1)", "", "| flow | question | kind | n | as expected | mean | spread | bands | as expected by band |", "|---|---|---|---|---|---|---|---|---|"]
    for r in per_question(js):
        acc = f"{r['correct']}/{r['n_scored']} = {r['accuracy']:.0%}" if r["n_scored"] else "-"
        bands = ", ".join(f"{b} {n}" for b, n in r["bands"].items())
        accb = ", ".join(f"{b} {a:.0%}" for b, a in r["acc_by_band"].items()) or "-"
        L.append(f"| {r['flow']} | {r['question']} | {r['kind']} | {r['n']} | {acc} | {_f(r['mean'])} | {_f(r['std'])} | {bands} | {accb} |")
    L += ["", "## Calibration (Choice judgements with a known truth)", "",
          "GPT flows (`_gpt`, 160-D): their own call sites (`.gpt`) and finer bins near 1; a GPT field's band is `auto` "
          f"at or above {policy.GPT_FIELD_CONFIDENCE['review_below']} (`gpt_field_confidence.review_below`), a to-do below.", ""]
    flows = sorted({j.flow for j in js if j.kind in ("choice", "field") and j.correct is not None})
    for flow in flows:
        fj = [j for j in js if j.flow == flow]
        fields_only = all(j.kind == "field" for j in fj if j.kind in ("choice", "field"))
        edges = GPT_CAL_BIN_EDGES if "_gpt" in flow else CAL_BIN_EDGES
        for key in (("confidence",) if fields_only else ("top_prob", "confidence")):
            cal = calibration(fj, key=key, edges=edges)
            if cal["n"] == 0:
                continue
            L += [f"**{flow} · {key}** — n = {cal['n']}, ECE = {cal['ece']:.3f}", "", "| band | n | mean P | hits |", "|---|---|---|---|"]
            for b in cal["bins"]:
                if b["n"]:
                    L.append(f"| {b['lo']:.2f}–{b['hi']:.2f} | {b['n']} | {b['mean_p']:.3f} | {b['hit_rate']:.0%} |")
            L.append("")
    L += ["## top-prob vs. confidence", "", "| flow | n | mean difference | max difference | another band by top-prob |", "|---|---|---|---|---|"]
    for r in top_prob_vs_confidence(js):
        L.append(f"| {r['flow']} | {r['n']} | {r['mean_abs_diff']:.3f} | {r['max_abs_diff']:.3f} | {r['band_differs']} |")
    L += ["", "## The policy bands evaluated again (without calls)", "",
          "`cases_human`: in the manual queue already; `cases_uncertain_only`: uncertain ONLY for the gap to the second option — these "
          "would go to the manual queue with `uncertain_review: true`. `as expected` is of those judgements: if it is low, the band is a good signal; if high, the switch would only add manual work. "
          "`noul_uncertain`: Noul signals in the middle band.", "",
          "| flow | cases | human | uncertain only | uncertain, as expected | Noul uncertain |", "|---|---|---|---|---|---|"]
    for r in policy_reeval(js):
        acc = f"{r['uncertain_only_accuracy']:.0%}" if r["uncertain_only_accuracy"] is not None else "-"
        L.append(f"| {r['flow']} | {r['cases']} | {r['cases_human']} | {r['cases_uncertain_only']} | {acc} | {r['noul_uncertain']} |")
    L += ["", "## Silent errors (wrong, no to-do in the recorded run)", ""]
    srows = silent_errors(js)
    if srows:
        L += ["Judgments with a known truth whose run rows record their to-dos. `flagged`: the run left a to-do on the "
              "wrong answer (on the field, or on the item for a type or an intent, its own low-confidence band "
              "included); `silent`: it passed without one. A field outside the policy's to-do fields can be silent "
              "below the threshold too: its colour still shows the lower confidence.", "",
              "| flow | scored | wrong | flagged | silent | first silent cases |", "|---|---|---|---|---|---|"]
        for r in srows:
            L.append(f"| {r['flow']} | {r['scored']} | {r['wrong']} | {r['flagged']} | {r['silent']} | {', '.join(r['silent_cases']) or '-'} |")
    else:
        L.append("(no input row records its to-dos)")
    L += ["", "## Parent label (registry v2, `parent_min_prob`)", ""]
    prows = parent_fallback_summary(js)
    if prows:
        L += ["`usable`: a judgement outside the auto band whose family's summed probability reaches `parent_min_prob`; `right`: the expected label's family matches.", "",
              "| flow | n | human | uncertain | parent usable | of them right | parent right in all |", "|---|---|---|---|---|---|---|"]
        for r in prows:
            L.append(f"| {r['flow']} | {r['n']} | {r['human']} | {r['uncertain']} | {r['parent_usable']} | {r['parent_correct']} | {r['parent_correct_all']}/{r['parent_scored']} |")
    else:
        L.append("(the run rows have no `parent` field - a registry v1 run)")
    L += ["", "## Determinism (repeated runs)", ""]
    rows = determinism_summary(jd)
    if rows:
        L += ["| flow | question | cases | runs | mean spread | max spread | flips |", "|---|---|---|---|---|---|---|"]
        for r in rows:
            L.append(f"| {r['flow']} | {r['question']} | {r['cases']} | {r['runs']} | {r['std_mean']:.4f} | {r['std_max']:.4f} | {r['flips']} |")
    else:
        L.append("(no determinism file among the inputs)")
    L.append("")
    return "\n".join(L)


def write_report(paths: list[Path | str] | None = None, out: Path | None = None) -> tuple[str, Path]:
    paths = list(paths) if paths else default_inputs()
    md = report_markdown(paths)
    out = out or RUNS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_eval_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    return md, out
