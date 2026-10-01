"""The cost view (082).

The processing cost per item, per provider and model, per run and per work package, read from what is already recorded:
the call log (every paid call with its cost; a call without a known cost is held apart at its reserved maximum) and the
ledger (the questions answered from an earlier answer, at 0 USD). The pre-start overview is saved with the run and
compared with the actual calls. Synthetic rows and a fake JEV client, no paid calls.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal

from jav import costs, ocr, store, work
from jav.config import AZURE_DI_MODEL
from jav.runtime import calls
from tests import test_api
from tests.test_api import _ready_wp, _start

env = test_api.env


def _call(run_id, item_id, provider, model, *, status="succeeded", cost=None, max_cost="0.010000", step=None):
    """One call-log row as the call log writes it: a document flow's call carries the item's flow identifier; an
    Azure recognition carries the run and the document's fingerprint in its step."""
    flow = run_id if provider == "azure_di" else work.flow_run_id(run_id, item_id)
    step = step or (f"azure_di:ocr:{item_id[:16]}" if provider == "azure_di" else f"{provider}:{status}:{cost}:{model}")
    with store.connect() as c:
        attempt = c.execute("SELECT COUNT(*) FROM invocations WHERE run_id=? AND step_id=?", (flow, step)).fetchone()[0] + 1
        c.execute("INSERT INTO invocations(run_id, step_id, attempt, provider, model_requested, model_actual, budget_scope, status,"
                  " max_cost_usd, cost_usd, cost_known, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (flow, step, attempt, provider, model, model if status == "succeeded" else None, run_id, status, max_cost,
                   cost, int(cost is not None), datetime.now(timezone.utc).isoformat()))


def _reused(run_id, item_id, provider="jev", model="jev-1.13.0", n=1, suffix=""):
    for _ in range(n):
        store.ledger_add(run_id=f"{work.flow_run_id(run_id, item_id)}{suffix}", step="detect", provider=provider, model=model,
                         input_tokens=None, output_tokens=None, cost_usd=0.0, seconds=0.0, cached=True)


def _queued_run(c, folder):
    wp = _ready_wp(c, folder)
    run_id = _start(c, wp["id"]).json()["run_id"]
    a, b = sorted(i["item_id"] for i in wp["items"])
    return wp, run_id, a, b


# --- per item, run and package ----------------------------------------------------------------------------------


def test_costs_are_split_by_item_and_model_and_unknown_costs_are_held_apart(env):
    wp, run_id, a, b = _queued_run(env["client"], env["folder"])
    _call(run_id, a, "jev", "jev-1.13.0", cost="0.002000")
    _call(run_id, a, "jev", "jev-1.13.0", status="failed", max_cost="0.010000")
    _call(run_id, a, "openai", "gpt-4.1-mini", cost="0.001000")
    _call(run_id, b, "azure_di", AZURE_DI_MODEL, status="failed", max_cost="0.020000")
    _reused(run_id, a, n=3)
    _reused(run_id, b, suffix="-doc_detect")

    got = costs.run_costs(run_id)
    item_a = {(x.provider, x.model): x for x in got.items[a].lines}
    jev = item_a[("jev", "jev-1.13.0")]
    assert (jev.calls, jev.failed, jev.usd, jev.held_usd, jev.reused) == (2, 1, Decimal("0.002"), Decimal("0.01"), 3)
    assert item_a[("openai", "gpt-4.1-mini")].usd == Decimal("0.001")
    assert got.items[a].usd == Decimal("0.003") and got.items[a].held_usd == Decimal("0.01") and got.items[a].reused == 3
    item_b = {(x.provider, x.model): x for x in got.items[b].lines}
    azure = item_b[("azure_di", AZURE_DI_MODEL)]
    # a failed attempt costs nothing known: it is not added to the actual cost, only held at its reserved maximum
    assert (azure.calls, azure.failed, azure.usd, azure.held_usd) == (1, 1, Decimal(0), Decimal("0.02"))
    assert item_b[("jev", "jev-1.13.0")].reused == 1
    assert got.usd == Decimal("0.003") and got.held_usd == Decimal("0.03") and got.reused == 4
    totals = {(x.provider, x.model): x for x in got.lines}
    assert totals[("jev", "jev-1.13.0")].reused == 4 and totals[("jev", "jev-1.13.0")].calls == 2


