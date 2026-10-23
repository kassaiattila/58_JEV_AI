"""The read-only view of the rules (218, plan G-process-core P3e): Settings › Rules.

Plain-language summary: for every machine decision point of the decision trace the view shows, in plain words, what it
decides and what it is not for (`configs/rule_help.json`), the rule values it decides with, read from the rule files
the running process loaded, which version of each rule file is in use and since when, and how many decisions the trace
holds, how many of them with the rule files in use now, and the latest. A point without a description, or a value whose
key is not in a file its point reads, fails here. Synthetic data, a temporary store, no paid calls.
"""

from __future__ import annotations

import fnmatch
import json

import pytest
from fastapi.testclient import TestClient

from jav.ai import policy
from jav.app import datasets, registrations, rules_view
from jav.app.tablequery import Query
from jav.core import cfg, rulebook, store, trace
from jav.service import api
from tests.test_workflow_tasks_215 import _monthly
from tests.test_workflows_146 import db  # noqa: F401 - the fixture is used by name


def _help() -> dict:
    registrations.load_all()
    return cfg.load("rule_help")


def _rows() -> dict[str, dict]:
    page = datasets.query("rules", {}, Query(limit=1000))
    return {r["_key"]: r for r in page["rows"]}


def _value(row: dict, key: str) -> dict:
    return next(v for v in row["_values"] if v["key"] == key)


def test_every_decision_point_has_its_plain_description():
    help_ = _help()
    assert set(help_["points"]) == {p.code for p in trace.points()}
    for p in trace.points():
        entry = help_["points"][p.code]
        assert entry["area"] in help_["areas"], p.code
        assert entry["title"].strip() and entry["what"].strip() and entry["not_for"].strip(), p.code
        assert all(help_["files"].get(f, "").strip() for f in p.files), p.code  # each rule file it reads has a title


def test_every_shown_value_is_a_key_of_a_file_its_point_reads():
    help_ = _help()
    for code, entry in help_["points"].items():
        files = trace.point(code).files
        assert entry["values"], code
        for spec in entry["values"]:
            assert any(fnmatch.fnmatchcase(spec["file"], f) for f in files), (code, spec["file"])
            assert spec["format"] in rules_view.FORMATS, (code, spec["format"])
            assert spec["label"].strip(), code
            value = rules_view.resolve(rules_view.config_of(spec["file"]), spec["key"])  # KeyError: not in the file
            if spec["format"] == "labels":  # every code it shows has its own label
                assert set(value) <= set(spec["labels"]), (code, spec["key"])


def test_an_unknown_key_is_refused():
    with pytest.raises(KeyError):
        rules_view.resolve(cfg.load("policy"), "bands.default.no_such_value")
    with pytest.raises(KeyError):
        rules_view.resolve(cfg.load("recipes"), "recipes[no-such-recipe].max_item_usd")


def test_the_view_shows_the_running_rules_in_their_areas(db, monkeypatch):  # noqa: F811
    help_ = _help()
    rows = _rows()
    assert list(rows) == sorted(help_["points"], key=lambda k: list(help_["areas"]).index(help_["points"][k]["area"]))
    route = rows["extract.route"]
    assert (route["area"], route["decision"]) == ("extraction", "Accepting the extracted data")
    assert (route["what"], route["not_for"]) == (help_["points"]["extract.route"]["what"],
                                                 help_["points"]["extract.route"]["not_for"])
    high = _value(route, "bands.high_stakes.choice_human_max_conf")
    assert (high["format"], high["value"]) == ("percent", policy.band("invoice.pick.high_stakes")["choice_human_max_conf"])
    # codes are shown by the interface's own labels (Hungarian source, translated by the interface)
    doc_types = cfg.load("field_labels")["doc_types"]
    hungarian = _value(rows["detect.detail_type"], "detect_issuer.hungarian_types")
    assert hungarian["value"] == [doc_types[k] for k in cfg.load("policy")["detect_issuer"]["hungarian_types"]]
    fields = cfg.load("field_labels")["fields"]
    assert _value(rows["finance.duplicate"], "compared_fields")["value"] == [
        fields[k] for k in cfg.load("duplicates")["compared_fields"]]
    # an email's next step by its code, as the interface names steps everywhere; the quote request's reads the text too
    sent = _value(rows["email.next_flow"], "sent_route")
    assert (sent["format"], sent["value"]) == ("route", {"code": "archive:sent", "reads_text": False})
    by_intent = _value(rows["email.next_flow"], "intent_route")
    intents = datasets.label_set("intent")
    assert by_intent["format"] == "routes"
    assert by_intent["value"][0] == [intents["quote_request"], {"code": "m2:quote_request", "reads_text": True}]
    assert by_intent["value"][1] == [intents["szamlakuldes"], {"code": "human:fetch_document", "reads_text": False}]
    assert datasets.label_set("next_flow")["archive:sent"] in rows["email.next_flow"]["values"]
    assert _value(rows["email.intent"], "signal_review")["value"] == ["An instruction hidden in the email"]
    engine = _value(rows["ocr.escalation"], "escalation.engine")
    assert (engine["format"], engine["value"]) == ("name", "Azure DI")
    email = _value(rows["workflow.budget_gate"], "recipes[processing].max_item_usd_by_kind.email.*")
    assert (email["format"], email["value"]) == ("usd", [["JEV", "0.05"]])
    # a changed rule shows at once: the values are read from the loaded rule file, not kept
    monkeypatch.setitem(cfg.load("policy")["ocr"], "escalate_min_mean_conf", 0.9)
    assert _value(_rows()["ocr.escalation"], "ocr.escalate_min_mean_conf")["value"] == 0.9
    # the searchable text of the values names each label and value
    assert "Sent when the average word confidence is below 90 %" in _rows()["ocr.escalation"]["values"]


