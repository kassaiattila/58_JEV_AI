"""Burr replay of the approved real sample and a new measurement of JEV capabilities on it."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from decimal import Decimal
from pathlib import Path

from jav import store
from jav.adapters.jev import CacheOnlyAdapter, JevAdapter  # noqa: F401 (CacheOnlyAdapter: re-export for older drivers)
from jav.config import PROJECT_ROOT
from jav.models import LineLayout
from jav.experiments.stack_trial import DirectAdapter, TypedAdapter, run_trial
from jav.experiments.run_stack_trial import score_result
from jav.grounded_claims import protected_boundaries, GroundedClaim, verify_claim
from jav.experiments.jev_patterns import stitch_and_classify
from jav.source_find import find_source, SearchPolicy

DATA = PROJECT_ROOT/"runs/20260921_stack_trial"
PRIOR = DATA/"measurement_122920"
OUT = PROJECT_ROOT/"runs/20260921_real_grounded"


def reserve_call(path: Path, *, already_used: int, maximum: int) -> int:
    """Durable reservation BEFORE the call; it is not released on error or interruption either."""
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS reservations (id INTEGER PRIMARY KEY)")
        db.execute("BEGIN IMMEDIATE")
        used = db.execute("SELECT count(*) FROM reservations").fetchone()[0]
        if already_used+used >= maximum:
            raise RuntimeError("approved adapter call budget exhausted")
        db.execute("INSERT INTO reservations DEFAULT VALUES")
    return already_used+used+1


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")


def prior_usage():
    with sqlite3.connect(PRIOR/"business.sqlite") as db:
        count,cost = db.execute("SELECT count(*),sum(cost_usd) FROM ledger WHERE cached=0").fetchone()
    return count,round(cost,6)


def code_hashes():
    return {str(p.relative_to(PROJECT_ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ("jav","configs") for p in sorted((PROJECT_ROOT/folder).rglob("*"))
            if p.suffix in (".py",".json")}


# CacheOnlyAdapter: in jav/adapters/jev.py since 2026-09-27 (040, K0); imported above, the same class.


class BoundedAdapter(JevAdapter):
    def _live(self,*args,**kwargs):
        count,cost = prior_usage()
        with store.connect() as db:
            extra = db.execute("SELECT coalesce(sum(cost_usd),0) FROM ledger WHERE cached=0").fetchone()[0]
        if cost+extra >= 1:
            raise RuntimeError("approved recorded cost budget exhausted")
        reserve_call(OUT/"budget.sqlite",already_used=count,maximum=200)
        return super()._live(*args,**kwargs)


def partition_layout(rows: list[LineLayout]) -> list[list[LineLayout]]:
    """Page by page, within the existing trial's limit of 80 lines / 16000 characters; no line is split."""
    chunks = []
    current = []
    size = 0
    for row in rows:
        if len(row.text) > 16000:
            raise ValueError("one source line exceeds structure budget")
        if current and (row.page != current[-1].page or len(current) == 80 or size+len(row.text)>16000):
            chunks.append(current)
            current,size = [],0
        current.append(row)
        size += len(row.text)
    if current:
        chunks.append(current)
    return chunks


