"""The state snapshot does not present a failed golden run as the latest measurement (076).

On 2026-09-28 the G-path golden runs ran without an OpenAI key: every case failed, and the snapshot showed "no cases"
as if there had been no measurement, hiding the last real one. A run in which no case produced data is skipped, and
named next to the latest real run.
"""

import json

from jav import admin


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _ok_row(case):
    return {"case_id": case, "doc_type": "invoice_hu", "arm": "G", "route": "auto", "review_reasons": [],
            "datapoints": {"invoice_number": "A-1"}, "scores": {"invoice_number": True, "gross_total": False}}


def _failed_row(case):
    return {"case_id": case, "doc_type": "invoice_hu", "arm": "G", "route": "human",
            "review_reasons": ["llm:failed:MissingAPIKeyError", "no_invoice"], "datapoints": None,
            "scores": {"invoice_number": None, "gross_total": None}}


def _g_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(admin, "RUNS_DIR", tmp_path)
    return [g for g in admin.last_golden_results() if g["flow"] == "invoice_hu G-kar"]


def test_failed_newer_run_is_skipped_and_named(tmp_path, monkeypatch):
    _write(tmp_path / "20260921_040000_golden_G.jsonl", [_ok_row("c1"), _ok_row("c2")])
    _write(tmp_path / "20260928_083050_golden_G.jsonl", [_failed_row("c1"), _failed_row("c2")])
    [g] = _g_rows(monkeypatch, tmp_path)
    assert g["file"] == "20260921_040000_golden_G.jsonl"
    assert (g["n"], g["ok"], g["scored"]) == (2, 2, 4)
    assert g["skipped_failed"] == {"file": "20260928_083050_golden_G.jsonl", "reason": "llm:failed:MissingAPIKeyError"}


def test_a_later_real_run_clears_the_note(tmp_path, monkeypatch):
    _write(tmp_path / "20260921_040000_golden_G.jsonl", [_ok_row("c1")])
    _write(tmp_path / "20260928_083050_golden_G.jsonl", [_failed_row("c1")])
    _write(tmp_path / "20261001_090000_golden_G.jsonl", [_ok_row("c1")])
    [g] = _g_rows(monkeypatch, tmp_path)
    assert g["file"] == "20261001_090000_golden_G.jsonl"
    assert g["skipped_failed"] is None


def test_only_failed_runs_still_show_the_latest_with_no_cases(tmp_path, monkeypatch):
    _write(tmp_path / "20260928_083050_golden_G.jsonl", [_failed_row("c1")])
    [g] = _g_rows(monkeypatch, tmp_path)
    assert (g["file"], g["n"], g["scored"]) == ("20260928_083050_golden_G.jsonl", 0, 0)
    assert admin.score_text(g["ok"], g["scored"]) == "nincs eset"
