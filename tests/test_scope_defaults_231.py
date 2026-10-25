"""231 (plan stage C, C2d): a scope part may take a default from the parts given, and a case keeps its party and period
in the shared scope's own columns.

A needed part with a default (the reconciliation's accounts: the party's own accounts) need not be given; a value given
wins over it, and a default that finds nothing for the scope is the part's missing error. A part without a default is
still asked first. The case's party and period go into the columns every package's scope keeps them in, so a party's
merge reaches the case and a domain reads its scope as its own packages'; a package taken over gives its party and
period from those columns.
"""

from __future__ import annotations

import pytest

from jav.app import process_runtime, scopes


def _probe(monkeypatch, default):
    calls = []

    def check(value, error):
        if value == "bad":
            raise error("bad probe")
        return value

    def missing(error):
        return error("the probe is missing")

    def fill(scope):
        calls.append(dict(scope))
        return default(scope)

    monkeypatch.setitem(scopes._PARTS, "probe", scopes.Part("probe", __name__, check, str, missing, default=fill))
    return calls


def test_a_needed_part_takes_its_default_from_the_parts_checked_before_it(monkeypatch):
    calls = _probe(monkeypatch, lambda scope: f"of {scope['period'][0]}")
    got = scopes.check(["period", "probe"], {"period": ["2026-06-01", "2026-06-30"]})
    assert got == {"period": ("2026-06-01", "2026-06-30"), "probe": "of 2026-06-01"}
    assert calls == [{"period": ("2026-06-01", "2026-06-30")}]


def test_a_given_value_wins_over_the_default_and_is_checked(monkeypatch):
    calls = _probe(monkeypatch, lambda scope: "default")
    assert scopes.check(["probe"], {"probe": "mine"}) == {"probe": "mine"} and calls == []
    with pytest.raises(scopes.ScopeError, match="bad probe"):
        scopes.check(["probe"], {"probe": "bad"})


def test_a_default_that_finds_nothing_is_the_missing_error(monkeypatch):
    _probe(monkeypatch, lambda scope: None)
    with pytest.raises(scopes.ScopeError, match="the probe is missing"):
        scopes.check(["probe"], {})


def test_a_part_without_a_default_is_still_asked_first(monkeypatch):
    calls = _probe(monkeypatch, lambda scope: "default")
    with pytest.raises(scopes.ScopeError, match="period"):
        scopes.check(["period", "probe"], {})
    assert calls == []


def test_a_person_is_asked_only_the_parts_without_a_default(monkeypatch):
    _probe(monkeypatch, lambda scope: "default")
    assert scopes.asks(["probe", "period", "party"]) == ["party", "period"]


def test_a_case_keeps_its_party_and_period_in_the_shared_columns():
    assert process_runtime._scope_columns({"party": "party-0123456789ab", "period": ("2026-06-01", "2026-06-30"),
                                           "accounts": ["HU1"]}) == {
        "party_id": "party-0123456789ab", "period_start": "2026-06-01", "period_end": "2026-06-30"}
    assert process_runtime._scope_columns({"sources": ["wp-0123456789ab"]}) == {
        "party_id": None, "period_start": None, "period_end": None}


def test_a_package_taken_over_gives_its_party_and_period_from_their_columns():
    stored = {"party_id": "party-0123456789ab", "period_start": "2026-06-01", "period_end": "2026-06-30",
              "parts": {"accounts": ["HU1"]}}
    assert [process_runtime._stored_value(stored, key) for key in ("party", "period", "accounts", "sources")] == [
        "party-0123456789ab", ["2026-06-01", "2026-06-30"], ["HU1"], None]
    assert process_runtime._stored_value({"parts": {"party": "party-ffffffffffff"}, "party_id": None}, "party") == (
        "party-ffffffffffff")
