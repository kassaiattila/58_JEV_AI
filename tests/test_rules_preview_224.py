"""224 (plan G-process-core P3d): a rule file's candidate version tried on the decisions the trace holds - free.

Plain-language summary: before a rule changes, `rules-preview` shows which earlier machine decisions would come out
otherwise: for every decision point that reads the rule file, how many decisions the trace holds, how many would change
and how, and which to-dos would open or close. Each rule is run on the stored inputs twice, with the rule files in use
now and with the candidate in place of one, each in a process of its own; nothing in the store changes and no AI is
asked. Here on an invented store: the file in use as its own candidate changes nothing; a known threshold change
changes exactly the decisions inside the moved band; a changed duplicate family closes one kind of to-do and opens
another.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jav import cli
from jav.app import registrations
from jav.core import cfg, store, todo_kinds, trace
from jav.domains.finance import duplicates
from jav.evals import rules_preview
from jav.flows import flow_detect
from tests.test_before_after_replay_173 import processed  # noqa: F401 - pytest fixture

TAX = "12345676-2-41"


@pytest.fixture
def traced(tmp_path):
    """An invented store whose trace holds five type decisions (the confidence 0.55, 0.62, 0.65, 0.75, 0.9) and one
    duplicate decision (a pair differing only in its issue date: a modified version)."""
    registrations.load_all()
    path = tmp_path / "preview.sqlite"
    with store.use_store(path):
        with store.connect() as c:
            store.begin_immediate(c)
            for n, conf in enumerate((0.55, 0.62, 0.65, 0.75, 0.9)):
                inputs = {"engine": "jev", "doc_type": "invoice", "confidence": conf, "measured": True,
                          "probabilities": {"invoice": conf, "other": round(1 - conf, 2)}}
                trace.record_in(c, flow_detect.DOC_TYPE_POINT, subject=("document", f"doc-{n}"), inputs=inputs,
                                outcome=flow_detect.doc_type_rule(inputs), keys={"policy.json": ("bands.default.choice_human_max_conf",)})
            fields = {"invoice_number": "INV-2026/7", "supplier_tax_id": TAX, "supplier_name": "Example Trading Ltd",
                      "issue_date": "2026-09-02", "gross_total": "1270.00", "currency": "HUF"}
            inputs = {"doc_id": "a" * 64, "doc_type": "invoice_hu", "fields": fields,
                      "others": [{"doc_id": "b" * 64, "doc_type": "invoice_hu", "fields": {**fields, "issue_date": "2026-09-03"},
                                  "seq": 1, "decided": False}]}
            trace.record_in(c, duplicates.DUPLICATE_POINT, subject=("document", "a" * 64), inputs=inputs,
                            outcome=duplicates.duplicate_rule(inputs), keys=duplicates.TRACE_KEYS)
    return path


def _candidate(tmp_path: Path, name: str, change) -> Path:
    data = json.loads(cfg.path_of(name).read_text(encoding="utf-8"))
    change(data)
    data["meta"]["version"] = "9.9.9"
    out = tmp_path / f"{name}.candidate.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def _point(report: dict, code: str) -> dict:
    return next(p for p in report["points"] if p["point"] == code)


def test_the_file_in_use_as_its_own_candidate_changes_nothing(traced) -> None:
    report = rules_preview.preview("policy.json", cfg.path_of("policy").read_bytes(), store_path=traced)
    assert report["same_content"] is True
    doc_type = _point(report, flow_detect.DOC_TYPE_POINT)
    assert (doc_type["decisions"], doc_type["changed"], doc_type["errors"]) == (5, 0, 0)
    assert {p["point"] for p in report["points"]} >= {"detect.doc_type", "detect.detail_type", "extract.route", "email.intent"}
    assert report["total"] == {"decisions": 5, "changed": 0, "errors": 0}


def test_a_moved_threshold_changes_exactly_the_decisions_inside_the_band(traced, tmp_path) -> None:
    def raise_threshold(d):
        d["bands"]["default"]["choice_human_max_conf"] = 0.7

    candidate = _candidate(tmp_path, "policy", raise_threshold).read_bytes()
    report = rules_preview.preview("policy.json", candidate, store_path=traced)
    doc_type = _point(report, flow_detect.DOC_TYPE_POINT)
    assert (doc_type["decisions"], doc_type["changed"]) == (5, 2)  # 0.62 and 0.65 now wait for a person
    assert sorted(e["subject"] for e in doc_type["examples"]) == ["document:doc-1", "document:doc-2"]
    assert all(e["changes"] == {"uncertain": [False, True]} for e in doc_type["examples"])
    assert report["candidate"]["version"] == "9.9.9" and report["current"]["version"] == cfg.version("policy")
    with store.use_store(traced), store.read_only():
        assert len(trace.rows(point=flow_detect.DOC_TYPE_POINT)) == 5  # read only: nothing was written


def test_a_changed_duplicate_rule_closes_one_to_do_and_opens_another(traced, tmp_path) -> None:
    def without_the_issue_date(d):
        d["duplicates"]["compared_fields"] = ["gross_total", "currency"]

    candidate = _candidate(tmp_path, "finance", without_the_issue_date).read_bytes()
    report = rules_preview.preview("finance.json", candidate, store_path=traced)
    assert [p["point"] for p in report["points"]] == [duplicates.DUPLICATE_POINT]  # only this point reads the file
    dup = _point(report, duplicates.DUPLICATE_POINT)
    assert (dup["decisions"], dup["changed"]) == (1, 1)
    prefix = "b" * duplicates.PREFIX
    assert dup["closed"] == {todo_kinds.code_of(f"duplicate:variant:{prefix}"): 1}
    assert dup["opened"] == {todo_kinds.code_of(f"duplicate:copy:{prefix}"): 1}


def test_a_candidate_that_is_no_rule_file_is_refused(traced) -> None:
    with pytest.raises(rules_preview.PreviewError, match="not JSON"):
        rules_preview.preview("policy.json", b"{not json", store_path=traced)
    with pytest.raises(rules_preview.PreviewError, match="meta.version"):
        rules_preview.preview("policy.json", b'{"meta": {}}', store_path=traced)
    with pytest.raises(rules_preview.PreviewError, match="no rule file"):
        rules_preview.preview("nothing_here.json", b'{"meta": {"version": "1.0.0"}}', store_path=traced)


def test_a_replay_shows_a_whole_items_effect_of_the_candidate(processed, tmp_path) -> None:  # noqa: F811
    """The replay of a backup's items twice, with the rules in use now and with the candidate: two invented invoices
    whose picks the fake JEV answers with 0.97 wait for a person when the high-stakes threshold is 0.99. Nothing asks a
    provider (the replay's own gate)."""
    made = processed
    def strict(d):
        d["bands"]["high_stakes"]["choice_human_max_conf"] = 0.99

    candidate = _candidate(tmp_path, "policy", strict).read_bytes()
    report = rules_preview.replay("policy.json", candidate, baseline=made["backup"], work_dir=tmp_path / "work",
                                  out_dir=tmp_path / "replays", size=10, jev_cache=made["cache"])
    assert report["replays"]["current"]["passed"] and report["replays"]["candidate"]["passed"]
    assert report["replays"]["current"]["items"] == report["replays"]["candidate"]["items"] == 2
    changed = [d["key"] for d in report["differences"]]
    assert any(k.startswith("replay/") and k.endswith("/rows") for k in changed), changed  # each item's stored rows
    places = [place for d in report["differences"] for place in d["places"]]
    assert any("high_stakes_conf" in place for place in places), places[:10]  # the to-do the stricter band opens
    assert report["replays"]["current"]["live_calls"] == report["replays"]["candidate"]["live_calls"] == 0


def test_the_command_reads_a_candidate_file_or_a_git_reference(traced, tmp_path, capsys) -> None:
    def raise_threshold(d):
        d["bands"]["default"]["choice_human_max_conf"] = 0.7

    candidate = _candidate(tmp_path, "policy", raise_threshold)
    assert cli.main(["rules-preview", "policy.json", "--candidate", str(candidate), "--store", str(traced)]) == 0
    text = capsys.readouterr().out
    assert "detect.doc_type: 5 decisions, 2 would change" in text and "no AI call, nothing written" in text
    assert cli.main(["rules-preview", "policy.json", "--ref", "no-such-ref-224", "--store", str(traced)]) == 2
    assert "no-such-ref-224" in capsys.readouterr().out
    assert rules_preview.from_ref("HEAD", "policy.json")[:1] == b"{"
