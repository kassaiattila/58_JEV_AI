"""122 (GPT round, step M5): data extraction on a local case list, each document with its expected type pack.

The case list is the detection measurement's (`jav.evals_detect.load_case_file`: `case_id`, `path`, `expected`,
`expected_detail`), kept outside git because it names real documents; only the cases with an `expected_detail` that
is a type pack run. The run is a paid measurement under a hard budget in code (`calls.measurement`): the G path's
OpenAI budget (plus JEV when it verifies with JEV), or the S path's JEV budget. Nothing is approved or corrected; the
rows say what each pack extracted and which to-dos it raised.

    python -m jav.experiments.extract_cases runs/quality_122/cases.json --arm S --budget-usd 0.03 --live
    python -m jav.experiments.extract_cases runs/quality_122/cases.json --arm G --no-jev --budget-usd 0.05 \
        --only-detail proforma_invoice --live

Output: `runs/<timestamp>_extract_cases_<arm>/rows.jsonl` (the extracted values, to-dos and status per case).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from jav.config import PROJECT_ROOT

RUNS = PROJECT_ROOT / "runs"


def limits_for(arm: str, jev: bool, budget_usd: Decimal, jev_budget_usd: Decimal | None) -> dict[str, Decimal]:
    """The S path calls JEV only; the G path calls OpenAI, and JEV too when it verifies with JEV."""
    if arm == "S":
        return {"jev": budget_usd}
    out = {"openai": budget_usd}
    if jev:
        out["jev"] = jev_budget_usd if jev_budget_usd is not None else Decimal("0")
    return out


def run(case_file: Path, *, arm: str, jev: bool, budget_usd: Decimal, out_dir: Path,
        jev_budget_usd: Decimal | None = None, only_detail: str | None = None) -> list[dict[str, Any]]:
    from jav import flow, typepack
    from jav.evals_detect import load_case_file
    from jav.runtime import calls

    packs = set(typepack.keys())
    cases = [c for c in load_case_file(case_file) if c.expected_detail in packs
             and (only_detail is None or c.expected_detail == only_detail)]
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    with calls.measurement(f"measure-{out_dir.name}", limits_for(arm, jev, budget_usd, jev_budget_usd)):
        for case in cases:
            row: dict[str, Any] = {"case_id": case.case_id, "pack": case.expected_detail, "arm": arm, "jev": jev}
            try:
                st = flow.run_one(str(case.path), f"x122-{case.case_id}", arm, tracker=False, doc_type=case.expected_detail, jev=jev)
            except Exception as exc:  # noqa: BLE001 - a failed case is a row of the measurement, not its end
                row.update(error=f"{type(exc).__name__}: {exc}")
            else:
                record = st.invoice.model_dump(mode="json") if st.invoice is not None else None
                row.update(run_id=st.run_id, values=record, needs_review=st.needs_review,
                           review_reasons=list(st.review_reasons), final_status=st.final_status)
            rows.append(row)
            with (out_dir / "rows.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            print(f"[{len(rows)}/{len(cases)}] {case.case_id} {case.expected_detail} {arm}: "
                  f"{row.get('final_status') or row.get('error')} review={row.get('needs_review')}")
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cases", type=Path)
    ap.add_argument("--arm", choices=("S", "G"), required=True)
    ap.add_argument("--no-jev", action="store_true", help="the G path verified by the code alone")
    ap.add_argument("--budget-usd", required=True, help="hard budget: OpenAI on the G path, JEV on the S path")
    ap.add_argument("--jev-budget-usd", help="the G path's JEV budget when it verifies with JEV")
    ap.add_argument("--only-detail", help="only the cases with this expected type pack")
    ap.add_argument("--store", type=Path, help="a separate measurement store (results, to-dos and call log stay out of the work store)")
    ap.add_argument("--live", action="store_true", help="paid run (needs a clean working tree)")
    args = ap.parse_args(argv)
    if args.arm == "S" and args.no_jev:
        print("the S path needs JEV")
        return 2
    if not args.live:
        print("dry run: add --live for the paid run")
        return 0
    from jav.devstate import git_state

    git = git_state()
    if git is None or git.dirty:
        print("a live run needs a clean working tree (CLAUDE.md §4)")
        return 2
    import contextlib

    from jav import store

    out = RUNS / f"{datetime.now():%Y%m%d_%H%M%S}_extract_cases_{args.arm}{'_nojev' if args.no_jev else ''}"
    with store.use_store(args.store) if args.store else contextlib.nullcontext():
        rows = run(args.cases, arm=args.arm, jev=not args.no_jev, budget_usd=Decimal(args.budget_usd), out_dir=out,
                   jev_budget_usd=Decimal(args.jev_budget_usd) if args.jev_budget_usd else None, only_detail=args.only_detail)
    (out / "accounting.json").write_text(json.dumps({"experiment": "122 extract_cases", "commit": git.head, "arm": args.arm,
                                                     "jev": not args.no_jev, "budget_usd": args.budget_usd,
                                                     "rows": len(rows)}, indent=1), encoding="utf-8")
    print(f"output: {out}")
    from jav.eval_report import report_budget_skips

    # 123: exit code 3 = the budget left cases without a result
    return 3 if report_budget_skips(rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
