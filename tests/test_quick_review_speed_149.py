"""149 (backlog Q-quick-review-speed): the quick review runs the pairing once.

In the 2022–2025 package of the store the quick review took 6.8 s on its first and 3.0 s on every later request. The
cause: it ran the whole pairing twice, once for the workspace (kept until its inputs change) and once more for the sure
pairs, which were never kept. The sure pairs are now read from the kept workspace, with the same rules: proposed, the
only candidate of its line and its invoice, no source review needed, the package's own invoice, the line in the period
and in no approved statement. The normaliser of names and numbers is memoised as well (a pure function of its text).

Synthetic documents and made-up accounts only; no AI call.
"""

from __future__ import annotations

from typing import Any

import pytest

from jav import store
from jav.domains.finance import reconcile, reconcile_package as rp, reconcile_review as rr
from tests.test_reconcile_review_147 import _setup


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        rp.clear_cache()
        yield
        rp.clear_cache()


def _counting(monkeypatch) -> list[int]:
    calls: list[int] = []
    real = reconcile.propose

    def propose(snap: dict[str, Any]) -> dict[str, Any]:
        calls.append(1)
        return real(snap)

    monkeypatch.setattr(reconcile, "propose", propose)
    return calls


def _old_proposed_pairs(wp_id: str) -> list[dict[str, str]]:
    """The rule as it was before 149, from a fresh pairing (`_context`)."""
    ctx = rp._context(wp_id)
    sc = ctx["scope"]
    who = rp._Parties(sc, ctx["invoices"])
    return [{"invoice_doc_id": c["invoice_id"], "line_id": c["line_id"]} for c in ctx["result"]["candidates"]
            if c["proposed"] and not c["multiple_candidates"] and not c["source_review_required"] and who.own(c["invoice_id"])
            and c["line_id"] not in ctx["locked"]
            and sc["period_start"] <= str(ctx["prepared"]["lines"][c["line_id"]].get("booking_date") or "")[:10] <= sc["period_end"]]


def _key(pairs: list[dict[str, str]]) -> list[tuple[str, str]]:
    return sorted((p["invoice_doc_id"], p["line_id"]) for p in pairs)


def test_the_review_runs_the_pairing_once_and_then_not_at_all(db, monkeypatch):
    wp_id, _ids, _inv = _setup()
    calls = _counting(monkeypatch)
    rr.review(wp_id)
    assert len(calls) == 1  # was 2: the workspace and the sure pairs each paired the whole scope
    rr.review(wp_id)
    assert len(calls) == 1  # was 3: the sure pairs were never kept


def test_the_sure_pairs_are_the_same_as_before(db):
    wp_id, ids, inv = _setup()
    pairs = rp.proposed_pairs(wp_id)
    assert _key(pairs) == _key(_old_proposed_pairs(wp_id)) == [(inv, ids["pair"])]
    sure = {g["id"]: g for g in rr.review(wp_id)["groups"]}["sure_pairs"]
    assert [ln["id"] for ln in sure["lines"]] == [ids["pair"]]


def test_an_accepted_pair_leaves_the_sure_pairs(db):
    wp_id, ids, _inv = _setup()
    assert rr.accept(wp_id, "sure_pairs", [ids["pair"]], actor="reviewer") == 1
    assert rp.proposed_pairs(wp_id) == _old_proposed_pairs(wp_id) == []


@pytest.mark.parametrize("text, expected", [("INV-001/A", "inv 001 a"), ("Árvíztűrő Kft.", "arvizturo kft"), (None, ""),
                                            (12.5, "12 5")])
def test_the_memoised_normaliser_gives_the_same_words(text, expected):
    assert reconcile.normalize(text) == expected
    assert reconcile.normalize(text) == expected  # from the memo
