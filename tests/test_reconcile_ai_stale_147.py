"""147 (DECISIONS 147): after the AI's question changes (the kind of payment gains salary, call site 1.1.0), a run with
`stale` asks again only the lines whose answer came from an older version of the question; a line whose answer is
current, given by a run on another package sharing it, costs no call.

Synthetic documents, made-up accounts and stand-in models only; no network, no paid call.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from jav import reconcile_ai, store
from tests.test_reconcile_ai_134 import FakeJev, _line
from tests.test_reconcile_ai_partner_136 import MARKET, _ids, _market, _package


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield


def _run(wp: str, tmp_path, jev: FakeJev, monkeypatch, **kw) -> dict:
    monkeypatch.setattr(reconcile_ai, "get_adapter", lambda: jev)
    return reconcile_ai.run(wp, engines=["jev"], limits={"jev": Decimal("0.10")}, out_dir=tmp_path, **kw)


def test_stale_asks_again_only_the_answers_of_an_older_question(db, monkeypatch, tmp_path):
    wp = _package(_market(1)[0], _line("Jane Example", "95.00", memo="for the lessons"))
    _run(wp, tmp_path, FakeJev(), monkeypatch)
    ids = _ids(wp)
    with store.connect() as c:  # the market line's answer came from an older version of the question
        c.execute("UPDATE reconcile_ai_proposals SET config_hash='older' WHERE line_id=?", (ids[MARKET[0]],))
    assert reconcile_ai.estimate(wp)["plan"]["jev"]["requests"] == 0  # without stale: every line has an answer
    assert reconcile_ai.estimate(wp, stale=True)["plan"]["jev"]["requests"] == 1
    jev = FakeJev()
    r = _run(wp, tmp_path, jev, monkeypatch, stale=True)
    assert [s["line"]["counterparty"] for s, _q in jev.asked] == [MARKET[0]]
    assert r["counts"]["jev"]["asked"] == 1 and r["counts"]["jev"]["skipped"] == 1
    assert reconcile_ai.estimate(wp, stale=True)["plan"]["jev"]["requests"] == 0


def test_an_older_answer_is_not_lent_to_the_partners_other_lines(db, monkeypatch, tmp_path):
    wp = _package(*_market(2))
    _run(wp, tmp_path, FakeJev(), monkeypatch)
    with store.connect() as c:
        c.execute("UPDATE reconcile_ai_proposals SET config_hash='older'")
    jev = FakeJev()
    r = _run(wp, tmp_path, jev, monkeypatch, stale=True)
    assert len(jev.asked) == 1 and r["counts"]["jev"]["inherited"] == 1  # asked once, lent fresh to the other line
