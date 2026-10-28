"""231 (stage U, U1e; the owner's decision of 2026-10-28): the IT quote's example material, an invented price list.

The live store has no price list, so an IT quote could not be tried. The IT quote's pack names the invented seller's
price list of the golden set (`configs/golden_quotes.json`) as its example material: installed, the examples' machine
makes it from the seller's sheet with the set's discount rules and a person makes it active; installed again, it
changes nothing; it goes in one go unless a case keeps it. A list a person made is never the examples' to remove.
Invented data; no paid call.
"""

from __future__ import annotations

import pytest

from jav.app import examples, registrations
from jav.core import cfg, store
from jav.core.identity import person
from jav.core.process import cases
from jav.core.process.definition import StepDef
from jav.domains.quotes import invented_golden, price_list_examples, price_lists
from tests.test_process_turn_214 import define

registrations.load_all()
ANNA = "Minta Anna"


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "prices.sqlite"):
        yield tmp_path


def _state() -> dict:
    [state] = examples.of("it_quote")["sets"]
    return state


def test_the_it_quote_installs_the_invented_price_list_as_its_example(db) -> None:
    assert _state()["state"] == examples.MISSING
    examples.install("it_quote", ANNA)
    state = _state()
    assert (state["state"], state["example"]) == (examples.INSTALLED, True)
    chosen = price_lists.chosen()
    golden = invented_golden.load()
    assert chosen is not None and len(chosen.items) == len(golden.price_list.items) and chosen.currency == "HUF"
    assert [(r.category, str(r.percent)) for r in chosen.discounts] == [
        (d.category, str(d.percent)) for d in golden.price_list.discounts]
    examples.install("it_quote", ANNA)  # again: nothing new
    assert len(price_lists.listing()) == 1


def test_the_example_price_list_goes_unless_a_case_keeps_it(db) -> None:
    examples.install("it_quote", ANNA)
    pl = price_lists.chosen()
    cases.start("holder", define(StepDef(id="a", kind="turn_note")), {"resources": {"price_list": f"{pl.price_list}@1"}},
                person(ANNA))
    with pytest.raises(examples.ExampleInUse):
        examples.remove("it_quote", ANNA)
    with cases.transaction() as c:
        c.execute("DELETE FROM process_cases WHERE case_id='holder'")
    examples.remove("it_quote", ANNA)
    assert _state()["state"] == examples.MISSING and price_lists.listing() == []


def test_a_price_list_a_person_made_is_not_the_examples_to_remove(db, tmp_path) -> None:
    sheet = invented_golden.write_price_list(tmp_path / "list.xlsx")
    made = price_lists.add(price_list_examples.list_name(cfg.load("golden_quotes")), "list.xlsx", sheet.read_bytes(), actor=ANNA)
    with pytest.raises(examples.ExampleRefused):
        examples.remove("it_quote", ANNA)
    assert price_lists.get(made["price_list"], 1)["made_by"] == ANNA
