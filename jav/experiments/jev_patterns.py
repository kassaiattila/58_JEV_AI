"""Elkülönített JEV-mintapróbák; saját tesztadat, nincs üzemi route-módosítás."""
from __future__ import annotations

import re
from typing import Callable
from typesafe_sdk import Choice, Noul, Score, SystemOneResponse

Ask = Callable[[str, object, dict], SystemOneResponse]


def stitch_and_classify(lines: list[str], config: dict, ask: Ask, *,
                        blocked_before: dict[int, list[str]] | None = None) -> dict:
    """Szomszédos sorok kérdése -> forrásból másolt blokkok -> blokkfajta.

    A cookbook írásjel-függő sávja kísérleti adat, nem üzemi policy.
    Üres soron nincs kérdés és nincs összefűzés; minden blokk hordozza a sorait.
    """
    if len(lines) > 80 or sum(map(len, lines)) > 16000:
        raise ValueError("A kis próba legfeljebb 80 sort / 16000 karaktert kezel")
    blocked_before = blocked_before or {}
    if any(not isinstance(i, int) or i < 1 or i >= len(lines) for i in blocked_before):
        raise ValueError("A védett határ két létező sor között legyen")
    questions = {}
    for i in range(1, len(lines)):
        if i not in blocked_before and lines[i].strip() and lines[i-1].strip():
            questions[f"L{i:03d}"] = Noul(
                instructions=config["join_question"].format(current=f"L{i:03d}", previous=f"L{i-1:03d}"),
                criteria=config["join_criteria"],
            )
    state = "\n".join(f"L{i:03d}: {text}" for i, text in enumerate(lines))
    response = ask("stitch", state, questions) if questions else None
    joins = {key: value.noul for key, value in response.nouls.items()} if response else {}
    blocks = []
    for i, text in enumerate(lines):
        if not text.strip():
            continue
        terminal = bool(i and re.search(r'[.!?:;…]["\x27)\]]*$', lines[i-1].rstrip()))
        threshold = config["join_after_terminal" if terminal else "join_after_dangling"]
        key = f"L{i:03d}"
        if blocks and i not in blocked_before and key in joins and joins[key] >= threshold:
            blocks[-1]["text"] += " " + text
            blocks[-1]["source_lines"].append(i)
        else:
            blocks.append({"text": text, "source_lines": [i]})
    if blocks:
        qs = {f"B{i:03d}": Choice(instructions=config["block_question"].format(block=f"B{i:03d}"),
                                  criteria=config["block_types"]) for i in range(len(blocks))}
        classified = ask("block_type", "\n".join(f"B{i:03d}: {b['text']}" for i, b in enumerate(blocks)), qs)
        for i, block in enumerate(blocks):
            block["kind"] = classified.choices[f"B{i:03d}"].choice
    return {"blocks": blocks, "joins": joins, "blocked_before": blocked_before}


def assess_pair(invoice: dict, payment: dict, config: dict, ask: Ask) -> dict:
    """Egy teljes összegű, egy-számla/egy-utalás jelöltpár szintetikus próbája.

    Részfizetés, gyűjtőutalás, díjlevonás nem ennek a kísérletnek a tárgya.
    """
    from decimal import Decimal, InvalidOperation
    try:
        left, right = Decimal(invoice["amount"]), Decimal(payment["amount"])
        amount_equal = left == right if left.is_finite() and right.is_finite() else None
    except (KeyError, InvalidOperation, TypeError):
        amount_equal = None
    currency_equal = (invoice["currency"].upper() == payment["currency"].upper()
                      if invoice.get("currency") and payment.get("currency") else None)
    reference_equal = (invoice["reference"] == payment["reference"]
                       if invoice.get("reference") and payment.get("reference") else None)
    facts = dict(amount_equal=amount_equal, currency_equal=currency_equal, reference_equal=reference_equal)
    if any(value is False for value in facts.values()):
        return {"outcome": "different", "code_facts": facts, "decided_by": "code"}
    if amount_equal is None or currency_equal is None:
        return {"outcome": "uncertain", "code_facts": facts, "decided_by": "code"}
    questions = {"match": Score(instructions=config["question"], criteria=config["levels"]),
                 "same_party": Noul(instructions=config["party_question"])}
    response = ask("pair_score", {"invoice": invoice, "payment": payment, "code_facts": facts}, questions)
    answer = response.scores["match"]
    return {"outcome": ("different", "uncertain", "same")[min(int(answer.score + .5), 2)],
            "score": answer.score, "probabilities": answer.probabilities,
            "same_party_p": response.nouls["same_party"].noul, "code_facts": facts, "decided_by": "jev"}


