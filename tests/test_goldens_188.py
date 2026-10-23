"""188 (plan 185 T3a): every golden set in one registry, measured by one command (`measure`, `jav/evals/goldens.py`).

The data point golden sets come from the type packs, the type recognition and the email intent golden sets are the
two flows', and a logic pack's come from its domain's measurement module (the reconciliation: the pairs proposed by
code and the incoming money kinds; until 204 named in the logic pack's registration). Each golden set is measured by
the same function its own command calls, with the same arguments (`tests/test_golden_commands_188.py`). Without a
budget only earlier answers count; a paid measurement names exactly one golden set. One round writes one receipt (with
the commit) and one log of the sets' own reports.

Stand-in measuring functions only: no case is run and no call is made.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from jav import cli
from jav.evals import evals, evals_detect, evals_email, goldens
from jav.domains.finance import reconcile, reconcile_ai, goldens as reconcile_goldens
from tests.test_golden_commands_188 import (CREDIT_RESULT, credit_kinds_call, detect_call, email_call, golden_call,
                                            record)

LEGACY = {"invoice_hu": 12, "viz_szamla": 10, "belepo_jegy": 11}
COUNT_CASES = evals.count_cases  # the real counter, before the fixture below replaces it


@pytest.fixture(autouse=True)
def legacy_counts(monkeypatch):
    """The legacy golden manifest lives outside the repository: its case counts are given here."""
    monkeypatch.setattr(evals, "count_cases", lambda type_key: LEGACY.get(type_key, 0))


def keys() -> list[str]:
    return [g.key for g in goldens.sets()]


# --- the registry -----------------------------------------------------------------------------------------------------


def test_a_type_pack_with_golden_cases_has_a_golden_set_on_each_of_its_paths():
    k = keys()
    assert {"datapoints:invoice_hu:S", "datapoints:invoice_hu:G", "datapoints:viz_szamla:S",
            "datapoints:viz_szamla:G"} <= set(k)
    assert "datapoints:belepo_jegy:G" in k and "datapoints:belepo_jegy:S" not in k  # a G-only pack
    assert not [x for x in k if x.startswith("datapoints:foldgaz_szamla")]  # no case: no golden set


def test_only_the_legacy_cases_the_data_point_measurement_reads_are_counted(monkeypatch, tmp_path):
    """The packs converted from legacy types keep their expected values without the `datapoints` record. 197 (plan 197
    K0): the data point measurement reads that flat record by the pack's own fields, so they count too; a record with
    none of the pack's fields does not."""
    (tmp_path / "expected").mkdir()
    cases = [("doc-extract/a", "invoice_hu", {"datapoints": {"invoice_number": "1"}}),
             ("doc-extract/b", "invoice_hu", {"datapoints": {"invoice_number": "2"}}),
             ("doc-extract/c", "belepo_jegy", {"seat": "12"}),
             ("doc-extract/e", "belepo_jegy", {"no_such_field": "x"}),
             ("doc-extract/d", "viz_szamla", {"datapoints": {}})]
    for case_id, _, expected in cases:
        name = case_id.split("/", 1)[1]
        (tmp_path / "expected" / f"{name}.json").write_text(json.dumps(expected), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"cases": [{"id": i, "type_key": t, "input_ref": f"/{i}.pdf"} for i, t, _ in cases]}),
                        encoding="utf-8")
    monkeypatch.setattr(evals, "GOLDEN_MANIFEST", manifest)
    monkeypatch.setattr(evals, "GOLDEN_EXPECTED_DIR", tmp_path)
    assert [COUNT_CASES(t) for t in ("invoice_hu", "belepo_jegy", "viz_szamla", "foldgaz_szamla")] == [2, 1, 1, 0]
    [seat] = evals.load_cases("belepo_jegy")  # the record without a field of the pack is left out, as counted
    assert (seat.case_id, seat.expected, seat.expected_valid) == ("c", {"seat": "12"}, True)
    monkeypatch.setattr(evals, "GOLDEN_MANIFEST", tmp_path / "missing.json")
    assert COUNT_CASES("invoice_hu") == 0


