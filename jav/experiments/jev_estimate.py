"""127: the free pre-estimate of a paid JEV measurement (the 069 method, kept as a tool this time).

The measurement's own commands run unchanged (the same flows, OCR texts, budgets and question texts), but JEV is a
stand-in: a question already in the request-hash cache gets its saved answer, a question that is not is never sent -
it is counted with its size and answered with a neutral stand-in (the first option, 0.5), so the flow goes on as if
answered. Nothing is written to the JEV cache; results, to-dos and the ledger go into a temporary store, the raw run
files into the output folder. No API key is needed for JEV; OpenAI and Azure are not called either (the measurements
run under a JEV-only budget, so no other provider can be called).

The cost of a live question is estimated from its request size: about 2.5 characters per token on average (expected)
and at most 0.6 tokens per character (upper bound, measured in the call log; `jav/runtime/calls.py`). The worst-case
reservation of the largest question is reported too: a hard budget has to leave at least that much room.

    python -m jav.experiments.jev_estimate golden:invoice_hu synthetic:invoice_foreign detect-golden email-golden
    python -m jav.experiments.jev_estimate detect-cases:runs/quality_122/cases.json extract-cases:runs/quality_127/sample.json

Steps: `golden:<type>` (S path on the legacy golden set), `synthetic:<type>` (S path on the synthetic cases),
`detect-golden`, `detect-cases:<case file>`, `email-golden`, `verifier-probe:<type>` (the G path's JEV check on the
golden extracts), `extract-cases:<case file>` (S path on a local case list, `jav.experiments.extract_cases`). Output: `runs/<timestamp>_jev_estimate/` (`estimate.json`, `estimate.md`,
the raw run files of the steps, which hold stand-in answers and are no measurement).
"""

from __future__ import annotations

import argparse
import contextlib
import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from typesafe_sdk import Choice, Noul, SystemOneResponse

from jav.adapters.jev import JevAdapter, use_adapter
from jav.config import CACHE_DIR, JEV_RETRY, JEV_USD_PER_MTOK, RUNS_DIR

TOKENS_PER_CHAR = Decimal("0.4")  # about 2.5 characters per token (JEV_PLAYBOOK §3)
TOKENS_PER_CHAR_MAX = Decimal("0.6")  # at most 0.60 of the request's characters (jav/runtime/calls.py, TOKEN_OVERHEAD)
NO_LIMIT = Decimal("1000")  # the steps run under a JEV-only budget, as the paid measurement; nothing is reserved
MODULES_WITH_RUNS_DIR = ("jav.evals", "jav.evals_detect", "jav.evals_email")


@dataclass
class Request:
    step: str
    request_id: str
    chars: int
    n_questions: int
    cached: bool
    reserve_usd: str  # the worst-case reservation a live call of this request would make


def request_body(state: object, questions: dict[str, Any]) -> str:
    """The request as the live path measures it (`JevAdapter._live`)."""
    return json.dumps({"state": state, "questions": {k: q.model_dump(mode="json") for k, q in questions.items()}},
                      ensure_ascii=False, default=str, sort_keys=True)


def stand_in(questions: dict[str, Any], model: str, chars: int) -> SystemOneResponse:
    """A neutral answer: the first option, 0.5 for a yes/no, the middle of a scale."""
    answers: dict[str, Any] = {}
    for key, q in questions.items():
        if isinstance(q, Choice):
            options = list(q.criteria)
            rest = 0.5 / max(len(options) - 1, 1)
            answers[key] = {"type": "choice", "choice": options[0], "confidence": 0.5,
                            "probabilities": {o: (0.5 if i == 0 else rest) for i, o in enumerate(options)}}
        elif isinstance(q, Noul):
            answers[key] = {"type": "noul", "noul": 0.5}
        else:
            levels = list(q.criteria)
            answers[key] = {"type": "score", "score": 0.5, "confidence": 0.5, "legend": dict(enumerate(levels)),
                            "probabilities": {i: 1 / len(levels) for i in range(len(levels))}}
    usage = {"input_tokens": int(chars * TOKENS_PER_CHAR), "output_tokens": 0}
    return SystemOneResponse.model_validate({"model": model, "usage": usage, "answers": answers})


class EstimatingAdapter(JevAdapter):
    """Answers from the real request-hash cache and writes nothing to it; a missing answer is never requested, it is
    recorded and answered with `stand_in`. The model is the concrete version the cache keys name."""

    def __init__(self, model: str, cache_dir: Path = CACHE_DIR) -> None:
        super().__init__(client=None, cache_dir=cache_dir, model=model)
        self.write_cache = False
        self.step = ""
        self.requests: list[Request] = []

    def ask(self, request_id: str, state: object, questions: dict[str, Any], **kwargs: Any):  # type: ignore[override]
        from jav.runtime import calls

        body = request_body(state, questions)
        result = super().ask(request_id, state, questions, **kwargs)
        reserve = calls.estimate_max_cost(input_bytes=calls.utf8_bytes(body), max_output_tokens=0,
                                          usd_per_mtok=(Decimal(str(JEV_USD_PER_MTOK)), Decimal(0)),
                                          repeats=1 + int(JEV_RETRY.get("max_retries", 0)))
        self.requests.append(Request(self.step, request_id, len(body), len(questions), result.cached, str(reserve)))
        return result

    def _live(self, request_id, state, questions, *, model, run_id, config_hash):  # noqa: ANN001 - the parent's signature
        return stand_in(questions, model, len(request_body(state, questions))), 0.0


