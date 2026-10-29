"""231 (stage U, U4c; the owner's decisions of 2026-10-29): a default is tried on the earlier decisions before it is
made active.

Every traced decision that read the key, in a case or outside one, is run again with the values it was made with and
with the tried value in place: the preview counts them, the changed ones (with examples) and the failed ones. A
decision a process's own value of the key decided is counted apart, as a default would not have reached it; one made
while an earlier default was active is replayed with that default and is tried like the others. Nothing is written
and no AI is asked. An invented decision point over a real rule key; an empty store.
"""

from __future__ import annotations

import pytest

from jav.app import registrations, rule_defaults
from jav.core import cfg, store, trace

registrations.load_all()

FILE, KEY = "quotes", "draft.max_lines"


def _max_lines() -> int:
    return cfg.load(FILE)["draft"]["max_lines"]


@pytest.fixture
def db(tmp_path, monkeypatch):
    point = trace.Point("invented.lines", "Whether a quote's lines fit.", "-", __name__, ("quotes.json",),
                        rule=lambda inputs: inputs["lines"] <= _max_lines())
    monkeypatch.setitem(trace._POINTS, point.code, point)
    with store.use_store(tmp_path / "preview.sqlite"):
        rule_defaults.use()
        rule_defaults._forget()
        try:
            yield point
        finally:
            cfg.use_defaults(None)
            rule_defaults._forget()


def _decide(point: trace.Point, lines: int) -> None:
    with store.connect() as c:
        trace.record_in(c, point.code, subject=("quote", f"q{lines}"), inputs={"lines": lines},
                        outcome=point.rule({"lines": lines}), keys={"quotes.json": [KEY]})


def test_a_default_is_tried_on_every_decision_that_read_its_key(db) -> None:
    file_value = _max_lines()
    for lines in (3, 50, file_value + 100):
        _decide(db, lines)
    own = cfg.Overlay({FILE: {KEY: 2}}, {FILE: {KEY: {"setting": "it_quote/rule/quotes.draft.max_lines", "version": 1}}})
    with cfg.overlay(own):  # a case whose process kept its own value
        _decide(db, 1)
    tried = rule_defaults.preview(FILE, KEY, 10)
    assert (tried["decisions"], tried["changed"], tried["failed"], tried["covered"]) == (3, 1, 0, 1)
    [example] = tried["examples"]
    assert (example["subject"], example["before"], example["after"], example["case"]) == ("quote:q50", True, False, None)
    assert tried["file_value"] == file_value
    assert len(trace.rows(point=db.code)) == 4  # nothing written


def test_a_decision_made_under_an_earlier_default_is_replayed_with_it(db) -> None:
    rule_defaults.propose(FILE, KEY, 40, "anna")
    rule_defaults.activate(FILE, KEY, 1, "anna")
    _decide(db, 50)  # outside a case: the active default decided (50 > 40)
    [row] = trace.rows(point=db.code)
    assert row["outcome"] is False and row["rules"][0]["process_values"][0]["setting"] == f"default:{FILE}.{KEY}"
    tried = rule_defaults.preview(FILE, KEY, 100)
    assert (tried["decisions"], tried["changed"], tried["covered"]) == (1, 1, 0)
    assert (tried["examples"][0]["before"], tried["examples"][0]["after"]) == (False, True)


def test_a_value_out_of_bounds_is_not_tried(db) -> None:
    with pytest.raises(rule_defaults.DefaultError, match="between"):
        rule_defaults.preview(FILE, KEY, 0)
