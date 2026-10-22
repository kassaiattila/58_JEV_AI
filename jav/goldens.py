"""The golden sets in one registry, measured by one command (188, plan 185 T3a).

Plain-language summary: a golden set is a list of cases whose right answer is known in advance; measuring the system
on it shows how many answers come out as expected. Until now every golden set had its own command: the data points
of a type pack, the type recognition, the email intent and the reconciliation. This registry lists every golden set
in one place, and `python -m jav.cli measure` measures them with one command, the same way, with one receipt.

Where the golden sets come from:

- the data points: every type pack with cases in the legacy golden manifest or among the synthetic cases
  (`configs/golden_synthetic.json`), on each of its paths (S, G); they follow from the type packs, so nothing is
  registered by hand;
- the type recognition and the email intent: the two flows' golden sets, described here; 190: the quote request's
  invented emails, their intent and the requests read from them (`jav/evals_quotes.py`);
- a logic pack: the golden sets it names in its registration (`LogicPack.goldens`), as the reconciliation does;
- 197: the general facts of a held-out family (`configs/golden_facts.json`, `jav/evals_facts.py`): a type pack's
  legacy golden documents with the pack withheld, as a document of an unknown type continues.

A golden set is measured by the same function its own command calls, with the same arguments
(`tests/test_golden_commands_188.py`), so the raw run files, their names and the reports stay comparable with the
earlier measurements. The one intended difference: the incoming money kinds can be measured without a budget too, from
earlier answers, which their own command refuses (158).

Budget (160): without a budget only earlier answers count (the JEV cache, the call log's earlier answers), so a round
over every golden set is free; a case without an earlier answer is left without a result and counted. A paid round
measures exactly one golden set that asks AI, so the owner's sub-budget belongs to that set alone.

A round writes the sets' own reports into one log (`runs/<stamp>_measure.log`) and one receipt
(`runs/<stamp>_measure.jsonl`: the commit, whether the working tree was clean and the options, then one line per set
with its counts and the raw run files it wrote), and prints one line per set.

Layer: business module (the registry and the round); the measuring functions are imported where they run.
"""

from __future__ import annotations

import contextlib
import json
import time
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable

from jav.config import RUNS_DIR

LAYERS = ("datapoints", "type", "intent", "logic_pack")
ENGINES = ("jev", "gpt")
SYNTHETIC = "synthetic"
RECEIPT = "measure"

S_NEEDS_JEV = ("the S path needs JEV (JEV chooses among the candidates the code finds): measure it with --engine jev, "
               "or measure the G path")


class UnknownGolden(LookupError):
    """A selector that names no golden set."""


class RoundRefused(ValueError):
    """A round that cannot run as asked: a paid round of more than one golden set or of one that asks no AI, or a
    round that asks again without a budget."""


@dataclass(frozen=True)
class Options:
    """How a round measures.

    - `engine`: "jev" (JEV, and GPT where the path asks it: the G path's extraction) or "gpt" (GPT alone, 160-D);
    - `use_cache`: False asks every question again (live calls, so it needs a budget);
    - `jev_budget_usd`, `budget_usd`: the owner's sub-budgets for JEV and OpenAI; without them earlier answers only.
    """

    engine: str = "jev"
    use_cache: bool = True
    jev_budget_usd: Decimal | None = None
    budget_usd: Decimal | None = None

    def __post_init__(self) -> None:
        if self.engine not in ENGINES:
            raise ValueError(f"unknown engine {self.engine!r}: one of {ENGINES}")

    @property
    def jev(self) -> bool:
        return self.engine == "jev"

    @property
    def budgeted(self) -> bool:
        return self.jev_budget_usd is not None or self.budget_usd is not None

    def answering_budget(self, what: str) -> tuple[Decimal | None, str | None]:
        """The budget of a golden set whose command takes one budget, for the engine that answers: (the budget, None),
        or (None, why it is refused) when only the other engine's budget is given, so a budget is never moved over."""
        mine, other = (self.jev_budget_usd, self.budget_usd) if self.jev else (self.budget_usd, self.jev_budget_usd)
        if other is not None and mine is None:
            flag = "--jev-budget-usd" if self.jev else "--budget-usd"
            return None, f"{what} with {self.engine} takes its budget from {flag}"
        return mine, None