def test_the_synthetic_cases_are_a_golden_set_of_their_own():
    k = keys()
    assert {"datapoints:invoice_out:S:synthetic", "datapoints:invoice_out:G:synthetic",
            "datapoints:invoice_hu:S:synthetic"} <= set(k)
    assert "datapoints:invoice_out:S" not in k  # the legacy manifest has no invoice_out case
    assert goldens.get("datapoints:invoice_out:S:synthetic").count() == 8


def test_the_flows_and_the_reconciliation_have_their_golden_sets():
    by_key = {g.key: g for g in goldens.sets()}
    assert by_key["types"].layer == "type" and by_key["intents"].layer == "intent"
    assert by_key["reconcile:pairs"].engines == ()  # code only, always free
    assert by_key["reconcile:credit_kinds"].engines == ("jev", "gpt")
    # 204 (R1h): described by the finance domain's measurement module, no longer by the logic pack's registration
    assert [g.key for g in reconcile_goldens.GOLDENS] == ["reconcile:pairs", "reconcile:credit_kinds"]
    assert {by_key[k].layer for k in ("reconcile:pairs", "reconcile:credit_kinds")} == {"logic_pack"}


def test_the_order_is_data_points_then_the_flows_then_the_logic_packs():
    layers = [g.layer for g in goldens.sets()]
    assert layers == sorted(layers, key=goldens.LAYERS.index)
    assert len(set(keys())) == len(keys())


@pytest.mark.parametrize(("key", "owner", "layer"), [
    ("other:x", "other", "logic_pack"),  # no such logic pack
    ("other:x", "reconcile", "logic_pack"),  # not named after its pack
    ("reconcile:x", "reconcile", "type"),  # not a logic pack's
])
def test_a_logic_pack_golden_set_must_be_named_after_the_pack(monkeypatch, key, owner, layer):
    """204 (R1h): until 204 the logic pack refused such a golden set in its registration; the registry now refuses to
    list one from a domain's measurement module."""
    golden = goldens.Golden(key=key, layer=layer, owner=owner, what="w", engines=(),
                            count=lambda: 1, measure=lambda options: goldens.Outcome(), module=__name__)
    monkeypatch.setattr(reconcile_goldens, "GOLDENS", (*reconcile_goldens.GOLDENS, golden))
    with pytest.raises(ValueError, match=f"jav.domains.finance.goldens: its golden set '{key}'"):
        goldens.sets()


def test_a_golden_set_needs_a_known_layer_and_engines():
    with pytest.raises(ValueError):
        goldens.Golden(key="x", layer="nonsense", owner="x", what="w", engines=(), count=lambda: 0,
                       measure=lambda o: goldens.Outcome(), module=__name__)
    with pytest.raises(ValueError):
        goldens.Golden(key="x", layer="type", owner="x", what="w", engines=("claude",), count=lambda: 0,
                       measure=lambda o: goldens.Outcome(), module=__name__)


def test_selection_by_key_or_by_its_first_parts():
    assert [g.key for g in goldens.select(["types"])] == ["types"]
    picked = [g.key for g in goldens.select(["datapoints:invoice_hu"])]
    assert picked == ["datapoints:invoice_hu:S", "datapoints:invoice_hu:G", "datapoints:invoice_hu:S:synthetic",
                      "datapoints:invoice_hu:G:synthetic"]
    assert [g.key for g in goldens.select(["reconcile", "types"])] == ["types", "reconcile:pairs",
                                                                       "reconcile:credit_kinds"]
    assert [g.key for g in goldens.select([])] == keys()
    with pytest.raises(goldens.UnknownGolden, match="datapoints:invoice"):
        goldens.select(["datapoints:invoice"])  # a part of a key's part is not a selection


def test_a_whole_key_names_its_own_set_alone():
    """200 (M-jev-114): a whole key is not also the first parts of a longer key, so a paid round can name the legacy
    S path alone; the shorter selector still names both."""
    assert [g.key for g in goldens.select(["datapoints:invoice_hu:S"])] == ["datapoints:invoice_hu:S"]
    assert [g.key for g in goldens.select(["datapoints:invoice_hu:S:synthetic"])] == ["datapoints:invoice_hu:S:synthetic"]
    goldens._check(goldens.select(["datapoints:invoice_hu:S"]), goldens.Options(jev_budget_usd=Decimal("0.01")))


