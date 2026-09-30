"""M1 eval: detect-golden a régi típus-címkézett manifestekből + korpusz-bejárás riporttal + kézi ellenőrző minta."""

from __future__ import annotations

import json
import random
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from jav.policy import DETECT_LOW_CONFIDENCE  # 066 Á38: a küszöb a policyból
from jav import store
from jav.config import GOLDEN_MANIFEST, OLD_PROJECT_ROOT, RUNS_DIR
from jav.doc_types import DOC_TYPE_KEYS, OLD_TYPE_MAP

TRIAGE_MANIFEST = OLD_PROJECT_ROOT / "flows" / "doc-triage-bare" / "golden" / "manifest.json"


@dataclass
class DetectCase:
    case_id: str
    path: Path
    expected: str  # a mi taxonómiánk szerint
    old_type: str


def load_detect_cases() -> list[DetectCase]:
    """Unió: doc-triage golden (60, típus-címke) + doc-extract golden (típus = type_key). Dedup útvonal szerint."""
    seen: dict[Path, DetectCase] = {}
    for manifest, label_key in ((TRIAGE_MANIFEST, "expected"), (GOLDEN_MANIFEST, "type_key")):
        if not manifest.exists():
            continue
        m = json.loads(manifest.read_text(encoding="utf-8"))
        for c in m.get("cases", []):
            old = c.get(label_key) or c.get("type_key")
            path = OLD_PROJECT_ROOT / c["input_ref"].lstrip("/")
            if path.suffix.lower() != ".pdf" or not path.exists() or path in seen:
                continue
            mapped = OLD_TYPE_MAP.get(old, "other")
            seen[path] = DetectCase(case_id=c["id"], path=path, expected=mapped, old_type=old)
    return list(seen.values())


def detect_golden(use_cache: bool = True) -> list[dict[str, Any]]:
    from jav.flow_detect import run_detect

    cases = load_detect_cases()
    rows: list[dict[str, Any]] = []
    for case in cases:
        t0 = time.perf_counter()
        st = run_detect(str(case.path), use_cache=use_cache)
        r = st.result
        rows.append({
            "case_id": case.case_id, "expected": case.expected, "old_type": case.old_type,
            "got": r.doc_type if r else None, "confidence": r.confidence if r else None,
            "issuer_hu": r.issuer_hu if r else None, "language": r.language if r else None,
            "status": st.final_status, "seconds": round(time.perf_counter() - t0, 2),
            "top3": dict(sorted(r.probabilities.items(), key=lambda kv: -kv[1])[:3]) if r else {},
            "parent": r.parent if r else None, "parent_prob": r.parent_prob if r else None,
        })
    RUNS_DIR.mkdir(exist_ok=True)
    out = RUNS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_detect_golden.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print_detect_report(rows)
    print(f"\nNyers futások: {out}")
    return rows


def detect_determinism(n: int = 3, limit: int | None = None) -> None:
    """n ismételt, cache NÉLKÜLI futás a detect-goldenen (`no_cache_write()` alatt, a referencia-cache érintetlen):
    típus-flipek esetenként, confidence-szórás. A sorok az eval-riport determinizmus-szakaszába illenek."""
    from jav.adapters.jev import get_adapter
    from jav.flow_detect import run_detect

    cases = load_detect_cases()
    if limit:
        cases = cases[:limit]
    per_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with get_adapter().no_cache_write():
        for k in range(n):
            for case in cases:
                st = run_detect(str(case.path), use_cache=False)
                r = st.result
                if r is None:
                    continue
                per_case[case.case_id].append({
                    "case_id": case.case_id, "expected": case.expected, "old_type": case.old_type, "got": r.doc_type,
                    "confidence": r.confidence, "issuer_hu": r.issuer_hu, "language": r.language, "status": st.final_status,
                    "top3": dict(sorted(r.probabilities.items(), key=lambda kv: -kv[1])[:3]), "parent": r.parent, "parent_prob": r.parent_prob,
                    "run_no": k + 1,
                })
            print(f"  {k + 1}/{n} kör kész")
    flips = 0
    stds: list[float] = []
    for cid, rs in per_case.items():
        if len({r["got"] for r in rs}) > 1:
            flips += 1
            print(f"  FLIP {cid}: {[r['got'] for r in rs]} conf={[r['confidence'] for r in rs]}")
        if len(rs) > 1:
            stds.append(statistics.pstdev(r["confidence"] for r in rs))
    print(f"\n### Detect determinizmus - {len(per_case)} eset × {n} futás (cache nélkül)")
    print(f"**Flip (eltérő típus futások közt):** {flips}/{len(per_case)}")
    if stds:
        print(f"**Choice confidence szórás:** átlag {statistics.mean(stds):.4f}, max {max(stds):.4f}")
    RUNS_DIR.mkdir(exist_ok=True)
    out = RUNS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_detect_determinism.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for rs in per_case.values() for r in rs) + "\n", encoding="utf-8")
    print(f"Nyers futások: {out}")


