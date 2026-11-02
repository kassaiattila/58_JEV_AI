"""277 (O3; the owner's decision of 2026-11-02: one case type in place of several alike): a process pack's choices.

A pack may ask a choice when a case starts (the invoices' source, whether the emails are routed, the product): each
option leaves steps out, sets resources and step parameters, and brings its own example material. A case's pack is the
pack narrowed by its choices before its definition is made, so a step left out is not in the case at all: the engine,
the track and the sub-cases see only the chosen steps. The check refuses a choice that names what is not there, and
checks every combination of the options as a pack of its own. Synthetic pack data built from a real pack, no AI call.
"""

from __future__ import annotations

import copy

import pytest

from jav.app import process_packs, registrations
from jav.core import cfg


@pytest.fixture(scope="module", autouse=True)
def _registered() -> None:
    registrations.load_all()


def _chained() -> dict:
    """An invented four-step chain with a choice of the invoices' source (the shape of the merged monthly
    reconciliation), built on the real two-source pack."""
    data = copy.deepcopy(cfg.load("process:two_sources_reconciliation"))
    data["id"] = "two_sources_reconciliation"
    data["choices"] = [{"id": "invoices_from", "title": "Where the invoices come from", "default": "folder", "options": [
        {"id": "folder", "title": "A folder", "leaves_out": ["emails"]},
        {"id": "mailbox", "title": "A mailbox", "leaves_out": ["invoices"]},
        {"id": "both", "title": "Both"}]}]
    return data


def _pack(data: dict) -> process_packs.ProcessPack:
    return process_packs.ProcessPack.model_validate(data)


def _problems(data: dict) -> list[str]:
    return process_packs._problems(_pack(data))


def test_a_pack_with_a_choice_passes_its_check_and_lists_its_variants() -> None:
    pack = _pack(_chained())
    assert _problems(_chained()) == []
    assert process_packs.variants(pack) == [{"invoices_from": "folder"}, {"invoices_from": "mailbox"},
                                            {"invoices_from": "both"}]
    assert process_packs.variants(_pack(copy.deepcopy(cfg.load("process:it_quote")))) == [{}]


def test_the_chosen_pack_leaves_the_steps_out_and_the_steps_that_waited_for_them_wait_for_the_rest() -> None:
    pack = _pack(_chained())
    folder = process_packs.chosen(pack, {})  # the default
    assert [s.id for s in folder.steps] == ["invoices", "statements", "reconcile"]
    assert next(s for s in folder.steps if s.id == "reconcile").after == ("invoices", "statements")
    overview = folder.screens.tabs[0]
    assert [e.step for e in overview.elements] == [None, "invoices", "statements", "reconcile"]
    assert folder.choices == ()  # a narrowed pack asks nothing more
    mailbox = process_packs.chosen(pack, {"invoices_from": "mailbox"})
    assert [s.id for s in mailbox.steps] == ["emails", "statements", "reconcile"]
    both = process_packs.chosen(pack, {"invoices_from": "both"})
    assert [s.id for s in both.steps] == ["invoices", "emails", "statements", "reconcile"]
    # the definition a case keeps has the chosen steps only
    assert [s.id for s in process_packs.definition(folder).steps] == ["invoices", "statements", "reconcile"]
    assert process_packs.definition(folder).version == pack.version


def test_an_unknown_choice_or_option_is_refused_and_a_pack_without_choices_stays_as_it_is() -> None:
    pack = _pack(_chained())
    with pytest.raises(process_packs.PackError, match="no choice 'product'"):
        process_packs.chosen(pack, {"product": "x"})
    with pytest.raises(process_packs.PackError, match="no option 'tray' of the choice 'invoices_from'"):
        process_packs.chosen(pack, {"invoices_from": "tray"})
    quote = process_packs.load("it_quote")
    assert process_packs.chosen(quote, {}) is quote
    assert process_packs.chosen(quote, None) is quote
    with pytest.raises(process_packs.PackError, match="no choice"):
        process_packs.chosen(quote, {"invoices_from": "folder"})
    assert process_packs.picked(pack, None) == {"invoices_from": "folder"}


def test_an_option_sets_resources_step_parameters_and_its_own_examples() -> None:
    data = copy.deepcopy(cfg.load("process:insurance_offer"))
    facts = next(s for s in data["steps"] if s["id"] == "facts")
    data["choices"] = [{"id": "product", "title": "Product", "default": "invented", "options": [
        {"id": "invented", "title": "Invented"},
        {"id": "other", "title": "Another", "params": {"facts": {"readings": "fact_readings_allianz_property"}},
         "examples": {"documents": "allianz_property_documents"}}]}]
    pack = _pack(data)
    other = process_packs.chosen(pack, {"product": "other"})
    assert next(s for s in other.steps if s.id == "facts").params == {**facts["params"], "readings": "fact_readings_allianz_property"}
    assert other.examples is not None and other.examples.documents == "allianz_property_documents"
    invented = process_packs.chosen(pack, {})
    assert next(s for s in invented.steps if s.id == "facts").params == facts["params"]
    assert invented.examples == pack.examples


def _with_choice(**option) -> dict:
    data = _chained()
    data["choices"][0]["options"][1].update(option)
    return data


@pytest.mark.parametrize(("change", "expected"), [
    (lambda d: d["choices"][0].update(default="tray") or d, "choice 'invoices_from': its default 'tray' is none of its options"),
    (lambda d: d["choices"].append(copy.deepcopy(d["choices"][0])) or d, "a choice is listed twice: invoices_from"),
    (lambda d: d["choices"][0]["options"].append({"id": "both", "title": "Again"}) or d,
     "choice 'invoices_from': an option is listed twice: both"),
    (lambda d: _with_choice(leaves_out=["ghost"]), "option 'mailbox' leaves out no step 'ghost'"),
    (lambda d: _with_choice(params={"ghost": {"pack": "documents"}}), "option 'mailbox' sets parameters of no step 'ghost'"),
    (lambda d: _with_choice(params={"statements": {"_start": "auto"}}), "option 'mailbox' sets the pack's own parameter '_start'"),
    (lambda d: _with_choice(resources={"price_list": "x"}), "option 'mailbox' sets 'price_list', which is no resource of the pack"),
    (lambda d: _with_choice(params={"statements": {"pack": "nowhere"}}), "with invoices_from=mailbox: step 'statements'"),
    (lambda d: _with_choice(leaves_out=["invoices", "emails", "statements", "reconcile"]),
     "with invoices_from=mailbox: it leaves out every step"),
    (lambda d: d.update(replaces=[{"pack": "two_sources_reconciliation"}]) or d, "replaces itself"),
    (lambda d: d.update(replaces=[{"pack": "old_chain", "choices": {"invoices_from": "tray"}}]) or d,
     "replaces 'old_chain': no option 'tray' of the choice 'invoices_from'"),
])
def test_a_choice_that_names_what_is_not_there_is_refused(change, expected) -> None:
    problems = _problems(change(_chained()))
    assert any(expected in p for p in problems), problems
