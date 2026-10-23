"""197 (plan 197 K2a): field proposals for teaching a type, from a held-out family's development half's general facts.

The names that recur in at least a few development documents become proposals; code joins only the spellings of one
name and a bilingual label's first part, never synonyms; a date kind needs every value to be exactly one date. The
facts come from the family's latest measurement; a development document without one is refused. Synthetic facts only;
no AI call."""

import json

import pytest

from jav import cli, type_teaching
from jav.core import store


def _fact(prop, value, *, entity="jegy", support=0.9):
    return {"proposal": {"entity": entity, "property": prop, "value": value, "state": "stated"},
            "grounding": "literal_match", "semantic_support": support}


def test_a_fact_name_becomes_an_ascii_key():
    assert type_teaching.field_key("Időpont") == "idopont"
    assert type_teaching.field_key("születési hely") == "szuletesi_hely"
    assert type_teaching.field_key("2. sor") == "field_2_sor"


def test_only_recurring_names_are_proposed_with_their_spellings_joined():
    docs = {
        "a": [_fact("Sor/Row", "5"), _fact("időpont", "2026.05.20. 20:00"), _fact("mérkőzés", "A - B")],
        "b": [_fact("sor", "7"), _fact("Időpont", "2026.06.01."), _fact("meccs", "C - D")],
        "c": [_fact(" sor ", "9"), _fact("időpont", "június 3."), _fact("sor", "10", support=0.1)],
    }
    by_key = {p.key: p for p in type_teaching.propose(docs, min_documents=3)}
    assert set(by_key) == {"sor", "idopont"}  # the synonyms stay apart, under the threshold
    row = by_key["sor"]
    assert (row.documents, row.repeated, row.supported, row.kind) == (3, 1, 3, "text")
    assert row.names == ("jegy. sor ", "jegy.Sor/Row", "jegy.sor")
    assert by_key["idopont"].kind == "text"  # "június 3." has no year: not exactly one date
    assert {p.key for p in type_teaching.propose(docs, min_documents=1)} >= {"merkozes", "meccs"}


def test_a_date_kind_needs_every_value_to_be_one_date():
    docs = {k: [_fact("kiállítás dátuma", v)] for k, v in (("a", "2026.05.20."), ("b", "2026-06-01"), ("c", "2026. 07. 02."))}
    [proposal] = type_teaching.propose(docs, min_documents=3)
    assert (proposal.key, proposal.kind) == ("kiallitas_datuma", "date")


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from jav.core import cfg

    halves = {"families": {"demo": {"development": ["a" * 64, "b" * 64], "evaluation": ["c" * 64]}}}
    original = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: halves if name == "golden_facts" else original(name))
    with store.use_store(tmp_path / "teach.sqlite"):
        from jav.documents import native_results  # noqa: F401 - the native tables

        yield tmp_path


def _outcome(sha, facts, *, scope="measure-20261022_071649-facts_demo"):
    payload = json.dumps({"interpretation": {"facts": facts} if facts is not None else None})
    with store.connect() as c:
        c.execute("INSERT INTO native_outcomes(outcome_id, graph_id, run_id, item_id, reading_id, payload, payload_sha256)"
                  " VALUES (?,?,?,?,?,?,?)", (f"o-{sha[:4]}-{scope}", f"{scope}:{sha[:16]}", scope, sha, "r", payload, "x"))


