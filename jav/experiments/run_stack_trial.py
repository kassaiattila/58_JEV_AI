"""Valós, párosított Burr/JEV SDK–Pydantic AI próba, rögzített helyi címkékkel."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import statistics
import time
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

from jav import store
from jav.adapters.jev import JevAdapter
from jav.config import PROJECT_ROOT, OLD_PROJECT_ROOT
from jav.evals import field_equal
from jav.experiments.stack_trial import DirectAdapter, TypedAdapter, run_trial
from jav.typepack import get as get_pack

DATA = PROJECT_ROOT / "runs/20260921_stack_trial"


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def line_scorer():
    path = OLD_PROJECT_ROOT / "orchestrator/framework/scorers.py"
    spec = importlib.util.spec_from_file_location("legacy_scorers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.score_line_items


def score_result(flow, result, label):
    if flow == "detect":
        actual = result.result.doc_type if result.result else None
        return {"correct": actual == label["doc_type"] if label["doc_type"] else None,
                "automatic": result.result is not None and not result.uncertain,
                "actual": actual, "expected": label["doc_type"],
                "label_ambiguous": label["doc_type"] is None}
    pack = get_pack(label["doc_type"])
    actual = result.invoice.to_datapoints(tuple(pack.fields)) if result.invoice else {}
    checks = {k: field_equal(k, actual.get(k), v, pack.kind(k)) for k, v in label["invoice"].items()}
    lines = line_scorer()(label["line_items"], actual.get("line_items"))
    return {"correct": all(checks.values()), "automatic": result.route == "auto",
            "field_checks": checks, "actual": actual, "expected": label["invoice"],
            "high_stakes_errors": [k for k in pack.high_stakes if k in checks and not checks[k]],
            "line_items": lines, "expected_line_count": len(label["line_items"]),
            "actual_line_count": len(actual.get("line_items") or []),
            "complete_document_correct": all(checks.values()) and lines["matched"] == lines["total"],
            "review_reasons": result.review_reasons}


def summarize(rows):
    out = {}
    for flow in sorted({r["flow"] for r in rows}):
        for arm in ("sdk", "pydantic"):
            for split in ("development", "evaluation", "regression", "all"):
                subset = [r for r in rows if r["flow"] == flow and r["arm"] == arm and (split == "all" or r["split"] == split)]
                first = [r for r in subset if r["mode"] == "live" and r["repeat"] == 0]
                if not first:
                    continue
                live = [r for r in subset if r["mode"] == "live"]
                scored = [r for r in first if r.get("correct") is not None]
                auto = [r for r in scored if r.get("automatic")]
                times = sorted(r["wall_seconds"] for r in live)
                item = {"documents": len(first), "scored_documents": len(scored),
                        "correct_documents": sum(r["correct"] for r in scored),
                        "automatic_documents": sum(bool(r.get("automatic")) for r in first),
                        "scored_automatic": len(auto), "wrong_automatic": sum(not r["correct"] for r in auto),
                        "unscored_automatic": sum(r.get("correct") is None and bool(r.get("automatic")) for r in first),
                        "errors": sum(bool(r.get("error")) for r in first),
                        "live_runs": len(live), "mean_seconds": statistics.mean(times),
                        "max_seconds": max(times), "live_cost_usd": round(sum(r["cost_usd"] for r in live), 6),
                        "live_input_tokens": sum(r["input_tokens"] for r in live),
                        "live_calls": sum(r["calls"] for r in live),
                        "cache_runs": sum(r["mode"] == "cache" for r in subset),
                        "cache_calls": sum(r["cached_calls"] for r in subset if r["mode"] == "cache")}
                repeated = [r for r in live if r["repeat"] > 0]
                baseline = {r["case_id"]: r for r in first}
                item["changed_outputs"] = sum(r.get("actual") != baseline[r["case_id"]].get("actual") for r in repeated)
                item["changed_routes"] = sum(r.get("automatic") != baseline[r["case_id"]].get("automatic") for r in repeated)
                if flow == "invoice":
                    item.update(correct_fields=sum(sum(r.get("field_checks", {}).values()) for r in first),
                                total_fields=sum(len(r.get("field_checks", {})) for r in first),
                                wrong_auto_high_stakes=sum(bool(r.get("high_stakes_errors")) for r in auto),
                                complete_document_correct=sum(r.get("complete_document_correct", False) for r in first),
                                expected_line_count=sum(r.get("expected_line_count", 0) for r in first),
                                actual_line_count=sum(r.get("actual_line_count", 0) for r in first))
                out[f"{flow}/{arm}/{split}"] = item
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--prepare-ocr", action="store_true")
    args = parser.parse_args()
    sample = json.loads((DATA / "sample.json").read_text(encoding="utf-8"))
    labels = json.loads((DATA / "labels.json").read_text(encoding="utf-8"))
    cases = sample["cases"]
    if args.prepare_ocr:
        from jav.ocr import ocr_with_escalation
        result = []
        for case in cases:
            if case["text_source"] is not None:
                continue
            t0 = time.perf_counter()
            pdf, escalated = ocr_with_escalation(case["path"], page_count=case["page_count"])
            result.append({"case_id": case["case_id"], "seconds": time.perf_counter()-t0,
                           "signals": pdf.ocr, "escalated": escalated, "text_chars": len(pdf.text),
                           "azure_source_mount_eligible": False,
                           "cost_usd": 0,
                           "cost_note": "historical Azure cache reused; original charge not included" if pdf.ocr and pdf.ocr.get("engine") == "azure_di" else "local OCR; external fallback unavailable for source mount"})
            print(case["case_id"], "OCR", pdf.text_source, len(pdf.text), round(result[-1]["seconds"], 2), flush=True)
            write_json(DATA / "ocr_preparation.json", result)
        return
    if not args.live:
        parser.error("--live or --prepare-ocr required")
    # A címkék / csoportok a hívások előtt lezárva; utána nincs kérdéshangolás.
    groups = {split: {v["group"] for v in labels["cases"].values() if v["split"] == split}
              for split in ("development", "evaluation", "regression")}
    assert not groups["development"] & groups["evaluation"]
    assert len({c["sha256"] for c in cases}) == len(cases)
    for case in cases:
        assert hashlib.sha256(Path(case["path"]).read_bytes()).hexdigest() == case["sha256"]
    out = DATA / datetime.now().strftime("measurement_%H%M%S")
    out.mkdir()
    write_json(out / "frozen_labels.json", labels)
    manifest = {"sample_sha256": hashlib.sha256((DATA / "sample.json").read_bytes()).hexdigest(),
                "labels_sha256": hashlib.sha256((DATA / "labels.json").read_bytes()).hexdigest(),
                "repeats": 2, "cache_replay": True, "max_live_adapter_requests": 200, "max_recorded_cost_usd": 1.0,
                "packages": {p: importlib.metadata.version(p) for p in ("apache-burr", "pydantic-ai-slim", "typesafe-sdk")},
                "source_hashes": {str(p.relative_to(PROJECT_ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for root in ("jav", "configs") for p in sorted((PROJECT_ROOT/root).rglob("*")) if p.suffix in (".py", ".json")},
                "scope": "single-worker local persistence; current invoice S and detect graphs; no generator; assistant-labelled pilot",
                "inputs": "same PDF and canonical JSON state in both arms; native schema changes questions"}

    class BoundedAdapter(JevAdapter):
        def _live(self, *args, **kwargs):
            with store.connect() as db:
                n, cost = db.execute("SELECT count(*),coalesce(sum(cost_usd),0) FROM ledger WHERE cached=0").fetchone()
            if n >= manifest["max_live_adapter_requests"] or cost >= manifest["max_recorded_cost_usd"]:
                raise RuntimeError("trial budget exhausted")
            return super()._live(*args, **kwargs)

    base = BoundedAdapter(cache_dir=out / "cache")
    with store.use_store(out / "business.sqlite"):
        base.model = base.resolve_model(base.model, run_id="model_probe")
    manifest["model"] = base.model
    write_json(out / "manifest.json", manifest)
    print("OUT", out, flush=True)
    rows = []
    for case in sorted(cases, key=lambda c: ({"development": 0, "regression": 1, "evaluation": 2}[labels["cases"][c["case_id"]]["split"]], c["case_id"])):
        label = labels["cases"][case["case_id"]]
        for flow in (["detect", "invoice"] if "invoice" in label else ["detect"]):
            for repeat in range(3):
                mode = "cache" if repeat == 2 else "live"
                order = ["sdk", "pydantic"] if (int(case["case_id"][-2:])+repeat) % 2 == 0 else ["pydantic", "sdk"]
                for arm in order:
                    cls = DirectAdapter if arm == "sdk" else TypedAdapter
                    adapter = cls(base, force_live=mode == "live")
                    run_id = f"{case['case_id']}-{flow}-{arm}-{mode}-{repeat}"
                    t0 = time.perf_counter()
                    row = {"case_id": case["case_id"], "flow": flow, "arm": arm, "split": label["split"],
                           "repeat": repeat, "mode": mode, "run_id": run_id}
                    try:
                        with base.no_cache_write() if repeat == 1 else nullcontext():
                            result = run_trial(flow, case["path"], out, run_id, adapter, doc_type=label["doc_type"] or "invoice_hu")
                        write_json(out / f"{run_id}.json", result.model_dump(mode="json"))
                        row.update(score_result(flow, result, label))
                    except Exception as exc:
                        row.update(error=type(exc).__name__, error_message=str(exc)[:400],
                                   correct=None if flow == "detect" and label["doc_type"] is None else False,
                                   automatic=False)
                        # Hiányzó eredmény minden előre címkézett mezőn hiba.
                        if flow == "invoice":
                            row.update(field_checks={k: False for k in label["invoice"]}, expected_line_count=len(label["line_items"]))
                    row["wall_seconds"] = time.perf_counter()-t0
                    with store.use_store(out / "business.sqlite"):
                        ledger = store.ledger_for_run(run_id)
                    row.update(cost_usd=sum(r["cost_usd"] or 0 for r in ledger),
                               calls=len(ledger), cached_calls=sum(bool(r["cached"]) for r in ledger),
                               input_tokens=sum(r["input_tokens"] or 0 for r in ledger if not r["cached"]))
                    write_json(out / f"{run_id}_requests.json", adapter.audit)
                    rows.append(row)
                    with (out / "results.jsonl").open("a", encoding="utf-8") as file:
                        file.write(json.dumps(row, ensure_ascii=False, default=str)+"\n")
                    write_json(out / "summary.json", summarize(rows))
            print(case["case_id"], flow, "done", flush=True)
    print(json.dumps(summarize(rows), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
