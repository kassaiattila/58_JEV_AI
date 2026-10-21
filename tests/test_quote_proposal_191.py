"""191 (plan F-quote-package B4c, DECISIONS 191): the quote's proposal, asked on the package's page and made by the worker.

The owner asked that the system proposes the quote's content. A person asks; the local service only queues it, with
the cost cap the button shows (a budget per requested item and provider, `configs/quotes.json`); the worker matches each
requested item with the active price list with the application's engine, under that budget, and stores each answer
with its mark. The latest proposal says when the request or the price list changed since. Synthetic emails, a stand-in
JEV and GPT; no paid call.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from jav import price_lists, quote_golden, quote_package, quote_proposal, store
from jav.runtime import job_kinds, queue, worker
from tests import test_email_text_follow_up_190 as follow
from tests.test_email_text_follow_up_190 import _package, _run

env = follow.env  # the 190 fixture: a mailbox package of one quote request email, a stand-in JEV and GPT


def _price_list(tmp_path, name: str = "Invented 2026") -> str:
    made = price_lists.add(name, "p.xlsx", quote_golden.write_price_list(tmp_path / "p.xlsx").read_bytes(), actor="anna")
    price_lists.activate(made["price_list"], 1, actor="anna")
    return made["price_list"]


def _quote(env) -> str:
    wp_id = _package(env)
    _run_id, item = _run(wp_id)
    return quote_package.create(name="Monitors", source=wp_id, item_id=item["item_id"], actor="anna")["workpackage_id"]


def test_the_proposal_is_queued_with_its_cap_and_made_by_the_worker(env, tmp_path):
    quote = _quote(env)
    pl = _price_list(tmp_path)
    view = quote_package.view(quote)
    assert view["proposal"] is None and view["proposal_cap"] == {"engine": "jev", "items": 1, "usd": {"jev": "0.003"}}
    assert quote_package.next_step(quote)["code"] == "quote_propose"
    asked = quote_proposal.request(quote, actor="anna")
    assert (asked["state"], asked["engine"], asked["limits"], asked["price_list"]) == ("queued", "jev", {"jev": "0.003"}, pl)
    assert quote_proposal.request(quote, actor="anna")["requested_at"] == asked["requested_at"]  # one at a time
    assert quote_package.next_step(quote)["code"] == "quote_proposing"
    worker.run_worker(once=True)
    done = quote_proposal.current(quote)
    assert (done["state"], done["stale"], len(done["lines"])) == ("done", False, 1)
    line = done["lines"][0]
    assert line["description"] == "24 colos monitor" and line["answer"]["mark"] in ("sure", "check", "not_listed")
    assert line["answer"]["engine"] == "jev"
    if line["answer"]["sku"]:  # the proposed item's name from the price list version the proposal used
        assert line["answer"]["name"] == price_lists.version(pl, 1).item(line["answer"]["sku"]).name
    assert quote_package.next_step(quote)["code"] == "quote_compose"
    # a new active price list version makes the proposal stale; asking again replaces it
    price_lists.change_settings(pl, 1, discounts=[{"category": "hardware", "min_quantity": "10", "percent": "5"}],
                                currency="HUF", vat_percent="27", actor="anna")
    price_lists.activate(pl, 2, actor="anna")
    assert quote_proposal.current(quote)["stale"] is True
    assert quote_proposal.request(quote, actor="anna")["state"] == "queued"


def test_the_gpt_engine_reserves_its_own_cap(env, tmp_path, monkeypatch):
    quote = _quote(env)
    _price_list(tmp_path)
    monkeypatch.setattr(quote_proposal.app_settings, "engine_default", lambda: "gpt")
    assert quote_proposal.request(quote, actor="anna")["limits"] == {"openai": "0.03"}


def test_a_proposal_needs_a_readable_request_and_an_active_price_list(env, tmp_path):
    quote = _quote(env)
    with pytest.raises(quote_proposal.ProposalRefused, match="no active price list"):
        quote_proposal.request(quote, actor="anna")
    _price_list(tmp_path)
    with store.connect() as c:
        c.execute("UPDATE workpackage_items SET removed_revision=1")
    with pytest.raises(quote_proposal.ProposalRefused, match="can no longer be read"):
        quote_proposal.request(quote, actor="anna")


def test_a_job_that_ends_without_processing_shows_on_the_proposal(env, tmp_path):
    quote = _quote(env)
    _price_list(tmp_path)
    quote_proposal.request(quote, actor="anna")
    job = queue.claim("t")
    assert job is not None and job.kind == quote_proposal.JOB_KIND
    job_kinds.of(quote_proposal.JOB_KIND).abandon(job, "stopped")  # e.g. the worker stopped before processing it
    shown = quote_proposal.current(quote)
    assert (shown["state"], shown["error"]) == ("failed", "stopped")
    assert quote_package.next_step(quote)["code"] == "quote_propose"


def test_the_cap_is_the_budget_per_item_times_the_items():
    assert quote_proposal.cap(10, "jev") == {"jev": Decimal("0.030")}
    assert quote_proposal.cap(10, "gpt") == {"openai": Decimal("0.30")}


def test_the_service_queues_a_proposal(env, tmp_path):
    from fastapi.testclient import TestClient

    from jav.api import create_app

    quote = _quote(env)
    _price_list(tmp_path)
    with TestClient(create_app(store_path=tmp_path / "q.sqlite"), base_url="http://127.0.0.1:8930") as c:
        asked = c.post(f"/api/workpackages/{quote}/quote/proposal", headers={"X-Actor": "teszt.elek"}, json={})
        assert asked.status_code == 202 and asked.json()["state"] == "queued"
        page = c.get(f"/api/workpackages/{quote}").json()
        assert page["quote"]["proposal"]["state"] == "queued" and page["next"]["code"] == "quote_proposing"
        assert c.post("/api/workpackages/wp-000000000000/quote/proposal", headers={"X-Actor": "teszt.elek"},
                      json={}).status_code == 404