# --- the same call as the set's own command ---------------------------------------------------------------------------


@pytest.mark.parametrize(("key", "options", "expected"), [
    ("datapoints:invoice_hu:S", goldens.Options(), golden_call("S", "invoice_hu")),
    ("datapoints:viz_szamla:S", goldens.Options(use_cache=False), golden_call("S", "viz_szamla", use_cache=False)),
    ("datapoints:invoice_hu:G", goldens.Options(engine="gpt", budget_usd=Decimal("0.10")),
     golden_call("G", "invoice_hu", jev=False, budget_usd=Decimal("0.10"))),
    ("datapoints:invoice_hu:S", goldens.Options(jev_budget_usd=Decimal("0.02")),
     golden_call("S", "invoice_hu", jev_budget_usd=Decimal("0.02"))),
])
def test_a_data_point_golden_set_is_measured_as_its_command_measures_it(monkeypatch, key, options, expected):
    fake = record(monkeypatch, evals, "golden", [])
    goldens.get(key).measure(options)
    assert fake.calls == [expected]


def test_a_synthetic_golden_set_is_measured_as_its_command_measures_it(monkeypatch):
    monkeypatch.setattr(evals, "load_synthetic_cases", lambda type_key: [f"case of {type_key}"])
    fake = record(monkeypatch, evals, "golden", [])
    goldens.get("datapoints:invoice_out:G:synthetic").measure(goldens.Options())
    assert fake.calls == [golden_call("G", "invoice_out", cases=["case of invoice_out"], label="synthetic")]


def test_the_s_path_without_jev_is_refused_without_running(monkeypatch):
    fake = record(monkeypatch, evals, "golden", [])
    outcome = goldens.get("datapoints:invoice_hu:S").measure(goldens.Options(engine="gpt"))
    assert outcome.refused and "JEV" in outcome.refused and fake.calls == []


@pytest.mark.parametrize(("options", "expected"), [
    (goldens.Options(), detect_call()),
    (goldens.Options(use_cache=False), detect_call(use_cache=False)),
    (goldens.Options(jev_budget_usd=Decimal("0.05")), detect_call(budget_usd=Decimal("0.05"))),
    (goldens.Options(engine="gpt", budget_usd=Decimal("0.20")), detect_call(jev=False, budget_usd=Decimal("0.20"))),
])
def test_the_type_golden_set_is_measured_as_its_command_measures_it(monkeypatch, options, expected):
    fake = record(monkeypatch, evals_detect, "detect_golden", [])
    goldens.get("types").measure(options)
    assert fake.calls == [expected]


def test_the_type_golden_set_takes_the_budget_of_the_engine_that_answers(monkeypatch):
    """Its command's one budget is the answering engine's: the other engine's budget is refused, not moved over."""
    fake = record(monkeypatch, evals_detect, "detect_golden", [])
    outcome = goldens.get("types").measure(goldens.Options(budget_usd=Decimal("0.20")))
    assert outcome.refused and "--jev-budget-usd" in outcome.refused and fake.calls == []


@pytest.mark.parametrize(("options", "expected"), [
    (goldens.Options(), email_call()),
    (goldens.Options(engine="gpt", budget_usd=Decimal("0.30")), email_call(jev=False, budget_usd=Decimal("0.30"))),
    (goldens.Options(jev_budget_usd=Decimal("0.03")), email_call(jev_budget_usd=Decimal("0.03"))),
])
def test_the_intent_golden_set_is_measured_as_its_command_measures_it(monkeypatch, options, expected):
    fake = record(monkeypatch, evals_email, "email_golden", [])
    goldens.get("intents").measure(options)
    assert fake.calls == [expected]


