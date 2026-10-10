"""136 (backlog F-AI-proposals-only-new, DECISIONS 136): the AI is asked only about the lines that have no answer yet,
and the kind of payment once per partner: the partner's other lines take that answer over without a call. A line with
preselected invoices is still asked on its own (which invoice it pays); a line through a payment app or without a name
is asked alone, as it may pay anyone.

Synthetic documents, made-up accounts and stand-in models only; no network, no paid call.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from jav import gpt_choice, reconcile, reconcile_ai, reconcile_package, store
from tests import test_reconcile_k2_129 as k2
from tests.test_reconcile_ai_134 import ENERGY, TELECOM, FakeJev, _fake_gpt, _line

MARKET = ("EXAMPLEMARKET ONLINE 0001", "EXAMPLEMARKET ONLINE 0002", "EXAMPLEMARKET ONLINE 0003")


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield


def _package(*lines) -> str:
    k2._save_statement("stmt", *lines)
    k2._save("tel", TELECOM)
    k2._save("energy", ENERGY)
    return reconcile_package.create(name="Example", accounts=[reconcile.account_key(k2.OWN)], period_start="2026-04-01",
                                    period_end="2026-04-30", actor="tester")["workpackage_id"]


def _market(n: int = 3) -> list[dict]:
    return [_line(MARKET[i], f"{7 + i}.00", booking=f"2026-04-{3 + 7 * i:02d}") for i in range(n)]


def _run(wp: str, tmp_path, jev: FakeJev, monkeypatch, **kw) -> dict:
    monkeypatch.setattr(reconcile_ai, "get_adapter", lambda: jev)
    return reconcile_ai.run(wp, engines=["jev"], limits={"jev": Decimal("0.10")}, out_dir=tmp_path, **kw)


def _stored(engine: str = "jev") -> dict[str, dict]:
    with store.connect() as c:
        return {r["line_id"]: dict(r) for r in c.execute("SELECT * FROM reconcile_ai_proposals WHERE engine=?", (engine,))}


def _ids(wp: str) -> dict[str, str]:
    """The package's line ids by counterparty name."""
    return {ln["counterparty_name"]: ln["id"] for ln in reconcile_package.workspace(wp)["lines"]}


def test_a_partners_kind_is_asked_once_and_its_other_lines_take_it_over(db, monkeypatch, tmp_path):
    wp = _package(*_market())
    jev = FakeJev()
    r = _run(wp, tmp_path, jev, monkeypatch)
    assert len(jev.asked) == 1 and jev.asked[0][0]["line"]["counterparty"] == MARKET[0]  # the earliest line
    assert r["counts"]["jev"] == {"asked": 1, "inherited": 2, "skipped": 0, "pays": 0, "failed": 0}
    ids, stored = _ids(wp), _stored()
    first = ids[MARKET[0]]
    assert stored[first]["asked_line_id"] is None
    assert [stored[ids[m]]["asked_line_id"] for m in MARKET[1:]] == [first, first]
    assert {(row["kind"], row["kind_probability"]) for row in stored.values()} == {("retail_purchase", 0.9)}
    assert json.loads(stored[ids[MARKET[2]]]["kind_distribution"]) == {"retail_purchase": 0.9, "other": 0.1}
    ai = reconcile_package.workspace(wp)["lines"]
    assert sorted(ln["ai"]["jev"]["asked_line_id"] or "-" for ln in ai) == sorted(["-", first, first])
    rows = [json.loads(x) for x in open(r["raw"], encoding="utf-8")]
    assert sorted(row["how"] for row in rows) == ["asked", "inherited", "inherited"] and {row["engine"] for row in rows} == {"jev"}


def test_a_second_run_asks_only_the_new_lines_and_a_known_partner_costs_no_call(db, monkeypatch, tmp_path):
    wp = _package(_market(1)[0], _line("Jane Example", "95.00", memo="for the lessons"))
    _run(wp, tmp_path, FakeJev(), monkeypatch)
    k2._save_statement("stmt2", _line(MARKET[1], "8.00", booking="2026-04-15"), _line("EXAMPLE BAKERY", "3.00", booking="2026-04-16"))
    jev = FakeJev()
    r = _run(wp, tmp_path, jev, monkeypatch)
    assert [s["line"]["counterparty"] for s, _q in jev.asked] == ["EXAMPLE BAKERY"]
    assert r["counts"]["jev"] == {"asked": 1, "inherited": 1, "skipped": 2, "pays": 0, "failed": 0}
    ids = _ids(wp)
    assert _stored()[ids[MARKET[1]]]["asked_line_id"] == ids[MARKET[0]]