def test_the_package_adds_up_every_run(env):
    c = env["client"]
    wp, first, a, b = _queued_run(c, env["folder"])
    _call(first, a, "jev", "jev-1.13.0", cost="0.002000")
    work.cancel_run(first, actor="teszt.elek")
    ready = c.get(f"/api/workpackages/{wp['id']}/workflow/readiness").json()
    second = c.post(f"/api/workpackages/{wp['id']}/workflow/start", headers=test_api.HUMAN, json={
        "mode": "apply", "expected_revision": ready["assignment_revision"], "input_hash": ready["input_hash"], "rerun_of": first}).json()["run_id"]
    _call(second, b, "jev", "jev-1.13.0", cost="0.003000")
    _call(second, b, "openai", "gpt-4.1-mini", cost="0.001000")

    pkg = costs.package_costs(wp["id"])
    assert pkg.usd == Decimal("0.006")
    assert {(x.provider, x.model): x.usd for x in pkg.lines} == {("jev", "jev-1.13.0"): Decimal("0.005"), ("openai", "gpt-4.1-mini"): Decimal("0.001")}
    assert [(r.run_id, r.usd) for r in pkg.runs] == [(second, Decimal("0.004")), (first, Decimal("0.002"))]  # newest first


# --- planned and actual -------------------------------------------------------------------------------------------


def test_the_pre_start_overview_is_saved_with_the_run_and_compared_with_the_actual_calls(env):
    wp, run_id, a, b = _queued_run(env["client"], env["folder"])
    plan = work.get_run(run_id)["plan"]
    assert plan["paths"] == {"S": 2, "G": 0, "unknown": 0} and plan["documents"] == 2  # the invoice type is given, path S
    _call(run_id, a, "jev", "jev-1.13.0", cost="0.002000")
    _call(run_id, a, "openai", "gpt-4.1-mini", cost="0.001000")
    rows = {r["provider"]: r for r in costs.plan_vs_actual(run_id)["providers"]}
    assert rows["jev"]["expected"] == "yes" and not rows["jev"]["unexpected"] and rows["jev"]["usd"] == Decimal("0.002")
    assert rows["openai"]["expected"] == "no" and rows["openai"]["unexpected"]  # the overview did not count on OpenAI
    assert Decimal(rows["jev"]["limit_usd"]) > 0


def test_an_old_run_without_a_saved_overview_shows_the_actual_cost_only(env):
    wp, run_id, a, b = _queued_run(env["client"], env["folder"])
    with store.connect() as conn:
        conn.execute("UPDATE runs SET plan=NULL WHERE run_id=?", (run_id,))
    _call(run_id, a, "openai", "gpt-4.1-mini", cost="0.001000")
    view = costs.plan_vs_actual(run_id)
    assert view["plan_saved"] is False
    assert {(r["provider"], r["expected"], r["unexpected"]) for r in view["providers"]} >= {("openai", None, False)}


# --- the lists and the run view -------------------------------------------------------------------------------------


def test_the_run_items_list_has_a_cost_column_per_model_and_a_total(env):
    c = env["client"]
    wp, run_id, a, b = _queued_run(c, env["folder"])
    _call(run_id, a, "jev", "jev-1.13.0", cost="0.002000")
    _call(run_id, a, "openai", "gpt-4.1-mini", cost="0.001000")
    _call(run_id, a, "jev", "jev-latest", status="failed", max_cost="0.010000")  # a failed call knows only the alias
    _reused(run_id, b, n=2)
    body = c.post("/api/datasets/run_items/query", json={"scope": {"run_id": run_id}, "query": {}}).json()
    cols = {col["key"]: col for col in body["columns"]}
    assert cols["cost:jev:jev-1.13.0"]["label"] == "JEV · jev-1.13.0 (USD)" and not cols["cost:jev:jev-1.13.0"]["hidden"]
    assert "cost:openai:gpt-4.1-mini" in cols and not cols["cost_total"]["hidden"] and cols["cost_reused"]["hidden"]
    assert "cost:jev:jev-latest" not in cols and not cols["cost_held"]["hidden"]  # no column for a model without a known cost
    rows = {r["item_id"]: r for r in body["rows"]}
    assert Decimal(str(rows[a]["cost_total"])) == Decimal("0.003") and Decimal(str(rows[a]["cost:jev:jev-1.13.0"])) == Decimal("0.002")
    assert Decimal(str(rows[a]["cost_held"])) == Decimal("0.01") and rows[b]["cost_held"] is None
    assert Decimal(str(rows[b]["cost_total"])) == 0 and rows[b]["cost_reused"] == 2
    _call(run_id, b, "jev", "jev-1.13.0", cost="0.004000")  # a new call shows at the next request (the cache follows the call log)
    again = c.post("/api/datasets/run_items/query", json={"scope": {"run_id": run_id}, "query": {}}).json()
    assert Decimal(str({r["item_id"]: r for r in again["rows"]}[b]["cost_total"])) == Decimal("0.004")


