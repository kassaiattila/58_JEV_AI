"""197 (plan 197 K2a): field proposals for teaching a type, from a held-out family's development half's general facts.

The names that recur in at least a few development documents become proposals; code joins only the spellings of one
name and a bilingual label's first part, never synonyms; a date kind needs every value to be exactly one date. The
facts come from the family's latest measurement; a development document without one is refused. Synthetic facts only;
no AI call."""

import json

import pytest

from jav import cli, store, type_teaching


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
    from jav import cfg

    halves = {"families": {"demo": {"development": ["a" * 64, "b" * 64], "evaluation": ["c" * 64]}}}
    original = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: halves if name == "golden_facts" else original(name))
    with store.use_store(tmp_path / "teach.sqlite"):
        from jav import native_results  # noqa: F401 - the native tables

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
