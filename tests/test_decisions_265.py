"""265 (plan L, L2): OpenAI Decisions as a judgement service, offline.

The questions the flows ask JEV (Noul, Choice, Score) are translated into a Decisions request, and the answer back
into JEV's answer shape, so a call site reads it unchanged. The adapter is JEV's with its own provider, price, model,
cache key and physical call. The OpenAI transport is a local stand-in (`httpx2.MockTransport`): no paid call. The
answers follow the API reference's examples (developers.openai.com/api/reference/resources/decisions/methods/create).
"""

from __future__ import annotations

import json
from decimal import Decimal

import httpx2
import pytest
from openai import OpenAI
from typesafe_sdk import Choice, Noul, Score

from jav.ai import decisions_wire as wire
from jav.ai import jev
from jav.ai.decisions import DecisionsAdapter
from jav.core import calls, store

STATE = {"document": "Számla sorszáma: INV-2026-001\nVégösszeg: 12 700 Ft", "lines": ["L01: INV-2026-001"]}
QUESTIONS = {
    "number": Choice(instructions="Which option is the invoice number?",
                     criteria={"c1": "printed as 'INV-2026-001' at L01",
                               "none": {"what": "none of the options", "not_for": ["a phone number"]}}),
    "number__present": Noul(instructions="Is an invoice number printed on the document?"),
    "swapped": Noul(instructions={"rule": "compare the parties", "question": "Are the parties swapped?"},
                    criteria={"true": "the buyer is printed as the seller", "false": "they stand as printed"}),
    "urgency": Score(instructions="How urgent is the request?", criteria=["no deadline", "this month", "today"]),
}


