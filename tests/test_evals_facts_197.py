"""197 (plan 197 K1): the general facts measured on a held-out family's labelled documents.

A type pack's legacy golden documents go straight to the general facts with their pack withheld, and the pack's
scored fields are looked for among the facts by value. The halves are fixed in `configs/golden_facts.json`; a repeated
file is one document. Without a budget the native path gets a zero budget: an earlier answer is reused, a live call is
refused. Synthetic documents and an in-process model only; no provider call."""

from datetime import datetime
from decimal import Decimal
import pytest

from jav import evals_facts, goldens
from jav.core import cfg, store
from jav.evals import GoldenCase
from jav.typepack import get as get_pack
from tests.native_fixtures_109 import runtime_source, synthetic_gpt

PACK = get_pack("belepo_jegy")


def _fact(value, *, grounding="literal_match", state="stated", support=None, entity="ticket", prop="seat"):
    return {"proposal": {"entity": entity, "property": prop, "value": value, "state": state},
            "grounding": grounding, "semantic_support": support}


def test_the_halves_are_fixed_and_apart():
    for family, halves in cfg.load("golden_facts")["families"].items():
        dev, ev = set(halves["development"]), set(halves["evaluation"])
        assert dev and ev and not dev & ev, family
        assert all(len(s) == 64 and int(s, 16) >= 0 for s in dev | ev)
        assert family in get_pack(family).key  # a family names a type pack


def test_a_value_counts_as_found_only_in_a_checked_stated_fact():
    expected = {"seat": "12", "row": "5", "gate": "B", "sector": "C2"}
    facts = [_fact("12", support=0.9), _fact("5", grounding="rejected", prop="row"),
             _fact("b", state="uncertain", prop="gate"), _fact("c2", support=0.2, prop="sector")]
    s = evals_facts.score(facts, expected, PACK)
    assert set(s) == {"seat", "row", "gate", "sector"}  # only the fields with an expected value
    assert s["seat"] == {"found": True, "supported": True, "rejected_only": False, "names": ["ticket.seat"]}
    assert (s["row"]["found"], s["row"]["rejected_only"]) == (False, True)
    assert (s["gate"]["found"], s["gate"]["rejected_only"]) == (False, True)  # not stated: not found
    assert (s["sector"]["found"], s["sector"]["supported"]) == (True, False)  # the name comparison folds the case


def test_without_jev_a_found_value_has_no_support_judgement():
    s = evals_facts.score([_fact("12")], {"seat": "12"}, PACK)
    assert s["seat"]["found"] and s["seat"]["supported"] is None
    t = evals_facts.totals([{"half": "evaluation", "scores": s}, {"half": "development", "scores": None}])
    assert t == {"documents": 2, "answered": 1, "expected": 1, "found": 1, "supported": 0, "rejected_only": 0}


@pytest.fixture
def family(tmp_path, monkeypatch):
    """One synthetic ticket in the evaluation half, listed twice as the manifest repeats a file."""
    with store.use_store(tmp_path / "facts.sqlite"):
        doc, _ = runtime_source(tmp_path, monkeypatch)  # "Order code: 0012", read in process
        case = GoldenCase(case_id="ticket-a", pdf=doc, expected={"seat": "0012", "row": "7"}, expected_valid=True,
                          type_key="belepo_jegy")
        monkeypatch.setattr(evals_facts, "load_cases", lambda key: [case, case])
        import hashlib
        sha = hashlib.sha256(doc.read_bytes()).hexdigest()
        monkeypatch.setattr(evals_facts, "_split", lambda key: {sha: "evaluation"})
        monkeypatch.setattr(evals_facts, "RUNS_DIR", tmp_path / "runs")
        yield sha


def test_a_document_outside_the_split_is_refused(family, monkeypatch):
    monkeypatch.setattr(evals_facts, "_split", lambda key: {})
    with pytest.raises(evals_facts.FactsGoldenError):
        evals_facts.cases("belepo_jegy")


class _Clock:
    """Each measurement a second later, so each has a scope of its own (a scope's name is its second)."""

    seconds = 0

    @classmethod
    def now(cls):
        cls.seconds += 1
        return datetime(2026, 10, 22, 12, 0, cls.seconds % 60)


def test_measured_once_per_file_and_free_again_from_the_earlier_answer(family, monkeypatch):
    monkeypatch.setattr(evals_facts, "datetime", _Clock)
    requests = synthetic_gpt(monkeypatch, payload={"facts": [
        {"entity": "ticket", "property": "seat", "value": "0012", "state": "stated",
         "citations": [{"occurrence_id": "o0", "element_id": "e0", "quote": "Order code: 0012"}]}], "gaps": []})
    assert evals_facts.count("belepo_jegy") == 1  # the repeated file is one document
    [row] = evals_facts.measure("belepo_jegy", jev=False, budget_usd=Decimal("1"))
    assert (row["outcome"], row["half"], row["sha256"]) == ("succeeded", "evaluation", family)
    assert row["scores"]["seat"]["found"] and not row["scores"]["row"]["found"]
    assert row["counts"]["facts"] == 1 and len(requests) == 1
    [again] = evals_facts.measure("belepo_jegy", jev=False)  # no budget: the earlier answer only
    assert again["scores"] == row["scores"] and len(requests) == 1
    [live] = evals_facts.measure("belepo_jegy", jev=False, use_cache=False)  # asking again without a budget: refused
    assert live["scores"] is None and live["outcome"] == "failed" and len(requests) == 1


def test_the_family_is_a_golden_set_of_the_shared_measurement(family, monkeypatch):
    synthetic_gpt(monkeypatch)
    golden = goldens.get("facts:belepo_jegy")
    assert (golden.layer, golden.owner, golden.count()) == ("datapoints", "native", 1)
    outcome = golden.measure(goldens.Options(engine="gpt", budget_usd=Decimal("1")))
    assert (outcome.unit, outcome.cases, outcome.answered, outcome.scored) == ("values", 1, 1, 2)
