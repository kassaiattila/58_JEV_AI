"""231 (stage D, D-c7c): rules proposed from a condition document, by GPT under a budget or by a free stand-in.

The stand-in, answering with the invented insurer's rules for the pages asked, proposes exactly the 16 rules a careful
person reads, each turned into a rule of the registry's form and checked by code with nothing blocking. GPT's proposals
go through the call log and the ledger under a budget, a few pages at a time, after the catalogue and the cover
modules; a page its marking keeps out is never sent; a record that is no rule says why. A stand-in model stands for
GPT; no paid call.
"""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from jav.ai import gpt_answer
from jav.app import product_sets, rule_proposals
from jav.core import calls, cfg, store
from jav.documents import page_text

SET = product_sets.load()
MARKERS = cfg.load("rule_proposals")["skip_page_markers"]
GENERAL = "inv_general_conditions@1"
MODULES = {m.code: m.name for m in SET.products["inv_business_property"].modules}


def _pages(ident: str, rows: list[list[str]] | None = None) -> page_text.DocumentPages:
    return page_text.from_rows(rows or product_sets.document_pages(SET, ident), MARKERS)


def _comparable(rule) -> dict:
    return rule.model_dump(mode="json", exclude={"origin"})


def test_the_stand_in_proposes_the_sixteen_rules_and_nothing_blocks() -> None:
    proposed = []
    for ident, entry in SET.documents.items():
        proposed += rule_proposals.propose(f"{ident}@1", _pages(ident), "property", proposer=rule_proposals.set_proposer(SET),
                                           modules=MODULES, document=entry.content)
    assert len(proposed) == 16 and all(p.rule is not None and p.problem is None for p in proposed)
    assert sorted(_comparable(p.rule)["title"] for p in proposed) == sorted(r.title for r in SET.rules.values())
    by_title = {r.title: r for r in SET.rules.values()}
    assert all(_comparable(p.rule) == _comparable(by_title[p.rule.title]) for p in proposed)
    assert all(p.rule.origin == {"kind": "proposal"} for p in proposed)
    assert not any(p.check.blocking for p in proposed)


class _Agent:
    """A GPT stand-in answering every prompt with the given rules; the prompts it was sent are kept."""

    def __init__(self, answer: rule_proposals.ProposedRules):
        self.answer, self.prompts = answer, []

    def run_sync(self, prompt, **_kw):
        self.prompts.append(prompt)
        return SimpleNamespace(output=self.answer, usage=SimpleNamespace(input_tokens=3000, output_tokens=900),
                               response=SimpleNamespace(model_name="gpt-5.4-mini"))


@pytest.fixture()
def db(tmp_path):
    with store.use_store(tmp_path / "proposals.sqlite"):
        yield