def _answer(**over):
    body = {
        "model": "gpt-6-luna",
        "answers": [
            {"type": "choice", "name": "number", "choice": "c1", "confidence": 0.91,
             "probabilities": [{"value": "c1", "probability": 0.95}, {"value": "none", "probability": 0.05}]},
            {"type": "predicate", "name": "number__present", "probability": 0.97},
            {"type": "predicate", "name": "swapped", "probability": 0.04},
            {"type": "score", "name": "urgency", "score": 1.1, "confidence": 0.55,
             "probabilities": [{"value": 0, "label": "0", "probability": 0.1}, {"value": 1, "label": "1", "probability": 0.7},
                               {"value": 2, "label": "2", "probability": 0.2}]},
        ],
        "usage": {"input_tokens": 2000, "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                  "output_tokens": 0, "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": 2000},
    }
    body.update(over)
    return body


class Service:
    """A local stand-in of the Decisions endpoint: it records each request and answers with the next reply."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[dict] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        assert request.url.path.endswith("/decisions")
        self.requests.append(json.loads(request.content))
        status, body = self.replies.pop(0)
        return httpx2.Response(status, json=body)

    def adapter(self, tmp_path) -> DecisionsAdapter:
        client = OpenAI(api_key="synthetic-offline-key", max_retries=0,
                        http_client=httpx2.Client(transport=httpx2.MockTransport(self)))
        return DecisionsAdapter(client=client, cache_dir=tmp_path / "decisions-cache")


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.setenv("JAV_PROVIDERS_ON", "openai_decisions")  # off by default; these tests call it (offline)
    with store.use_store(tmp_path / "w.sqlite"):
        yield tmp_path


# --- the request ----------------------------------------------------------------------------------------------------

def test_every_kind_of_question_is_translated():
    body = wire.request(STATE, QUESTIONS, model="gpt-6-luna")
    assert body["model"] == "gpt-6-luna"
    assert body["input"] == [{"role": "user", "content": [{"type": "input_json", "data": STATE}]}]
    number, present, swapped, urgency = body["questions"]
    assert number == {"type": "choice", "name": "number", "instructions": "Which option is the invoice number?",
                      "choices": [{"value": "c1", "description": "printed as 'INV-2026-001' at L01"},
                                  {"value": "none", "description": "what: none of the options\nnot_for: a phone number"}]}
    assert present == {"type": "predicate", "name": "number__present",
                       "instructions": "Is an invoice number printed on the document?"}
    assert swapped["instructions"] == [
        {"type": "input_json", "data": {"rule": "compare the parties", "question": "Are the parties swapped?"}},
        {"type": "input_text", "text": "True means: the buyer is printed as the seller"},
        {"type": "input_text", "text": "False means: they stand as printed"}]
    assert urgency["levels"] == [{"label": "0", "description": "no deadline"}, {"label": "1", "description": "this month"},
                                 {"label": "2", "description": "today"}]


def test_a_state_beyond_the_json_limits_goes_as_text():
    big = {"document": "x" * (wire.JSON_MAX_BYTES + 1)}
    part = wire.request(big, {"q": Noul(instructions="?")}, model="m")["input"][0]["content"][0]
    assert part["type"] == "input_text" and json.loads(part["text"]) == big
    many = {"lines": [str(i) for i in range(wire.JSON_MAX_VALUES)]}
    assert not wire.json_fits(many)
    assert wire.request(many, {"q": Noul(instructions="?")}, model="m", state_mode="json")["input"][0]["content"][0]["type"] == "input_text"
    assert wire.request(STATE, {"q": Noul(instructions="?")}, model="m", state_mode="text")["input"][0]["content"][0]["type"] == "input_text"


@pytest.mark.parametrize("questions", [
    {"one": Choice(criteria={"only": None})},
    {"wide": Score(criteria=[str(i) for i in range(11)])},
    {f"q{i}": Noul(instructions="?") for i in range(401)},
])
def test_a_request_beyond_the_api_limits_is_refused(questions):
    with pytest.raises(wire.Unfit):
        wire.request(STATE, questions, model="m")


# --- the answer -----------------------------------------------------------------------------------------------------

def test_the_answer_reads_as_jev_answers():
    r = wire.to_system_one(_answer(), QUESTIONS)
    assert r.model == "gpt-6-luna"
    assert r.choices["number"].choice == "c1" and r.choices["number"].confidence == 0.91
    assert r.choices["number"].probabilities == {"c1": 0.95, "none": 0.05}
    assert r.nouls["number__present"].noul == 0.97 and r.nouls["swapped"].noul == 0.04
    assert r.scores["urgency"].score == 1.1 and r.scores["urgency"].probabilities == {0: 0.1, 1: 0.7, 2: 0.2}
    assert r.scores["urgency"].legend == {0: "no deadline", 1: "this month", 2: "today"}
    assert r.usage.input_tokens == 2000 and r.cached_tokens == 0
    jev.validate_response(r, QUESTIONS)


def test_an_unnamed_answer_takes_its_question_by_position():
    body = _answer()
    for a in body["answers"]:
        a["name"] = None
    assert wire.to_system_one(body, QUESTIONS).nouls["swapped"].noul == 0.04


def test_a_refused_or_missing_answer_is_no_answer():
    refused = _answer()
    refused["answers"][2] = {"type": "refusal", "name": "swapped"}
    with pytest.raises(wire.Refused) as caught:
        wire.to_system_one(refused, QUESTIONS)
    assert caught.value.names == ["swapped"]
    missing = _answer()
    del missing["answers"][3]
    with pytest.raises(jev.InvalidJevResponse):
        wire.to_system_one(missing, QUESTIONS)


@pytest.mark.parametrize(("index", "broken"), [
    (2, {"type": "predicate", "name": "swapped"}),  # no probability: the SDK's answer object holds null
    (2, {"type": "predicate", "name": "swapped", "probability": None}),
    (0, {"type": "choice", "name": "number", "choice": "c1", "probabilities": []}),  # no confidence
    (3, {"type": "score", "name": "urgency", "score": 1.0, "confidence": 0.5, "probabilities": [{"value": "high"}]}),
])
def test_an_answer_without_its_value_is_no_answer(index, broken):
    body = _answer()
    body["answers"][index] = broken
    with pytest.raises(jev.InvalidJevResponse):
        wire.to_system_one(body, QUESTIONS)


def test_a_score_level_is_read_by_the_label_the_request_gave_it():
    body = _answer()
    body["answers"][3]["probabilities"] = [{"value": 1, "label": "0", "probability": 0.1},
                                           {"value": 2, "label": "1", "probability": 0.7},
                                           {"value": 3, "label": "2", "probability": 0.2}]
    assert wire.to_system_one(body, QUESTIONS).scores["urgency"].probabilities == {0: 0.1, 1: 0.7, 2: 0.2}


# --- the adapter ----------------------------------------------------------------------------------------------------

def test_a_question_is_asked_once_then_answered_from_the_cache(work):
    service = Service((200, _answer()))
    adapter = service.adapter(work)
    first = adapter.ask("select", STATE, QUESTIONS, run_id="run-265")
    again = adapter.ask("select", STATE, QUESTIONS, run_id="run-265")
    assert len(service.requests) == 1
    sent = service.requests[0]
    assert sent["prompt_cache_options"] == {"mode": "explicit"}  # the prompt cache is off: no cache write is paid
    assert [q["name"] for q in sent["questions"]] == list(QUESTIONS)
    assert first.response.choices["number"].choice == "c1" and not first.cached
    assert again.cached and again.cache_key == first.cache_key
    assert first.call.cost_usd == 0.0002  # 2 000 uncached input tokens at 0.10 USD per million
    with store.connect() as c:
        rows = c.execute("SELECT provider, model, cost_usd, cached FROM ledger ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [("openai_decisions", "gpt-6-luna", 0.0002, 0), ("openai_decisions", "gpt-6-luna", 0.0, 1)]
    assert (work / "decisions-cache" / f"{first.cache_key}.json").exists()


def test_in_a_measurement_it_spends_from_the_openai_budget(work):
    service = Service((200, _answer()))
    adapter = service.adapter(work)
    with calls.measurement("measure-265", {"openai": Decimal("0.01")}) as scope:
        adapter.ask("select", STATE, QUESTIONS, run_id="run-265")
        assert calls.left(scope, "openai") == Decimal("0.0098")
    with store.connect() as c:
        row = c.execute("SELECT provider, step_id, status, cost_usd FROM invocations").fetchone()
    assert (row["provider"], row["status"], row["cost_usd"]) == ("openai_decisions", "succeeded", "0.000200")
    assert row["step_id"].startswith("decisions:select:")


def test_without_an_openai_budget_nothing_is_sent(work):
    service = Service()
    adapter = service.adapter(work)
    with calls.measurement("measure-265", {"jev": Decimal("1")}):
        with pytest.raises(jev.JevUnavailableError, match="budget_exceeded"):
            adapter.ask("select", STATE, QUESTIONS, run_id="run-265")
    assert service.requests == []


def test_the_prompt_cache_is_priced_by_token_kind(work):
    service = Service((200, _answer(usage={"input_tokens": 300_000, "output_tokens": 0,
                                           "input_tokens_details": {"cached_tokens": 100_000, "cache_write_tokens": 50_000}})))
    adapter = service.adapter(work)
    result = adapter.ask("select", STATE, QUESTIONS, run_id="run-265")
    # 150 000 uncached at 0.10, 100 000 read at 0.01, 50 000 written at 0.125, all twice above 272 000 tokens
    assert result.call.cost_usd == pytest.approx(2 * (0.015 + 0.001 + 0.00625))


def test_a_request_over_the_token_limit_is_remembered(work):
    too_large = {"error": {"message": "too long", "type": "invalid_request_error", "code": "context_length_exceeded"}}
    service = Service((400, too_large))
    adapter = service.adapter(work)
    with pytest.raises(jev.JevUnavailableError) as first:
        adapter.ask("select", STATE, QUESTIONS, run_id="run-265")
    assert jev.TOKEN_LIMIT_MARK in first.value.reason and first.value.reason.startswith("BadRequestError:400")
    with pytest.raises(jev.JevUnavailableError) as again:  # the same request is refused without a call
        adapter.ask("select", STATE, QUESTIONS, run_id="run-265")
    assert again.value.reason == first.value.reason and len(service.requests) == 1


@pytest.mark.parametrize(("reply", "reason"), [
    ((429, {"error": {"message": "slow down", "type": "rate_limit", "code": "rate_limit_exceeded"}}), "RateLimitError:429:rate_limit_exceeded"),
    ((500, {"error": {"message": "oops", "type": "server_error", "code": None}}), "InternalServerError:500"),
])
def test_an_error_answer_becomes_an_unavailable_judge(work, reply, reason):
    adapter = Service(reply).adapter(work)
    with pytest.raises(jev.JevUnavailableError) as caught:
        adapter.ask("select", STATE, QUESTIONS, run_id="run-265")
    assert caught.value.reason == reason
    with store.connect() as c:
        assert c.execute("SELECT provider, error FROM ledger").fetchone()["provider"] == "openai_decisions"


def test_an_answer_without_its_value_becomes_an_unavailable_judge(work):
    body = _answer()
    body["answers"][1] = {"type": "predicate", "name": "number__present"}
    adapter = Service((200, body)).adapter(work)
    with pytest.raises(jev.JevUnavailableError, match="InvalidJevResponse"):
        adapter.ask("select", STATE, QUESTIONS, run_id="run-265")
    with store.connect() as c:
        row = c.execute("SELECT provider, error FROM ledger").fetchone()
    assert row["provider"] == "openai_decisions" and row["error"].startswith("InvalidJevResponse")


def test_a_provider_switched_off_here_is_never_sent(work, monkeypatch):
    """The provider registry's switch is the last word (configs/providers.json `enabled`): a run queued while OpenAI
    Decisions was on, or a command naming it, sends nothing once it is off; the flow raises its to-do."""
    monkeypatch.delenv("JAV_PROVIDERS_ON")
    service = Service((200, _answer()))
    adapter = service.adapter(work)
    with calls.measurement("measure-265", {"openai": Decimal("0.01")}):
        with pytest.raises(jev.JevUnavailableError, match="under_measurement"):
            adapter.ask("select", STATE, QUESTIONS, run_id="run-265")
    assert service.requests == []


def test_a_refusal_becomes_an_unavailable_judge(work):
    body = _answer()
    body["answers"][0] = {"type": "refusal", "name": "number"}
    adapter = Service((200, body)).adapter(work)
    with pytest.raises(jev.JevUnavailableError, match="refusal"):
        adapter.ask("select", STATE, QUESTIONS, run_id="run-265")


def test_a_model_the_answer_names_is_remembered_for_the_key(work):
    service = Service((200, _answer(model="gpt-6-luna-2026-11-01")))
    adapter = service.adapter(work)
    first = adapter.ask("select", STATE, QUESTIONS, run_id="run-265")
    assert first.call.model == "gpt-6-luna-2026-11-01"
    fresh = Service().adapter(work)  # another process: the remembered model gives the same key, from the cache
    assert fresh.ask("select", STATE, QUESTIONS, run_id="run-265").cached


def test_without_a_judgement_service_nothing_is_asked(work, monkeypatch):
    monkeypatch.setattr(jev, "_refuse", lambda request_id: (_ for _ in ()).throw(jev.JevUnavailableError("disabled")))
    service = Service()
    adapter = service.adapter(work)
    with jev.disabled(), pytest.raises(jev.JevUnavailableError, match="disabled"):
        adapter.ask("select", STATE, QUESTIONS, run_id="run-265")
    assert service.requests == []


def test_without_an_openai_key_it_is_unavailable(work):
    adapter = DecisionsAdapter(cache_dir=work / "decisions-cache")
    with calls.measurement("measure-265", {"openai": Decimal("0.01")}):
        with pytest.raises(jev.JevUnavailableError, match="missing_key"):
            adapter.ask("select", STATE, QUESTIONS, run_id="run-265")


def test_outside_a_run_or_a_budgeted_command_its_own_client_sends_nothing(work, monkeypatch):
    """As JEV's own client (265, SEC-02): with the installation's key but no run and no measurement budget, only
    earlier answers count; the client is made (the key is checked) and nothing is sent."""
    made = []
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-offline-key")
    monkeypatch.setattr(DecisionsAdapter, "_new_client", lambda self, key: made.append(key) or object())
    adapter = DecisionsAdapter(cache_dir=work / "decisions-cache")
    assert calls.current() is None
    with pytest.raises(jev.JevUnavailableError, match="no_budget"):
        adapter.ask("select", STATE, QUESTIONS, run_id="run-265")
    assert made == ["synthetic-offline-key"]


def test_an_unfit_request_is_the_flows_to_do_not_a_crash(work):
    adapter = Service().adapter(work)
    with pytest.raises(jev.JevUnavailableError, match="unfit"):
        adapter.ask("select", STATE, {"one": Choice(criteria={"only": None})}, run_id="run-265")