def classify_hierarchy(text: str, config: dict, ask: Ask) -> dict:
    """Kétszintű próba: K család megtartása, a következő kérdések egy kötegben.

    A geometriai átlag rangsorolási jel, nem kalibrált dokumentum-helyesség.
    Az ismeretlen opciót a nyertes kiválasztásakor sem dobjuk el.
    """
    tree = config["tree"]
    criteria = {key: {"description": node["description"], "children": node["children"]}
                for key, node in tree.items()}
    criteria["other"] = config["other"]
    root = ask("hierarchy_root", text, {"root": Choice(instructions=config["question"], criteria=criteria)})
    probabilities = root.choices["root"].probabilities
    selected = sorted(tree, key=lambda key: (-probabilities[key], key))[:config["beam_width"]]
    qs = {key: Choice(instructions={"question":config["question"], "parent":tree[key]["description"]},
                       criteria={**tree[key]["children"], "other":config["other"]}) for key in selected}
    children = ask("hierarchy_children", text, qs)
    ranking = [{"path":["other"], "score":probabilities["other"]}]
    for parent in selected:
        for child, p in children.choices[parent].probabilities.items():
            ranking.append({"path":[parent, child], "score":(probabilities[parent]*p)**.5})
    ranking.sort(key=lambda row: (-row["score"], row["path"]))
    best = ranking[0]
    separation = best["score"]/ranking[1]["score"] if ranking[1]["score"] else None
    return {"label":best["path"][-1], "path":best["path"], "ranking":ranking, "separation":separation}


def main() -> None:
    import argparse
    import hashlib
    import json
    from contextlib import nullcontext
    from datetime import datetime
    from pathlib import Path
    from jav import cfg, store
    from jav.adapters.jev import JevAdapter
    from jav.config import PROJECT_ROOT

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    if not args.live or not 1 <= args.repeat <= 5:
        parser.error("--live és 1..5 közötti --repeat szükséges")
    config_path = PROJECT_ROOT / "configs/experiments/jev_patterns.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config_hash = hashlib.sha256(config_path.read_bytes() + Path(__file__).read_bytes() +
                                 cfg.config_hash("models").encode()).hexdigest()[:16]
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_jev_patterns_probe"
    out = PROJECT_ROOT / "runs" / run_id
    out.mkdir(parents=True)
    adapter = JevAdapter(cache_dir=out / "cache")
    adapter.model = adapter.resolve_model(adapter.model, run_id=run_id)
    manifest = {"run_id":run_id, "model":adapter.model, "config_hash":config_hash, "config":config,
                "source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "repeats":args.repeat,
                "evidence":"Synthetic capability probe; no domain deployment or held-out evaluation"}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = []
    for pattern in ("structure", "pair", "hierarchy"):
        settings = config[pattern]
        for case in settings["cases"]:
            for repeat in range(args.repeat):
                calls = []
                def ask(step, state, questions):
                    result = adapter.ask(f"{pattern}.{step}", state, questions, run_id=run_id,
                                         config_hash=config_hash, use_cache=False)
                    calls.append({"step":step, "state":state,
                                  "questions":{k:q.model_dump(mode="json") for k,q in questions.items()},
                                  "response":result.response.model_dump(mode="json"),
                                  "call":result.call.model_dump(mode="json")})
                    return result.response
                with adapter.no_cache_write() if repeat else nullcontext():
                    if pattern == "structure":
                        result = stitch_and_classify(case["lines"], settings, ask)
                        correct = {"groups":[b["source_lines"] for b in result["blocks"]] == case["groups"],
                                   "kinds":[b["kind"] for b in result["blocks"]] == case["kinds"]}
                    elif pattern == "pair":
                        result = assess_pair(case["invoice"], case["payment"], settings, ask)
                        correct = {"outcome":result["outcome"] == case["expected"]}
                    else:
                        result = classify_hierarchy(case["text"], settings, ask)
                        correct = {"label":result["label"] == case["expected"]}
                row = {"pattern":pattern, "case_id":case["id"], "repeat":repeat,
                       "result":result, "correct":correct, "calls":calls}
                rows.append(row)
                with (out / "results.jsonl").open("a",encoding="utf-8") as f:
                    f.write(json.dumps(row,ensure_ascii=False)+"\n")
            print(pattern, case["id"], correct, flush=True)
    summary = {"run_id":run_id, "model":adapter.model}
    for pattern in ("structure", "pair", "hierarchy"):
        first = [r for r in rows if r["pattern"]==pattern and r["repeat"]==0]
        def decision(r):
            if pattern=="structure": return [(b["source_lines"],b["kind"]) for b in r["result"]["blocks"]]
            return r["result"]["outcome" if pattern=="pair" else "label"]
        flips=sum(decision(r)!=decision(ref) for ref in first for r in rows
                  if r["pattern"]==pattern and r["case_id"]==ref["case_id"] and r["repeat"]>0)
        summary[pattern]={"first_correct_cases":sum(all(r["correct"].values()) for r in first),
                          "first_total_cases":len(first), "changed_case_repeats":flips,
                          "first_model_calls":sum(len(r["calls"]) for r in first)}
    ledger=store.ledger_for_run(run_id)
    summary.update(cost_usd=round(sum(r["cost_usd"] or 0 for r in ledger),6), ledger_calls=len(ledger))
    (out / "ledger.json").write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print(out)


if __name__ == "__main__":
    main()