@pytest.mark.parametrize(("options", "expected"), [
    (goldens.Options(jev_budget_usd=Decimal("0.01")), credit_kinds_call("jev", {"jev": Decimal("0.01")})),
    (goldens.Options(engine="gpt", budget_usd=Decimal("0.02"), use_cache=False),
     credit_kinds_call("gpt", {"openai": Decimal("0.02")}, use_cache=False)),
])
def test_the_incoming_money_kinds_are_measured_as_their_command_measures_them(monkeypatch, options, expected):
    fake = record(monkeypatch, reconcile_ai, "golden", CREDIT_RESULT)
    goldens.get("reconcile:credit_kinds").measure(options)
    assert fake.calls == [expected]


def test_without_a_budget_the_incoming_money_kinds_use_earlier_answers_only(monkeypatch):
    """The one intended difference: their own command refuses to run without a budget (158); the shared command
    measures them from earlier answers, as every other golden set (160)."""
    fake = record(monkeypatch, reconcile_ai, "golden", CREDIT_RESULT)
    goldens.get("reconcile:credit_kinds").measure(goldens.Options())
    args, kwargs = credit_kinds_call("jev", {})
    assert fake.calls == [(args, {**kwargs, "earlier_only": True})]


def test_the_pairs_golden_set_is_measured_as_its_command_measures_it(monkeypatch):
    fake = record(monkeypatch, reconcile, "golden_score", {"passed": 2, "total": 3, "failures": {"c3": ["pairs"]}})
    outcome = goldens.get("reconcile:pairs").measure(goldens.Options())
    assert fake.calls == [((), {})]
    assert (outcome.cases, outcome.answered, outcome.right, outcome.scored, outcome.unit) == (3, 3, 2, 3, "cases")
    assert outcome.failures == ("c3: pairs",)


# --- what a golden set's outcome counts -------------------------------------------------------------------------------


def test_a_data_point_outcome_counts_the_scored_fields_of_the_cases_with_a_result(monkeypatch):
    rows = [{"case_id": "a", "datapoints": {"x": 1}, "scores": {"invoice_number": True, "gross_total": False,
                                                                 "payment_iban": True, "due_date": None}},
            {"case_id": "b", "datapoints": None, "scores": {}, "review_reasons": ["llm:failed:BudgetExceeded"]}]
    record(monkeypatch, evals, "golden", rows)
    outcome = goldens.get("datapoints:invoice_hu:S").measure(goldens.Options())
    # the informational bank account is not scored, as in the golden report's total; a field the case leaves out neither
    assert (outcome.cases, outcome.answered, outcome.right, outcome.scored, outcome.unit) == (2, 1, 1, 2, "fields")
    assert outcome.without_result == 1


def test_an_s_path_case_the_budget_refused_has_no_result(monkeypatch):
    """200 (M-jev-114): the S path still returns data points when JEV is refused for the budget (every field empty),
    so such a case was counted as answered and wrong; the budget left it without a result, as the golden command
    reports it (`eval_report.budget_skips`)."""
    rows = [{"case_id": "a", "datapoints": {"x": 1}, "scores": {"invoice_number": True, "gross_total": True}},
            {"case_id": "b", "datapoints": {"invoice_number": None}, "scores": {"invoice_number": False, "gross_total": False},
             "review_reasons": ["jev_unavailable:budget_exceeded", "validator:totals.unparseable"]}]
    record(monkeypatch, evals, "golden", rows)
    outcome = goldens.get("datapoints:invoice_hu:S").measure(goldens.Options())
    assert (outcome.cases, outcome.answered, outcome.right, outcome.scored) == (2, 1, 2, 2)
    assert outcome.without_result == 1


def test_a_type_and_an_intent_outcome_count_the_cases(monkeypatch):
    rows = [{"case_id": "a", "expected": "x", "got": "x"}, {"case_id": "b", "expected": "x", "got": "y"},
            {"case_id": "c", "expected": "x", "got": None}]
    record(monkeypatch, evals_detect, "detect_golden", rows)
    record(monkeypatch, evals_email, "email_golden", rows)
    for key in ("types", "intents"):
        o = goldens.get(key).measure(goldens.Options())
        assert (o.cases, o.answered, o.right, o.scored, o.unit) == (3, 2, 1, 2, "cases"), key