def test_the_facts_come_from_the_latest_measurement_and_a_missing_one_is_refused(isolated, capsys):
    rejected = {**_fact("sor", "Z-0"), "grounding": "rejected"}
    _outcome("a" * 64, [_fact("sor", "Z-1"), rejected])
    with pytest.raises(type_teaching.TeachingError):
        type_teaching.development_facts("demo")
    assert cli.main(["type-propose", "demo"]) == 2
    _outcome("b" * 64, None)  # a measurement without an answer does not count
    with pytest.raises(type_teaching.TeachingError):
        type_teaching.development_facts("demo")
    _outcome("b" * 64, [_fact("sor", "Z-2")], scope="measure-20261022_090000-facts_demo")
    facts = type_teaching.development_facts("demo")
    assert [len(facts[s]) for s in ("a" * 64, "b" * 64)] == [1, 1]  # the rejected fact is left out
    out = isolated / "proposal.json"
    assert cli.main(["type-propose", "demo", "--min-documents", "2", "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert (report["documents"], [f["key"] for f in report["fields"]]) == (2, ["sor"])
    assert "Z-" not in out.read_text(encoding="utf-8")  # names and counts only, no value


# --- K2b-c: the draft, its candidate pack and its golden set ------------------------------------------------------------


DRAFT = {
    "meta": {"name": "type_draft:demo_taught", "version": "0.1.0", "changelog": [{"version": "0.1.0", "date": "2026-10-22", "note": "test"}]},
    "key": "demo_taught", "label": "Demó (tanított)", "family": "demo", "parent": "ticket",
    "document": "A demo ticket with an issue date",
    "fields": [{"key": "ticket_id", "label": "Jegyazonosító", "kind": "text", "meaning": "the ticket's id"},
               {"key": "issued", "label": "Kiállítva", "kind": "date", "meaning": "the day it was issued"},
               {"key": "price", "label": "Ár", "kind": "money", "meaning": "the price", "scored": False}],
}


def _draft(**change):
    return type_teaching.TaughtDraft.model_validate({**DRAFT, **change})


@pytest.mark.parametrize("change", [
    {"fields": [DRAFT["fields"][0], DRAFT["fields"][0]]},                        # a key twice
    {"fields": [{**DRAFT["fields"][0], "kind": "list"}]},                        # a list is not taught yet
    {"fields": [{**DRAFT["fields"][2]}]},                                        # nothing scored
    {"key": "Demo Taught"},                                                      # not an identifier
])
def test_a_draft_that_cannot_make_a_pack_is_refused(change):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _draft(**change)


def test_the_candidate_is_never_detected_and_measured_only_by_its_own_key():
    from datetime import date

    files = type_teaching.candidate(_draft(), today=date(2026, 10, 22))
    pack, site = files["pack"], files["callsite"]
    assert (pack["auto_detect"], pack["golden_type_key"], pack["arms"], pack["parent"]) == (False, "demo_taught", ["G"], "ticket")
    assert pack["scored_fields"] == ["ticket_id", "issued"] and pack["meta"]["taught"]["state"] == "candidate"
    assert (site["inherits"], site["field_specs"]["issued"]) == ("verify", "the day it was issued")
    assert "- `issued`: the day it was issued. Write it as an ISO date (YYYY-MM-DD)." in files["prompt"]
    assert "Write it as a decimal number" in files["prompt"] and files["prompt"].startswith("<!--")
    assert files["schema"]["properties"]["price"]["type"] == ["string", "null"]


def test_a_candidate_is_written_but_a_pack_that_is_not_one_is_never_overwritten(tmp_path):
    dirs = {"types_dir": tmp_path, "callsites_dir": tmp_path, "prompts_dir": tmp_path}
    paths = type_teaching.write_candidate(_draft(), **dirs)
    assert [p.name for p in paths] == ["demo_taught.json", "verify_demo_taught.json", "demo_taught_prompt.md",
                                       "demo_taught_schema.json"]
    type_teaching.write_candidate(_draft(document="A demo ticket"), **dirs)  # still the draft's candidate: replaced
    assert json.loads(paths[0].read_text(encoding="utf-8"))["document"] == "A demo ticket"
    paths[0].write_text(json.dumps({"meta": {"name": "type:demo_taught", "version": "1.0.0"}}), encoding="utf-8")
    with pytest.raises(type_teaching.TeachingError):
        type_teaching.write_candidate(_draft(), **dirs)


def test_the_registry_checklist_names_only_what_is_missing(tmp_path):
    for rel, data in (("configs/field_labels.json", {"fields": {"ticket_id": "Jegyazonosító", "issued": "Kelt"},
                                                     "doc_types": {}, "by_type": {}}),
                      ("configs/capability_catalog.json", {"expected_document_keys": []}),
                      ("configs/doc_types.json", {"old_type_map": {}}), ("configs/engine_matrix.json", {"sites": {}}),
                      ("configs/naming.json", {"types": {}})):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_request_keys_190.py").write_text("", encoding="utf-8")
    todo = type_teaching.registry_entries(_draft(), root=tmp_path)
    assert len(todo) == 8  # its name, a new field (price), its own name of a shared one (issued), and five registries
    assert any('"by_type": {"demo_taught": {"issued": "Kiállítva"}}' in t for t in todo)
    labels = {"fields": {"ticket_id": "Jegyazonosító", "issued": "Kelt", "price": "Ár"},
              "doc_types": {"demo_taught": "Demó (tanított)"}, "by_type": {"demo_taught": {"issued": "Kiállítva"}}}
    (tmp_path / "configs" / "field_labels.json").write_text(json.dumps(labels), encoding="utf-8")
    (tmp_path / "configs" / "capability_catalog.json").write_text(json.dumps({"expected_document_keys": ["demo_taught"]}),
                                                               encoding="utf-8")
    (tmp_path / "configs" / "doc_types.json").write_text(json.dumps({"old_type_map": {"demo_taught": "ticket"}}), encoding="utf-8")
    (tmp_path / "configs" / "engine_matrix.json").write_text(json.dumps({"sites": {"verify_demo_taught": {}}}), encoding="utf-8")
    (tmp_path / "configs" / "naming.json").write_text(json.dumps({"types": {"demo_taught": {}}}), encoding="utf-8")
    (tmp_path / "tests" / "test_request_keys_190.py").write_text('"demo_taught": "a",\n"demo_taught": "b",\n', encoding="utf-8")
    assert type_teaching.registry_entries(_draft(), root=tmp_path) == []


def test_the_taught_tickets_files_are_what_its_draft_makes():
    """The generated files are edited through the draft only: they are exactly what the draft makes, on its date; a
    detection switch (199, K2d) adds only its version records and turns `auto_detect`."""
    from datetime import date

    draft = type_teaching.load_draft("belepo_jegy_taught")
    files = type_teaching.candidate(draft, today=date(2026, 10, 22))
    paths = type_teaching.candidate_paths(draft.key)
    assert json.loads(paths["schema"].read_text(encoding="utf-8")) == files["schema"]
    assert paths["prompt"].read_text(encoding="utf-8") == files["prompt"]
    site = json.loads(paths["callsite"].read_text(encoding="utf-8"))
    assert {k: v for k, v in site.items() if k != "meta"} == {k: v for k, v in files["callsite"].items() if k != "meta"}
    pack, made = json.loads(paths["pack"].read_text(encoding="utf-8")), files["pack"]
    assert {k: v for k, v in pack.items() if k not in ("meta", "auto_detect")} == {
        k: v for k, v in made.items() if k not in ("meta", "auto_detect")}
    assert [pack["meta"]["changelog"][0][k] for k in ("version", "date")] == [made["meta"]["changelog"][0][k] for k in ("version", "date")]
    assert {k: pack["meta"]["taught"][k] for k in ("family", "draft")} == {k: made["meta"]["taught"][k] for k in ("family", "draft")}
    assert type_teaching.registry_entries(draft) == []  # registered everywhere


def test_a_taught_candidate_is_measured_on_its_familys_evaluation_half_only(monkeypatch):
    from jav import evals_facts, goldens
    from jav.evals import GoldenCase

    def fact_case(name, half):
        return evals_facts.FactCase(case=GoldenCase(case_id=name, pdf=None, expected={}, expected_valid=True,
                                                    type_key="belepo_jegy"), sha256=name * 64, half=half)

    monkeypatch.setattr(evals_facts, "cases", lambda family: [fact_case("a", "development"), fact_case("b", "evaluation")])
    golden = goldens.get("taught:belepo_jegy_taught:evaluation")
    assert (golden.layer, golden.owner, golden.count()) == ("datapoints", "belepo_jegy_taught", 1)
    seen = {}

    def fake_golden(arm, run_one, *, cases, type_key, label, **_kw):
        seen.update(arm=arm, cases=[(c.case_id, c.type_key) for c in cases], type_key=type_key, label=label)
        return []

    monkeypatch.setattr("jav.evals.golden", fake_golden)
    golden.measure(goldens.Options(engine="gpt"))
    assert seen == {"arm": "G", "cases": [("b", "belepo_jegy_taught")], "type_key": "belepo_jegy_taught", "label": "taught"}
    # its own development half, an in-sample check named as such
    own = goldens.get("taught:belepo_jegy_taught:development")
    assert "in-sample" in own.what and own.count() == 1
    assert [g.key for g in goldens.select(["taught:belepo_jegy_taught:evaluation"])] == [golden.key]  # one set
    own.measure(goldens.Options(engine="gpt"))
    assert (seen["cases"], seen["label"]) == ([("a", "belepo_jegy_taught")], "taught_development")
