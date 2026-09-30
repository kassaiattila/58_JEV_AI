"""Golden eval: loading cases from the legacy manifest, comparators, candidate recall, golden and determinism runs.

Scoring contract (legacy manifest `_compare_contract`): money by Decimal equality; names case-insensitive,
whitespace-collapsed, tolerant of trailing punctuation; tax number without spaces (hyphens stay); date ISO; null==null
is a hit. `payment_iban` (and, for foreign invoices, the addresses) is NOT scored in the legacy contract - we report it
separately as an informational column.

Type-independent: the type pack under measurement (`jav/typepack.py`) supplies the field list, the kinds (comparator),
the scored / informational fields and the golden `type_key`; the raw run rows carry the `doc_type` and the
`flow_label` (`invoice_S` for the Hungarian, `invoice_foreign_S` for the foreign invoice), which the eval report and
the admin read.
"""

from __future__ import annotations

import json
import re
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from jav.config import GOLDEN_EXPECTED_DIR, GOLDEN_MANIFEST, OLD_PROJECT_ROOT, RUNS_DIR
from jav.models import Candidate, FlowState, money_label, normalize_date, normalize_tax_id
from jav.typepack import CANDIDATE_KIND_OF, DEFAULT_KEY, TypePack, get as get_pack

_HU = get_pack(DEFAULT_KEY)
INFORMATIONAL_FIELDS = _HU.informational_fields
STRICT_SCORED = _HU.strict_scored
FIELD_KIND = {f: CANDIDATE_KIND_OF[k] for f, k in _HU.fields.items() if k in CANDIDATE_KIND_OF}  # legacy name (field -> candidate kind, hu)


@dataclass
class GoldenCase:
    case_id: str
    pdf: Path
    expected: dict[str, Any]  # datapoints
    expected_valid: bool
    type_key: str = DEFAULT_KEY


def load_cases(type_key: str = DEFAULT_KEY) -> list[GoldenCase]:
    """The legacy manifest's cases for one type (by the pack's `golden_type_key`)."""
    pack = get_pack(type_key)
    manifest = json.loads(GOLDEN_MANIFEST.read_text(encoding="utf-8"))
    cases: list[GoldenCase] = []
    for c in manifest.get("cases", []):
        if c.get("type_key") != pack.golden_type_key:
            continue
        name = c["id"].split("/", 1)[1]
        pdf = OLD_PROJECT_ROOT / c["input_ref"].lstrip("/")
        expected_path = GOLDEN_EXPECTED_DIR / c.get("expected_ref", f"expected/{name}.json")
        exp = json.loads(expected_path.read_text(encoding="utf-8"))
        cases.append(GoldenCase(case_id=name, pdf=pdf, expected=exp["datapoints"], expected_valid=exp.get("expected_valid", True), type_key=type_key))
    return cases


def _flow_label(type_key: str, arm: str) -> str:
    return f"invoice_{arm}" if type_key == DEFAULT_KEY else f"{type_key}_{arm}"


def _run_name(type_key: str, base: str) -> str:
    """File-name pattern: the Hungarian invoice keeps the earlier `golden_S` / `determinism_S_n5`, other types use
    `<type>_golden_S` (the eval report's file-name pattern matches on the suffix; the rows' `flow_label` says the flow).
    With a forced OCR engine (`JAV_OCR_ENGINE`) the engine name is prefixed to the file name
    (`azure_di_<type>_golden_S`) so that measurements do not get mixed up."""
    import os

    from jav.ocr import ENGINE_ENV

    name = base if type_key == DEFAULT_KEY else f"{type_key}_{base}"
    forced = os.environ.get(ENGINE_ENV)
    return f"{forced}_{name}" if forced else name


# --- comparators -----------------------------------------------------------------------

_TRAILING_PUNCT = re.compile(r"[\s.,;:]+$")


def _norm_name(v: Any) -> str:
    return _TRAILING_PUNCT.sub("", " ".join(str(v).split())).casefold()


def _norm_money(v: Any) -> str | None:
    try:
        return money_label(Decimal(str(v).replace(" ", "")))
    except (InvalidOperation, ValueError):
        return None


