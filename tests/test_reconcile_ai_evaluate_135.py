"""135 (plan 134 P2): the AI's stored answers measured against a person's decisions on a package's lines, per engine -
free and read only. A paired line's invoice and a marked line's reason are the reference; open lines do not count.

Synthetic documents, made-up accounts and stored answers only; no model is called.
"""

from __future__ import annotations

import pytest

from jav import reconcile, reconcile_ai, reconcile_package as rp, store
from tests import test_reconcile_k2_129 as k2
from tests.test_reconcile_ai_134 import ENERGY, LINES, TELECOM


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield


def _answer(options, pays=None, kind="other", error=None):
    return {"options": options, "pays": pays, "pays_probability": 0.8 if pays else None, "kind": kind, "kind_probability": 0.9,
            "measured": error is None, "error": error}


def test_the_answers_are_measured_against_the_persons_pairs_and_marks(db):
    stmt = k2._save_statement("stmt", *LINES)
    tel, energy = k2._save("tel", TELECOM), k2._save("energy", ENERGY)
    wp_id = rp.create(name="Example", accounts=[reconcile.account_key(k2.OWN)], period_start="2026-04-01",
                      period_end="2026-04-30", actor="tester")["workpackage_id"]
    telecom, lessons, market = [{"id": ln["id"], "statement_id": stmt} for ln in reconcile.with_line_ids(stmt, list(LINES))]
    save = lambda line, engine, answer: reconcile_ai._save(wp_id, line, engine, answer, None)  # noqa: E731
    save(telecom, "jev", _answer([tel, energy], pays=tel, kind="utility_or_telecom"))
    save(telecom, "gpt", _answer([tel, energy], kind="retail_purchase"))
    save(lessons, "jev", _answer([], kind="person_transfer"))
    save(lessons, "gpt", _answer([energy], pays=energy, kind="retail_purchase"))
    save(market, "jev", _answer([], kind="retail_purchase"))
    rp.allocate(wp_id, [{"invoice_doc_id": tel, "line_id": telecom["id"]}], note=None, actor="t")
    rp.mark(wp_id, [lessons["id"]], category="private", note=None, actor="t")

    ev = reconcile_ai.evaluate(wp_id)
    assert ev["lines_decided"] == 2  # the open line does not count
    assert ev["engines"]["jev"] == {"pays": {"not_asked": 1, "right": 1}, "kind": {"agrees": 1, "no_suggestion": 1}}
    assert ev["engines"]["gpt"] == {"pays": {"missed": 1, "wrong": 1}, "kind": {"agrees": 1, "differs": 1}}
    assert {r["decision"] for r in ev["rows"]} == {"paired", "marked"}

    save(telecom, "gpt", _answer([energy], kind="utility_or_telecom"))  # the paired invoice was not offered
    save(lessons, "jev", _answer([], error="JevUnavailableError: x"))
    ev = reconcile_ai.evaluate(wp_id)
    assert ev["engines"]["gpt"]["pays"] == {"not_offered": 1, "wrong": 1}
    assert ev["engines"]["jev"]["pays"] == {"failed": 1, "right": 1}
