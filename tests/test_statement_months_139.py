"""139 (DECISIONS 139): one valid statement per own account, currency and day.

Two statements of the same account and currency booking the same days: the better source replaces the other when it
covers the other's whole period (code-read and balance-checked > extracted and balance-checked > unchecked); an equal
rank or a partial cover is a conflict a person decides, and a person's choice wins over the rule. A replaced
statement's decisions go to the same lines of the statement that replaced it; what has no same line is left over.
Synthetic statements only."""

from __future__ import annotations

import pytest

from jav import statement_months as sm

def _st(sid: str, start: str, end: str, *, doc_type: str = "statement_table", verified: bool = True, currency: str = "HUF",
        account: str = "117730161234567800000000", lines: list[dict] | None = None, seq: int = 1) -> dict:
    lines = lines if lines is not None else [_ln(sid, "2026-01-05", "100.00"), _ln(sid, "2026-01-20", "250.00", "credit")]
    return {"id": sid, "doc_type": doc_type, "account": account, "currency": currency, "period_start": start, "period_end": end,
            "verified": verified, "lines": lines, "seq": seq, "opening_balance": "0", "closing_balance": "0"}


def _ln(sid: str, day: str, amount: str, direction: str = "debit", n: int = 0) -> dict:
    return {"id": f"{sid[:4]}:{day}:{amount}:{direction}:{n}", "booking_date": day, "amount": amount, "direction": direction,
            "statement_id": sid}


def test_rank_follows_the_configured_order():
    assert sm.rank(_st("a", "2026-01-01", "2026-01-31")) == 0  # code-read, checked
    assert sm.rank(_st("b", "2026-01-01", "2026-01-31", doc_type="statement_erste")) == 1  # extracted, checked
    assert sm.rank(_st("c", "2026-01-01", "2026-01-31", verified=False)) == 2  # the Erste export without its PDF
    assert sm.rank(_st("d", "2026-01-01", "2026-01-31", doc_type="statement_cib", verified=False)) == 2


@pytest.mark.parametrize("a, b, expected", [
    (("2026-01-01", "2026-01-31"), ("2026-01-15", "2026-02-14"), True),
    (("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-02-28"), False),  # adjacent
    (("2026-01-05", "2026-02-04"), ("2026-02-04", "2026-03-04"), False),  # a card cycle starting on the closing day
    (("2026-01-01", "2026-01-31"), ("2026-01-01", "2026-01-31"), True),  # the same month twice
    (("2026-01-01", "2026-01-31"), ("2026-01-31", "2026-01-31"), True),  # a one-day statement on the last day
])
def test_overlap(a, b, expected):
    assert sm.overlaps(sm.dates(*a), sm.dates(*b)) is expected
    assert sm.overlaps(sm.dates(*b), sm.dates(*a)) is expected


def test_the_better_source_replaces_the_worse_and_takes_its_decisions():
    old = _st("old-xml-0000000000", "2026-01-01", "2026-01-31", verified=False, seq=1)
    new = _st("new-xml-pdf-000000", "2026-01-01", "2026-01-31", seq=2)
    res = sm.resolve([old, new], {})
    assert res.replaced == {old["id"]: sm.Replacement(old["id"], new["id"], "rule")}
    assert res.conflicts == []
    assert res.line_map == {old["lines"][0]["id"]: new["lines"][0]["id"], old["lines"][1]["id"]: new["lines"][1]["id"]}
    assert res.orphans == {}
    assert [s["id"] for s in res.live([old, new])] == [new["id"]]


def test_the_rank_decides_not_the_order_of_processing():
    better = _st("code-00000000000000", "2026-01-01", "2026-01-31", seq=1)
    later = _st("ai-pdf-00000000000000", "2026-01-01", "2026-01-31", doc_type="statement_erste", seq=5)
    assert sm.resolve([better, later], {}).replaced[later["id"]].new == better["id"]