def _hu_bban(v: Any) -> str:
    """The same Hungarian bank account as IBAN / 24 digits / 16 digits: normalise to the 24-digit BBAN (16 digits + 8
    zeros)."""
    s = str(v).replace(" ", "").replace(" ", "").replace("-", "").upper()
    if s.startswith("HU"):
        return s[4:]  # the BBAN follows HU + 2 check digits
    digits = re.sub(r"\D", "", s)
    return digits + "0" * 8 if len(digits) == 16 else digits


def _norm_date(v: Any) -> str:
    d = normalize_date(str(v), intl=True)
    return d.isoformat() if d else str(v).strip()


def field_equal(field: str, got: Any, expected: Any, kind: str | None = None) -> bool:
    """Comparison by the field's KIND (the legacy contract); without `kind`, taken from the Hungarian invoice pack."""
    if got is None or expected is None:
        return got is None and expected is None
    kind = kind or _HU.kind(field)
    if kind in ("money", "number"):
        return _norm_money(got) == _norm_money(expected)
    if kind == "tax_id":
        return normalize_tax_id(got) == normalize_tax_id(expected)
    if kind == "iban":
        return _hu_bban(got) == _hu_bban(expected)
    if kind == "date":
        return _norm_date(got) == _norm_date(expected)
    if kind in ("currency", "country"):
        return str(got).strip().upper() == str(expected).strip().upper()
    return _norm_name(got) == _norm_name(expected)


def field_in_candidates(field: str, expected: Any, cands: list[Candidate], kind: str | None = None) -> bool:
    return any(field_equal(field, c.label, expected, kind) for c in cands)


_ACCENT_FOLD = str.maketrans("áéíóöőúüűÁÉÍÓÖŐÚÜŰ", "aeiooouuuAEIOOOUUU")
_PUNCT_ALL = re.compile(r"[^\w\s]", re.UNICODE)


def _fold_ocr(v: Any) -> str:
    """OCR-tolerant form: accents stripped, lower case, no punctuation, whitespace collapsed
    ("SZÉCHENYI ÚT 101." == "szechenyi ut 101")."""
    return " ".join(_PUNCT_ALL.sub(" ", str(v).translate(_ACCENT_FOLD)).split()).casefold()


def field_equal_lenient(field: str, got: Any, expected: Any, kind: str | None = None) -> bool:
    """Strict equality OR - for text kinds (name, address, text) - OCR-tolerant equality (ignoring accents, case and
    punctuation). The second, informational score for OCR-text types: how much of the error is only OCR accent noise."""
    if field_equal(field, got, expected, kind):
        return True
    if got is None or expected is None:
        return False
    kind = kind or _HU.kind(field)
    return kind in ("name", "address", "text") and _fold_ocr(got) == _fold_ocr(expected)


# --- candidate recall (offline, no API) ------------------------------------------------