@dataclass(frozen=True)
class Outcome:
    """What the measurement of one golden set counted.

    - `cases`: the cases measured; `answered`: those with a result (the rest had no earlier answer, ran out of budget
      or failed);
    - `right` of `scored`: the judgements as expected, counted in `unit`: "fields" (a type pack's scored fields without
      the informational ones, as in the golden report's total), "cases" (one judgement per case) or "judgements" (190:
      the quote requests' fields, numbers of items and item quantities) or "values" (197: the expected values found
      among the general facts);
    - `refused`: why the set was not measured as asked (nothing was run); `error`: why its measurement broke off;
    - `failures`: the cases a code-only golden set got wrong, with what differed.
    """

    cases: int = 0
    answered: int = 0
    right: int = 0
    scored: int = 0
    unit: str = "cases"
    refused: str | None = None
    error: str | None = None
    failures: tuple[str, ...] = ()

    @property
    def without_result(self) -> int:
        return self.cases - self.answered


@dataclass(frozen=True)
class Golden:
    """One golden set.

    - `key`: its name in the command: `datapoints:<type>:<path>[:synthetic]`, `types`, `intents` or
      `<logic pack kind>:<name>`;
    - `layer`: one of `LAYERS`; `owner`: the type pack, the flow or the logic pack it measures; `what`: one sentence;
    - `engines`: the engines it can be measured with (`ENGINES`); none: code only, it asks no AI and is always free;
    - `count()`: its number of cases, without measuring;
    - `measure(options)`: measures it, printing its own report, and returns the `Outcome`;
    - `module`: the module that describes it.
    """

    key: str
    layer: str
    owner: str
    what: str
    engines: tuple[str, ...]
    count: Callable[[], int]
    measure: Callable[[Options], Outcome]
    module: str

    def __post_init__(self) -> None:
        if not self.key or any(ch.isspace() for ch in self.key):
            raise ValueError(f"golden set key {self.key!r}: a name without spaces")
        if self.layer not in LAYERS:
            raise ValueError(f"golden set {self.key!r}: unknown layer {self.layer!r}, one of {LAYERS}")
        if not set(self.engines) <= set(ENGINES):
            raise ValueError(f"golden set {self.key!r}: unknown engine in {self.engines}, one of {ENGINES}")


# --- the data points of the type packs ---------------------------------------------------------------------------------


def _datapoint_outcome(rows: list[dict[str, Any]], type_key: str) -> Outcome:
    from jav.typepack import get as get_pack

    strict = get_pack(type_key).strict_scored
    with_result = [r for r in rows if r.get("datapoints") is not None]
    vals = [r["scores"][f] for r in with_result for f in strict if r["scores"].get(f) is not None]
    return Outcome(cases=len(rows), answered=len(with_result), right=sum(vals), scored=len(vals), unit="fields")


def _datapoint_golden(type_key: str, arm: str, *, synthetic: bool) -> Golden:
    """A type pack's data points on one path, on the legacy golden set or on its synthetic cases, measured as
    `golden --arm <arm> --type <type> [--synthetic]` measures them."""
    from jav import cfg, evals

    def count() -> int:
        if synthetic:
            return sum(1 for c in cfg.load("golden_synthetic")["cases"] if c["type_key"] == type_key)
        return evals.count_cases(type_key)

    def measure(options: Options) -> Outcome:
        from jav.flow import run_one

        if arm == "S" and not options.jev:
            return Outcome(unit="fields", refused=S_NEEDS_JEV)
        cases = evals.load_synthetic_cases(type_key) if synthetic else None
        if synthetic and not cases:
            return Outcome(unit="fields", refused=f"no synthetic case for {type_key}")
        rows = evals.golden(arm, run_one, cases=cases, tracker=False, use_cache=options.use_cache, type_key=type_key,
                            jev=options.jev, budget_usd=options.budget_usd, jev_budget_usd=options.jev_budget_usd,
                            label=SYNTHETIC if synthetic else "golden")
        return _datapoint_outcome(rows, type_key)

    where = "its synthetic cases (configs/golden_synthetic.json)" if synthetic else "the legacy golden documents"
    return Golden(key=f"datapoints:{type_key}:{arm}" + (f":{SYNTHETIC}" if synthetic else ""), layer="datapoints",
                  owner=type_key, what=f"the data points of {type_key} on the {arm} path, on {where}",
                  engines=("jev",) if arm == "S" else ENGINES, count=count, measure=measure, module=__name__)


def datapoint_goldens() -> list[Golden]:
    """Every type pack with golden cases, on each of its paths: the legacy golden set first, then the synthetic cases."""
    from jav import typepack

    out: list[Golden] = []
    for type_key in typepack.extractable_keys():
        arms = typepack.get(type_key).arms
        for synthetic in (False, True):
            for arm in ("S", "G"):
                if arm in arms:
                    golden = _datapoint_golden(type_key, arm, synthetic=synthetic)
                    if golden.count():
                        out.append(golden)
    return out