def test_the_package_lists_show_the_cost_of_each_run_and_of_the_package(env):
    c = env["client"]
    wp, run_id, a, b = _queued_run(c, env["folder"])
    _call(run_id, a, "jev", "jev-1.13.0", cost="0.002000")
    _reused(run_id, b, n=2)
    runs = c.post("/api/datasets/runs/query", json={"scope": {"workpackage_id": wp["id"]}, "query": {}}).json()
    assert Decimal(str(runs["rows"][0]["cost_usd"])) == Decimal("0.002")
    pkg = c.post("/api/datasets/package_costs/query", json={"scope": {"workpackage_id": wp["id"]}, "query": {}}).json()
    row = next(r for r in pkg["rows"] if r["provider"] == "jev")
    assert (row["model"], Decimal(str(row["usd"])), row["calls"], row["reused"], row["runs"]) == ("jev-1.13.0", Decimal("0.002"), 1, 2, 1)
    assert next(col for col in pkg["columns"] if col["key"] == "provider")["labels"]["azure_di"] == "Azure DI"


def test_the_run_view_carries_the_planned_and_actual_cost(env):
    c = env["client"]
    wp, run_id, a, b = _queued_run(c, env["folder"])
    _call(run_id, a, "jev", "jev-1.13.0", cost="0.002000")
    _call(run_id, b, "jev", "jev-latest", status="failed")
    view = c.get(f"/api/runs/{run_id}").json()["costs"]
    jev = next(r for r in view["providers"] if r["provider"] == "jev")
    assert view["plan_saved"] and jev["expected"] == "yes" and Decimal(jev["usd"]) == Decimal("0.002")
    assert jev["models"] == ["jev-1.13.0"] and jev["calls"] == 2 and jev["failed"] == 1  # the alias of a failed call is not a model


# --- the earlier Azure recognition ----------------------------------------------------------------------------------


def test_text_taken_from_an_earlier_azure_recognition_is_counted_as_a_reused_answer(env, monkeypatch, tmp_path):
    wp, run_id, a, b = _queued_run(env["client"], env["folder"])
    item = next(i for i in wp["items"] if i["item_id"] == a)
    path = work.source_file(item)
    monkeypatch.setattr(ocr, "CACHE_DIR", tmp_path / "ocr")
    (tmp_path / "ocr").mkdir()
    cached = {"layout": [], "signals": {}, "engine": "azure_di", "engine_version": ocr.engine_version("azure_di"), "page_count": 1,
              "words": [[]], "page_sizes": [[595, 842]]}
    (tmp_path / "ocr" / f"{ocr.cache_key(path, 'azure_di')}.json").write_text(json.dumps(cached), encoding="utf-8")
    with calls.use_run(budget_scope=run_id):
        ocr.ocr_pdf(path, engine_name="azure_di")
    ocr.ocr_pdf(path, engine_name="azure_di")  # outside a run (measurements, command line): nothing is written
    line = {(x.provider, x.model): x for x in costs.run_costs(run_id).items[a].lines}[("azure_di", AZURE_DI_MODEL)]
    assert (line.calls, line.usd, line.reused) == (0, Decimal(0), 1)