def candidate_recall(cases: list[GoldenCase] | None = None, verbose: bool = True, type_key: str = DEFAULT_KEY) -> dict[str, tuple[int, int]]:
    from jav.candidates import find_all, find_currencies
    from jav.pdf import read_document

    pack = get_pack(type_key)
    cases = cases or load_cases(type_key)
    hits: dict[str, int] = defaultdict(int)
    totals: dict[str, int] = defaultdict(int)
    misses: list[str] = []
    counts: dict[str, list[int]] = defaultdict(list)
    for case in cases:
        pdf = read_document(case.pdf)  # text layer, or OCR (from the cache)
        if pdf.text_source is None:
            misses.append(f"{case.case_id}: nincs szöveg (szövegréteg és OCR sem)")
            continue
        cands = find_all(pdf.layout, pack.candidate_profile, text_labels=pack.text_labels)
        currencies = find_currencies(pdf.layout, pack.candidate_profile)
        for kind, items in cands.items():
            counts[kind].append(len(items))
        for field in pack.scored_fields:
            expected = case.expected.get(field)
            if expected is None:
                continue
            kind = pack.kind(field)
            if kind == "country" or (kind == "text" and field not in pack.text_labels):
                continue  # closed Choice list (country, payment method, reading method), not from candidates - recall is undefined here
            totals[field] += 1
            if kind == "currency":
                ok = str(expected).upper() in currencies
            elif kind == "text":
                ok = field_in_candidates(field, expected, cands.get(f"text:{field}", []), kind)  # labelled text candidates
            else:
                ok = field_in_candidates(field, expected, cands.get(CANDIDATE_KIND_OF[kind], []), kind)
            if ok:
                hits[field] += 1
            else:
                misses.append(f"{case.case_id}: {field} = {expected!r} nincs a jelöltek közt")
    result = {f: (hits[f], totals[f]) for f in pack.scored_fields if totals[f]}
    if verbose:
        print(f"### Jelölt-recall - {type_key} ({len(cases)} eset, profil: {pack.candidate_profile})\n")
        print("| mező | recall | n |\n|---|---|---|")
        for f, (h, t) in result.items():
            tag = " (informatív)" if f in pack.informational_fields else ""
            print(f"| {f}{tag} | {h / t:.0%} | {h}/{t} |")
        all_h = sum(h for f, (h, t) in result.items() if f in pack.strict_scored)
        all_t = sum(t for f, (h, t) in result.items() if f in pack.strict_scored)
        print(f"\n**Összes pontozott:** {all_h}/{all_t} = {all_h / max(all_t, 1):.1%}")
        print("\nJelöltszám fajtánként (min/medián/max): " + ", ".join(
            f"{k} {min(v)}/{int(statistics.median(v))}/{max(v)}" for k, v in counts.items() if v))
        if misses:
            print("\nHiányok:")
            for m in misses:
                print("  - " + m)
    return result


# --- golden run and determinism --------------------------------------------------------


def _score_state(state: FlowState, expected: dict[str, Any], pack: TypePack) -> dict[str, bool | None]:
    """The legacy contract: a key MISSING from the golden set is not scored (None); an explicit null means the field
    must be empty (e.g. the legacy `real_ms` case has no supplier_country key)."""
    got = state.invoice.to_datapoints(pack.record_fields) if state.invoice else {}
    return {f: (field_equal(f, got.get(f), expected.get(f), pack.kind(f)) if state.invoice and f in expected else None) for f in pack.scored_fields}


def _score_state_lenient(state: FlowState, expected: dict[str, Any], pack: TypePack) -> dict[str, bool | None]:
    got = state.invoice.to_datapoints(pack.record_fields) if state.invoice else {}
    return {f: (field_equal_lenient(f, got.get(f), expected.get(f), pack.kind(f)) if state.invoice and f in expected else None) for f in pack.scored_fields}


def _state_row(case: GoldenCase, state: FlowState, run_no: int, seconds: float, pack: TypePack) -> dict[str, Any]:
    from jav.jev_select import record_conf

    picks = {
        f: {
            "label": p.label,
            "confidence": p.confidence,
            "n_options": p.n_options,
            "top3": dict(sorted(p.probabilities.items(), key=lambda kv: -kv[1])[:3]),
            "present_p": p.present_p,
            "line_no": p.line_no,
        }
        for f, p in state.picks.items()
    }
    verdicts = state.verdicts.model_dump() if state.verdicts else None
    return {
        "case_id": case.case_id,
        "doc_type": pack.key,
        "flow_label": _flow_label(pack.key, state.arm),
        "arm": state.arm,
        "run_no": run_no,
        "seconds": round(seconds, 2),
        "final_status": state.final_status,
        "route": state.route,
        "review_reasons": state.review_reasons,
        "datapoints": state.invoice.to_datapoints(pack.record_fields) if state.invoice else None,
        "scores": _score_state(state, case.expected, pack),
        "scores_lenient": _score_state_lenient(state, case.expected, pack),  # OCR-tolerant (accent-insensitive) second score
        "text_source": state.text_source,
        "ocr_conf": state.ocr_conf,
        "ocr_engine": state.ocr_engine,
        "ocr_escalated": state.ocr_escalated,
        "expected_present": {f: case.expected.get(f) is not None for f in pack.scored_fields if f in case.expected},  # ground truth for the presence Noul
        "record_conf": record_conf(state.picks) if state.arm == "S" else None,
        "picks": picks,
        "verdicts": verdicts,
        "jev_calls": [c.model_dump() for c in state.jev_calls],
        "validation": [v.model_dump() for v in state.validation],
    }