def test_each_rule_file_shows_its_version_and_since_when_it_is_in_use(db):  # noqa: F811
    snapshot = rulebook.current()
    row = _rows()["extract.route"]
    files = {f["file"]: f for f in row["_files"]}
    assert list(files) == ["policy.json", "types/*.json"]
    policy_file = files["policy.json"]
    meta = cfg.load("policy")["meta"]
    dated = next(e["date"] for e in meta["changelog"] if e["version"] == meta["version"])
    assert (policy_file["title"], policy_file["version"], policy_file["dated"], policy_file["since"]) == (
        "Shared decision thresholds", snapshot.files["policy.json"].version, dated, None)  # no run has used it yet
    packs = files["types/*.json"]
    assert packs["count"] == sum(fnmatch.fnmatchcase(p, "types/*.json") for p in snapshot.files)
    assert packs["version"] is None
    with store.connect() as c:  # a run, an item or a decision stores the snapshot it was made with
        rulebook.store_in(c, snapshot)
        first = c.execute("SELECT first_seen_at FROM rule_files WHERE sha256=?",
                          (snapshot.files["policy.json"].sha256,)).fetchone()[0]
    files = {f["file"]: f for f in _rows()["extract.route"]["_files"]}
    assert files["policy.json"]["since"] == first and files["types/*.json"]["since"] == first
    assert "Shared decision thresholds (policy.json) " + snapshot.files["policy.json"].version in _rows()["extract.route"]["files"]


def test_the_decisions_are_counted_from_the_trace(db):  # noqa: F811
    rows = _rows()
    assert (rows["workflow.budget_gate"]["decisions"], rows["workflow.budget_gate"]["current"],
            rows["workflow.budget_gate"]["last_at"]) == (0, 0, None)
    wf_id = _monthly(db)
    gates = trace.rows(point="workflow.budget_gate", case_id=wf_id)
    gate = _rows()["workflow.budget_gate"]
    assert (gate["decisions"], gate["current"], gate["last_at"]) == (len(gates), len(gates), max(r["at"] for r in gates))
    assert len(gates) == 2
    # a decision made with an earlier version of a rule file counts, but not as one made with the rules in use now
    earlier = [{**r, "sha256": "0" * 64, "version": "0.9.0"} for r in gates[0]["rules"]]
    with store.connect() as c:
        c.execute("INSERT INTO decision_trace(point, subject_kind, subject_id, inputs, inputs_sha, outcome, rules,"
                  " snapshot_id, at) VALUES ('workflow.budget_gate', 'workflow_step', 'old', '{}', '', '{}', ?, '', ?)",
                  (json.dumps(earlier), "2000-01-01T00:00:00+00:00"))
    gate = _rows()["workflow.budget_gate"]
    assert (gate["decisions"], gate["current"], gate["last_at"]) == (3, 2, max(r["at"] for r in gates))
    assert _rows()["extract.route"]["decisions"] == 0


def test_the_service_serves_the_rules_table(tmp_path):
    c = TestClient(api.create_app(store_path=tmp_path / "w.sqlite"), base_url="http://127.0.0.1:8930")
    assert "rules" in {d["name"] for d in c.get("/api/datasets").json()["datasets"]}
    body = c.post("/api/datasets/rules/query", json={"scope": {}, "query": {}}).json()
    assert {r["_key"] for r in body["rows"]} == set(_help()["points"])
    columns = {col["key"]: col for col in body["columns"]}
    assert columns["area"]["labels"] == _help()["areas"]
    assert [k for k, col in columns.items() if not col["hidden"]] == ["area", "decision", "values", "files", "decisions"]