def prepare():
    if (OUT/"manifest.json").exists():
        raise RuntimeError("prepared evidence exists; inspect it rather than overwrite")
    OUT.mkdir(parents=True,exist_ok=True)
    sample,labels = read(DATA/"sample.json"),read(DATA/"labels.json")
    for case in sample["cases"]:
        if hashlib.sha256(Path(case["path"]).read_bytes()).hexdigest() != case["sha256"]:
            raise RuntimeError("source changed: "+case["case_id"])
    base = CacheOnlyAdapter(cache_dir=PRIOR/"cache",model="jev-1.13.0")
    rows,inputs = [],[]
    for case in sample["cases"]:
        label = labels["cases"][case["case_id"]]
        for flow in (["detect","invoice"] if "invoice" in label else ["detect"]):
            for arm in (["sdk","pydantic"] if flow=="invoice" else ["sdk"]):
                adapter = (DirectAdapter if arm=="sdk" else TypedAdapter)(base)
                run_id = f"{case['case_id']}-{flow}-{arm}"
                started = time.perf_counter()
                with base.no_cache_write():
                    state = run_trial(flow,case["path"],OUT,run_id,adapter,doc_type=label["doc_type"] or "invoice_hu")
                write(OUT/(run_id+".json"),state.model_dump(mode="json"))
                result = score_result(flow,state,label)
                rows.append(dict(case_id=case["case_id"],flow=flow,arm=arm,run_id=run_id,
                                 seconds=time.perf_counter()-started,score=result))
                if flow=="invoice" and arm=="sdk":
                    chunks = partition_layout(state.layout)
                    inputs.append(dict(case_id=case["case_id"],text=state.text,layout=[r.model_dump() for r in state.layout],
                                       invoice=state.invoice.model_dump(mode="json"),doc_type=state.doc_type,
                                       source_sha256=case["sha256"],structure_chunks=len(chunks)))
                print("baseline",run_id,state.final_status,flush=True)
    write(OUT/"baseline.json",rows)
    write(OUT/"frozen_inputs.json",inputs)
    write(OUT/"frozen_labels.json",labels)
    old_used,old_cost = prior_usage()
    maximum_calls = sum(2*c["structure_chunks"]+4 for c in inputs)
    if old_used+maximum_calls > 200:
        raise RuntimeError("planned new measurement would exceed approved call budget")
    configs = {name:read(PROJECT_ROOT/f"configs/experiments/{name}.json")
               for name in ("jev_patterns","grounded_structure","source_find")}
    write(OUT/"manifest.json",dict(prior_calls=old_used,prior_cost_usd=old_cost,max_new_calls=maximum_calls,
         approved_total_calls=200,approved_total_cost_usd=1,model="jev-1.13.0",configs=configs,
         hashes=code_hashes(),sample_hash=hashlib.sha256((DATA/"sample.json").read_bytes()).hexdigest(),
         inputs_hash=hashlib.sha256((OUT/"frozen_inputs.json").read_bytes()).hexdigest(),
         labels_hash=hashlib.sha256((OUT/"frozen_labels.json").read_bytes()).hexdigest(),
         scope="same authorized twenty PDFs; cached existing Burr flows, six invoice live postprocessors; no generator"))
    print("prepared",len(rows),"Burr runs; new call upper bound",maximum_calls,flush=True)


def evaluate_case(case, labels, configs, ask, *, query="What is the document's gross total including VAT, not the net amount or the outstanding balance?"):
    """Shared bounded structure/search/claim evaluation, no storage or network ownership."""
    blocks,parts = [],[]
    layout = [LineLayout.model_validate(r) for r in case["layout"]]
    for part,chunk in enumerate(partition_layout(layout)):
        guards = protected_boundaries(chunk,configs["grounded_structure"]["boundaries"])
        grouped = stitch_and_classify([r.text for r in chunk],configs["jev_patterns"]["structure"],ask,blocked_before=guards)
        for block in grouped["blocks"]:
            block["document_lines"] = [chunk[i].no for i in block["source_lines"]]
            block["page"] = chunk[0].page
            block["part"] = part
            blocks.append(block)
        parts.append(dict(page=chunk[0].page,lines=[r.no for r in chunk],boundaries=guards))
    found = find_source(case["text"],query,ask,
                        SearchPolicy(**configs["source_find"]["policy"]),prompts=configs["source_find"])
    claims = []
    value = case["invoice"].get("gross_total")
    if found.status=="candidate" and value is not None:
        evidence = found.candidates[0]
        for variant,amount in (("actual",Decimal(value)),("altered_plus_one",Decimal(value)+1)):
            claim = GroundedClaim(statement=f"The document's gross total including VAT is {amount} {case['invoice'].get('currency')}. This is the gross total, not the net total or an outstanding balance.",
                source_sha256=found.source_sha256,start=evidence.start,end=evidence.end,quote=evidence.quote)
            checked = verify_claim(case["text"],claim,configs["grounded_structure"]["claims"],ask)
            claims.append(dict(variant=variant,result=checked))
    def normal(text):
        return re.sub(r"\s+"," ",unicodedata.normalize("NFC",text).casefold()).strip()
    items = [b for b in blocks if b["kind"]=="item"]
    cover = [any(normal(g["description"]) in normal(b["text"]) for b in items)
             for g in labels[case["case_id"]]["line_items"]]
    result = dict(case_id=case["case_id"],parts=parts,blocks=blocks,source_search=found.model_dump(mode="json"),
                  claims=claims,item_blocks=len(items),gold_description_literal_coverage=cover,
                  expected_items=len(cover),structured_item_values_extracted=False,
                  proposed_status="needs_review",reason="line_item_values_and_completeness_not_validated")
    return result