def test_an_incoming_money_kind_outcome_counts_the_engine_asked(monkeypatch):
    result = {**CREDIT_RESULT, "engines": {"gpt": {"cases": 5, "right": 3, "failed": 1, "by_kind": {}, "confusions": {}}}}
    record(monkeypatch, reconcile_ai, "golden", result)
    o = goldens.get("reconcile:credit_kinds").measure(goldens.Options(engine="gpt", budget_usd=Decimal("0.01")))
    assert (o.cases, o.answered, o.right, o.scored) == (5, 4, 3, 4)


# --- a round ----------------------------------------------------------------------------------------------------------


def _fake_round(monkeypatch, *, detect_rows=None, score=None):
    record(monkeypatch, evals_detect, "detect_golden", detect_rows if detect_rows is not None else
           [{"case_id": "a", "expected": "x", "got": "x"}])
    record(monkeypatch, reconcile, "golden_score", score or {"passed": 1, "total": 1, "failures": {}})


def test_a_round_writes_one_receipt_and_one_log(monkeypatch, tmp_path, capsys):
    _fake_round(monkeypatch)
    monkeypatch.setattr(evals_detect, "detect_golden", lambda **kw: print("the detect report") or
                        [{"case_id": "a", "expected": "x", "got": "x"}])
    r = goldens.measure_round(goldens.select(["types", "reconcile:pairs"]), goldens.Options(), runs_dir=tmp_path)
    assert r.exit_code == 0
    rows = [json.loads(x) for x in r.receipt.read_text(encoding="utf-8").splitlines()]
    head, results = rows[0], rows[1:]
    assert head["receipt"] == "measure" and "commit" in head and "clean" in head and head["engine"] == "jev"
    assert [x["key"] for x in results] == ["types", "reconcile:pairs"]
    assert results[0]["right"] == 1 and results[0]["unit"] == "cases"
    assert "the detect report" in r.log.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "the detect report" not in out  # the sets' own reports go to the log, the summary to the screen
    assert "types" in out and "reconcile:pairs" in out and r.receipt.name in out


def test_a_round_names_the_raw_run_files_each_set_wrote(monkeypatch, tmp_path):
    def detect(**kw):
        (tmp_path / "20261021_000000_detect_golden.jsonl").write_text("{}\n", encoding="utf-8")
        return [{"case_id": "a", "expected": "x", "got": "x"}]

    monkeypatch.setattr(evals_detect, "detect_golden", detect)
    r = goldens.measure_round(goldens.select(["types"]), goldens.Options(), runs_dir=tmp_path)
    assert r.results[0].raw == ("20261021_000000_detect_golden.jsonl",)


def test_a_round_exits_with_three_when_a_case_has_no_result_and_one_when_code_fails(monkeypatch, tmp_path):
    _fake_round(monkeypatch, detect_rows=[{"case_id": "a", "expected": "x", "got": None}])
    assert goldens.measure_round(goldens.select(["types"]), goldens.Options(), runs_dir=tmp_path).exit_code == 3
    _fake_round(monkeypatch, score={"passed": 0, "total": 1, "failures": {"c": ["pairs"]}})
    r = goldens.measure_round(goldens.select(["types", "reconcile:pairs"]), goldens.Options(), runs_dir=tmp_path)
    assert r.exit_code == 1  # a code-only golden set has to pass every case; a model's wrong answer is not a failure


def test_a_paid_round_measures_exactly_one_golden_set_that_asks_ai(tmp_path):
    paid = goldens.Options(jev_budget_usd=Decimal("0.05"))
    with pytest.raises(goldens.RoundRefused, match="one golden set"):
        goldens.measure_round(goldens.select(["types", "intents"]), paid, runs_dir=tmp_path)
    with pytest.raises(goldens.RoundRefused, match="asks no AI"):
        goldens.measure_round(goldens.select(["reconcile:pairs"]), paid, runs_dir=tmp_path)


