"""Párosított szerkezetpróba és forrásállítás-ellenőrzés, mesterséges szövegeken."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from jav import store
from jav.adapters.jev import JevAdapter
from jav.config import PROJECT_ROOT
from jav.models import LineLayout, CellLayout
from jav.source_find import find_source, SearchPolicy, PROMPTS
from jav.experiments.jev_patterns import stitch_and_classify
from jav.grounded_claims import protected_boundaries, GroundedClaim, verify_claim


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--repeat",type=int,default=2)
    args = parser.parse_args()
    if not args.live or not 1 <= args.repeat <= 2:
        parser.error("--live and --repeat 1..2 required; synthetic input only")
    root = PROJECT_ROOT
    files = [Path(__file__), root/"jav/experiments/grounded_structure.py", root/"jav/experiments/jev_patterns.py",
             root/"jav/source_find.py", PROMPTS, root/"configs/experiments/grounded_structure.json",
             root/"configs/experiments/jev_patterns.json"]
    config = json.loads(files[-2].read_text(encoding="utf-8"))
    old = json.loads(files[-1].read_text(encoding="utf-8"))["structure"]
    search = json.loads(PROMPTS.read_text(encoding="utf-8"))
    hashes = {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    fingerprint = hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")+"_grounded_structure"
    out = root/"runs"/run_id
    out.mkdir(parents=True)
    (out/"manifest.json").write_text(json.dumps(dict(run_id=run_id,config=config,original_structure=old,
        search=search,files=hashes,repeats=args.repeat,max_calls=160,cost_stop_usd=.1,
        evidence="Synthetic development/regression only, no production pipeline activation"),ensure_ascii=False,indent=2),encoding="utf-8")
    adapter = JevAdapter(cache_dir=out/"cache",model="jev-1.13.0")
    rows = []
    with store.use_store(out/"store.sqlite"), adapter.no_cache_write():
        calls = []
        def ask(step,state,questions):
            ledger = store.ledger_for_run(run_id)
            if len(ledger)>=160 or sum(r["cost_usd"] or 0 for r in ledger)>=.1:
                raise RuntimeError("probe budget exhausted")
            response = adapter.ask(step,state,questions,run_id=run_id,use_cache=False,config_hash=fingerprint)
            calls.append(dict(step=step,state=state,questions={k:v.model_dump(mode="json") for k,v in questions.items()},
                              response=response.response.model_dump(mode="json"),call=response.call.model_dump(mode="json")))
            return response.response
        def save(row):
            row["calls"] = list(calls)
            rows.append(row)
            with (out/"results.jsonl").open("a",encoding="utf-8") as stream:
                stream.write(json.dumps(row,ensure_ascii=False)+"\n")
            print(row["kind"],row["case_id"],row["arm"],row["repeat"],row["correct"],flush=True)
        for domain,settings in (("invoice",old),("notes",{**old,**config["notes"]})):
            for case in settings["cases"]:
                layout = [LineLayout(no=i+1,page=case.get("pages",[1]*len(case["lines"]))[i],text=line,
                            cells=[CellLayout(text=s.strip(),x0=j*100,x1=j*100+90) for j,s in enumerate(line.split("|"))])
                          for i,line in enumerate(case["lines"])]
                guards = protected_boundaries(layout,config["boundaries"])
                for repeat in range(args.repeat):
                    # Az elsőbbségi sorrend váltakozik, hogy ne mindig azonos kar fusson előbb.
                    for arm in (("baseline","protected") if repeat%2==0 else ("protected","baseline")):
                        calls.clear()
                        result = stitch_and_classify(case["lines"],settings,ask,blocked_before=guards if arm=="protected" else None)
                        grouping = [b["source_lines"] for b in result["blocks"]] == case["groups"]
                        kinds = case["kinds"] is None or [b["kind"] for b in result["blocks"]] == case["kinds"]
                        save(dict(kind="structure",domain=domain,case_id=case["id"],repeat=repeat,arm=arm,
                                  result=result,correct=grouping and kinds,groups_correct=grouping,kinds_correct=kinds))
        for case in config["claims"]["cases"]:
            for repeat in range(args.repeat):
                calls.clear()
                text = case["text"]
                search_result = None
                if "query" in case:
                    search_result = find_source(text,case["query"],ask,SearchPolicy(**search["policy"]),prompts=search)
                    if search_result.status != "candidate":
                        result = dict(status="no_source_candidate",search=search_result.model_dump())
                        save(dict(kind="claim",case_id=case["id"],repeat=repeat,arm="source_verify",result=result,correct=False))
                        continue
                    evidence = search_result.candidates[0]
                    start,end,quote = evidence.start,evidence.end,evidence.quote
                else:
                    quote = case["quote"]
                    start = max(0,text.find(quote))
                    end = start+len(quote)
                claim = GroundedClaim(statement=case["statement"],source_sha256=hashlib.sha256(text.encode()).hexdigest(),
                                      start=start,end=end,quote=quote)
                result = verify_claim(text,claim,config["claims"],ask)
                save(dict(kind="claim",case_id=case["id"],repeat=repeat,arm="source_verify",result=result,
                          search=search_result.model_dump() if search_result else None,correct=result["status"]==case["expected"]))
        ledger = store.ledger_for_run(run_id)
        summary = dict(run_id=run_id,models=sorted({r["model"] for r in ledger}),calls=len(ledger),
                       cost_usd=round(sum(r["cost_usd"] or 0 for r in ledger),6),errors=sum(bool(r["error"]) for r in ledger))
        for kind,arm in (("structure","baseline"),("structure","protected"),("claim","source_verify")):
            selected = [r for r in rows if r["kind"]==kind and r["arm"]==arm]
            first = [r for r in selected if r["repeat"]==0]
            summary[f"{kind}_{arm}"] = dict(first_correct=sum(r["correct"] for r in first),first_total=len(first),
                                            all_correct=sum(r["correct"] for r in selected),all_total=len(selected))
        (out/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
        (out/"ledger.json").write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2))
    print(out)


if __name__ == "__main__":
    main()