def test_redo_asks_again_but_still_once_per_partner(db, monkeypatch, tmp_path):
    wp = _package(*_market())
    _run(wp, tmp_path, FakeJev(), monkeypatch)
    jev = FakeJev()
    r = _run(wp, tmp_path, jev, monkeypatch, redo=True)
    assert len(jev.asked) == 1 and r["counts"]["jev"] == {"asked": 1, "inherited": 2, "skipped": 0, "pays": 0, "failed": 0}


def test_lines_with_preselected_invoices_are_asked_one_by_one_and_lend_their_kind(db, monkeypatch, tmp_path):
    lines = (_line("EXAMPLETELECOM 0001", "100.00", booking="2026-04-05"), _line("EXAMPLETELECOM 0002", "101.00", booking="2026-04-09"),
             _line("EXAMPLETELECOM 0003", "30.00", booking="2026-04-02"))
    wp = _package(*lines)
    jev = FakeJev()
    r = _run(wp, tmp_path, jev, monkeypatch)
    assert [("pays" in q) for _s, q in jev.asked] == [True, True]  # the 30.00 line has no preselected invoice
    assert r["counts"]["jev"] == {"asked": 2, "inherited": 1, "skipped": 0, "pays": 2, "failed": 0}
    ids = _ids(wp)
    inherited = _stored()[ids["EXAMPLETELECOM 0003"]]
    assert inherited["asked_line_id"] == ids["EXAMPLETELECOM 0001"] and inherited["pays"] is None
    assert json.loads(inherited["options"]) == []


def test_a_line_through_a_payment_app_or_without_a_name_is_asked_alone(db, monkeypatch, tmp_path):
    lines = (_line("SIMPLEP*iCsekk app 0001", "3.00", booking="2026-04-03"), _line("SIMPLEP*iCsekk app 0002", "4.00", booking="2026-04-04"),
             _line(None, "5.00", memo="A", booking="2026-04-05"), _line(None, "6.00", memo="B", booking="2026-04-06"))
    wp = _package(*lines)
    jev = FakeJev()
    r = _run(wp, tmp_path, jev, monkeypatch)
    assert len(jev.asked) == 4 and r["counts"]["jev"]["inherited"] == 0
    assert all(row["asked_line_id"] is None for row in _stored().values())


def test_a_failed_answer_is_not_lent_and_the_line_takes_it_over_next_time(db, monkeypatch, tmp_path):
    wp = _package(*_market())
    r = _run(wp, tmp_path, FakeJev(fail_on=MARKET[0]), monkeypatch)
    assert r["counts"]["jev"] == {"asked": 2, "inherited": 1, "skipped": 0, "pays": 0, "failed": 1}
    ids = _ids(wp)
    assert _stored()[ids[MARKET[2]]]["asked_line_id"] == ids[MARKET[1]]
    jev = FakeJev()
    r = _run(wp, tmp_path, jev, monkeypatch)
    assert jev.asked == [] and r["counts"]["jev"] == {"asked": 0, "inherited": 1, "skipped": 2, "pays": 0, "failed": 0}
    first = _stored()[ids[MARKET[0]]]
    assert first["error"] is None and first["asked_line_id"] == ids[MARKET[1]]


def test_both_engines_ask_once_per_partner(db, monkeypatch, tmp_path):
    wp = _package(*_market())
    monkeypatch.setattr(reconcile_ai, "get_adapter", lambda: FakeJev())
    sent = []
    monkeypatch.setattr(gpt_choice, "ask", lambda *a, **k: sent.append(a) or _fake_gpt(*a, **k))
    r = reconcile_ai.run(wp, engines=["jev", "gpt"], limits={"jev": Decimal("0.10"), "openai": Decimal("0.30")}, out_dir=tmp_path)
    assert len(sent) == 1 and r["counts"]["gpt"] == {"asked": 1, "inherited": 2, "skipped": 0, "pays": 0, "failed": 0}
    assert {row["kind"] for row in _stored("gpt").values()} == {"other"}


def test_the_free_estimate_plans_the_calls_per_engine(db, monkeypatch, tmp_path):
    wp = _package(*_market(), _line("Jane Example", "95.00", memo="for the lessons"))
    est = reconcile_ai.estimate(wp)
    assert (est["lines"], est["with_options"]) == (4, 1)
    assert est["plan"]["jev"] == est["plan"]["gpt"] == {"answered": 0, "requests": 2, "with_options": 1, "inherited": 2}
    _run(wp, tmp_path, FakeJev(), monkeypatch)
    est = reconcile_ai.estimate(wp)
    assert est["plan"]["jev"] == {"answered": 4, "requests": 0, "with_options": 0, "inherited": 0}
    assert Decimal(est["reservations_usd"]["jev"]) == 0 and Decimal(est["reservations_usd"]["openai"]) > 0