def live(*,replay=False):
    manifest = read(OUT/"manifest.json")
    if manifest["hashes"] != code_hashes():
        raise RuntimeError("code/config changed since preparation")
    for name,key in (("frozen_inputs.json","inputs_hash"),("frozen_labels.json","labels_hash")):
        if hashlib.sha256((OUT/name).read_bytes()).hexdigest() != manifest[key]:
            raise RuntimeError("frozen evidence changed")
    # The sample and every original file must still be unchanged right before the network call.
    if hashlib.sha256((DATA/"sample.json").read_bytes()).hexdigest() != manifest["sample_hash"]:
        raise RuntimeError("approved sample changed")
    for case in read(DATA/"sample.json")["cases"]:
        if hashlib.sha256(Path(case["path"]).read_bytes()).hexdigest() != case["sha256"]:
            raise RuntimeError("source changed")
    mode = "replay" if replay else "live"
    destination = OUT/(mode+"_results.json")
    if destination.exists():
        raise RuntimeError("measurement already exists; do not overwrite")
    adapter = (CacheOnlyAdapter if replay else BoundedAdapter)(cache_dir=OUT/"cache",model=manifest["model"])
    configs = manifest["configs"]
    results = []
    inputs = read(OUT/"frozen_inputs.json")
    labels = read(OUT/"frozen_labels.json")["cases"]
    config_hash = hashlib.sha256(json.dumps(manifest["hashes"],sort_keys=True).encode()).hexdigest()
    with store.use_store(OUT/"business.sqlite"):
        for case in inputs:
            calls = []
            run_id = case["case_id"]+"-grounded-"+mode
            def ask(step,state,questions):
                answer = adapter.ask(step,state,questions,run_id=run_id,config_hash=config_hash,use_cache=replay)
                calls.append(dict(step=step,state=state,questions={k:q.model_dump(mode="json") for k,q in questions.items()},
                                  response=answer.response.model_dump(mode="json"),call=answer.call.model_dump(mode="json")))
                return answer.response
            result = evaluate_case(case, labels, configs, ask)
            result["calls"] = calls
            blocks = result["blocks"]
            items = [b for b in blocks if b["kind"] == "item"]
            cover = result["gold_description_literal_coverage"]
            claims = result["claims"]
            results.append(result)
            write(OUT/(run_id+".json"),result)
            print(mode,case["case_id"],"blocks",len(blocks),"item_blocks",len(items),"literal_coverage",sum(cover),"/",len(cover),
                  "claims",[(c["variant"],c["result"]["status"]) for c in claims],flush=True)
        write(destination,results)
        all_ledger = []
        for case in inputs:
            all_ledger.extend(store.ledger_for_run(case["case_id"]+"-grounded-"+mode))
        write(OUT/(mode+"_ledger.json"),all_ledger)
        print(mode,"calls",len(all_ledger),"cost",round(sum(r["cost_usd"] for r in all_ledger),6))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare",action="store_true")
    group.add_argument("--live",action="store_true")
    group.add_argument("--replay",action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare()
    else:
        live(replay=args.replay)


if __name__ == "__main__":
    main()
