"""Közös eval-modul (keret-réteg): a flow-k nyers futásaiból (`runs/*.jsonl`) egységes ítélet-lista, abból riport.

Flow-független: a bemenet a négy meglévő golden-formátum (invoice S / G, doc_detect, email_intent) és a determinizmus-
fájlok; a fájlnév-minta mondja meg, melyik flow. Egy **ítélet** (`Judgment`) = egy Jev-kérdés egy esetre: Choice
(label, confidence, top-prob, második opció) vagy Noul (P(igen)), ha van igazság, akkor `expected` + `correct`.
Minden szám hívás nélkül, $0-ért készül; a sávok a `configs/policy.json` `bands` készleteiből (`jav/policy.py`).

Szakaszok: kérdésenkénti pontosság és sáv-eloszlás (sávonkénti pontossággal), kalibrációs görbe (bin-enként P vs.
találat, ECE) top-prob és confidence szerint, top-prob vs. confidence eltérés, policy-sáv újraértékelés (hány eset
váltana sávot az `uncertain_review` kapcsolóval), determinizmus (kérdésenkénti szórás, flipek).

Új flow bekötése: egy `_from_<flow>(row) -> list[Judgment]` kivonatoló + a fájlnév-minta a `FLOW_PATTERNS`-ben.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal

from jav import policy
from jav.config import RUNS_DIR

Kind = Literal["choice", "noul", "score"]  # score: a conf / top_prob a Choice-hoz hasonlóan értelmezve, a címke a szint

# fájlnév-minta -> flow-név (a determinizmus-fájlok ugyanabba a flow-ba tartoznak, több sor esetenként)
FLOW_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"_golden_S\.jsonl$|_determinism_S_n\d+\.jsonl$", "invoice_S"),
    (r"_golden_G\.jsonl$|_determinism_G_n\d+\.jsonl$", "invoice_G"),
    (r"_detect_golden\.jsonl$|_detect_determinism.*\.jsonl$", "doc_detect"),
    (r"_email_golden\.jsonl$|_email_determinism.*\.jsonl$", "email_intent"),
    (r"_verifier_probe\.jsonl$", "invoice_verify_probe"),
    (r"_email_injection_probe\.jsonl$", "email_injection_probe"),
)
DEFAULT_GLOBS: tuple[str, ...] = ("*_golden_S.jsonl", "*_golden_G.jsonl", "*_detect_golden.jsonl", "*_email_golden.jsonl",
                                  "*_determinism_S_n*.jsonl", "*_determinism_G_n*.jsonl", "*_detect_determinism.jsonl", "*_email_determinism.jsonl",
                                  "*_verifier_probe.jsonl", "*_email_injection_probe.jsonl")
CAL_BIN_EDGES: tuple[float, ...] = (0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0)


@dataclass
class Judgment:
    flow: str
    case_id: str
    question: str  # mező (S), flag-név (G), kérdés-azonosító (detect / email)
    kind: Kind
    callsite: str  # policy-sáv hívási hely (configs/policy.json band_for)
    label: str | None
    expected: str | None
    correct: bool | None
    confidence: float | None  # Choice confidence (koncentráltság)
    top_prob: float | None  # a választott opció valószínűsége
    second_prob: float | None  # a második opció valószínűsége (None, ha nincs)
    p: float | None  # Noul P(igen)
    route_recorded: str | None  # a futásban rögzített útvonal (route / next_flow), ha van
    run_no: int = 1
    field: str | None = None  # G-kar: melyik mezőre vonatkozik a flag
    parent: str | None = None  # regiszter v2: a legvalószínűbb opció családja (a futás-sorból)
    parent_prob: float | None = None  # a család összesített valószínűsége
    parent_correct: bool | None = None  # a várt címke családja == parent (ha van igazság)


# --- fájl -> ítéletek ----------------------------------------------------------------------------


def flow_of(path: Path | str) -> str | None:
    name = Path(path).name
    for pattern, flow in FLOW_PATTERNS:
        if re.search(pattern, name):
            return flow
    return None


def is_determinism(path: Path | str) -> bool:
    return "determinism" in Path(path).name


def load_rows(path: Path | str) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]


def _top2(probs: dict[str, float] | None) -> tuple[float | None, float | None]:
    if not probs:
        return None, None
    vals = sorted((float(v) for v in probs.values()), reverse=True)
    return vals[0], (vals[1] if len(vals) > 1 else None)


def _from_invoice_S(row: dict[str, Any]) -> list[Judgment]:
    out = []
    scores = row.get("scores") or {}
    expected_present = row.get("expected_present") or {}
    flow = row.get("flow_label") or "invoice_S"  # típus-csomagonként külön flow (invoice_S = magyar, invoice_foreign_S = külföldi számla)
    high_stakes = policy.high_stakes_for(row.get("doc_type"))
    for field, pick in (row.get("picks") or {}).items():
        top, second = _top2(pick.get("top3"))
        if pick.get("confidence") is None:  # 069 (Á11): jelölt nélkül nincs Choice-ítélet, csak (esetleg) jelenlét-ítélet
            out.extend(_presence_judgment(row, flow, field, pick, expected_present))
            continue
        out.append(Judgment(
            flow=flow, case_id=row["case_id"], question=field, kind="choice",
            callsite="invoice.pick.high_stakes" if field in high_stakes else "invoice.pick",
            label=pick.get("label"), expected=None, correct=scores.get(field), confidence=float(pick["confidence"]),
            top_prob=top, second_prob=second, p=None, route_recorded=row.get("route"), run_no=int(row.get("run_no", 1)),
        ))
        out.extend(_presence_judgment(row, flow, field, pick, expected_present))
    return out


def _presence_judgment(row: dict[str, Any], flow: str, field: str, pick: dict[str, Any],
                       expected_present: dict[str, Any]) -> list[Judgment]:
    """Jelenlét-Noul (select.json v1.1.0): igazság = a golden várt értéke nem None."""
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
        # igazság: pontozott mezőnél a flagnek akkor kell jeleznie, ha a mező rossz; a címke p >= 0,5
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


def _parent_fields(row: dict[str, Any], parent_of: dict[str, str]) -> dict[str, Any]:
    parent, prob = row.get("parent"), row.get("parent_prob")
    exp = row.get("expected")
    correct = None if parent is None or exp is None or exp not in parent_of else parent_of[exp] == parent
    return {"parent": parent, "parent_prob": prob, "parent_correct": correct}


def _from_detect(row: dict[str, Any]) -> list[Judgment]:
    from jav.doc_types import PARENT_OF

    if row.get("got") is None:
        return []
    top, second = _top2(row.get("top3"))
    out = [Judgment(flow="doc_detect", case_id=row["case_id"], question="doc_type", kind="choice", callsite="detect.doc_type",
                    label=row["got"], expected=row.get("expected"), correct=None if row.get("expected") is None else row["got"] == row["expected"],
                    confidence=float(row["confidence"]), top_prob=top, second_prob=second, p=None, route_recorded=row.get("status"),
                    run_no=int(row.get("run_no", 1)), **_parent_fields(row, PARENT_OF))]
    if row.get("issuer_hu") is not None:
        out.append(Judgment(flow="doc_detect", case_id=row["case_id"], question="issuer_is_hungarian", kind="noul", callsite="detect.issuer_is_hungarian",
                            label="yes" if row["issuer_hu"] >= 0.5 else "no", expected=None, correct=None, confidence=None, top_prob=None,
                            second_prob=None, p=float(row["issuer_hu"]), route_recorded=None, run_no=int(row.get("run_no", 1))))
    return out


def _from_email(row: dict[str, Any]) -> list[Judgment]:
    from jav.intents import PARENT_OF

    if row.get("got") is None:
        return []
    top, second = _top2(row.get("top3"))
    out = [Judgment(flow="email_intent", case_id=row["case_id"], question="intent", kind="choice", callsite="email.intent",
                    label=row["got"], expected=row.get("expected"), correct=None if row.get("expected") is None else row["got"] == row["expected"],
                    confidence=float(row["confidence"]), top_prob=top, second_prob=second, p=None, route_recorded=row.get("next_flow"),
                    run_no=int(row.get("run_no", 1)), **_parent_fields(row, PARENT_OF))]
    for key, p in (row.get("signals") or {}).items():
        out.append(Judgment(flow="email_intent", case_id=row["case_id"], question=key, kind="noul", callsite="email.signal",
                            label="yes" if p >= 0.5 else "no", expected=None, correct=None, confidence=None, top_prob=None, second_prob=None,
                            p=float(p), route_recorded=None, run_no=int(row.get("run_no", 1))))
    for key, s in (row.get("scores") or {}).items():  # v1.1.0: Score-jel (urgency) - címke = szint, conf + szint-valószínűségek
        top, second = _top2(s.get("probabilities"))
        out.append(Judgment(flow="email_intent", case_id=row["case_id"], question=key, kind="score", callsite=f"email.{key}",
                            label=str(s.get("level")), expected=None, correct=None, confidence=float(s.get("confidence") or 0.0),
                            top_prob=top, second_prob=second, p=None, route_recorded=None, run_no=int(row.get("run_no", 1))))
    return out


def _from_verify_probe(row: dict[str, Any]) -> list[Judgment]:
    """Ellenőrző-szonda: ismert igazsággal. Hibás variánsnál a várt flag igazsága `yes`; a tökéletes kivonatnál a golden
    lefedte mezők minden flagjének igazsága `no` (a szonda `p`-je ott a legmagasabb ilyen flag). A többi flag igazság nélkül."""
    out: list[Judgment] = []
    variant, target = row["variant"], row["target"]
    t_flag, _, t_field = target.partition(":")
    case_id = f"{row['case_id']}/{variant}"
    doc_type = row.get("doc_type", "invoice_hu")
    flow = "invoice_verify_probe" if doc_type == "invoice_hu" else f"{doc_type}_verify_probe"

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


def _from_email_injection(row: dict[str, Any]) -> list[Judgment]:
    """Beszúrt-utasítás szonda: mint az e-mail golden, de a `prompt_injection` Noul igazsága ismert (clean -> no, elrontott -> yes),
    az eset `<eset>/<variáns>`; az intent igazsága a golden várt szándéka (az elrontott változatnál is - flip = hiba)."""
    out = _from_email(row)
    variant = row.get("variant", "clean")
    for j in out:
        j.flow = "email_injection_probe"
        j.case_id = f"{row['case_id']}/{variant}"
        if j.kind == "noul" and j.question == "prompt_injection":
            j.expected = "no" if variant == "clean" else "yes"
            j.correct = j.label == j.expected
    return out


EXTRACTORS: dict[str, Callable[[dict[str, Any]], list[Judgment]]] = {
    "invoice_S": _from_invoice_S, "invoice_G": _from_invoice_G, "doc_detect": _from_detect, "email_intent": _from_email,
    "invoice_verify_probe": _from_verify_probe, "email_injection_probe": _from_email_injection,
}


def judgments_from_file(path: Path | str) -> list[Judgment]:
    flow = flow_of(path)
    if flow is None:
        raise ValueError(f"ismeretlen futás-fájl (nincs flow-minta): {path}")
    extract = EXTRACTORS[flow]
    out: list[Judgment] = []
    seen: dict[str, int] = defaultdict(int)  # determinizmus-fájl run_no nélkül (email): esetenként sorszámozunk
    for row in load_rows(path):
        js = extract(row)
        if js and "run_no" not in row:
            # az ítélet case_id-ja szerint (a szonda variánsai külön esetek: `<eset>/<variáns>`), nem a nyers sor szerint
            key = js[0].case_id
            seen[key] += 1
            for j in js:
                j.run_no = seen[key]
        out.extend(js)
    return out


# --- sávok és összesítések ------------------------------------------------------------------------


def band_of(j: Judgment) -> str:
    if j.kind == "noul":
        return policy.noul_band(j.p or 0.0, j.callsite)
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
    """Flow × kérdés: n, pontosság, conf/p átlag és szórás, sáv-eloszlás, sávonkénti pontosság (csak az 1. futás)."""
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


def calibration(js: list[Judgment], *, key: str = "top_prob") -> dict[str, Any]:
    """Choice-ítéletek igazsággal: bin-enként átlagos P vs. találati arány, ECE (n-súlyozott |acc - P|)."""
    items = [j for j in _first_runs(js) if j.kind == "choice" and j.correct is not None and getattr(j, key) is not None]
    bins = []
    n_total = len(items)
    ece = 0.0
    for lo, hi in zip(CAL_BIN_EDGES, CAL_BIN_EDGES[1:]):
        last = hi == CAL_BIN_EDGES[-1]
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
    """Flow-nként: a confidence és a top-prob átlagos / legnagyobb eltérése, és hány ítéletnél adna más sávot a top-prob."""
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
    """Esetenként: van-e `human` ítélet (review most is), és van-e CSAK `uncertain` (review lenne `uncertain_review: true` mellett).

    A `uncertain_only` esetek pontossága mondja meg, érdemes-e a kapcsolót bekapcsolni: ha ezek pontatlanok, a sáv
    jó jelzés; ha pontosak, a kapcsoló csak felesleges kézi munkát adna.
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
            bands = {band_of(j) for j in items if j.kind == "choice"}
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
    """Szülő-címke (regiszter v2): a nem-auto sávú Choice-ítéletek közül hánynál használható a család
    (`policy.parent_fallback`), és hánynál egyezik a várt címke családjával."""
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


