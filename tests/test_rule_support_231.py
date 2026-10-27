"""231 (stage D, D-c7d): JEV's judgement of how far the cited page supports a proposed rule, a mark and never an acceptance.

One JEV request per proposal code found nothing blocking in: which kind of rule the page states (or none), whether the
page states each row of the decision table, and whether it names something the rule leaves out; the cited page goes in
verbatim and the rule written out by code in English. The answer is a mark (supported, to check, contradicted) beside
the proposal, never a decision. JEV unavailable or switched off: the proposal is not asked and keeps the code's checks;
a blocked proposal is never sent. A stand-in JEV; no paid call.
"""

from __future__ import annotations

from types import SimpleNamespace

from typesafe_sdk import Choice, Noul

from jav.ai import jev
from jav.app import product_sets, rule_proposals, rule_support
from jav.core import cfg
from jav.documents import page_text

SET = product_sets.load()
MARKERS = cfg.load("rule_proposals")["skip_page_markers"]
CASH = SET.rules["inv_class_cash"]


class StandInJev:
    """Answers every request with the given kind and probabilities, and keeps the requests; or raises `error`."""

    def __init__(self, kind: str, *, rows: float = 0.95, left_out: float = 0.05, confidence: float = 0.92,
                 error: str | None = None):
        self.kind, self.rows, self.left_out, self.confidence, self.error = kind, rows, left_out, confidence, error
        self.asked: list[tuple[dict, dict]] = []

    def ask(self, request_id, state, questions, *, run_id, use_cache=True, config_hash=None):
        self.asked.append((state, questions))
        if self.error:
            raise jev.JevUnavailableError(self.error)
        dist = {self.kind: self.confidence, "none" if self.kind != "none" else "requirement": 1 - self.confidence}
        nouls = {k: SimpleNamespace(noul=self.rows) for k in questions if k.startswith("row_")}
        nouls["left_out"] = SimpleNamespace(noul=self.left_out)
        response = SimpleNamespace(choices={"kind": SimpleNamespace(choice=self.kind, probabilities=dist, confidence=self.confidence)},
                                   nouls=nouls)
        return SimpleNamespace(response=response, call=SimpleNamespace(model="jev-test", cost_usd=0.0))


def _pages(ident: str = "inv_security_rules") -> page_text.DocumentPages:
    return page_text.from_rows(product_sets.document_pages(SET, ident), MARKERS)


def test_a_supported_rule_is_marked_supported_and_never_accepted() -> None:
    stand_in = StandInJev("requirement")
    with jev.use_adapter(stand_in):
        found = rule_support.support(CASH, _pages(), run_id="t")
    assert (found.mark, found.reason, found.kind, found.rows, found.left_out) == ("supported", None, "requirement", (0.95,) * 3, 0.05)
    state, questions = stand_in.asked[0]
    assert set(questions) == {"kind", "row_1", "row_2", "row_3", "left_out"}
    assert isinstance(questions["kind"], Choice) and isinstance(questions["row_2"], Noul)
    assert "none" in questions["kind"].criteria and len(questions["kind"].criteria) == 9
    assert "row 2 of the proposed rule" in questions["row_2"].instructions
    assert CASH.source.quote in state["page"] and state["quote"] == CASH.source.quote
    assert state["rule"]["rows"][0] == ("1. When Asset group is Cash and Sum insured is above 5000000 HUF: Protection class "
                                        "required: 4; Security measures required: A safe of grade 3 at least, Alarm with remote signalling.")
    assert state["rule"]["applies_to"] == "Asset group" and state["rule"]["modules"] == ["burglary"]


def test_a_row_the_page_does_not_state_or_no_rule_at_all_is_contradicted_and_doubt_is_to_check() -> None:
    cases = [(StandInJev("requirement", rows=0.1), "contradicted", "the page does not state a row"),
             (StandInJev("none", confidence=0.95), "contradicted", "the page states no such rule"),
             (StandInJev("requirement", rows=0.5), "check", "a row is not clearly stated"),
             (StandInJev("requirement", left_out=0.8), "check", "the page may name something the rule leaves out"),
             (StandInJev("sublimit"), "check", "the page states another kind of rule")]
    for stand_in, mark, reason in cases:
        with jev.use_adapter(stand_in):
            found = rule_support.support(CASH, _pages(), run_id="t")
        assert (found.mark, found.reason) == (mark, reason), stand_in.__dict__


def test_without_jev_the_proposal_is_not_asked_and_keeps_the_code_checks() -> None:
    with jev.use_adapter(StandInJev("requirement", error="budget")):
        assert rule_support.support(CASH, _pages(), run_id="t") == rule_support.Support("not_asked", "jev_unavailable:budget")
    with jev.disabled():  # processing without JEV asks nothing: no verifier, the code's checks stay
        proposed = rule_proposals.propose("inv_security_rules@1", _pages(), "property", proposer=rule_proposals.set_proposer(SET),
                                          document=SET.documents["inv_security_rules"].content)
    assert len(proposed) == 4 and all(p.support is None and p.check is not None for p in proposed)


def test_only_a_proposal_code_found_nothing_blocking_in_is_sent() -> None:
    wrong = rule_proposals.record_of(CASH).model_copy(update={"page": 9})
    proposer = lambda request: rule_proposals.ProposedRules(rules=[rule_proposals.record_of(CASH), wrong])  # noqa: E731
    stand_in = StandInJev("requirement")
    with jev.use_adapter(stand_in):
        proposed = rule_proposals.propose("inv_security_rules@1", _pages(), "property", proposer=proposer,
                                          document=SET.documents["inv_security_rules"].content,
                                          verifier=lambda rule, pages: rule_support.support(rule, pages, run_id="t"))
    assert [p.check.blocking for p in proposed] == [False, True]
    assert [p.support.mark if p.support else None for p in proposed] == ["supported", None]
    assert len(stand_in.asked) == 1


def test_a_list_of_codes_is_written_out_by_the_codes_it_is_compared_with() -> None:
    """231 (U-A3): a rule comparing the requested modules (a list of codes) with codes is written out for JEV by those
    codes, as the evaluation compares them. Before, writing it out raised, so the re-check stopped on such a rule."""
    row = CASH.table.rows[0]
    rows = (row.model_copy(update={"when": {**row.when, "requested_modules": {"in": ["burglary"]}}}),
            row.model_copy(update={"when": {"requested_modules": {"eq": "burglary"}}}))
    rule = CASH.model_copy(update={"table": CASH.table.model_copy(update={"rows": rows})})
    written = rule_support.rule_sentences(rule)["rows"]
    assert "and Requested cover modules is one of Burglary and robbery:" in written[0]
    assert written[1].startswith("2. When Requested cover modules is Burglary and robbery:")