# --- the two flows: the type recognition and the email intent ----------------------------------------------------------


def _case_outcome(rows: list[dict[str, Any]]) -> Outcome:
    answered = [r for r in rows if r.get("got") is not None]
    return Outcome(cases=len(rows), answered=len(answered), right=sum(r["got"] == r["expected"] for r in answered),
                   scored=len(answered))


def _count_types() -> int:
    from jav import evals_detect

    return len(evals_detect.load_detect_cases())


def _measure_types(options: Options) -> Outcome:
    """As `detect-golden` measures it: one budget, the answering engine's."""
    from jav import evals_detect

    budget, refused = options.answering_budget("the type recognition")
    if refused:
        return Outcome(refused=refused)
    return _case_outcome(evals_detect.detect_golden(use_cache=options.use_cache, jev=options.jev, descriptions=True,
                                                    budget_usd=budget, cases=None, label="golden"))


def _count_intents() -> int:
    from jav import evals_email

    return evals_email.count_cases()


def _measure_intents(options: Options) -> Outcome:
    """As `email-golden` measures it."""
    from jav import evals_email

    return _case_outcome(evals_email.email_golden(use_cache=options.use_cache, limit=None, jev=options.jev,
                                                  budget_usd=options.budget_usd,
                                                  jev_budget_usd=options.jev_budget_usd))


def _count_quote_intents() -> int:
    from jav import evals_quotes

    return evals_quotes.count_intents()


def _measure_quote_intents(options: Options) -> Outcome:
    from jav import evals_quotes

    return _case_outcome(evals_quotes.quote_intents(use_cache=options.use_cache, jev=options.jev,
                                                    budget_usd=options.budget_usd, jev_budget_usd=options.jev_budget_usd))


def _count_quote_requests() -> int:
    from jav import evals_quotes

    return evals_quotes.count_requests()


def _measure_quote_requests(options: Options) -> Outcome:
    from jav import evals_quotes

    rows = evals_quotes.quote_requests(use_cache=options.use_cache, jev=options.jev, budget_usd=options.budget_usd,
                                       jev_budget_usd=options.jev_budget_usd)
    right, scored = evals_quotes.judgements(rows)
    return Outcome(cases=len(rows), answered=sum(1 for r in rows if r.get("score")), right=right, scored=scored,
                   unit="judgements")


FLOW_GOLDENS = (
    Golden(key="types", layer="type", owner="doc_detect", what="the document type recognition on the legacy golden "
           "documents", engines=ENGINES, count=_count_types, measure=_measure_types, module=__name__),
    Golden(key="intents", layer="intent", owner="email_intent", what="the email intent on the legacy golden emails",
           engines=ENGINES, count=_count_intents, measure=_measure_intents, module=__name__),
    # 190 (plan 189 A2g): the quote request's invented golden set (configs/golden_quotes.json, jav/evals_quotes.py)
    Golden(key="quotes:intents", layer="intent", owner="email_intent", what="the email intent on the invented quote "
           "request emails", engines=ENGINES, count=_count_quote_intents, measure=_measure_quote_intents, module=__name__),
)
# 190: the quote requests read from the same emails, with the type packs' data points (the registry's layer order)
QUOTE_GOLDENS = (
    Golden(key="quotes:requests", layer="datapoints", owner="quote_request", what="the quote requests read from the "
           "invented emails' text and attachments", engines=ENGINES, count=_count_quote_requests,
           measure=_measure_quote_requests, module=__name__),
)


# 197 (plan 197 K1): the general facts of each held-out family, with the data points (the registry's layer order)


def _fact_golden(family: str) -> Golden:
    from jav import evals_facts

    def measure(options: Options) -> Outcome:
        rows = evals_facts.measure(family, jev=options.jev, use_cache=options.use_cache, budget_usd=options.budget_usd,
                                   jev_budget_usd=options.jev_budget_usd)
        t = evals_facts.totals(rows)
        return Outcome(cases=t["documents"], answered=t["answered"], right=t["found"], scored=t["expected"], unit="values")

    return Golden(key=f"facts:{family}", layer="datapoints", owner="native",
                  what=f"the general facts of {family}'s legacy golden documents, its type pack withheld",
                  engines=ENGINES, count=lambda: evals_facts.count(family), measure=measure, module=__name__)


def fact_goldens() -> list[Golden]:
    from jav import evals_facts

    return [g for g in (_fact_golden(family) for family in evals_facts.families()) if g.count()]


# 197 (plan 197 K2c): a taught type's candidate pack on its family's evaluation half only (its draft learnt from the
# development half), on the G path, scored as the data point golden sets are