def _dump_rows(rows: list[dict[str, Any]], name: str) -> Path:
    RUNS_DIR.mkdir(exist_ok=True)
    path = RUNS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{name}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    return path


def golden(
    arm: str, run_one: Callable[..., FlowState], cases: list[GoldenCase] | None = None, tracker: bool = False, use_cache: bool = True,
    type_key: str = DEFAULT_KEY,
) -> list[dict[str, Any]]:
    pack = get_pack(type_key)
    cases = cases or load_cases(type_key)
    rows: list[dict[str, Any]] = []
    for case in cases:
        t0 = time.perf_counter()
        state = run_one(str(case.pdf), case.case_id, arm, run_no=1, tracker=tracker, use_cache=use_cache, doc_type=type_key)
        rows.append(_state_row(case, state, 1, time.perf_counter() - t0, pack))
        print(f"  {case.case_id:40} {state.final_status:12} {state.route or '-':6} {time.perf_counter() - t0:5.1f}s")
    path = _dump_rows(rows, _run_name(type_key, f"golden_{arm}"))
    print_golden_report(rows, arm, pack)
    print(f"\nNyers futások: {path}")
    return rows


def print_golden_report(rows: list[dict[str, Any]], arm: str, pack: TypePack | None = None) -> None:
    pack = pack or get_pack(rows[0].get("doc_type", DEFAULT_KEY) if rows else DEFAULT_KEY)
    scored = [r for r in rows if r["datapoints"] is not None]
    print(f"\n### Golden - {pack.key} {arm}-kar ({len(scored)}/{len(rows)} eset kivonatolva)\n")
    print("| mező | pontosság | n | átlag conf (S) / max flag (G) |\n|---|---|---|---|")
    for f in pack.scored_fields:
        vals = [r["scores"][f] for r in scored if r["scores"].get(f) is not None]
        if not vals:
            continue
        acc = sum(vals) / len(vals)
        if arm == "S":
            confs = [c for r in scored if f in r["picks"] and (c := r["picks"][f]["confidence"]) is not None]  # 069: None without candidates
            extra = f"{statistics.mean(confs):.2f}" if confs else "-"
        else:
            flags = [max(r["verdicts"]["flags"].get(f, {"_": 0.0}).values()) for r in scored if r["verdicts"]]
            extra = f"{statistics.mean(flags):.2f}" if flags else "-"
        tag = " (informatív)" if f in pack.informational_fields else ""
        print(f"| {f}{tag} | {acc:.0%} | {len(vals)} | {extra} |")
    strict = [r["scores"][f] for r in scored for f in pack.strict_scored if r["scores"].get(f) is not None]
    print(f"\n**Pontozott mezők összesen:** {sum(strict)}/{len(strict)} = {sum(strict) / max(len(strict), 1):.1%}")
    if any(r.get("text_source") == "ocr" for r in rows):
        lenient = [r["scores_lenient"][f] for r in scored for f in pack.strict_scored if r.get("scores_lenient", {}).get(f) is not None]
        print(f"**OCR-tűrő (ékezet-, kisbetű-, írásjel-független) egyezés:** {sum(lenient)}/{len(lenient)} = {sum(lenient) / max(len(lenient), 1):.1%}"
              f"  (a különbség = csak az OCR ékezet-zaja; OCR-szövegű esetek: {sum(1 for r in rows if r.get('text_source') == 'ocr')}/{len(rows)})")
    routes = Counter(r["route"] or r["final_status"] for r in rows)
    print("**Route-eloszlás:** " + ", ".join(f"{k}: {v}" for k, v in routes.items()))
    secs = [r["seconds"] for r in rows]
    print(f"**Idő:** átlag {statistics.mean(secs):.1f}s / eset")
    for r in rows:
        if r["route"] == "human":
            print(f"  - {r['case_id']}: " + "; ".join(r["review_reasons"][:6]))
    wrong = [(r["case_id"], f, (r["datapoints"] or {}).get(f)) for r in scored for f in pack.strict_scored if r["scores"].get(f) is False]
    if wrong:
        print("\n**Hibás mezők:**")
        for cid, f, got in wrong:
            print(f"  - {cid}: {f} = {got!r}")


