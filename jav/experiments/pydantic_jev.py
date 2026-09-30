"""Kis Pydantic AI–JEV próba a meglévő adapterrel, változatlan üzemi flow-k mellett.

A Pydantic AI saját TypeSafeModel-je végzi a kérdésfordítást és a válasz tipizálását.
A Provider illesztése csak a hálózati határt köti a meglévő cache/ledger/retry adapterre.
Szándékosan szekvenciális kísérlet, nem általános aszinkron kliens.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, create_model
from pydantic_ai import Agent
from pydantic_ai.models.typesafe import TypeSafeModel
from pydantic_ai.profiles.typesafe import typesafe_model_profile
from pydantic_ai.providers import Provider
from pydantic_ai.usage import UsageLimits
from typesafe_sdk import Choice, Noul, Score

from jav.adapters.jev import JevAdapter, JevResult, Question


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)


def output_model(questions: dict[str, Question]) -> type[BaseModel]:
    """A kísérlet sík kérdéskészlete -> típusos séma, jelentés-leírásokkal.

    A Noul criteria a leírásba kerül, mert a natív fordító nem ad külön criteria-t.
    Ez szemantikailag összehasonlítható, de NEM byte-azonos kérdés; a próba ezt méri.
    """
    fields = {}
    for name, question in questions.items():
        description = _text(question.instructions)
        if isinstance(question, Noul):
            if question.criteria is not None:
                description = _text({"instructions": question.instructions,
                                     "criteria": question.model_dump(mode="json")["criteria"]})
            fields[name] = (float, Field(ge=0, le=1, description=description))
        else:
            criteria = question.criteria if isinstance(question, Choice) else dict(enumerate(question.criteria))
            options = tuple(Annotated[Literal[key], Field(description=_text(value))] for key, value in criteria.items())
            fields[name] = (Union[options], Field(description=description))
    return create_model("JevProbeOutput", **fields)


@dataclass
class TypedResult:
    output: dict[str, Any]
    details: dict[str, Any]
    model: str | None
    calls: list[JevResult]
    requests: list[dict[str, Any]]


@dataclass
class AdapterClient:
    adapter: JevAdapter
    run_id: str
    config_hash: str
    use_cache: bool
    request_id: str = "pydantic_jev_probe"
    calls: list[JevResult] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)

    async def system_one(self, state, questions, *, model, **kwargs):
        # A beállítások csendes elvesztése helyett egyértelműen elutasítjuk őket.
        if any(value is not None for value in kwargs.values()):
            raise ValueError("A próba időkorlátját és retry-ját a projekt adaptere kezeli; extra beállítás nem támogatott")
        if self.requests:
            raise ValueError("Ez a próba egyetlen kötegelt kérést enged futásonként")
        self.requests.append({"state": state, "questions": questions})
        result = self.adapter.ask(self.request_id, state, questions, model=model,
                                  run_id=self.run_id, config_hash=self.config_hash, use_cache=self.use_cache)
        self.calls.append(result)
        return result.response


class AdapterProvider(Provider[AdapterClient]):
    def __init__(self, client: AdapterClient):
        self._adapter_client = client

    @property
    def name(self) -> str:
        return "typesafe"

    @property
    def base_url(self) -> str:
        return "https://api.typesafe.ai"

    @property
    def client(self) -> AdapterClient:
        return self._adapter_client

    model_profile = staticmethod(typesafe_model_profile)


def run_typed(text: str, questions: dict[str, Question], *, adapter: JevAdapter,
              run_id: str, config_hash: str, use_cache: bool = True,
              request_id: str = "pydantic_jev_probe") -> TypedResult:
    client = AdapterClient(adapter, run_id, config_hash, use_cache, request_id=request_id)
    model = TypeSafeModel(adapter.model, provider=AdapterProvider(client))
    agent = Agent(model, output_type=output_model(questions), retries=0)
    result = agent.run_sync(text, usage_limits=UsageLimits(request_limit=1))
    return TypedResult(result.output.model_dump(mode="json"), result.response.provider_details or {},
                       result.response.model_name, client.calls, client.requests)


def main() -> None:
    """Reprodukálható kis élő próba; csak mesterséges szövegek, külön cache."""
    import argparse
    import hashlib
    import importlib.metadata
    from datetime import datetime
    from pathlib import Path
    from jav import cfg, store
    from jav.config import PROJECT_ROOT

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="A kis, fizetős JEV-próba indítása")
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    if not args.live or not 1 <= args.repeat <= 5:
        parser.error("--live és 1..5 közötti --repeat szükséges")
    config_path = PROJECT_ROOT / "configs/experiments/pydantic_jev.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    questions = {}
    for name, source in config["sources"].items():
        q = cfg.load(source)["questions"][name]
        cls = {"choice": Choice, "noul": Noul, "score": Score}[q["kind"]]
        questions[name] = cls(instructions=q["instructions"], criteria=q["criteria"])
    provenance = {
        "config": config, "source_hash": cfg.config_hash(*set(config["sources"].values()), "models"),
        "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "packages": {p: importlib.metadata.version(p) for p in ("pydantic-ai-slim", "typesafe-sdk")},
    }
    config_hash = hashlib.sha256(json.dumps(provenance, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_pydantic_jev_probe"
    out = PROJECT_ROOT / "runs" / run_id
    out.mkdir(parents=True)
    adapter = JevAdapter(cache_dir=out / "cache")
    concrete = adapter.resolve_model(adapter.model, run_id=run_id)
    adapter.model = concrete
    provenance.update(model=concrete, config_hash=config_hash, run_id=run_id, repeats=args.repeat,
                      evidence="synthetic capability probe, not a held-out domain evaluation")
    (out / "manifest.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = []

    def values(response):
        return {"language": response.choices["language"].choice,
                "requires_action": response.nouls["requires_action"].noul,
                "urgency": min(int(response.scores["urgency"].score + .5), 3)}

    def record(case, arm, repeat, result, output, details=None, seconds=None):
        observed = {**output, "requires_action": output["requires_action"] >= .5}
        row = {"case_id": case["id"], "arm": arm, "repeat": repeat, "output": output,
               "expected": case["expected"], "correct": {k: observed[k] == v for k, v in case["expected"].items()},
               "response": result.response.model_dump(mode="json"), "call": result.call.model_dump(mode="json"),
               "cached": result.cached, "cache_key": result.cache_key, "details": details,
               "wall_seconds": seconds}
        rows.append(row)
        with (out / "results.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    import time
    for case in config["cases"]:
        for repeat in range(args.repeat):
            # Minden mért ismétlés élő; csak az első hoz létre külön próba-cache-t.
            from contextlib import nullcontext
            with adapter.no_cache_write() if repeat else nullcontext():
                t0 = time.perf_counter()
                direct = adapter.ask("sdk_probe", case["text"], questions, run_id=run_id, config_hash=config_hash, use_cache=False)
                record(case, "sdk", repeat, direct, values(direct.response), seconds=time.perf_counter()-t0)
                t0 = time.perf_counter()
                typed = run_typed(case["text"], questions, adapter=adapter, run_id=run_id, config_hash=config_hash, use_cache=False)
                record(case, "pydantic", repeat, typed.calls[0], typed.output, typed.details, time.perf_counter()-t0)
            if repeat == 0:
                request = typed.requests[0]
                replay = adapter.ask("compiled_replay", request["state"], request["questions"], run_id=run_id, config_hash=config_hash)
                assert replay.cached and replay.cache_key == typed.calls[0].cache_key
                assert replay.response.model_dump(mode="json") == typed.calls[0].response.model_dump(mode="json")
                cached = run_typed(case["text"], questions, adapter=adapter, run_id=run_id, config_hash=config_hash)
                assert cached.calls[0].cached and cached.output == typed.output
                record(case, "pydantic_cache", 0, cached.calls[0], cached.output, cached.details)
                audit = {"sdk": {k: q.model_dump(mode="json") for k, q in questions.items()},
                         "pydantic": {k: q.model_dump(mode="json") for k, q in request["questions"].items()},
                         "same_state": request["state"] == case["text"]}
                (out / "request_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        print(case["id"], "done", flush=True)
    ledger = store.ledger_for_run(run_id)
    (out / "ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"run_id": run_id, "model": concrete, "cost_usd": round(sum(r["cost_usd"] or 0 for r in ledger), 6),
               "ledger_calls": len(ledger), "cached_calls": sum(bool(r["cached"]) for r in ledger)}
    for arm in ("sdk", "pydantic"):
        subset = [r for r in rows if r["arm"] == arm]
        first = [r for r in subset if r["repeat"] == 0]
        flips = sum(any(r["output"][k] != ref["output"][k] for k in ("language", "urgency")) or
                    ((r["output"]["requires_action"] >= .5) != (ref["output"]["requires_action"] >= .5))
                    for ref in first for r in subset if r["case_id"] == ref["case_id"] and r["repeat"] > 0)
        summary[arm] = {"first_correct": sum(sum(r["correct"].values()) for r in first), "first_total": len(first)*3,
                        "live_repeats": len(subset), "changed_case_repeats": flips,
                        "mean_input_tokens": sum(r["call"]["input_tokens"] or 0 for r in subset)/len(subset),
                        "mean_wall_seconds": sum(r["wall_seconds"] for r in subset)/len(subset)}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(out)


if __name__ == "__main__":
    main()
