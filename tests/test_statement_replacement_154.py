"""154 (DECISIONS 154): the rule replaces a statement only when none of its lines is lost.

A statement read by code and checked by its balances replaced an AI-extracted one of the same account and period by
rule, even when a line of the old one had no same line on the new one, so a crafted file that reads cleanly could hide
real lines from the reconciliation. Now the rule replaces only when every line of the old statement has its same line
(booking day, amount, direction) on the new one, or when the new one comes from an approved live run (a person has
checked it); otherwise the pair is a conflict a person decides, as a pair of the same rank with other lines. A person's
choice still wins. On the live store the rule replaced 20 statements; 3 lack a line an unapproved trial run's AI read
another way (a swapped date, a credit read as a debit), and all 3 replacing statements come from an approved live run,
so nothing changes there. Synthetic statements only.
"""

from __future__ import annotations

from jav.domains.finance import statement_months as sm
from tests.test_statement_months_139 import _ln, _st


def _pair(new_lines: list[dict]) -> tuple[dict, dict]:
    old = _st("old-ai-000000000000", "2026-01-01", "2026-01-31", doc_type="statement_cib", verified=False, lines=[
        _ln("old-", "2026-01-05", "100.00"), _ln("old-", "2026-01-20", "250.00", "credit")])
    return old, _st("new-code-0000000000", "2026-01-01", "2026-01-31", lines=new_lines, seq=2)


def test_a_better_statement_keeping_every_line_replaces_by_rule():
    old, new = _pair([_ln("new-", "2026-01-05", "100"), _ln("new-", "2026-01-20", "250", "credit"),
                      _ln("new-", "2026-01-25", "9.99")])  # one more line is fine: nothing of the old one is lost
    res = sm.resolve([old, new], {})
    assert res.replaced == {old["id"]: sm.Replacement(old["id"], new["id"], "rule")}
    assert res.conflicts == [] and res.orphans == {}


def test_a_better_statement_dropping_a_line_is_a_conflict():
    old, new = _pair([_ln("new-", "2026-01-05", "100")])
    res = sm.resolve([old, new], {})
    assert res.replaced == {} and res.conflicts == [(new["id"], old["id"])]
    assert [s["id"] for s in res.live([old, new])] == [old["id"], new["id"]]


def test_a_line_read_another_way_is_a_conflict():
    # the live store's case: the same amount on the same day, AI read the credit as a debit
    old, new = _pair([_ln("new-", "2026-01-05", "100"), _ln("new-", "2026-01-20", "250", "debit")])
    assert sm.resolve([old, new], {}).conflicts == [(new["id"], old["id"])]


def test_a_persons_choice_still_replaces_and_sets_the_lost_line_apart():
    old, new = _pair([_ln("new-", "2026-01-05", "100")])
    res = sm.resolve([old, new], {sm.pair_key(old["id"], new["id"]): new["id"]})
    assert res.replaced == {old["id"]: sm.Replacement(old["id"], new["id"], "person")}
    assert res.orphans == {old["lines"][1]["id"]: old["id"]} and res.conflicts == []


def test_the_rule_is_data(monkeypatch):
    old, new = _pair([_ln("new-", "2026-01-05", "100")])
    conf = {**sm._conf(), "keep_every_line": False}
    monkeypatch.setattr(sm, "_conf", lambda: conf)
    assert sm.resolve([old, new], {}).replaced[old["id"]].how == "rule"


def test_a_statement_of_an_approved_live_run_replaces_even_when_it_lacks_a_line():
    old, new = _pair([_ln("new-", "2026-01-05", "100")])
    new["work_run"] = "run-000000000042"
    res = sm.resolve([old, new], {}, approved={"run-000000000042"})
    assert res.replaced == {old["id"]: sm.Replacement(old["id"], new["id"], "rule")}
    assert res.orphans == {old["lines"][1]["id"]: old["id"]}  # the lacking line is left over, as before
    assert sm.resolve([old, new], {}, approved=set()).conflicts == [(new["id"], old["id"])]


def test_the_approval_is_looked_up_in_the_store(tmp_path):
    from jav.core import store
    from tests import test_reconcile_k2_129 as k2

    old, new = _pair([_ln("new-", "2026-01-05", "100")])
    with store.use_store(tmp_path / "r.sqlite"):
        k2._run(k2.RUN, ["new"], approved=True)
        new["work_run"] = k2.RUN
        assert sm.resolve([old, new], {}).replaced[old["id"]].how == "rule"
        new["work_run"] = "run-000000000099"  # unknown, so not approved
        assert sm.resolve([old, new], {}).conflicts == [(new["id"], old["id"])]
