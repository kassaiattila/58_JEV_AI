"""Képességpróbák: bizonyító sorok és kódos korlátok, hálózat nélkül."""
from types import SimpleNamespace

from jav.experiments.jev_patterns import stitch_and_classify, assess_pair, classify_hierarchy


def test_protected_boundary_cannot_be_overridden_by_model():
    def ask(step, state, questions):
        # Szándékosan túlbuzgó modell: minden szomszédot összefűzne.
        return SimpleNamespace(nouls={"L001": SimpleNamespace(noul=1), "L002": SimpleNamespace(noul=1)},
                               choices={key: SimpleNamespace(choice="item") for key in questions})
    config = {"join_question":"Join {previous} and {current}?", "join_criteria":{},
              "join_after_terminal":.5, "join_after_dangling":.2,
              "block_question":"Classify {block}", "block_types":{"item":"item", "other":"other"}}
    result = stitch_and_classify(["Description", "Annual support for", "the software"], config, ask,
                                blocked_before={1: ["header"]})
    assert [b["source_lines"] for b in result["blocks"]] == [[0], [1, 2]]
    assert result["blocked_before"] == {1: ["header"]}


def test_stitch_keeps_source_lines_and_never_crosses_blank_separator():
    calls = []

    def ask(step, state, questions):
        calls.append((step, state, questions))
        return SimpleNamespace(
            nouls={key: SimpleNamespace(noul=.99) for key in questions},
            choices={key: SimpleNamespace(choice="item") for key in questions},
        )

    config = {"join_question": "Does {current} continue {previous}?",
              "join_criteria": {"true": "continuation", "false": "new item"},
              "join_after_dangling": .7, "join_after_terminal": .9,
              "block_question": "What is {block}?", "block_types": {"item": "item", "other": "other"}}
    lines = ["Annual support for", "the payroll module", "", "A separate item"]
    result = stitch_and_classify(lines, config, ask)
    assert [b["source_lines"] for b in result["blocks"]] == [[0, 1], [3]]
    assert [b["text"] for b in result["blocks"]] == ["Annual support for the payroll module", "A separate item"]
    assert len(calls) == 2 and len(calls[0][2]) == 1
    assert result["joins"] == {"L001": .99}


def test_amount_or_currency_conflict_prevents_match_without_model():
    def no_call(*args):
        raise AssertionError("A kódos kizárásnál nem kell JEV")

    config = {}
    invoice = {"amount": "100.00", "currency": "EUR", "party": "Example"}
    assert assess_pair(invoice, {**invoice, "amount": "99.99"}, config, no_call)["outcome"] == "different"
    assert assess_pair(invoice, {**invoice, "currency": "USD"}, config, no_call)["outcome"] == "different"


def test_missing_reference_stays_visible_and_score_uses_nearest_level():
    def ask(step, state, questions):
        assert state["code_facts"]["amount_equal"] is True
        assert state["code_facts"]["reference_equal"] is None
        return SimpleNamespace(scores={"match": SimpleNamespace(score=1.4, probabilities={0:.1, 1:.4, 2:.5})},
                               nouls={"same_party": SimpleNamespace(noul=.9)})

    config = {"question": "Same payment?", "levels": ["different", "uncertain", "same"], "party_question": "Same party?"}
    result = assess_pair({"amount":"100", "currency":"EUR", "party":"Example"},
                         {"amount":"100.00", "currency":"EUR", "party":"Example"}, config, ask)
    assert result["outcome"] == "uncertain" and result["score"] == 1.4


def test_hierarchy_second_branch_can_win_and_unknown_is_retained():
    seen = []
    def ask(step, state, questions):
        seen.append(list(questions))
        distributions = {"root": {"goods": .52, "services": .46, "other": .02},
                         "goods": {"printer": .4, "paper": .3, "other": .3},
                         "services": {"repair": .98, "training": .01, "other": .01}}
        return SimpleNamespace(choices={k: SimpleNamespace(probabilities=distributions[k]) for k in questions})
    config = {"beam_width": 2, "question": "Select a category", "other": "None of these",
              "tree": {"goods": {"description":"goods", "children":{"printer":"printer", "paper":"paper"}},
                       "services": {"description":"service", "children":{"repair":"repair", "training":"training"}}}}
    result = classify_hierarchy("printer repair", config, ask)
    assert result["label"] == "repair" and result["path"] == ["services", "repair"]
    assert seen == [["root"], ["goods", "services"]]
    assert any(row["path"] == ["other"] for row in result["ranking"])