def concrete_model(cache_dir: Path = CACHE_DIR) -> str:
    """The concrete version behind the configured alias, as the cache keys name it (`_model_versions.json`)."""
    from jav.adapters.jev import MODEL_VERSIONS_FILE, _CONCRETE_MODEL
    from jav.config import JEV_MODEL

    if _CONCRETE_MODEL.match(JEV_MODEL):
        return JEV_MODEL
    versions = json.loads((cache_dir / MODEL_VERSIONS_FILE).read_text(encoding="utf-8"))
    return versions[JEV_MODEL]["model"]


@contextlib.contextmanager
def only_adapter(adapter: JevAdapter) -> Iterator[None]:
    """The stand-in is the only JEV adapter while the steps run: the scoped one, and the default one too (a context
    the scoped adapter does not reach still cannot send a question)."""
    from jav.adapters import jev

    saved = jev._default_adapter
    jev._default_adapter = lambda: adapter  # type: ignore[assignment]
    try:
        with use_adapter(adapter):
            yield
    finally:
        jev._default_adapter = saved


@contextlib.contextmanager
def runs_redirected(out: Path) -> Iterator[None]:
    """The steps' raw run files go to `out`, never to runs/ (they hold stand-in answers, not a measurement)."""
    import importlib

    saved = []
    for name in MODULES_WITH_RUNS_DIR:
        module = importlib.import_module(name)
        saved.append((module, module.RUNS_DIR))
        module.RUNS_DIR = out
    try:
        yield
    finally:
        for module, value in saved:
            module.RUNS_DIR = value


def run_step(step: str, out: Path) -> None:
    kind, _, arg = step.partition(":")
    if kind in ("golden", "synthetic"):
        from jav import evals
        from jav.flow import run_one

        cases = evals.load_synthetic_cases(arg, out_dir=out / "synthetic") if kind == "synthetic" else None
        evals.golden("S", run_one, cases=cases, type_key=arg, jev_budget_usd=NO_LIMIT, label=kind)
    elif kind == "detect-golden":
        from jav import evals_detect

        evals_detect.detect_golden(budget_usd=NO_LIMIT)
    elif kind == "detect-cases":
        from jav import evals_detect

        evals_detect.detect_golden(budget_usd=NO_LIMIT, cases=evals_detect.load_case_file(Path(arg)), label="cases")
    elif kind == "email-golden":
        from jav import evals_email

        evals_email.email_golden(jev_budget_usd=NO_LIMIT)
    elif kind == "verifier-probe":
        from jav import evals

        evals.verifier_probe(type_key=arg, jev_budget_usd=NO_LIMIT)
    elif kind == "extract-cases":
        from jav.experiments import extract_cases

        extract_cases.run(Path(arg), arm="S", jev=True, budget_usd=NO_LIMIT, out_dir=out / "extract_cases")
    else:
        raise ValueError(f"unknown step: {step}")


def summary(requests: list[Request]) -> dict[str, Any]:
    by_step: dict[str, dict[str, Any]] = {}
    for r in requests:
        s = by_step.setdefault(r.step, {"requests": 0, "cached": 0, "live": 0, "live_chars": 0, "max_reserve_usd": Decimal(0)})
        s["requests"] += 1
        if r.cached:
            s["cached"] += 1
            continue
        s["live"] += 1
        s["live_chars"] += r.chars
        s["max_reserve_usd"] = max(s["max_reserve_usd"], Decimal(r.reserve_usd))
    price = Decimal(str(JEV_USD_PER_MTOK)) / Decimal(1_000_000)
    for s in by_step.values():
        s["expected_usd"] = (s["live_chars"] * TOKENS_PER_CHAR * price).quantize(Decimal("0.000001"))
        s["upper_usd"] = (s["live_chars"] * TOKENS_PER_CHAR_MAX * price).quantize(Decimal("0.000001"))
    total = {k: sum((s[k] for s in by_step.values()), Decimal(0) if k.endswith("usd") else 0)
             for k in ("requests", "cached", "live", "live_chars", "expected_usd", "upper_usd")}
    total["max_reserve_usd"] = max((s["max_reserve_usd"] for s in by_step.values()), default=Decimal(0))
    return {"steps": by_step, "total": total}


def report(result: dict[str, Any]) -> str:
    lines = ["| step | requests | from the cache | live | expected USD | upper USD | largest reservation USD |",
             "|---|---|---|---|---|---|---|"]
    for name, s in [*result["steps"].items(), ("total", result["total"])]:
        lines.append(f"| {name} | {s['requests']} | {s['cached']} | {s['live']} | {s['expected_usd']} | {s['upper_usd']} | "
                     f"{s['max_reserve_usd']} |")
    return "\n".join(lines)


def estimate(steps: list[str], out: Path) -> dict[str, Any]:
    from jav import store

    out.mkdir(parents=True, exist_ok=True)
    adapter = EstimatingAdapter(concrete_model())
    with store.use_store(out / "estimate.sqlite"), only_adapter(adapter), runs_redirected(out):
        for step in steps:
            adapter.step = step
            run_step(step, out)
    result = summary(adapter.requests)
    (out / "estimate.json").write_text(json.dumps({"steps": steps, **result, "requests": [asdict(r) for r in adapter.requests]},
                                                  ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "estimate.md").write_text(report(result) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("steps", nargs="+", help="golden:<type> | synthetic:<type> | detect-golden | detect-cases:<file> | "
                                             "email-golden | verifier-probe:<type> | extract-cases:<file>")
    ap.add_argument("--out", help="output folder (default: runs/<timestamp>_jev_estimate)")
    args = ap.parse_args(argv)
    out = Path(args.out) if args.out else RUNS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_jev_estimate"
    result = estimate(args.steps, out)
    print("\n" + report(result))
    print(f"\n{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
