"""231 (stage D, D-c7c): rules proposed from a condition document, by GPT under a budget or by a free stand-in.

The stand-in, answering with the invented insurer's rules for the pages asked, proposes exactly the 16 rules a careful
person reads, each turned into a rule of the registry's form and checked by code with nothing blocking. GPT's proposals
go through the call log and the ledger under a budget, a few pages at a time, after the catalogue and the cover
modules; a page its marking keeps out is never sent; a record that is no rule says why. A stand-in model stands for
GPT; no paid call.
"""

from __future__ import annotations

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
    assert "=== page 1 ===" in agent.prompts[0] and "=== page 4 ===" not in agent.prompts[0]
    assert '"name": "sum_insured"' in agent.prompts[0] and '"code": "burglary"' in agent.prompts[0]
    assert per == 3 and [p.pages for p in proposed] == [(1, 2, 3), (4,)]
    assert all(p.rule is not None and not p.check.blocking for p in proposed)
    rows = store.ledger_for_run(scope)
    assert [(r["step"], r["provider"], r["input_tokens"]) for r in rows] == [("rule_proposal_gpt", "openai", 3000)] * len(agent.prompts)


def test_gpt_is_not_asked_without_a_budget(db) -> None:
    agent = _Agent(rule_proposals.ProposedRules())
    with gpt_answer.use_agent_factory(lambda model, instructions: agent), pytest.raises(gpt_answer.NoBudget):
        rule_proposals.propose(GENERAL, _pages("inv_general_conditions"), "property", proposer=rule_proposals.gpt_proposer("x"))
    assert agent.prompts == []


def test_a_page_its_marking_keeps_out_is_never_sent(db) -> None:
    rows = product_sets.document_pages(SET, "inv_general_conditions")
    rows[1] = [*rows[1], "Internal"]
    agent = _Agent(rule_proposals.ProposedRules())
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
