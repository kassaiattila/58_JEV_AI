"""158 (backlog F-incoming-money-kinds; DECISIONS 152, 154, 158): the AI is asked what kind of incoming money a credit
line is.

Code leaves incoming money without an outgoing invoice as a candidate out of the pairing (`not_outgoing_payment`), so the
AI was never asked about it, and the kinds it knew were kinds of payment going out. Found on 2026-10-13: the request did
not say which way the money went, and a partner's kind was lent by name alone, so a purchase's kind could pass to the
same shop's refund. Now:

- the left-out incoming money is asked its kind (no invoice question), with the kinds the owner chose: a customer's
  payment, an own transfer, income, interest, a refund, an owner's contribution, other; the request says the money came
  in; a line going out is asked exactly as before (the same request, the same cache key);
- a partner's answer is lent only to lines going the same way, and an answer of the other way's question counts as none;
- a customer's payment says an outgoing invoice is expected: the quick review lists it under "an invoice is expected";
- the preselection offers only the invoices on the line's side (148: a debit pays an incoming invoice, a credit an
  outgoing one);
- an invented golden set measures the question per engine (`golden`), without storing anything.

Synthetic documents, made-up accounts and stand-in models only; no network, no paid call.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from jav.ai import gpt_choice
from jav.core import cfg, store
from jav.domains.finance import reconcile, reconcile_ai, reconcile_package, reconcile_review
from tests import test_reconcile_k2_129 as k2

INCOMING = ["customer_payment", "own_transfer", "income", "interest", "refund", "owner_contribution", "other"]


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield


def _credit(name: str | None, amount: str, memo: str | None = None, booking: str = "2026-04-10") -> dict:
    return k2._line(memo=memo, amount=amount, counterparty_name=name, counterparty_account=None, booking_date=booking,
                    direction="credit")


def _debit(name: str | None, amount: str, memo: str | None = None, booking: str = "2026-04-10") -> dict:
    return k2._line(memo=memo, amount=amount, counterparty_name=name, counterparty_account=None, booking_date=booking)


def _package(*lines, invoices: dict | None = None, doc_type: str = "invoice_hu") -> str:
    k2._save_statement("stmt", *lines)
    for name, inv in (invoices or {}).items():
        k2._save(name, inv, doc_type=doc_type)
    return reconcile_package.create(name="Example", accounts=[reconcile.account_key(k2.OWN)], period_start="2026-04-01",
                                    period_end="2026-04-30", actor="tester")["workpackage_id"]


class KindJev:
    """Answers the kind with `answer` (or `by_memo[memo]`) when it is among the question's kinds, else the first kind;
    records the asks."""

    def __init__(self, answer: str = "customer_payment", by_memo: dict[str, str] | None = None):
        self.asked: list[tuple[dict, dict]] = []
        self.answer, self.by_memo = answer, by_memo or {}

    def ask(self, request_id, state, questions, *, run_id, use_cache, config_hash):
        self.asked.append((state, questions))
        kinds = list(questions["line_kind"].criteria)
        wanted = self.by_memo.get(state["line"].get("memo") or "", self.answer)
        kind = wanted if wanted in kinds else kinds[0]
        choices = {"line_kind": SimpleNamespace(choice=kind, probabilities={kind: 0.96, "other": 0.04})}
        if "pays" in questions:
            choices["pays"] = SimpleNamespace(choice="none", probabilities={"none": 1.0})
        return SimpleNamespace(response=SimpleNamespace(choices=choices), call=SimpleNamespace(model="jev-test", cost_usd=0.0))


def _run(wp: str, tmp_path, jev: KindJev, monkeypatch, **kw) -> dict:
    monkeypatch.setattr(reconcile_ai, "get_adapter", lambda: jev)
    return reconcile_ai.run(wp, engines=["jev"], limits={"jev": Decimal("0.10")}, out_dir=tmp_path, **kw)


def _stored(engine: str = "jev") -> dict[str, dict]:
    with store.connect() as c:
        return {r["line_id"]: dict(r) for r in c.execute("SELECT * FROM reconcile_ai_proposals WHERE engine=?", (engine,))}


def _ids(wp: str) -> dict[str, str]:
    return {ln["counterparty_name"]: ln["id"] for ln in reconcile_package.workspace(wp)["lines"]}


# --- which lines are asked, and how ---------------------------------------------------------------------------------


def test_incoming_money_left_out_by_code_is_asked_its_kind_only(db, monkeypatch, tmp_path):
    wp = _package(_credit("Example Customer Kft", "250.00", memo="INV-0012"))
    line = reconcile_package.workspace(wp)["lines"][0]
    assert (line["state"], line["excluded_reason"]) == ("excluded", "not_outgoing_payment")
    jev = KindJev()
    r = _run(wp, tmp_path, jev, monkeypatch)
    assert r["counts"]["jev"]["asked"] == 1
    state, questions = jev.asked[0]
    assert set(questions) == {"line_kind"}  # no invoice question
    assert list(questions["line_kind"].criteria) == INCOMING
    assert "money received" in questions["line_kind"].instructions
    assert state["line"]["direction"] == "incoming (a credit)"
    row = _stored()[line["id"]]
    assert (row["kind"], row["kind_question"]) == ("customer_payment", "credit_kind")


def test_a_line_going_out_is_asked_exactly_as_before(db, monkeypatch, tmp_path):
    wp = _package(_debit("EXAMPLEMARKET ONLINE", "7.00"))
    jev = KindJev("retail_purchase")
    _run(wp, tmp_path, jev, monkeypatch)
    state, questions = jev.asked[0]
    assert "direction" not in state["line"]  # the request and its cache key are unchanged
    site = cfg.load("callsite:reconcile_line")["questions"]["line_kind"]
    assert questions["line_kind"].instructions == site["instructions"] and list(questions["line_kind"].criteria) == list(site["criteria"])
    assert _stored()[_ids(wp)["EXAMPLEMARKET ONLINE"]]["kind_question"] == "line_kind"


def test_a_partners_kind_passes_only_to_lines_going_the_same_way(db, monkeypatch, tmp_path):
    wp = _package(_debit("EXAMPLESHOP", "30.00", booking="2026-04-03"), _debit("EXAMPLESHOP", "12.00", booking="2026-04-05"),
                  _credit("EXAMPLESHOP", "30.00", memo="refund", booking="2026-04-09"))
    jev = KindJev("refund")
    r = _run(wp, tmp_path, jev, monkeypatch)
    assert r["counts"]["jev"] == {"asked": 2, "inherited": 1, "skipped": 0, "pays": 0, "failed": 0}
    asked = sorted(s["line"].get("direction", "out") for s, _q in jev.asked)
    assert asked == ["incoming (a credit)", "out"]
    kinds = {row["kind"] for row in _stored().values()}
    assert kinds == {"refund", "utility_or_telecom"}  # the debit's kind is never the refund's


def test_an_answer_of_the_outgoing_question_counts_as_none_for_incoming_money(db, monkeypatch, tmp_path):
    wp = _package(_credit("Example Customer Kft", "250.00", memo="INV-0012"))
    line_id = reconcile_package.workspace(wp)["lines"][0]["id"]
    with store.connect() as c:  # an answer stored before 158: the outgoing kinds, no question recorded
        c.execute("INSERT INTO reconcile_ai_proposals(line_id, engine, statement_doc_id, workpackage_id, options, kind,"
                  " kind_probability, measured, config_hash, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (line_id, "jev", "x", wp, "[]", "online_order", 0.9, 1, "old", "2026-10-12T00:00:00+00:00"))
    assert reconcile_ai.estimate(wp)["plan"]["jev"]["requests"] == 1
    jev = KindJev()
    _run(wp, tmp_path, jev, monkeypatch)
    assert len(jev.asked) == 1 and _stored()[line_id]["kind"] == "customer_payment"


def test_a_package_never_asked_can_be_asked_about_its_incoming_money_alone(db, monkeypatch, tmp_path):
    wp = _package(_debit("EXAMPLEMARKET ONLINE", "7.00"), _credit("Example Customer Kft", "250.00", memo="INV-0012"))
    assert reconcile_ai.estimate(wp, incoming_only=True)["plan"]["jev"]["requests"] == 1
    assert reconcile_ai.estimate(wp)["plan"]["jev"]["requests"] == 2
    jev = KindJev()
    r = _run(wp, tmp_path, jev, monkeypatch, incoming_only=True)
    assert r["lines"] == 1 and [s["line"].get("direction") for s, _q in jev.asked] == ["incoming (a credit)"]
    assert set(_stored()) == {_ids(wp)["Example Customer Kft"]}


def test_the_preselection_offers_only_the_invoices_on_the_lines_side(db):
    outgoing = k2._invoice(number="OUT-04", supplier_name="Example Supplier Kft.", buyer_name="Example Buyer Kft.")
    wp = _package(_debit("Example Buyer", "100.00", memo=None), _credit("Example Buyer", "101.00", memo=None),
                  invoices={"out": outgoing}, doc_type="invoice_out")
    ws = reconcile_package.workspace(wp)
    by_dir = {ln["direction"]: ln for ln in ws["lines"]}
    assert [i["id"] for i in reconcile_ai.preselect(by_dir["credit"], ws["invoices"])] == [k2._id("out")]
    assert reconcile_ai.preselect(by_dir["debit"], ws["invoices"]) == []  # a debit never pays an outgoing invoice


# --- what the answer means --------------------------------------------------------------------------------------------


def test_a_customers_payment_is_listed_where_an_invoice_is_expected(db, monkeypatch, tmp_path):
    wp = _package(_credit("Example Customer Kft", "250.00", memo="INV-0012"), _credit(None, "0.42", memo="Interest"))
    _run(wp, tmp_path, KindJev(by_memo={"Interest": "interest"}), monkeypatch)
    view = reconcile_review.review(wp)
    groups = {g["id"]: g for g in view["groups"]}
    assert [ln["counterparty_name"] for ln in groups["expects_invoice"]["lines"]] == ["Example Customer Kft"]
    # it is shown, but a person has nothing to decide on it (the quick review's "lines to decide" stays as before)
    assert (groups["expects_invoice"]["count"], groups["expects_invoice"]["to_decide"]) == (1, 0)
    assert all(g["to_decide"] == g["count"] for g in view["groups"] if g["id"] != "expects_invoice")
    assert view["excluded"]["not_outgoing_payment"]["count"] == 1  # the other one stays informational
    with pytest.raises(reconcile_review.ReviewError):
        reconcile_review.accept(wp, "expects_invoice", [_ids(wp)["Example Customer Kft"]], actor="tester")


def test_the_incoming_kinds_suggest_the_existing_reasons(db):
    site = cfg.load("callsite:reconcile_line")
    assert set(site["questions"]["credit_kind"]["criteria"]) == set(INCOMING)
    assert {k: site["kind_marks"].get(k) for k in INCOMING} == {
        "customer_payment": None, "own_transfer": "own_transfer", "income": "salary", "interest": "fee", "refund": None,
        "owner_contribution": None, "other": None}
    assert "customer_payment" in site["kind_expects_invoice"]
    for kind, c in site["questions"]["credit_kind"]["criteria"].items():
        assert c["what"] and c["not_for"] and c["examples"], kind


def test_every_kind_has_a_label_on_the_pairing_page_and_a_hungarian_one():
    root = Path(__file__).resolve().parents[1] / "ui" / "src"
    labels = (root / "domains" / "finance" / "reconcile" / "labels.ts").read_text(encoding="utf-8")  # 231 (C3e)
    block = re.search(r"export const KIND[^{]*\{(.*?)\}\);", labels, re.S).group(1)
    shown = dict(re.findall(r"(\w+): \"([^\"]+)\"", block))
    hu = json.loads((root / "i18n" / "hu-native.json").read_text(encoding="utf-8"))
    questions = cfg.load("callsite:reconcile_line")["questions"]
    for kind in [*questions["line_kind"]["criteria"], *questions["credit_kind"]["criteria"]]:
        assert kind in shown, kind
        assert hu.get(shown[kind]), shown[kind]


def test_gpt_gets_the_incoming_kinds_for_incoming_money(db, monkeypatch, tmp_path):
    wp = _package(_credit("Example Customer Kft", "250.00", memo="INV-0012"))
    sent = []

    def fake(request_id, instructions, prompt, fields, *, run_id, limits):
        sent.append((instructions, json.loads(prompt), fields))
        return SimpleNamespace(values={"line_kind": "customer_payment"}, probabilities={"line_kind": {"customer_payment": 0.9}},
                               confidence={"line_kind": 0.9}, measured=True, call=SimpleNamespace(model="gpt-test", cost_usd=0.0))

    monkeypatch.setattr(gpt_choice, "ask", fake)
    reconcile_ai.run(wp, engines=["gpt"], limits={"openai": Decimal("0.10")}, out_dir=tmp_path)
    instructions, prompt, fields = sent[0]
    assert fields == {"line_kind": INCOMING} and prompt["line"]["direction"] == "incoming (a credit)"
    assert "money received" in instructions and "utility_or_telecom" not in instructions


# --- the invented golden set ------------------------------------------------------------------------------------------


def test_the_golden_set_covers_every_kind_and_none_of_the_examples():
    cases = cfg.load("golden_credit_kinds")["cases"]
    criteria = cfg.load("callsite:reconcile_line")["questions"]["credit_kind"]["criteria"]
    assert {c["expected"] for c in cases} == set(INCOMING)
    assert min(sum(c["expected"] == k for c in cases) for k in INCOMING) >= 3
    examples = {e.casefold() for c in criteria.values() for e in c["examples"]}
    texts = {str(c.get(f) or "").casefold() for c in cases for f in ("counterparty_name", "description", "memo")}
    assert not examples & texts
    assert len({c["id"] for c in cases}) == len(cases)


def test_the_golden_measurement_scores_each_engine_and_stores_nothing(db, monkeypatch, tmp_path):
    monkeypatch.setattr(reconcile_ai, "get_adapter", lambda: KindJev("other"))
    r = reconcile_ai.golden(engines=["jev"], limits={"jev": Decimal("0.05")}, out_dir=tmp_path)
    cases = cfg.load("golden_credit_kinds")["cases"]
    others = sum(c["expected"] == "other" for c in cases)
    assert r["engines"]["jev"]["right"] == others and r["engines"]["jev"]["cases"] == len(cases)
    assert r["engines"]["jev"]["by_kind"]["other"] == {"right": others, "cases": others}
    rows = [json.loads(x) for x in open(r["raw"], encoding="utf-8")]
    assert len(rows) == len(cases) and {row["expected"] for row in rows} == set(INCOMING)
    assert _stored() == {}


def test_the_golden_measurement_needs_a_budget_per_engine(db):
    with pytest.raises(ValueError):
        reconcile_ai.golden(engines=["jev", "gpt"], limits={"jev": Decimal("0.05")})


def test_the_command_runs_the_golden_set_only_with_a_budget(db, monkeypatch, tmp_path, capsys):
    from jav import cli

    monkeypatch.setattr(reconcile_ai, "get_adapter", lambda: KindJev("other"))
    original = reconcile_ai.golden
    monkeypatch.setattr(reconcile_ai, "golden", lambda **kw: original(out_dir=tmp_path, **kw))
    assert cli.main(["reconcile-ai", "--golden", "--engine", "jev"]) == 2  # no sub-budget: nothing is asked
    assert cli.main(["reconcile-ai", "--golden", "--engine", "jev", "--jev-budget-usd", "0.01"]) == 0
    out = capsys.readouterr().out
    assert "no budget for: jev" in out and "jev: 4/29 as labelled" in out
    assert cli.main(["reconcile-ai"]) == 2  # neither a package nor --golden