def determinism(
    arm: str, n: int, run_one: Callable[..., FlowState], cases: list[GoldenCase] | None = None, type_key: str = DEFAULT_KEY
) -> list[dict[str, Any]]:
    from jav.adapters.jev import get_adapter

    pack = get_pack(type_key)
    cases = cases or load_cases(type_key)
    rows: list[dict[str, Any]] = []
    # without the cache (no reads AND no writes): we measure the real run-to-run variation, and the golden
    # reference answers in the cache stay untouched (handoff 004 §4 pitfall)
    with get_adapter().no_cache_write():
        for case in cases:
            for run_no in range(1, n + 1):
                t0 = time.perf_counter()
                state = run_one(str(case.pdf), case.case_id, arm, run_no=run_no, tracker=False, use_cache=False, doc_type=type_key)
                rows.append(_state_row(case, state, run_no, time.perf_counter() - t0, pack))
            print(f"  {case.case_id:40} {n} futás kész")
    path = _dump_rows(rows, _run_name(type_key, f"determinism_{arm}_n{n}"))
    print_determinism_report(rows, arm, n, pack)
    print(f"\nNyers futások: {path}")
    return rows


def print_determinism_report(rows: list[dict[str, Any]], arm: str, n: int, pack: TypePack | None = None) -> None:
    pack = pack or get_pack(rows[0].get("doc_type", DEFAULT_KEY) if rows else DEFAULT_KEY)
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_case[r["case_id"]].append(r)
    print(f"\n### Determinizmus - {pack.key} {arm}-kar, n={n}, {len(by_case)} eset\n")
    print("| mező | egyezés | flip-esetek | conf átlag | conf szórás |\n|---|---|---|---|---|")
    # after the scored fields, the unscored ones too (informational): LLM drift often shows up there
    for f in pack.scored_fields + tuple(x for x in pack.header_fields if x not in pack.scored_fields):
        agree: list[float] = []
        flips: list[str] = []
        confs: list[float] = []
        stds: list[float] = []
        for case_id, runs in by_case.items():
            values = [json.dumps((r["datapoints"] or {}).get(f), ensure_ascii=False, default=str) for r in runs]
            modal, cnt = Counter(values).most_common(1)[0]
            agree.append(cnt / len(values))
            if cnt != len(values):
                flips.append(case_id)
            if arm == "S":
                cs = [c for r in runs if f in r["picks"] and (c := r["picks"][f]["confidence"]) is not None]
            else:
                cs = [max(r["verdicts"]["flags"].get(f, {"_": 0.0}).values()) for r in runs if r["verdicts"]]
            if cs:
                confs.append(statistics.mean(cs))
                stds.append(statistics.pstdev(cs) if len(cs) > 1 else 0.0)
        if not agree:
            continue
        if f not in pack.scored_fields:
            f = f + " (informatív)"
        print(
            f"| {f} | {statistics.mean(agree):.1%} | {len(flips)} | "
            f"{statistics.mean(confs):.2f} | {statistics.mean(stds):.3f} |"
            if confs
            else f"| {f} | {statistics.mean(agree):.1%} | {len(flips)} | - | - |"
        )
    if arm == "G":
        # stability of the JEV flags, independent of changes in the LLM values
        flag_std: list[float] = []
        for runs in by_case.values():
            keys = set()
            for r in runs:
                if r["verdicts"]:
                    keys |= {(f, fl) for f, d in r["verdicts"]["flags"].items() for fl in d}
            for f, fl in keys:
                ps = [r["verdicts"]["flags"].get(f, {}).get(fl) for r in runs if r["verdicts"]]
                ps = [p for p in ps if p is not None]
                if len(ps) > 1:
                    flag_std.append(statistics.pstdev(ps))
        if flag_std:
            print(f"\n**Jev-flag szórás (átlag, minden mező×flag):** {statistics.mean(flag_std):.3f}")
    route_flips = [cid for cid, runs in by_case.items() if len({r["route"] for r in runs}) > 1]
    print(f"**Route-flip esetek:** {len(route_flips)}" + (f" ({', '.join(route_flips)})" if route_flips else ""))


