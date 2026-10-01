"""The processing cost per item, run and work package (082, the cost view).

Nothing new is stored: the view is read from what every paid call already leaves behind.

- The call log (`invocations`, `jav/runtime/calls.py`): every paid call of a run (its budget scope) with its provider,
  model, state and cost. A document flow's call carries the item's flow identifier (`<run>:<item16>`, `work.flow_run_id`);
  an Azure recognition carries the run and the document's fingerprint in its step (`azure_di:ocr:<sha16>`), and a
  document's identifier is its content fingerprint.
- The ledger (`ledger`): also the questions answered from an earlier answer (an earlier JEV answer, the text of an
  earlier Azure recognition) at 0 USD, under the item's flow identifier.

A call without a known cost (failed, or with an unknown outcome) is not added to the actual cost: it is held apart at
its reserved maximum, as the budget counts it. Money: `Decimal`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from jav import store, work
from jav.runtime import calls

AZURE_STEP = "azure_di:ocr:"
PROVIDER_ORDER = ("jev", "openai", "azure_di")


@dataclass
class Line:
    """One provider and model: the paid calls made (`failed`: failed among them; `open`: still reserved or with an
    unknown outcome), the known actual cost, the reserved maximum of the calls without a known cost, and the number of
    answers taken from an earlier answer (free)."""

    provider: str
    model: str
    calls: int = 0
    failed: int = 0
    open: int = 0
    usd: Decimal = Decimal(0)
    held_usd: Decimal = Decimal(0)
    reused: int = 0

    def merge(self, other: Line) -> None:
        self.calls += other.calls
        self.failed += other.failed
        self.open += other.open
        self.usd += other.usd
        self.held_usd += other.held_usd
        self.reused += other.reused


@dataclass
class Summary:
    """Lines (one per provider and model, in a stable order) with their totals."""

    lines: list[Line] = field(default_factory=list)

    @property
    def usd(self) -> Decimal:
        return sum((x.usd for x in self.lines), Decimal(0))

    @property
    def held_usd(self) -> Decimal:
        return sum((x.held_usd for x in self.lines), Decimal(0))

    @property
    def reused(self) -> int:
        return sum(x.reused for x in self.lines)

    @property
    def calls(self) -> int:
        return sum(x.calls for x in self.lines)


@dataclass
class RunCosts(Summary):
    """A run's cost: per item, the calls not tied to one of its items (`other`), and the totals (`lines`)."""

    run_id: str = ""
    items: dict[str, Summary] = field(default_factory=dict)
    other: Summary = field(default_factory=Summary)


@dataclass
class RunTotal(Summary):
    run_id: str = ""
    created_at: str = ""
    mode: str = ""
    status: str = ""


@dataclass
class PackageCosts(Summary):
    """A work package's cost over all its runs (newest run first) and per provider and model."""

    workpackage_id: str = ""
    runs: list[RunTotal] = field(default_factory=list)


def _order(lines: dict[tuple[str, str], Line]) -> list[Line]:
    return [lines[k] for k in sorted(lines)]


def _total(summaries: list[Summary]) -> list[Line]:
    out: dict[tuple[str, str], Line] = {}
    for s in summaries:
        for x in s.lines:
            out.setdefault((x.provider, x.model), Line(x.provider, x.model)).merge(x)
    return _order(out)


def _item_of(flow_id: str, prefix: str) -> str | None:
    return flow_id[len(prefix):len(prefix) + 16] if flow_id.startswith(prefix) else None


def _collect(run_id: str) -> dict[str | None, dict[tuple[str, str], Line]]:
    """item16 (None: not tied to an item) → (provider, model) → line."""
    out: dict[str | None, dict[tuple[str, str], Line]] = defaultdict(dict)
    prefix = f"{run_id}:"

    def line(key: str | None, provider: str, model: str | None) -> Line:
        model = model or "?"
        return out[key].setdefault((provider, model), Line(provider, model))

    with store.connect() as c:
        for r in c.execute("SELECT run_id, step_id, provider, model_requested, model_actual, status, max_cost_usd, cost_usd, cost_known"
                           " FROM invocations WHERE budget_scope=?", (run_id,)):
            key = _item_of(r["run_id"], prefix)
            if key is None and r["step_id"].startswith(AZURE_STEP):
                key = r["step_id"][len(AZURE_STEP):][:16]
            x = line(key, r["provider"], r["model_actual"] or r["model_requested"])
            x.calls += 1
            x.failed += int(r["status"] == "failed")
            x.open += int(r["status"] in ("reserved", "uncertain"))
            if r["cost_known"]:
                x.usd += Decimal(r["cost_usd"])
            else:
                x.held_usd += Decimal(r["max_cost_usd"])
        # a range on the key index: every flow identifier of the run starts with `<run>:` (";" follows ":")
        for r in c.execute("SELECT run_id, provider, model, COUNT(*) n FROM ledger WHERE run_id >= ? AND run_id < ? AND cached=1"
                           " GROUP BY run_id, provider, model", (prefix, f"{run_id};")):
            line(_item_of(r["run_id"], prefix), r["provider"], r["model"]).reused += r["n"]
    return out