def _taught_golden(key: str) -> Golden:
    from dataclasses import replace

    from jav import evals, evals_facts, type_teaching

    family = type_teaching.load_draft(key).family

    def cases() -> list:
        return [replace(fc.case, type_key=key) for fc in evals_facts.cases(family) if fc.half == "evaluation"]

    def count() -> int:
        try:
            return len(cases())
        except OSError:
            return 0

    def measure(options: Options) -> Outcome:
        from jav.flow import run_one

        rows = evals.golden("G", run_one, cases=cases(), tracker=False, use_cache=options.use_cache, type_key=key,
                            jev=options.jev, budget_usd=options.budget_usd, jev_budget_usd=options.jev_budget_usd,
                            label="taught")
        return _datapoint_outcome(rows, key)

    return Golden(key=f"taught:{key}", layer="datapoints", owner=key,
                  what=f"the taught candidate {key} on the {family} family's evaluation half, on the G path",
                  engines=ENGINES, count=count, measure=measure, module=__name__)


def taught_goldens() -> list[Golden]:
    """Every taught draft whose candidate pack exists."""
    from jav import type_teaching, typepack

    packs = set(typepack.keys())
    return [g for g in (_taught_golden(p.stem) for p in sorted(type_teaching.DRAFTS_DIR.glob("*.json")) if p.stem in packs)
            if g.count()]


# --- the registry ------------------------------------------------------------------------------------------------------


def sets() -> list[Golden]:
    """Every golden set: the type packs' data points, the two flows', then the logic packs' in their registration
    order."""
    from jav import logic_packs, registrations

    registrations.load_all()
    return [*datapoint_goldens(), *QUOTE_GOLDENS, *fact_goldens(), *taught_goldens(), *FLOW_GOLDENS,
            *(g for pack in logic_packs.packs() for g in pack.goldens)]


def get(key: str) -> Golden:
    for golden in sets():
        if golden.key == key:
            return golden
    raise UnknownGolden(f"no golden set {key!r} (python -m jav.cli measure --list)")


def _matches(key: str, selector: str) -> bool:
    return key == selector or key.startswith(f"{selector}:")


def select(selectors: Iterable[str]) -> list[Golden]:
    """The golden sets a selector names, in the registry's order: a selector is a key or its first parts
    (`datapoints:invoice_hu` = both paths, with the synthetic cases; `reconcile` = the reconciliation's sets). No
    selector: every golden set."""
    selectors = list(selectors)
    every = sets()
    if not selectors:
        return every
    if unknown := [s for s in selectors if not any(_matches(g.key, s) for g in every)]:
        raise UnknownGolden(f"no golden set named {', '.join(unknown)} (python -m jav.cli measure --list)")
    return [g for g in every if any(_matches(g.key, s) for s in selectors)]


# --- a round -----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Result:
    golden: Golden
    outcome: Outcome
    raw: tuple[str, ...]
    seconds: float


@dataclass(frozen=True)
class Round:
    results: tuple[Result, ...]
    receipt: Path
    log: Path
    exit_code: int


def _check(selected: list[Golden], options: Options) -> None:
    if options.budgeted:
        if len(selected) != 1:
            raise RoundRefused(f"a paid measurement measures one golden set, so its sub-budget belongs to it alone; "
                               f"{len(selected)} are named")
        if not selected[0].engines:
            raise RoundRefused(f"{selected[0].key} asks no AI: it is measured without a budget")
    elif not options.use_cache and any(g.engines for g in selected):
        raise RoundRefused("asking again (--no-cache) makes live calls, which need the owner's sub-budget "
                           "(--jev-budget-usd, --budget-usd)")


def _measure_one(golden: Golden, options: Options) -> Outcome:
    try:
        return golden.measure(options)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - one set that cannot be measured does not stop the round
        traceback.print_exc()  # into the round's log, next to the set's report
        return Outcome(error=f"{type(exc).__name__}: {exc}")


def _result_text(golden: Golden, outcome: Outcome) -> str:
    if outcome.refused or outcome.error:
        return f"{golden.key}: {'refused' if outcome.refused else 'error'}: {outcome.refused or outcome.error}"
    share = f" = {outcome.right / outcome.scored:.1%}" if outcome.scored else ""
    missing = f", {outcome.without_result} without a result" if outcome.without_result else ""
    failed = f", wrong: {'; '.join(outcome.failures)}" if outcome.failures else ""
    return (f"{golden.key}: {outcome.cases} cases, {outcome.right}/{outcome.scored} {outcome.unit} as expected"
            f"{share}{missing}{failed}")