# --- JEV verifier probe (the JEV half of the G path, without OpenAI) ----------------------


PROBE_TARGET = {
    "perfect": "(none)",
    "parties_swapped": "parties_swapped",
    "net_is_gross": "off_target:net_total",
    "truncated_supplier": "incomplete:supplier_name",
    "invoice_number_emptied": "absence_wrong:invoice_number",
    "tax_id_is_phone": "wrong_kind:supplier_tax_id",
}
# Hungarian phone number on an invoice (+36 / 0036 / 06, area code, 6-7 digits) - the old pitfall: phone as tax number
PHONE_RE = re.compile(r"(?:\+36|0036|06)[\s\-/.]?\d{1,2}[\s\-/.]?\d{3}[\s\-]?\d{3,4}\b")


def _nonzero(v: Any) -> bool:
    try:
        return v is not None and Decimal(str(v)) != 0
    except InvalidOperation:
        return False


def perturb_extraction(dp: dict[str, Any], lines: list[Any]) -> dict[str, dict[str, Any]]:
    """The golden expected header extract and deliberately broken variants of it (the probe's input).

    Variants: perfect; parties swapped; truncated supplier name; emptied invoice number; net := gross (only if there is
    VAT and a net amount); a phone number in place of the supplier tax number (only if the invoice prints a phone number
    - the legacy project's typical GPT error, README).
    """
    swapped = dict(dp)
    swapped["supplier_name"], swapped["buyer_name"] = dp.get("buyer_name"), dp.get("supplier_name")
    swapped["supplier_tax_id"], swapped["buyer_tax_id"] = dp.get("buyer_tax_id"), dp.get("supplier_tax_id")
    out = {
        "perfect": dp,
        "parties_swapped": swapped,
        "truncated_supplier": dict(dp, supplier_name=" ".join(str(dp.get("supplier_name")).split()[:1])),
        "invoice_number_emptied": dict(dp, invoice_number=None),
    }
    if _nonzero(dp.get("vat_total")) and dp.get("net_total") is not None:
        out["net_is_gross"] = dict(dp, net_total=dp["gross_total"])
    for ln in lines:
        m = PHONE_RE.search(ln.text)
        if m:
            out["tax_id_is_phone"] = dict(dp, supplier_tax_id=re.sub(r"\D", "", m.group(0)))
            break
    return out