def test_equal_rank_or_a_partial_cover_is_a_conflict():
    a = _st("aaaa-0000000000000", "2026-01-01", "2026-01-31")
    # 144: with other lines; the same lines are one statement read twice (test_statement_fields_144)
    b = _st("bbbb-0000000000000", "2026-01-01", "2026-01-31", seq=2,
            lines=[_ln("bbbb", "2026-01-05", "100.00"), _ln("bbbb", "2026-01-21", "300.00", "credit")])
    assert sm.resolve([a, b], {}).conflicts == [(a["id"], b["id"])]
    short = _st("cccc-0000000000000", "2026-01-10", "2026-01-31")  # better, but does not cover the old one's first days
    worse = _st("dddd-0000000000000", "2026-01-01", "2026-01-31", verified=False)
    res = sm.resolve([short, worse], {})
    assert res.replaced == {} and res.conflicts == [(short["id"], worse["id"])]


def test_another_account_or_currency_or_adjacent_months_never_meet():
    jan = _st("jan-00000000000000", "2026-01-01", "2026-01-31")
    feb = _st("feb-00000000000000", "2026-02-01", "2026-02-28", verified=False)
    eur = _st("eur-00000000000000", "2026-01-01", "2026-01-31", currency="EUR", verified=False)
    other = _st("oth-00000000000000", "2026-01-01", "2026-01-31", account="HU42117730169999999900000000", verified=False)
    res = sm.resolve([jan, feb, eur, other], {})
    assert res.replaced == {} and res.conflicts == []


def test_a_persons_choice_wins_and_can_keep_the_worse_one():
    old = _st("old-xml-0000000000", "2026-01-01", "2026-01-31", verified=False)
    new = _st("new-xml-pdf-000000", "2026-01-01", "2026-01-31")
    res = sm.resolve([old, new], {sm.pair_key(old["id"], new["id"]): old["id"]})
    assert res.replaced == {new["id"]: sm.Replacement(new["id"], old["id"], "person")}
    a = _st("aaaa-0000000000000", "2026-01-01", "2026-01-31")
    b = _st("bbbb-0000000000000", "2026-01-01", "2026-01-31")
    assert sm.resolve([a, b], {sm.pair_key(a["id"], b["id"]): b["id"]}).replaced[a["id"]].how == "person"


def test_a_chain_ends_on_the_live_statement():
    unchecked = _st("u-0000000000000000", "2026-01-01", "2026-01-31", verified=False)
    extracted = _st("e-0000000000000000", "2026-01-01", "2026-01-31", doc_type="statement_erste")
    code = _st("c-0000000000000000", "2026-01-01", "2026-01-31")
    res = sm.resolve([unchecked, extracted, code], {})
    assert {k: v.new for k, v in res.replaced.items()} == {unchecked["id"]: code["id"], extracted["id"]: code["id"]}
    assert res.line_map[unchecked["lines"][0]["id"]] == code["lines"][0]["id"]


def test_lines_without_a_same_line_are_left_over_and_repeated_lines_pair_in_order():
    old = _st("old-0000000000000000", "2026-01-01", "2026-01-31", verified=False, lines=[
        _ln("old-", "2026-01-05", "100", n=0), _ln("old-", "2026-01-05", "100", n=1), _ln("old-", "2026-01-07", "7.5")])
    new = _st("new-0000000000000000", "2026-01-01", "2026-01-31", lines=[
        _ln("new-", "2026-01-05", "100.00", n=0), _ln("new-", "2026-01-05", "100.00", n=1), _ln("new-", "2026-01-07", "7.5", "credit")])
    res = sm.resolve([old, new], {})
    assert res.line_map == {old["lines"][0]["id"]: new["lines"][0]["id"], old["lines"][1]["id"]: new["lines"][1]["id"]}
    assert res.orphans == {old["lines"][2]["id"]: old["id"]}  # another direction is another line


def test_carry_moves_the_rows_and_sets_the_orphans_apart():
    res = sm.Resolution(replaced={"S1": sm.Replacement("S1", "S2", "rule")}, conflicts=[], line_map={"L1": "N1"},
                        orphans={"L2": "S1"})
    rows = [{"id": 1, "line_id": "L1", "statement_id": "S1"}, {"id": 2, "line_id": "L2", "statement_id": "S1"},
            {"id": 3, "line_id": "X", "statement_id": "S9"}]
    kept, left = sm.carry(rows, res)
    assert kept == [{"id": 1, "line_id": "N1", "statement_id": "S2", "carried_from": "L1"},
                    {"id": 3, "line_id": "X", "statement_id": "S9"}]
    assert left == [{"id": 2, "line_id": "L2", "statement_id": "S1"}]