def print_detect_report(rows: list[dict[str, Any]]) -> None:
    scored = [r for r in rows if r["status"] == "done"]
    ocr = [r for r in rows if r["status"] == "needs_ocr"]
    print(f"\n### Detect golden - {len(scored)} szöveges eset (+{len(ocr)} needs_ocr, kihagyva)\n")
    print("| elvárt típus | n | pontosság | átlag conf | tévesztések |\n|---|---|---|---|---|")
    by_exp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in scored:
        by_exp[r["expected"]].append(r)
    total_ok = 0
    for exp, rs in sorted(by_exp.items()):
        ok = sum(r["got"] == exp for r in rs)
        total_ok += ok
        wrong = Counter(r["got"] for r in rs if r["got"] != exp)
        print(f"| {exp} | {len(rs)} | {ok / len(rs):.0%} | {statistics.mean(r['confidence'] for r in rs):.2f} | "
              f"{', '.join(f'{k}×{v}' for k, v in wrong.items()) or '-'} |")
    print(f"\n**Összesen:** {total_ok}/{len(scored)} = {total_ok / max(len(scored), 1):.1%}")
    low = [r for r in scored if r["confidence"] < DETECT_LOW_CONFIDENCE]
    print(f"**confidence < 0,6:** {len(low)}/{len(scored)}")
    for r in scored:
        if r["got"] != r["expected"]:
            print(f"  - {r['case_id']}: várt {r['expected']}, kapott {r['got']} ({r['confidence']:.2f}) top3={r['top3']}")


# --- korpusz-bejárás --------------------------------------------------------------------------


def iter_pdfs(root: Path) -> list[Path]:
    return sorted({p for p in root.rglob("*") if p.suffix.lower() == ".pdf"})


def _already_detected() -> set[str]:
    with store.connect() as c:
        return {r["source_path"] for r in c.execute("SELECT source_path FROM documents WHERE doc_type IS NOT NULL OR has_text = 0")}


def detect_corpus(root: Path, *, limit: int | None = None, force: bool = False, use_cache: bool = True, redo_unknown: bool = False) -> None:
    from jav.flow_detect import run_detect

    pdfs = iter_pdfs(root)
    if redo_unknown:
        # a Jev 'unknown'-jai (tipikusan törött szövegréteg): újra a szigorított has_text_layer teszttel
        with store.connect() as c:
            redo = {r["source_path"] for r in c.execute("SELECT source_path FROM documents WHERE doc_type = 'unknown' OR type_conf < ?", (DETECT_LOW_CONFIDENCE,))}
        todo = [p for p in pdfs if str(p) in redo]
    else:
        done_paths = set() if force else _already_detected()
        todo = [p for p in pdfs if str(p) not in done_paths]
    if limit:
        todo = todo[:limit]
    print(f"{len(pdfs)} PDF, ebből feldolgozandó: {len(todo)} (kész: {len(pdfs) - len(todo)})")
    t0 = time.perf_counter()
    errors: list[str] = []
    for i, p in enumerate(todo, 1):
        try:
            st = run_detect(str(p), use_cache=use_cache)
            tag = st.result.doc_type if st.result else st.final_status
            conf = f"{st.result.confidence:.2f}" if st.result else "-"
        except Exception as exc:  # noqa: BLE001 - egy hibás PDF ne állítsa le a bejárást
            errors.append(f"{p.name}: {type(exc).__name__}: {exc}")
            tag, conf = "ERROR", "-"
        if i % 25 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)}  {time.perf_counter() - t0:6.0f}s  utolsó: {p.name[:50]} -> {tag} {conf}")
    if errors:
        print(f"\nHibák ({len(errors)}):")
        for e in errors[:20]:
            print("  - " + e)
    print_corpus_report(root)


