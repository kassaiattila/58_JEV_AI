"""231 (plan stage C, C2c; the owner's decision of 2026-10-25, DECISIONS 231): the AI pairing proposal as a step a person
starts on a reconciliation case.

Nothing is asked before a person starts the step. Then the worker asks JEV only about the lines still to decide, under
the run's own cap (at most 0.20 USD, `configs/finance.json`), every call through the call log as the case's business
work; the raw answers are stored where the pairing cards read them, and the case's cost element finds the spending. A
run whose every question failed shows why, and starting the step again makes a new run with its own cap. The step is
optional: a case whose reconciliation is approved without it closes. A stand-in JEV; no paid call.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from jav.app import case_views, package_release, parties, process_runtime
from jav.ai.jev import JevUnavailableError
from jav.core import store
from jav.core.process import engine
from jav.domains.finance import pairing_proposal, reconcile, reconcile_ai
from tests import test_reconcile_ai_134 as ai134
from tests import test_reconcile_k2_129 as k2
from tests.test_quote_path_231 import _drain

PERSON = "anna"


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "proposal.sqlite"):
        yield


class Down(ai134.FakeJev):
    def ask(self, request_id, state, questions, *, run_id, use_cache, config_hash):
        raise JevUnavailableError("TypeSafeRateLimitError:429")


def _case() -> str:
    k2._save_statement("stmt", *ai134.LINES)
    k2._save("tel", ai134.TELECOM)
    k2._save("energy", ai134.ENERGY)
    party = parties.create("Example Home", identities=[("account", reconcile.account_key(k2.OWN), k2.OWN)], actor="t")["id"]
    return process_runtime.start_case("reconciliation", {"party": party, "period": ["2026-04-01", "2026-04-30"]},
                                      name="April", actor=PERSON)


def _start(case: str) -> None:
    case_views.start_step(case, "propose", PERSON)


def _turns(case: str, n: int = 4) -> dict:
    for _ in range(n):
        engine.turn(case, wake=True)
        _drain()
    return engine.state(case)


def test_the_cap_is_jev_only_and_at_most_twenty_cents():
    assert pairing_proposal.cap() == (["jev"], {"jev": Decimal("0.20")})


def test_nothing_is_asked_before_a_person_starts_the_step(db, monkeypatch):
    jev = ai134.FakeJev()
    monkeypatch.setattr(reconcile_ai, "get_adapter", lambda: jev)
    case = _case()
    state = _turns(case)
    assert state["steps"]["propose"]["state"] == "running" and jev.asked == []
    page = case_views.view(case)
    assert page["steps"]["propose"]["awaiting_start"] is True
    proposal = next(e for t in page["tabs"] for e in t["elements"] if e["type"] == "pairing_proposal")
    assert proposal["data"] == {"run": None, "engines": ["jev"], "cap_usd": {"jev": "0.20"}}


def test_a_started_proposal_asks_jev_under_its_cap_and_stores_the_answers(db, monkeypatch):
    jev = ai134.FakeJev()
    monkeypatch.setattr(reconcile_ai, "get_adapter", lambda: jev)
    case = _case()
    _turns(case, 1)
    _start(case)
    state = _turns(case)
    assert state["steps"]["propose"]["state"] == "done" and jev.asked
    run = pairing_proposal.latest(case, "propose")
    assert (run["state"], run["round"], run["scope"]) == ("done", 1, f"case:{case}:propose:1")
    assert run["counts"]["jev"]["asked"] >= 1 and run["counts"]["jev"]["failed"] == 0
    with store.connect() as c:
        limit = c.execute("SELECT limit_usd FROM budgets WHERE scope=? AND provider='jev'", (run["scope"],)).fetchone()[0]
        stored = c.execute("SELECT COUNT(*) FROM reconcile_ai_proposals WHERE workpackage_id=? AND engine='jev'", (case,)).fetchone()[0]
    assert Decimal(limit) == Decimal("0.20") and stored >= 1  # the run's own budget scope, as the cost element reads it


def test_a_failed_run_shows_why_and_starting_again_is_a_new_run(db, monkeypatch):
    monkeypatch.setattr(reconcile_ai, "get_adapter", lambda: Down())  # every line's question fails
    case = _case()
    _turns(case, 1)
    _start(case)
    state = _turns(case)
    assert state["steps"]["propose"]["state"] == "failed"
    assert pairing_proposal.latest(case, "propose")["error"] == "every line's question failed"
    jev = ai134.FakeJev()
    monkeypatch.setattr(reconcile_ai, "get_adapter", lambda: jev)
    case_views.act(case, "propose", case_views.RETRY, PERSON)
    state = _turns(case)
    run = pairing_proposal.latest(case, "propose")
    assert (state["steps"]["propose"]["state"], run["round"], run["state"]) == ("done", 2, "done")


def test_a_case_approved_without_the_proposal_closes(db, monkeypatch):
    monkeypatch.setattr(reconcile_ai, "get_adapter", lambda: ai134.FakeJev())
    case = _case()
    _turns(case, 1)
    with store.connect() as c:
        store.begin_immediate(c)
        package_release.record_own(c, case, content={"invented": True}, fingerprint="f" * 16, locks=[], actor=PERSON)
    state = _turns(case)
    assert state["status"] == "closed" and state["steps"]["propose"]["result"] == {"skipped": True}
    assert case_views.view(case)["steps"]["propose"]["phase"] == "skipped"