def probe_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per variant: n, mean / min / max of the expected flag's P, two-sided band counts (policy `invoice.verify`), false
    positives."""
    from jav.policy import noul_band

    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by[r["variant"]].append(r)
    out: dict[str, dict[str, Any]] = {}
    for variant, rs in by.items():
        ps = [float(r["p"]) for r in rs]
        bands = Counter(noul_band(p, "invoice.verify") for p in ps)
        out[variant] = {
            "n": len(rs),
            "target": PROBE_TARGET.get(variant, "?"),
            "mean": round(statistics.mean(ps), 4),
            "min": round(min(ps), 4),
            "max": round(max(ps), 4),
            "bands": {b: bands.get(b, 0) for b in ("no", "uncertain", "yes")},
            "false_positives": sum(1 for r in rs if r.get("false_positive")),
        }
    return out


def verifier_probe(cases: list[GoldenCase] | None = None, use_cache: bool = True, type_key: str = DEFAULT_KEY) -> list[dict[str, Any]]:
    """Runs the JEV verifier on the golden EXPECTED extract (perfect) and on deliberately broken variants of it.

    This is the calibration test of the G path's JEV half: for the perfect extract the flags must be low, for the
    injected errors the matching flag must be high. No OpenAI call. The raw rows go to `runs/*_verifier_probe.jsonl`
    (variant, expected flag, P, band, all flags); the summary also shows the two-sided bands.
    """
    from jav.adapters.jev import get_adapter
    from jav.jev_verify import site_for
    from jav.pdf import read_document
    from jav.policy import REVIEW_FLAG_P, noul_band

    pack = get_pack(type_key)
    site = site_for(pack.key)
    cases = cases or load_cases(type_key)
    jev = get_adapter()
    rows: list[dict[str, Any]] = []
    print("| eset | variáns | várt flag | P | sáv | review-okok |\n|---|---|---|---|---|---|")
    for case in cases:
        pdf = read_document(case.pdf)
        header = {k: v for k, v in case.expected.items() if k != "line_items" and k in pack.fields}
        for variant, dp in perturb_extraction(header, pdf.layout).items():
            llm = {**{f: None for f in pack.header_fields}, **dp, "line_items": []}
            t0 = time.perf_counter()
            verdicts, call = site.verify(jev, pdf.layout, llm, run_id=f"probe-{case.case_id}-{variant}", use_cache=use_cache)
            seconds = time.perf_counter() - t0
            hot = [f"{fl}:{f}:{p:.2f}" for f, d in verdicts.flags.items() for fl, p in d.items() if p >= REVIEW_FLAG_P]
            hot += [f"{fl}:{p:.2f}" for fl, p in verdicts.doc_flags.items() if p >= REVIEW_FLAG_P]
            false_positive = False
            if variant == "perfect":
                # False positives are measured only on fields covered by the golden set that affect the ROUTE
                # (scored or high-stakes): the `absence_wrong` / line_items flag of fields / line items absent from
                # the golden set and the purely informational fields (address: the legacy contract does not score it,
                # nor does the policy send it to manual review) are legitimate JEV judgements, not errors.
                routed = {f for f in header if f in pack.strict_scored or f in pack.high_stakes}
                covered = [p for f, d in verdicts.flags.items() if f in routed for p in d.values()]
                covered.append(verdicts.doc_flags.get("parties_swapped", 0.0))
                p = max(covered + [0.0])
                hot = [h for h in hot if not h.startswith("line_items") and h.split(":")[1] in routed]
                hot += [f"unsupported:{f}" for f in verdicts.unsupported if f in routed]
                false_positive = bool(hot)
            else:
                hot += [f"unsupported:{f}" for f in verdicts.unsupported]
                flag, _, field = PROBE_TARGET[variant].partition(":")
                p = verdicts.flags.get(field, {}).get(flag, 0.0) if field else verdicts.doc_flags.get(flag, 0.0)
            row = {
                "case_id": case.case_id,
                "doc_type": pack.key,
                "variant": variant,
                "target": PROBE_TARGET[variant],
                "p": round(p, 4),
                "band": noul_band(p, "invoice.verify"),
                "false_positive": false_positive,
                "hot": hot,
                "flags": verdicts.flags,
                "doc_flags": verdicts.doc_flags,
                "unsupported": verdicts.unsupported,
                "perfect_fields": sorted(f for f in header if f in pack.strict_scored or f in pack.high_stakes),  # false positives are measured on these (eval-report ground truth)
                "model": verdicts.model,
                "cached": call.cached,
                "seconds": round(seconds, 3),
                "config_hash": site.config_hash,
            }
            rows.append(row)
            print(f"| {case.case_id} | {variant} | {row['target']} | {p:.2f} | {row['band']} | {'; '.join(hot)[:120] or '-'} |")
    print_probe_report(rows)
    path = _dump_rows(rows, _run_name(type_key, "verifier_probe"))
    print(f"\nnyers futás: {path}")
    return rows


def print_probe_report(rows: list[dict[str, Any]]) -> None:
    print("\n**Összegzés variánsonként (a várt flag P-je; a tökéletesnél a legmagasabb golden-mezős flag):**\n")
    print("| variáns | várt flag | n | átlag | min | max | nem | bizonytalan | igen | fals pozitív |\n|---|---|---|---|---|---|---|---|---|---|")
    for variant, s in probe_summary(rows).items():
        b = s["bands"]
        fp = f"{s['false_positives']}/{s['n']}" if variant == "perfect" else "-"
        print(f"| {variant} | {s['target']} | {s['n']} | {s['mean']:.2f} | {s['min']:.2f} | {s['max']:.2f} | {b['no']} | {b['uncertain']} | {b['yes']} | {fp} |")
    print("\n(tökéletes kivonatnál a jó: `nem` sáv; hibás variánsnál a jó: `igen` sáv; a `bizonytalan` sáv ma nem review-ok)")