def print_corpus_report(root: Path) -> None:
    with store.connect() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM documents WHERE source_path LIKE ?", (str(root) + "%",))]
    if not rows:
        print("nincs adat")
        return
    years = sorted({r["year"] for r in rows if r["year"]}, key=int)
    types = [t for t in DOC_TYPE_KEYS if any(r["doc_type"] == t for r in rows)] + ["needs_ocr"]
    print(f"\n### Korpusz - {len(rows)} dokumentum, típus × év\n")
    print("| típus | " + " | ".join(str(y) for y in years) + " | össz | átlag conf |\n|---|" + "---|" * (len(years) + 2))
    for t in types:
        rs = [r for r in rows if (r["doc_type"] == t) or (t == "needs_ocr" and r["has_text"] == 0)]
        if not rs:
            continue
        cells = [str(sum(1 for r in rs if r["year"] == y)) for y in years]
        confs = [r["type_conf"] for r in rs if r["type_conf"] is not None]
        print(f"| {t} | " + " | ".join(cells) + f" | {len(rs)} | {statistics.mean(confs):.2f} |" if confs else f"| {t} | " + " | ".join(cells) + f" | {len(rs)} | - |")
    low = [r for r in rows if r["type_conf"] is not None and r["type_conf"] < DETECT_LOW_CONFIDENCE]
    print(f"\n**confidence < 0,6:** {len(low)}/{len(rows)}  ·  **nyitott review:** {store.stats()['review_open']}")
    for r in sorted(low, key=lambda r: r["type_conf"])[:15]:
        print(f"  - {Path(r['source_path']).name[:60]}: {r['doc_type']} ({r['type_conf']:.2f})")


def write_manual_sample(root: Path, n: int = 40, seed: int = 1) -> Path:
    """Kézi ellenőrző lista Markdownban: rétegzett véletlen minta (típusonként arányosan, min. 2)."""
    from jav.pdf import read_document

    with store.connect() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM documents WHERE doc_type IS NOT NULL AND source_path LIKE ?", (str(root) + "%",))]
    random.seed(seed)
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_type[r["doc_type"]].append(r)
    sample: list[dict[str, Any]] = []
    for t, rs in by_type.items():
        k = max(2, round(n * len(rs) / max(len(rows), 1)))
        sample.extend(random.sample(rs, min(k, len(rs))))
    sample = sample[:n] if len(sample) > n else sample
    lines = [f"# Detect kézi ellenőrzés - {len(sample)} minta ({datetime.now():%Y-%m-%d})", "",
             "Jelöld: ✅ helyes / ❌ hibás (+ helyes típus). A fájlnév kattintható a OneDrive-ban.", "",
             "| # | ok? | predikció | conf | issuer_hu | fájl | első sorok |", "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(sorted(sample, key=lambda r: (r["doc_type"], r["type_conf"])), 1):
        try:
            head = " ⏎ ".join(read_document(r["source_path"]).lines[:3])[:140].replace("|", "¦")
        except Exception:  # noqa: BLE001
            head = "(nem olvasható)"
        lines.append(f"| {i} | | {r['doc_type']} | {r['type_conf']:.2f} | {r['issuer_hu']:.2f} | {Path(r['source_path']).name[:60].replace('|', '¦')} | {head} |")
    RUNS_DIR.mkdir(exist_ok=True)
    out = RUNS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_detect_manual_sample.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
