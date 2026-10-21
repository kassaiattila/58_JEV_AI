"""191 (plan F-quote-package B4b, DECISIONS 191): which item of the price list a requested item is.

Code decides first (an item code written in the request); otherwise one request asks which item it is (a Choice over
the list, plus none), whether the list sells such a thing at all, and whether the request says enough to tell one item.
The answer is marked with the default policy bands: sure, to check (with its likely candidates) or not in the list; a
person reviews every line. No price goes to the model. Stand-in JEV and GPT answers, the invented price list; no paid
call.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from typesafe_sdk import Noul

from jav import gpt_choice, quote_golden, quote_match, quote_pricing
from jav.adapters import jev as jev_mod
from tests.test_runtime_worker import FakeClient

PRICES = quote_pricing.golden_price_list(quote_golden.load())
REQUESTED = {"description": "2 db monitor", "quantity": "2", "unit": "db"}


class StandInJev:
    """Answers every request with the given choice distribution and yes/no probabilities, and keeps the requests."""

    def __init__(self, dist: dict[str, float], listed: float = 0.97, specific: float = 0.95, confidence: float = 0.95):
        self.dist, self.listed, self.specific, self.confidence = dist, listed, specific, confidence
        self.asked: list[tuple[dict, dict]] = []

    def ask(self, request_id, state, questions, *, run_id, use_cache=True, config_hash=None):
        self.asked.append((state, questions))
        choice = max(self.dist, key=self.dist.get)
        response = SimpleNamespace(
            choices={"item": SimpleNamespace(choice=choice, probabilities=self.dist, confidence=self.confidence)},
            nouls={"listed": SimpleNamespace(noul=self.listed), "specific": SimpleNamespace(noul=self.specific)})
        return SimpleNamespace(response=response, call=SimpleNamespace(model="jev-test", cost_usd=0.0))


# --- code first, and what is asked ---------------------------------------------------------------------------------------


def test_an_item_code_written_in_the_request_decides_without_a_question(monkeypatch):
    monkeypatch.setattr(quote_match, "get_adapter", lambda: pytest.fail("no question for a written item code"))
    answer = quote_match.match({"description": "2 x hw-mon-27 please", "quantity": "2"}, [], PRICES, engine="jev", run_id="t")
    assert (answer["mark"], answer["sku"], answer["method"]) == ("sure", "HW-MON-27", "code")
    assert quote_match.code_match("HW-MON-24 or HW-MON-27", PRICES) is None  # two codes: the question decides
    assert quote_match.code_match("HW-MON-245", PRICES) is None  # a code only as a whole word


def test_the_question_offers_every_item_and_none_and_sends_no_price():
    items = quote_match.options("monitor", PRICES)
    questions = quote_match.build_questions(items)
    assert set(questions) == {"item", "listed", "specific"} and isinstance(questions["listed"], Noul)
    criteria = questions["item"].criteria
    assert list(criteria)[:2] == ["HW-NB-14P", "HW-NB-15B"] and list(criteria)[-1] == "none" and len(criteria) == 25
    state = quote_match.build_state(REQUESTED, ["egy nyomtato"], items)
    assert state["requested_item"] == {"text": "2 db monitor", "quantity": "2", "unit": "db"}
    assert "54900" not in str(state) and "54900" not in str(criteria)  # code prices the line
    assert quote_match.gpt_fields(items)["item"][-1] == "none"


def test_a_long_list_is_cut_to_the_items_sharing_most_words(monkeypatch):
    site = quote_match._site()
    monkeypatch.setattr(quote_match, "_site", lambda: {**site, "state": {**site["state"], "max_options": 2}})
    kept = [i.sku for i in quote_match.options("24 colos monitor", PRICES)]
    assert kept == ["HW-MON-24", "HW-MON-27"]


def test_an_item_code_that_cannot_be_an_option_name_is_numbered():
    odd = PRICES.items[0].model_copy(update={"sku": "A B/1"})
    none = PRICES.items[1].model_copy(update={"sku": "none"})
    assert quote_match.option_keys([odd, none, PRICES.items[2]]) == ["item_1", "item_2", "HW-MON-24"]


# --- the marks -------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("dist, listed, specific, confidence, mark, candidates", [
    ({"HW-MON-24": 0.96, "HW-MON-27": 0.03, "none": 0.01}, 0.97, 0.95, 0.94, "sure", ["HW-MON-24"]),
    ({"HW-MON-24": 0.52, "HW-MON-27": 0.46, "none": 0.02}, 0.97, 0.10, 0.40, "check", ["HW-MON-24", "HW-MON-27"]),
    ({"none": 0.90, "HW-NB-14P": 0.10}, 0.05, 0.05, 0.85, "not_listed", ["HW-NB-14P"]),
    ({"HW-NB-14P": 0.80, "none": 0.20}, 0.10, 0.10, 0.70, "not_listed", ["HW-NB-14P"]),
])
def test_an_answer_is_marked_with_the_default_bands(monkeypatch, dist, listed, specific, confidence, mark, candidates):
    jev = StandInJev(dist, listed, specific, confidence)
    monkeypatch.setattr(quote_match, "get_adapter", lambda: jev)
    answer = quote_match.match(REQUESTED, [], PRICES, engine="jev", run_id="t")
    assert (answer["mark"], answer["candidates"], answer["method"]) == (mark, candidates, "jev")
    assert (answer["sku"] is None) is (mark == "not_listed")  # a line not listed proposes no item, its choice stays apart
    assert len(jev.asked) == 1


def _gpt_answer(item: str, probability: float):
    def ask(request_id, instructions, prompt, fields, *, run_id, limits):
        assert "HW-MON-24" in instructions and fields["item"][-1] == "none"
        return SimpleNamespace(values={"item": item, "listed": "yes", "specific": "yes"},
                               probabilities={"item": {item: probability}, "listed": {"yes": 0.99}, "specific": {"yes": 0.95}},
                               confidence={"item": probability, "listed": 0.99, "specific": 0.95}, measured=True,
                               call=SimpleNamespace(model="gpt-test", cost_usd=0.0))
    return ask


def test_the_gpt_engine_asks_the_same_questions(monkeypatch):
    monkeypatch.setattr(gpt_choice, "ask", _gpt_answer("HW-MON-24", 0.97))
    answer = quote_match.match(REQUESTED, [], PRICES, engine="gpt", run_id="t")
    assert (answer["mark"], answer["sku"], answer["engine"]) == ("sure", "HW-MON-24", "gpt")


@pytest.mark.jev_refusal
def test_the_gpt_engine_cannot_ask_jev(monkeypatch, tmp_path):
    client = FakeClient()

    def forgetful(requested, context, items, *, run_id):
        jev_mod.get_adapter().ask(quote_match.REQUEST_ID, {"x": 1}, {"q": Noul(instructions="?")}, run_id=run_id)
        raise AssertionError("JEV answered the GPT engine's question")

    monkeypatch.setattr(quote_match, "ask_gpt", forgetful)
    with jev_mod.use_adapter(jev_mod.JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")):
        with pytest.raises(jev_mod.JevUnavailableError, match="disabled"):
            quote_match.match(REQUESTED, [], PRICES, engine="gpt", run_id="t")
    assert client.calls == 0


# --- the golden set ------------------------------------------------------------------------------------------------------


class Oracle(StandInJev):
    """Answers each golden item as expected: its item surely, an ambiguous one split, an unlisted one as not listed."""

    def __init__(self) -> None:
        super().__init__({})
        self.expected = {i.written: m for c in quote_golden.load().cases for m in c.expected.matches
                         for i in [c.expected.request.items[m.item]]}

    def ask(self, request_id, state, questions, *, run_id, use_cache=True, config_hash=None):
        m = self.expected[state["requested_item"]["text"]]
        if m.blocker == "ambiguous":
            self.dist, self.listed, self.specific, self.confidence = {m.candidates[0]: 0.5, m.candidates[1]: 0.45, "none": 0.05}, 0.95, 0.1, 0.4
        elif m.blocker == "not_in_price_list":
            self.dist, self.listed, self.specific, self.confidence = {"none": 0.9, "HW-NB-14P": 0.1}, 0.05, 0.05, 0.85
        else:
            self.dist, self.listed, self.specific, self.confidence = {m.sku: 0.97, "none": 0.03}, 0.98, 0.95, 0.95
        return super().ask(request_id, state, questions, run_id=run_id)


def test_the_golden_set_judges_each_item_against_its_expected_match(monkeypatch, tmp_path):
    monkeypatch.setattr(quote_match, "get_adapter", Oracle)
    g = quote_match.golden(engine="jev", limits={"jev": Decimal("0.01")}, out_dir=tmp_path)
    assert g["items"] == 37 and g["tally"] == {"right": 37}
    with pytest.raises(ValueError, match="no budget"):
        quote_match.golden(engine="gpt", limits={"jev": Decimal("0.01")}, out_dir=tmp_path)