def test_a_failing_golden_set_does_not_stop_the_round(monkeypatch, tmp_path):
    def broken(**kw):
        raise RuntimeError("legacy golden set missing")

    _fake_round(monkeypatch)
    monkeypatch.setattr(evals_detect, "detect_golden", broken)
    r = goldens.measure_round(goldens.select(["types", "reconcile:pairs"]), goldens.Options(), runs_dir=tmp_path)
    assert r.results[0].outcome.error == "RuntimeError: legacy golden set missing"
    assert r.results[1].outcome.right == 1 and r.exit_code == 1


def test_the_latest_result_of_each_golden_set_comes_from_the_receipts(tmp_path):
    def receipt(stamp: str, commit: str, *rows: dict) -> None:
        head = {"receipt": "measure", "commit": commit, "clean": True, "engine": "jev", "use_cache": True}
        (tmp_path / f"{stamp}_measure.jsonl").write_text("".join(json.dumps(x) + "\n" for x in (head, *rows)),
                                                          encoding="utf-8")

    measured = {"cases": 3, "answered": 3, "right": 3, "scored": 3, "unit": "cases", "refused": None, "error": None}
    receipt("20261020_100000", "aaa", {"key": "types", **measured}, {"key": "intents", **measured},
            {"key": "reconcile:credit_kinds", **measured})
    receipt("20261021_100000", "bbb", {"key": "types", **measured, "right": 2},
            {"key": "intents", **measured, "refused": "the S path needs JEV"},
            {"key": "reconcile:credit_kinds", **measured, "answered": 0, "right": 0, "scored": 0})
    (tmp_path / "20261021_100000_golden_S.jsonl").write_text("{}\n", encoding="utf-8")  # a raw run, not a receipt
    latest = goldens.latest_results(tmp_path)
    assert latest["types"]["right"] == 2 and latest["types"]["receipt"] == "20261021_100000_measure.jsonl"
    assert latest["types"]["commit"] == "bbb" and latest["types"]["clean"] is True
    assert latest["intents"]["commit"] == "aaa"  # a refused set keeps its earlier result
    assert latest["reconcile:credit_kinds"]["commit"] == "aaa"  # so does one left without any result
    assert goldens.latest_results(tmp_path / "none") == {}


def test_the_state_snapshot_shows_every_golden_set(monkeypatch, tmp_path):
    from jav import admin

    monkeypatch.setattr(goldens, "RUNS_DIR", tmp_path)
    head = {"receipt": "measure", "commit": "abc1234", "clean": True, "engine": "jev", "use_cache": True}
    row = {"key": "reconcile:pairs", "cases": 100, "answered": 100, "right": 100, "scored": 100, "unit": "cases",
           "refused": None, "error": None}
    (tmp_path / "20261021_100000_measure.jsonl").write_text(json.dumps(head) + "\n" + json.dumps(row) + "\n",
                                                            encoding="utf-8")
    lines = admin.golden_set_lines()
    assert any("reconcile:pairs" in x and "100/100" in x and "abc1234" in x for x in lines)
    assert any(x.startswith("| types |") and "not measured" in x for x in lines)


# --- the command ------------------------------------------------------------------------------------------------------


def test_the_command_lists_the_golden_sets(capsys):
    assert cli.main(["measure", "--list"]) == 0
    out = capsys.readouterr().out
    for key in ("datapoints:invoice_hu:S", "types", "intents", "reconcile:pairs", "reconcile:credit_kinds"):
        assert key in out


def test_the_command_runs_the_chosen_golden_sets(monkeypatch, tmp_path, capsys):
    _fake_round(monkeypatch)
    monkeypatch.setattr(goldens, "RUNS_DIR", tmp_path)
    assert cli.main(["measure", "types", "reconcile:pairs"]) == 0
    assert len(list(tmp_path.glob("*_measure.jsonl"))) == 1


def test_the_command_refuses_an_unknown_golden_set_and_a_paid_round_of_many(capsys):
    assert cli.main(["measure", "nonsense"]) == 2
    assert "nonsense" in capsys.readouterr().out
    assert cli.main(["measure", "types", "intents", "--jev-budget-usd", "0.01"]) == 2
    assert "one golden set" in capsys.readouterr().out
