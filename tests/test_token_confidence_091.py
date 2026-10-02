"""091 (GPT field confidence, the owner's decision of 2026-10-02: token probability + code evidence, the weaker
counts): the probability of each top-level value of a structured GPT answer, from the provider's token
log-probabilities. Artificial token streams, no call.
"""

from __future__ import annotations

import json
import math

import pytest

from jav import token_confidence as tc


def _tokens(pieces: list[tuple[str, float]]) -> list[dict]:
    return [{"token": tok, "logprob": math.log(p), "top_logprobs": []} for tok, p in pieces]


def test_value_spans_cover_strings_literals_and_skip_nested_lists():
    text = '{"a":"x\\"y","b":null,"c":12.5,"items":[{"a":"inner"}],"d":""}'
    spans = tc.value_spans(text)
    assert set(spans) == {"a", "b", "c", "d"}  # the list is not a scored value; its inner "a" does not shadow the header
    assert text[slice(*spans["a"])] == '"x\\"y"'  # with its quotes and the escaped quote
    assert text[slice(*spans["b"])] == "null"
    assert text[slice(*spans["c"])] == "12.5"
    assert text[slice(*spans["d"])] == '""'
    assert json.loads(text)  # the fixture itself is valid JSON


def test_value_spans_tolerate_whitespace_and_a_cut_answer():
    assert tc.value_spans('{ "a" : "x" ,\n "b": true }') == {"a": (8, 11), "b": (20, 24)}
    assert tc.value_spans('{"a":"x","b":"unfinish') == {"a": (5, 8)}  # the cut value is left out
    assert tc.value_spans("not json") == {}


def test_probabilities_per_field_joint_min_first():
    toks = _tokens([('{"', 1.0), ("a", 1.0), ('":"', 0.9), ("INV", 0.8), ("-1", 0.5), ('","', 1.0),
                    ("b", 1.0), ('":', 1.0), ("null", 0.6), ("}", 1.0)])
    probs = tc.field_probabilities(toks)
    assert probs["a"]["joint"] == pytest.approx(0.9 * 0.8 * 0.5 * 1.0, abs=1e-4)  # opening quote .. closing quote
    assert probs["a"]["min"] == pytest.approx(0.5, abs=1e-4)
    assert probs["a"]["first"] == pytest.approx(0.9, abs=1e-4)  # the token that decides text against null
    assert probs["a"]["n"] == 4
    assert probs["b"] == {"joint": pytest.approx(0.6, abs=1e-4), "min": pytest.approx(0.6, abs=1e-4),
                          "first": pytest.approx(0.6, abs=1e-4), "n": 1}


def test_only_the_asked_fields_and_nothing_without_tokens():
    toks = _tokens([('{"a":', 1.0), ("1", 0.7), (',"b":', 1.0), ("2", 0.4), ("}", 1.0)])
    assert set(tc.field_probabilities(toks, fields=["b", "x"])) == {"b"}
    assert tc.field_probabilities([]) == {}
    assert tc.field_probabilities(None) == {}
