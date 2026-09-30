"""JEV-forráskeresés élő, szintetikus próbája; külön eredmény és költségnapló."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from jav import store
from jav.adapters.jev import JevAdapter
from jav.config import PROJECT_ROOT
from jav.source_find import PROMPTS, SearchPolicy, find_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--repeat", type=int, default=2)
    args = parser.parse_args()
    if not args.live or not 1 <= args.repeat <= 3:
        parser.error("Use --live and --repeat 1..3; input is synthetic only")
    config = json.loads(PROMPTS.read_text(encoding="utf-8"))
    case_path = PROJECT_ROOT / "configs/experiments/source_find_cases.json"
    cases = json.loads(case_path.read_text(encoding="utf-8"))
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_source_find"
    out = PROJECT_ROOT / "runs" / run_id
    out.mkdir(parents=True)
    source_files = [PROMPTS, case_path, Path(__file__), PROJECT_ROOT / "jav/source_find.py"]
    hashes = {str(path.relative_to(PROJECT_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files}
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    manifest = dict(run_id=run_id, repeats=args.repeat, files=hashes, config=config, cases=cases,
                    max_adapter_calls=100, cost_stop_usd=.1,
                    evidence="Synthetic capability probe, not production accuracy or unknown-field discovery")
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    adapter = JevAdapter(cache_dir=out / "cache", model="jev-1.13.0")
    rows = []
    with store.use_store(out / "store.sqlite"), adapter.no_cache_write():
        for case in cases["cases"]:
            text = "".join(f"Archive entry {i}\n" for i in range(case.get("prefix_lines", 0))) + case["text"]
            for repeat in range(args.repeat):
                calls = []

                def ask(step, state, questions):
                    ledger = store.ledger_for_run(run_id)
                    if len(ledger) >= 100 or sum(row["cost_usd"] or 0 for row in ledger) >= .1:
                        raise RuntimeError("probe budget reached; no further calls")
                    answer = adapter.ask(step, state, questions, run_id=run_id, config_hash=fingerprint, use_cache=False)
                    calls.append(dict(step=step, state=state,
                                      questions={k: q.model_dump(mode="json") for k, q in questions.items()},
                                      response=answer.response.model_dump(mode="json"), call=answer.call.model_dump(mode="json")))
                    return answer.response

                result = find_source(text, case["query"], ask, SearchPolicy(**config["policy"]), prompts=config)
                expected_ids = {f"L{i:06d}" for i in case["lines"]}
                correct = ((result.status == "candidate" and any(expected_ids <= set(c.line_ids) for c in result.candidates))
                           if case["expected"] == "candidate" else result.status in ("absent", "uncertain"))
                row = dict(case_id=case["id"], domain=case["domain"], repeat=repeat, correct=correct,
                           result=result.model_dump(mode="json"), calls=calls)
                rows.append(row)
                with (out / "results.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(case["id"], repeat, result.status, correct, flush=True)
                if result.errors:
                    raise RuntimeError("provider unavailable; partial evidence saved, probe stopped")
        first = [row for row in rows if row["repeat"] == 0]

        def decision(row):
            result = row["result"]
            return result["status"], [c["line_ids"] for c in result["candidates"]]

        ledger = store.ledger_for_run(run_id)
        summary = dict(run_id=run_id, first_correct=sum(r["correct"] for r in first), first_total=len(first),
                       all_correct=sum(r["correct"] for r in rows), all_total=len(rows),
                       changed_repeats=sum(decision(row) != decision(ref) for ref in first for row in rows
                                           if row["case_id"] == ref["case_id"] and row["repeat"] > 0),
                       adapter_calls=len(ledger), cost_usd=round(sum(r["cost_usd"] or 0 for r in ledger), 6),
                       errors=sum(bool(r["error"]) for r in ledger), models=sorted({r["model"] for r in ledger}))
        (out / "ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(out)


if __name__ == "__main__":
    main()