def run_costs(run_id: str) -> RunCosts:
    """The run's cost per item (every item of the run, an item without calls with no lines) and in total."""
    run = work.get_run(run_id)
    by_short = {i["item_id"][:16]: i["item_id"] for i in run["input"]["items"]}
    out = RunCosts(run_id=run_id, items={i: Summary() for i in by_short.values()})
    other: dict[tuple[str, str], Line] = {}
    for key, lines in _collect(run_id).items():
        item = by_short.get(key) if key else None
        if item is None:
            for k, x in lines.items():
                other.setdefault(k, Line(x.provider, x.model)).merge(x)
        else:
            out.items[item] = Summary(_order(lines))
    out.other = Summary(_order(other))
    out.lines = _total([*out.items.values(), out.other])
    return out


def run_total(run_id: str) -> Summary:
    """The run's totals per provider and model (without the per-item split)."""
    lines: dict[tuple[str, str], Line] = {}
    for item_lines in _collect(run_id).values():
        for k, x in item_lines.items():
            lines.setdefault(k, Line(x.provider, x.model)).merge(x)
    return Summary(_order(lines))


def package_costs(wp_id: str) -> PackageCosts:
    """The package's cost over all its runs."""
    work.get(wp_id)  # unknown package: KeyError
    runs = []
    for r in work.run_rows(wp_id):
        total = run_total(r["run_id"])
        runs.append(RunTotal(total.lines, run_id=r["run_id"], created_at=r["created_at"], mode=r["mode"], status=r["status"]))
    out = PackageCosts(workpackage_id=wp_id, runs=runs)
    out.lines = _total(list(runs))
    return out


def run_usd(run_ids: list[str]) -> dict[str, Decimal]:
    """The known actual cost of each run, in one query (the runs list)."""
    out = dict.fromkeys(run_ids, Decimal(0))
    if not run_ids:
        return out
    with store.connect() as c:
        for start in range(0, len(run_ids), 500):  # stays under the SQLite parameter limit
            chunk = run_ids[start:start + 500]
            for r in c.execute(f"SELECT budget_scope, cost_usd FROM invocations WHERE cost_known=1 AND budget_scope IN ({','.join('?' * len(chunk))})", chunk):
                out[r["budget_scope"]] += Decimal(r["cost_usd"])
    return out


# --- planned and actual ---------------------------------------------------------------------------------------------


def expected_providers(plan: dict[str, Any]) -> dict[str, str]:
    """What the pre-start overview (`work.run_plan`) said about each provider: `yes` (it will be called), `maybe` (it
    may be called, e.g. a document whose type is not known yet may need GPT) or `no`."""
    paths = plan.get("paths") or {}
    return {
        "jev": "yes" if plan.get("documents") or plan.get("emails") else "no",
        "openai": "yes" if paths.get("G") or plan.get("tasks_emails") else "maybe" if paths.get("unknown") else "no",
        "azure_di": "maybe" if plan.get("azure") else "no",
    }


def plan_vs_actual(run_id: str) -> dict[str, Any]:
    """Per provider: what the saved pre-start overview expected, the budget and its committed amount, and the actual
    calls and cost (models included). `unexpected`: the provider was called although the overview did not count on it.
    A run started before the overview was saved (`plan_saved` false) shows the actual part only."""
    run = work.get_run(run_id)
    plan = run.get("plan")
    expected = expected_providers(plan) if plan else {}
    budget = calls.budget_usage(run_id)["providers"]
    actual: dict[str, list[Line]] = defaultdict(list)
    for x in run_total(run_id).lines:
        actual[x.provider].append(x)
    rows = []
    for p in sorted(set(budget) | set(actual), key=lambda p: (PROVIDER_ORDER.index(p) if p in PROVIDER_ORDER else len(PROVIDER_ORDER), p)):
        lines = actual.get(p, [])
        s = Summary(lines)
        exp = expected.get(p)
        rows.append({"provider": p, "expected": exp,
                     "limit_usd": budget[p]["limit_usd"] if p in budget else None,
                     "committed_usd": budget[p]["committed_usd"] if p in budget else None,
                     "calls": s.calls, "failed": sum(x.failed for x in lines), "open": sum(x.open for x in lines),
                     "usd": s.usd, "held_usd": s.held_usd, "reused": s.reused, "models": [x.model for x in lines],
                     "unexpected": exp == "no" and s.calls > 0})
    return {"run_id": run_id, "plan_saved": plan is not None, "plan": plan, "providers": rows}
