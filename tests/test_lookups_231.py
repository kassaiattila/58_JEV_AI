"""231 (stage D, D-d5): outside checks through connectors, their answers offered as facts to the field check.

The invented company register and sanctions list answer from their data, inside the process and as a local web service.
In a case, a reading offers the policyholder's name, tax number and activity; two lookups ask the two registers with
them, independently, and the field check places what they answer: the register's status and the sanctions mark fill
facts still missing, and an activity that differs from the document's is a conflict left to the person. Each question
is in the call log under its register. A register that is down stops only its own step; once retried, the case goes
on. A lookup without the facts it asks with asks nothing. Invented data; no paid call.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request

import pytest
from pydantic import BaseModel, ConfigDict

from jav.app import capabilities, field_check, process_runtime, product_sets
from jav.core import cfg, connectors, identity, store
from jav.core.process import cases, engine, kinds
from jav.devtools import invented_services

ANNA = "Minta Anna"
SRC = {"item": "invented-document", "page": 1}
COMPANY = {"connector": "invented_company_register", "from_step": "read", "asks": {"tax_number": "tax_number"},
           "answers": {"company.status": "company_status", "company.activity_code": "activity_code"}}
SANCTIONS = {"connector": "invented_sanctions_list", "from_step": "read", "asks": {"name": "company_name"},
             "asks_if_known": {"tax_number": "tax_number"}, "answers": {"listed": "sanctions_listed"}}


def _claim(fact: str, value) -> dict:
    return {"unit": "holder", "level": "holder", "parent": None, "fact": fact, "value": value, "source": SRC,
            "reading": "invented_reading@1"}


READ = [_claim("company_name", "Minta Raktározó Zrt."), _claim("tax_number", "21357912-1-13"),
        _claim("activity_code", "4719")]


class _Offer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[dict]


def _pack(pid: str, claims: list[dict]) -> dict:
    return {"meta": {"name": f"process:{pid}", "version": "1.0.0"}, "id": pid, "title": "Invented lookups",
            "intake": [{"on": "manual", "starts": "manual"}], "resources": {"product": "inv_business_property"},
            "needs_at_start": ["product"],
            "steps": [{"id": "read", "uses": "invented_offer@1", "params": {"claims": claims}},
                      {"id": "company", "uses": "lookup@1", "params": COMPANY, "after": ["read"]},
                      {"id": "sanctions", "uses": "lookup@1", "params": SANCTIONS, "after": ["read"]},
                      {"id": "check", "uses": "field_check@1", "params": {"catalogue": "property", "product": "@product"},
                       "after": ["read", "company", "sanctions"]}],
            "screens": {"tabs": [{"id": "history", "label": "History", "elements": [{"type": "timeline"}]}]}}


@pytest.fixture()
def packs(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "_CAPS", dict(capabilities._CAPS))
    monkeypatch.setattr(kinds, "_KINDS", dict(kinds._KINDS))
    monkeypatch.setattr(connectors.time, "sleep", lambda _s: None)  # the retry's wait
    capabilities.register(capabilities.Capability(
        name="invented_offer", version=1, module="tests.synthetic", kind="machine", summary="Invented.", params=_Offer,
        run=lambda ctx, p: kinds.Done({"claims": p.claims}), state="step", output=capabilities.Result))
    data = {"process:invented_lookups": _pack("invented_lookups", READ),
            "process:invented_lookups_bare": _pack("invented_lookups_bare", READ[:1])}
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: data[name] if name in data else real(name))
    with store.use_store(tmp_path / "lookups.sqlite"):
        product_sets.install(product_sets.load(), maker=ANNA, approver="Minta Bela")
        yield


_CLOCK = [time.time()]


def _turn(case_id: str, **down: bool) -> None:
    _CLOCK[0] = max(_CLOCK[0], time.time()) + 10  # never behind the real time the steps' timers are set from
    with connectors.use_transport(invented_services.transport(down=frozenset(p for p, d in down.items() if d))):
        engine.turn(case_id, now=_CLOCK[0])


def _asked(provider: str) -> int:
    with store.connect() as c:
        return c.execute("SELECT COUNT(*) FROM invocations WHERE provider=?", (provider,)).fetchone()[0]


def test_the_invented_registers_answer_from_their_data() -> None:
    def ask(path: str, question: dict) -> dict:
        status, body = invented_services.answer(path, json.dumps(question).encode("utf-8"))
        assert status == 200
        return json.loads(body)

    found = ask("/company", {"tax_number": "12345676-2-41"})
    assert found["found"] and found["company"]["activity_code"] == "4719" and found["company"]["status"] == "active"
    assert ask("/company", {"tax_number": "00000000-0-00"}) == {"found": False}
    assert [e["matched_on"] for e in ask("/sanctions", {"tax_number": "90909094-2-42"})["entries"]] == ["tax_number"]
    by_name = ask("/sanctions", {"name": "  minta  RAKTÁROZÓ zrt"})
    assert by_name["listed"] and [e["matched_on"] for e in by_name["entries"]] == ["name"]
    assert ask("/sanctions", {"name": "Minta Kereskedő Kft.", "tax_number": "12345676-2-41"}) == {"listed": False, "entries": []}
    assert invented_services.answer("/nowhere", b"{}")[0] == 404
    assert invented_services.answer("/company", b"[1]")[0] == 400


def test_the_local_service_answers_over_http() -> None:
    running = invented_services.server(0)
    worker = threading.Thread(target=running.serve_forever, daemon=True)
    worker.start()
    try:
        port = running.server_address[1]
        request = urllib.request.Request(f"http://127.0.0.1:{port}/company", data=b'{"tax_number": "24681353-1-43"}',
                                         headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - the invented local service
            assert json.loads(response.read())["company"]["activity_code"] == "2562"
    finally:
        running.shutdown()
        running.server_close()


def test_two_lookups_offer_their_answers_and_the_field_check_places_them(packs) -> None:
    case_id = process_runtime.start_case("invented_lookups", {}, name="Invented lookups", actor=ANNA)
    _turn(case_id)
    _turn(case_id)
    steps = engine.state(case_id)["steps"]
    assert steps["company"]["result"]["answer"]["company"]["status"] == "under_liquidation"
    assert steps["sanctions"]["result"]["question"] == {"name": "Minta Raktározó Zrt.", "tax_number": "21357912-1-13"}
    view = field_check.view(case_id, "check")
    [holder] = [u for u in view["units"] if u["level"] == "holder"]
    assert holder["facts"]["company_status"] == "under_liquidation" and holder["facts"]["sanctions_listed"] is True
    assert holder["sources"]["sanctions_listed"]["interpretation"]["reading"] == "lookup:invented_sanctions_list"
    placed = {(c["from_step"], c["fact"]): (c["placement"], c["open"]) for c in view["claims"]}
    assert placed[("company", "activity_code")] == ("conflict", True)  # the register says 5210, the document 4719
    assert placed[("company", "company_status")] == ("filled", False)
    assert (_asked("invented_company_register"), _asked("invented_sanctions_list")) == (1, 1)


def test_a_register_that_is_down_stops_only_its_own_branch_until_retried(packs) -> None:
    case_id = process_runtime.start_case("invented_lookups", {}, name="Invented lookups", actor=ANNA)
    _turn(case_id, **{"/sanctions": True})
    steps = engine.state(case_id)["steps"]
    assert steps["company"]["state"] == "done" and steps["sanctions"]["state"] == "failed"
    assert "no usable answer (unreachable)" in steps["sanctions"]["note"] and steps["check"]["state"] != "done"
    assert _asked("invented_sanctions_list") == 2  # the question and its one retry
    cases.retry(case_id, "sanctions", identity.who(ANNA))
    _turn(case_id)
    _turn(case_id)
    assert engine.state(case_id)["steps"]["sanctions"]["state"] == "done"
    assert any(c["from_step"] == "sanctions" for c in field_check.view(case_id, "check")["claims"])


def test_a_lookup_without_the_facts_it_asks_with_asks_nothing(packs) -> None:
    case_id = process_runtime.start_case("invented_lookups_bare", {}, name="Invented lookups", actor=ANNA)
    _turn(case_id)
    steps = engine.state(case_id)["steps"]
    assert steps["company"]["result"] == {"asked": False, "missing": ["tax_number"], "claims": []}
    assert steps["sanctions"]["result"]["asked"] is True  # the name is enough; the tax number only when known
    assert _asked("invented_company_register") == 0
