"""Paired real-data revision, with a separately authorized, durable round budget."""
from __future__ import annotations

import argparse
import copy
import hashlib
from contextlib import nullcontext
from pathlib import Path

from jav import store
from jav.adapters.jev import JevAdapter
from jav.config import PROJECT_ROOT
from jav.experiments.real_grounded_trial import (
    DATA, OUT as PRIOR, CacheOnlyAdapter, code_hashes, evaluate_case, read, reserve_call, write,
)

OUT = PROJECT_ROOT / "runs/20260921_grounded_revision"
CONFIG = PROJECT_ROOT / "configs/experiments/grounded_revision.json"


class RoundAdapter(JevAdapter):
    def __init__(self, *, directory, limits, **kwargs):
        super().__init__(**kwargs)
        self.directory, self.limits = directory, limits

    def _live(self, *args, **kwargs):
        with store.connect() as db:
            cost = db.execute("SELECT coalesce(sum(cost_usd),0) FROM ledger WHERE cached=0").fetchone()[0]
        if cost >= self.limits["round_recorded_cost_limit_usd"]:
            raise RuntimeError("round recorded-cost stop threshold reached")
        reserve_call(self.directory / "budget.sqlite", already_used=0,
                     maximum=self.limits["round_adapter_call_limit"])
        return super()._live(*args, **kwargs)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare():
    if (OUT / "manifest.json").exists():
        raise RuntimeError("frozen round already exists")
    OUT.mkdir(parents=True, exist_ok=True)
    config = read(CONFIG)
    original = read(PRIOR / "manifest.json")["configs"]
    revised = copy.deepcopy(original)
    revised["grounded_structure"]["boundaries"].update(config["boundary_overrides"])
    revised["source_find"]["policy"].update(config["source_policy_overrides"])
    revised["source_find"].update(config["source_prompt_overrides"])
    for name in ("frozen_inputs.json", "frozen_labels.json"):
        (OUT / name).write_bytes((PRIOR / name).read_bytes())
    inputs = read(OUT / "frozen_inputs.json")
    maximum = sum(2 * c["structure_chunks"] + 4 for c in inputs) * 2 * config["repeats"]
    if maximum > config["round_adapter_call_limit"]:
        raise RuntimeError("planned call bound exceeds round limit")
    write(OUT / "manifest.json", dict(
        config=config, arms={"baseline":original, "revised":revised}, hashes=code_hashes(),
        sample_hash=digest(DATA / "sample.json"),
        frozen_hashes={name:digest(OUT / name) for name in ("frozen_inputs.json", "frozen_labels.json")},
        planned_call_bound=maximum, prior_calls=196, prior_recorded_usd=.053328,
        authorization="User approved additional real-document testing budget on 2026-09-21; "
                      "agent limits this new round to 200 adapter calls / 1 USD recorded stop threshold; "
                      "same approved twenty-document sample and api.typesafe.ai only.",
        evaluation="Six previously exposed labeled invoices; paired two live repetitions; not a held-out accuracy claim.",
    ))
    print("prepared; maximum new adapter calls", maximum)


def run(*, replay=False):
    manifest = read(OUT / "manifest.json")
    if manifest["hashes"] != code_hashes():
        raise RuntimeError("code/config changed after freeze")
    if manifest["sample_hash"] != digest(DATA / "sample.json"):
        raise RuntimeError("authorized sample changed")
    for name, expected in manifest["frozen_hashes"].items():
        if digest(OUT / name) != expected:
            raise RuntimeError("frozen evidence changed")
    for case in read(DATA / "sample.json")["cases"]:
        if digest(Path(case["path"])) != case["sha256"]:
            raise RuntimeError("source document changed")
    mode = "replay" if replay else "live"
    # Claim exclusive ownership before any request; a crashed round is investigated, never silently rerun.
    with (OUT / (mode + ".started")).open("x", encoding="utf-8") as f:
        f.write(mode)
    settings = manifest["config"]
    adapter = (CacheOnlyAdapter(cache_dir=OUT / "cache", model=settings["model"]) if replay else
               RoundAdapter(directory=OUT, limits=settings, cache_dir=OUT / "cache", model=settings["model"]))
    inputs = read(OUT / "frozen_inputs.json")
    labels = read(OUT / "frozen_labels.json")["cases"]
    rows = []
    config_hash = digest(OUT / "manifest.json")
    with store.use_store(OUT / "business.sqlite"):
        for repeat in range(1 if replay else settings["repeats"]):
            for case in inputs:
                for arm, configs in manifest["arms"].items():
                    run_id = f"{mode}-{repeat}-{case['case_id']}-{arm}"
                    calls = []
                    def ask(step, state, questions):
                        answer = adapter.ask(step, state, questions, run_id=run_id, config_hash=config_hash, use_cache=replay)
                        calls.append(dict(step=step, state=state,
                                          questions={k:q.model_dump(mode="json") for k,q in questions.items()},
                                          response=answer.response.model_dump(mode="json"),
                                          call=answer.call.model_dump(mode="json")))
                        return answer.response
                    with adapter.no_cache_write() if replay or repeat else nullcontext():
                        result = evaluate_case(case, labels, configs, ask, query=settings["query"])
                    result.update(arm=arm, repeat=repeat, calls=calls, run_id=run_id)
                    write(OUT / (run_id + ".json"), result)
                    rows.append(result)
                    print(run_id, "source",result["source_search"]["status"], "items",result["item_blocks"],
                          "claims", [c["result"]["status"] for c in result["claims"]], flush=True)
        write(OUT / (mode + "_results.json"), rows)
        ledger = [entry for row in rows for entry in store.ledger_for_run(row["run_id"])]
        write(OUT / (mode + "_ledger.json"), ledger)
        print(mode, "calls",len(ledger),"cost",round(sum(r["cost_usd"] for r in ledger),6),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "live", "replay"))
    args = parser.parse_args()
    prepare() if args.mode == "prepare" else run(replay=args.mode == "replay")


if __name__ == "__main__":
    main()