def test_gpt_proposes_through_the_call_log_a_few_pages_at_a_time(db) -> None:
    flood = rule_proposals.record_of(SET.rules["inv_flood_high"])
    agent = _Agent(rule_proposals.ProposedRules(rules=[flood]))
    with gpt_answer.use_agent_factory(lambda model, instructions: agent):
        with calls.outside_run("proposal-test", {"openai": Decimal("1.00")}) as scope:
            proposed = rule_proposals.propose(GENERAL, _pages("inv_general_conditions"), "property",
                                              proposer=rule_proposals.gpt_proposer(scope), modules=MODULES,
                                              document=SET.documents["inv_general_conditions"].content)
    per = cfg.load("gpt_rule_proposal")["pages_per_request"]
    assert len(agent.prompts) == -(-4 // per)  # four pages, `per` at a time
    assert "=== page 1 ===" in agent.prompts[0] and "=== page 4 ===" in agent.prompts[-1]
    # 231 (U-A3): the catalogue in compact JSON, without the fields a fact does not have
    assert '"name":"sum_insured"' in agent.prompts[0] and '"code":"burglary"' in agent.prompts[0]
    assert '"unit":null' not in agent.prompts[0] and '"options":null' not in agent.prompts[0]
    assert per == 4 and [p.pages for p in proposed] == [(1, 2, 3, 4)]
    assert all(p.rule is not None and not p.check.blocking for p in proposed)
    rows = store.ledger_for_run(scope)
    assert [(r["step"], r["provider"], r["input_tokens"]) for r in rows] == [("rule_proposal_gpt", "openai", 3000)] * len(agent.prompts)


def test_gpt_is_not_asked_without_a_budget(db) -> None:
    agent = _Agent(rule_proposals.ProposedRules(rules=[]))
    with gpt_answer.use_agent_factory(lambda model, instructions: agent), pytest.raises(gpt_answer.NoBudget):
        rule_proposals.propose(GENERAL, _pages("inv_general_conditions"), "property", proposer=rule_proposals.gpt_proposer("x"))
    assert agent.prompts == []


def test_a_page_its_marking_keeps_out_is_never_sent(db) -> None:
    rows = product_sets.document_pages(SET, "inv_general_conditions")
    rows[1] = [*rows[1], "Internal"]
    agent = _Agent(rule_proposals.ProposedRules(rules=[]))
    with gpt_answer.use_agent_factory(lambda model, instructions: agent):
        with calls.outside_run("proposal-marked", {"openai": Decimal("1.00")}) as scope:
            rule_proposals.propose(GENERAL, _pages("inv_general_conditions", rows), "property",
                                   proposer=rule_proposals.gpt_proposer(scope))
    sent = "\n".join(agent.prompts)
    on_page_2 = [s.title for s in SET.documents["inv_general_conditions"].content.sections if s.page == 2]
    assert "=== page 2 ===" not in sent and "=== page 3 ===" in sent
    assert on_page_2 and not any(title in sent for title in on_page_2)


def test_a_record_that_is_no_rule_says_why() -> None:
    record = rule_proposals.record_of(SET.rules["inv_flood_high"]).model_copy(update={"rows": []})
    rule, problem = rule_proposals.to_rule(record, "property", GENERAL)
    assert rule is None and problem.template == "its record is no rule: {{where}}: {{reason}}"
    assert str(problem).startswith("its record is no rule: table.rows: ")


def test_a_value_that_is_no_json_is_read_as_a_code() -> None:
    record = rule_proposals.record_of(SET.rules["inv_flood_high"])
    row = record.rows[0]
    bare = row.model_copy(update={"when": [row.when[0].model_copy(update={"value": "high"})]})
    rule, problem = rule_proposals.to_rule(record.model_copy(update={"rows": [bare]}), "property", GENERAL)
    assert problem is None and rule.table.rows[0].when == {"flood_zone": {"eq": "high"}}


def test_a_clause_cited_as_printed_is_the_registry_s_clause() -> None:
    """D-h: the first paid round cited every clause as printed, with its closing dot ("3.1."); the registry names it
    without ("3.1"), so none was paired and the code check would have found no such clause."""
    record = rule_proposals.record_of(SET.rules["inv_claims_factor"])
    rule, problem = rule_proposals.to_rule(record.model_copy(update={"clause": " 3.2. "}), "property", GENERAL)
    assert problem is None and rule.source.clause == SET.rules["inv_claims_factor"].source.clause == "3.2"


def _money_condition(rules) -> tuple[str, str, str]:
    """A rule of the set whose table compares a money fact, with that fact and comparison."""
    cat_facts = rule_proposals.facts.catalogue("property").facts
    for ident, rule in rules.items():
        for row in rule.table.rows:
            for fact, cond in row.when.items():
                if cat_facts[fact].type == "money":
                    return ident, fact, next(iter(cond))
    raise AssertionError("no money condition in the set")


def test_a_rule_listing_every_module_applies_to_every_module() -> None:
    """231 (U-A0; the D-h measurement): GPT listed every cover module where the rule is the product's whole ("none for
    every module"); the registry's form for that is no module named, so a later module is covered too."""
    record = rule_proposals.record_of(SET.rules["inv_flood_high"])
    every = record.model_copy(update={"modules": sorted(MODULES)})
    rule, problem = rule_proposals.to_rule(every, "property", GENERAL, modules=MODULES)
    assert problem is None and rule.modules == ()
    some = record.model_copy(update={"modules": sorted(MODULES)[:2]})
    assert rule_proposals.to_rule(some, "property", GENERAL, modules=MODULES)[0].modules == tuple(sorted(MODULES)[:2])


@pytest.mark.parametrize("printed", ["10000000 HUF", "10 000 000 Ft", "10.000.000 HUF"])
def test_an_amount_written_as_text_is_read_as_money(printed: str) -> None:
    """U-A0 (D-h): GPT wrote an amount as text ("10000000 HUF") where the catalogue's type is money; code reads it as
    an amount with its currency (Ft is HUF), so the rule is the registry's form and the code check sees its number."""
    ident, fact, op = _money_condition(SET.rules)
    record = rule_proposals.record_of(SET.rules[ident])
    row = next(r for r in record.rows if any(c.fact == fact for c in r.when))
    texts = [c.model_copy(update={"value": json.dumps(printed)}) if c.fact == fact else c for c in row.when]
    rule, problem = rule_proposals.to_rule(record.model_copy(update={"rows": [row.model_copy(update={"when": texts})]}),
                                           "property", GENERAL)
    assert problem is None
    assert rule.model_dump(mode="json")["table"]["rows"][0]["when"][fact][op] == {"amount": "10000000", "currency": "HUF"}


@pytest.mark.parametrize(("printed", "clause"), [("3.1.b)", "3.1"), ("1-4", "1"), ("2.2.", "2.2"), ("VIL 4.", "VIL 4"),
                                                  ("FOGALMAK", None), ("Jelen kiegészítő biztosítás szerint", None)])
def test_a_clause_cited_with_a_point_a_range_or_a_word_is_the_clause_or_none(printed: str, clause: str | None) -> None:
    """U-A3 (the paid round): the model cited "3.1.b)" (a lettered point of 3.1), "1-4" (a range), a heading word or a
    sentence; the registry's clause is the clause it stands in, the first of a range, or none."""
    record = rule_proposals.record_of(SET.rules["inv_flood_high"]).model_copy(update={"clause": printed})
    rule, problem = rule_proposals.to_rule(record, "property", GENERAL)
    assert problem is None and rule.source.clause == clause


def test_a_single_code_where_the_catalogue_wants_a_list_is_a_list() -> None:
    """U-A3: the model gave "x" for an outcome that is a list of codes (measures); it is ["x"]."""
    record = rule_proposals.record_of(SET.rules["inv_flood_high"])
    row = record.rows[0].model_copy(update={"then": [rule_proposals.ProposedOutcome(outcome="measures", value='"alarm"')]})
    rule, problem = rule_proposals.to_rule(record.model_copy(update={"rows": [row]}), "property", GENERAL)
    assert problem is None and rule.table.rows[0].then["measures"] == ["alarm"]



@pytest.mark.parametrize(("where", "name", "printed"), [("then", "measures", "["), ("then", "measures", '["alarm"'),
                                                        ("when", "asset_group", "["), ("when", "asset_group", '{"amount": 5')])
def test_a_value_begun_as_json_and_cut_off_is_no_rule(where: str, name: str, printed: str) -> None:
    """U-A3 (the paid round on the real conditions): 23 values of the model's records were a lone "[" where a list of
    codes was due. A value begun as JSON (a list, an object, a string) that is no JSON is cut off, not a bare code: the
    record is no rule and says which value, so it is never accepted as a list holding "[" (v1.53.0 made it one)."""
    record = rule_proposals.record_of(SET.rules["inv_flood_high"])
    row = record.rows[0]
    if where == "then":
        row = row.model_copy(update={"then": [rule_proposals.ProposedOutcome(outcome=name, value=printed)]})
    else:
        row = row.model_copy(update={"when": [rule_proposals.ProposedCondition(fact=name, op="in", value=printed)]})
    rule, problem = rule_proposals.to_rule(record.model_copy(update={"rows": [row]}), "property", GENERAL)
    assert rule is None and problem.template == "its record is no rule: {{where}}: {{reason}}"
    assert problem.params["where"] == f"table.rows.0.{where}.{name}" and printed in problem.params["reason"]


def test_a_clause_numbered_again_under_an_extension_s_code_is_found_by_its_page() -> None:
    """U-A3: an extension numbers its clauses from 1 again under its code ("I29 2" in the registry); the model cites
    "2" on that page; on the cited page it is the code's clause."""
    from jav.app.product_rules import ConditionDocument, Section

    document = ConditionDocument(kind="special", title="Feltételek", valid_from="2024-09-01", sections=(
        Section(clause="2", page=5), Section(clause="I29 1", page=14), Section(clause="I29 2", page=14), Section(clause="I28 2", page=15)))
    rule = rule_proposals.to_rule(rule_proposals.record_of(SET.rules["inv_flood_high"]), "property", GENERAL)[0]
    cited = rule.model_copy(update={"source": rule.source.model_copy(update={"page": 14, "clause": "2"})})
    assert rule_proposals.on_its_page(cited, document).source.clause == "I29 2"
    on_five = cited.model_copy(update={"source": cited.source.model_copy(update={"page": 5})})
    assert rule_proposals.on_its_page(on_five, document).source.clause == "2"  # the main part's own clause stays


def test_of_several_extensions_numbering_a_clause_on_one_page_the_quote_tells_which() -> None:
    """U-A3: one page holds three extensions, each with its clause 2 (G19 2, IKO 2, I29 2); the model cites "2" with a
    quote; the clause is the one whose heading stands last before the quote."""
    from jav.app.product_rules import ConditionDocument, Section

    document = ConditionDocument(kind="special", title="Feltételek", valid_from="2024-09-01", sections=tuple(
        Section(clause=c, page=14) for c in ("G19 1", "G19 2", "IKO 1", "IKO 2", "I29 1", "I29 2")))
    page = ("KIEGÉSZÍTŐ BIZTOSÍTÁS (G19)\n1. Küldött\n2. Küldött korlát\nKIEGÉSZÍTŐ BIZTOSÍTÁS (IKO)\n1. Törés\n"
            "2. Gépek külső okból bekövetkező törése\nKIEGÉSZÍTŐ BIZTOSÍTÁS (129)\n1. Vihar\n2. Szabadban tárolt vagyontárgyak")
    rule = rule_proposals.to_rule(rule_proposals.record_of(SET.rules["inv_flood_high"]), "property", GENERAL)[0]
    cited = rule.model_copy(update={"source": rule.source.model_copy(update={"page": 14, "clause": "2",
                                                                              "quote": "Gépek külső okból bekövetkező törése"})})
    assert rule_proposals.on_its_page(cited, document, page).source.clause == "IKO 2"
    assert rule_proposals.on_its_page(cited, document).source.clause == "2"  # without the page's text it stays


def test_a_record_s_form_is_set_right_where_its_meaning_is_plain() -> None:
    """U-A3 (the paid round on the real conditions): 41 proposals gave an amount or a percentage as a bare number, 16 put
    the rule above the level of the facts it reads, others compared a fact they did not list or gave `in` one value.
    Where the meaning is plain code sets it right: a bare number of a money fact is an amount in its currency, of a
    percentage its per cent; the rule's level is the lowest of its facts'; a compared fact is one it reads; `in` with
    one value is a list of it. A list of codes compared with codes keeps single codes."""
    record = rule_proposals.ProposedRule(
        title="Avult érték", kind="valuation", level="holder", modules=[], facts=["wear"], hit="first",
        rows=[rule_proposals.ProposedRow(when=[rule_proposals.ProposedCondition(fact="wear", op="gte", value='"30"'),
                                               rule_proposals.ProposedCondition(fact="sum_insured", op="gt", value="10000000"),
                                               rule_proposals.ProposedCondition(fact="asset_group", op="in", value='"stock"'),
                                               rule_proposals.ProposedCondition(fact="requested_modules", op="in", value='["burglary"]')],
                                         then=[rule_proposals.ProposedOutcome(outcome="verdict", value='"refer"')])],
        page=1, clause="1", quote="x")
    rule, problem = rule_proposals.to_rule(record, "property", GENERAL)
    assert problem is None, problem
    when = rule.model_dump(mode="json")["table"]["rows"][0]["when"]
    assert when["wear"] == {"gte": {"value": "30"}} and when["sum_insured"] == {"gt": {"amount": "10000000", "currency": "HUF"}}
    assert when["asset_group"] == {"in": ["stock"]} and when["requested_modules"] == {"in": ["burglary"]}
    assert rule.level == "asset_group" and set(rule.facts) == {"wear", "sum_insured", "asset_group", "requested_modules"}
    from jav.app import product_rules

    assert product_rules.rule_problems(rule) == []