def determinism_summary(js: list[Judgment]) -> list[dict[str, Any]]:
    """Több futás esetenként: kérdésenként a conf / p szórásának átlaga és maximuma, címke-flipek száma."""
    groups: dict[tuple[str, str], dict[tuple[str, str | None], list[Judgment]]] = defaultdict(lambda: defaultdict(list))
    for j in js:
        groups[(j.flow, j.question)][(j.case_id, j.field)].append(j)  # G-kar: eset × mező a futás-sorozat egysége
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


# --- riport --------------------------------------------------------------------------------------


def default_inputs() -> list[Path]:
    """Mintánként a legfrissebb runs/*.jsonl."""
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
    L = [f"# Eval-riport ({datetime.now():%Y-%m-%d %H:%M}) — hívás nélkül, a nyers futásokból", "",
         f"Sávok: `configs/policy.json` v{policy.cfg.version('policy')} (`bands` / `band_for`); a Choice-sáv = conf-küszöb + második-opció rés, a Noul-sáv kétoldali.", "",
         "## Források", ""]
    for p in paths:
        n = len(load_rows(p))
        L.append(f"- `{p.name}` → {flow_of(p)}{' (determinizmus)' if is_determinism(p) else ''}, {n} sor")
    L += ["", "## Kérdésenként (1. futás)", "", "| flow | kérdés | fajta | n | pontos | átlag | szórás | sávok | pontosság sávonként |", "|---|---|---|---|---|---|---|---|---|"]
    for r in per_question(js):
        acc = f"{r['correct']}/{r['n_scored']} = {r['accuracy']:.0%}" if r["n_scored"] else "-"
        bands = ", ".join(f"{b} {n}" for b, n in r["bands"].items())
        accb = ", ".join(f"{b} {a:.0%}" for b, a in r["acc_by_band"].items()) or "-"
        L.append(f"| {r['flow']} | {r['question']} | {r['kind']} | {r['n']} | {acc} | {_f(r['mean'])} | {_f(r['std'])} | {bands} | {accb} |")
    L += ["", "## Kalibráció (Choice-ítéletek igazsággal)", ""]
    flows = sorted({j.flow for j in js if j.kind == "choice" and j.correct is not None})
    for flow in flows:
        fj = [j for j in js if j.flow == flow]
        for key in ("top_prob", "confidence"):
            cal = calibration(fj, key=key)
            if cal["n"] == 0:
                continue
            L += [f"**{flow} · {key}** — n = {cal['n']}, ECE = {cal['ece']:.3f}", "", "| sáv | n | átlag P | találat |", "|---|---|---|---|"]
            for b in cal["bins"]:
                if b["n"]:
                    L.append(f"| {b['lo']:.2f}–{b['hi']:.2f} | {b['n']} | {b['mean_p']:.3f} | {b['hit_rate']:.0%} |")
            L.append("")
    L += ["## top-prob vs. confidence", "", "| flow | n | átlag eltérés | max eltérés | más sáv a top-prob szerint |", "|---|---|---|---|---|"]
    for r in top_prob_vs_confidence(js):
        L.append(f"| {r['flow']} | {r['n']} | {r['mean_abs_diff']:.3f} | {r['max_abs_diff']:.3f} | {r['band_differs']} |")
    L += ["", "## Policy-sáv újraértékelés (hívás nélkül)", "",
          "`cases_human`: most is kézi sor; `cases_uncertain_only`: CSAK a második-opció rés miatt bizonytalan — ezek `uncertain_review: true` "
          "mellett kézi sorba kerülnének. A `pontosság` az ilyen ítéleteké: ha alacsony, a sáv jó jelzés; ha magas, a kapcsoló csak kézi munkát adna. "
          "`noul_uncertain`: Noul-jelek a középső sávban.", "",
          "| flow | esetek | human | csak uncertain | uncertain pontosság | Noul uncertain |", "|---|---|---|---|---|---|"]
    for r in policy_reeval(js):
        acc = f"{r['uncertain_only_accuracy']:.0%}" if r["uncertain_only_accuracy"] is not None else "-"
        L.append(f"| {r['flow']} | {r['cases']} | {r['cases_human']} | {r['cases_uncertain_only']} | {acc} | {r['noul_uncertain']} |")
    L += ["", "## Szülő-címke (regiszter v2, `parent_min_prob`)", ""]
    prows = parent_fallback_summary(js)
    if prows:
        L += ["`használható`: nem-auto sávú ítélet, ahol a család összesített valószínűsége eléri a `parent_min_prob`-ot; `helyes`: a várt címke családja egyezik.", "",
              "| flow | n | human | uncertain | szülő használható | ebből helyes | szülő helyes összesen |", "|---|---|---|---|---|---|---|"]
        for r in prows:
            L.append(f"| {r['flow']} | {r['n']} | {r['human']} | {r['uncertain']} | {r['parent_usable']} | {r['parent_correct']} | {r['parent_correct_all']}/{r['parent_scored']} |")
    else:
        L.append("(a futás-sorokban nincs `parent` mező - regiszter v1 futás)")
    L += ["", "## Determinizmus (ismételt futások)", ""]
    rows = determinism_summary(jd)
    if rows:
        L += ["| flow | kérdés | esetek | futás | szórás átlag | szórás max | flip |", "|---|---|---|---|---|---|---|"]
        for r in rows:
            L.append(f"| {r['flow']} | {r['question']} | {r['cases']} | {r['runs']} | {r['std_mean']:.4f} | {r['std_max']:.4f} | {r['flips']} |")
    else:
        L.append("(nincs determinizmus-fájl a bemenetben)")
    L.append("")
    return "\n".join(L)


def write_report(paths: list[Path | str] | None = None, out: Path | None = None) -> tuple[str, Path]:
    paths = list(paths) if paths else default_inputs()
    md = report_markdown(paths)
    out = out or RUNS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_eval_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    return md, out