def _exit_code(results: list[Result]) -> int:
    """1: a set broke off, or a code-only set got a case wrong (a model's wrong answer is not a failure); 3: a case
    without a result, so the figures are not comparable; 2: nothing was measured; 0 otherwise."""
    if any(r.outcome.error or (not r.golden.engines and r.outcome.right < r.outcome.scored) for r in results):
        return 1
    if any(r.outcome.without_result for r in results):
        return 3
    if all(r.outcome.refused for r in results):
        return 2
    return 0


def _head(selected: list[Golden], options: Options, started: datetime, store_path: Path | None) -> dict[str, Any]:
    from jav import devstate

    git = devstate.git_state()
    return {"receipt": RECEIPT, "started": started.isoformat(timespec="seconds"),
            "commit": git.head if git else None, "branch": git.branch if git else None,
            "clean": git.dirty == 0 if git else None, "engine": options.engine, "use_cache": options.use_cache,
            "jev_budget_usd": str(options.jev_budget_usd) if options.jev_budget_usd is not None else None,
            "budget_usd": str(options.budget_usd) if options.budget_usd is not None else None,
            "store": str(store_path) if store_path else None, "selected": [g.key for g in selected]}


def measure_round(selected: list[Golden], options: Options, *, runs_dir: Path | None = None,
                  store_path: Path | None = None) -> Round:
    """Measures the golden sets one after the other: their own reports into the round's log, one line each on the
    screen, one receipt. `store_path` (122): a separate measurement store, so the results, to-dos and call log of the
    measurement stay out of the work store (without it they go into the work store, as with the sets' own commands)."""
    from jav import store

    _check(selected, options)
    runs_dir = runs_dir or RUNS_DIR
    runs_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now()
    stamp = f"{started:%Y%m%d_%H%M%S}"
    log, receipt = runs_dir / f"{stamp}_{RECEIPT}.log", runs_dir / f"{stamp}_{RECEIPT}.jsonl"
    head = _head(selected, options, started, store_path)
    results: list[Result] = []
    where = store.use_store(store_path) if store_path else contextlib.nullcontext()
    with where, log.open("w", encoding="utf-8", newline="\n") as fh:
        for golden in selected:
            before = {p.name for p in runs_dir.glob("*.jsonl")}
            print(f"\n## {golden.key}\n", file=fh, flush=True)
            t0 = time.perf_counter()
            with contextlib.redirect_stdout(fh), contextlib.redirect_stderr(fh):
                outcome = _measure_one(golden, options)
            raw = tuple(sorted({p.name for p in runs_dir.glob("*.jsonl")} - before))
            results.append(Result(golden, outcome, raw, round(time.perf_counter() - t0, 1)))
            print(_result_text(golden, outcome), flush=True)
    lines = [head] + [{"key": r.golden.key, "layer": r.golden.layer, "owner": r.golden.owner,
                       "engines": list(r.golden.engines), "seconds": r.seconds, "raw": list(r.raw),
                       "without_result": r.outcome.without_result,
                       **{k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(r.outcome).items()}}
                      for r in results]
    receipt.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), encoding="utf-8")
    code = _exit_code(results)
    print(f"\nReports: {log}\nReceipt: {receipt}")
    return Round(tuple(results), receipt, log, code)


def latest_results(runs_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    """The latest measured result of each golden set from the rounds' receipts (`runs/*_measure.jsonl`), with the
    receipt's name, its commit, whether the working tree was clean and the engine. A set refused or broken off in a
    later round, or left without any result there (no earlier answer, no budget), keeps its earlier result: that round
    measured nothing (as the golden table of the state snapshot skips a run whose every case failed, 076)."""
    runs_dir = runs_dir or RUNS_DIR
    latest: dict[str, dict[str, Any]] = {}
    for path in sorted(runs_dir.glob(f"*_{RECEIPT}.jsonl")):
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        if not rows or rows[0].get("receipt") != RECEIPT:
            continue
        head = rows[0]
        for row in rows[1:]:
            if not (row.get("refused") or row.get("error") or (row.get("cases") and not row.get("answered"))):
                latest[row["key"]] = {**row, "receipt": path.name, "commit": head.get("commit"),
                                      "clean": head.get("clean"), "engine": head.get("engine")}
    return latest


__all__ = ["ENGINES", "FLOW_GOLDENS", "LAYERS", "QUOTE_GOLDENS", "Golden", "Options", "Outcome", "Result", "Round", "RoundRefused",
           "UnknownGolden", "datapoint_goldens", "get", "latest_results", "measure_round", "select", "sets"]
