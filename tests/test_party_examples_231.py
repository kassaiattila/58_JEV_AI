"""231 (stage U, U1e; the owner's decision of 2026-10-28): the bank statements' and the reconciliation's example material.

Both processes belong to an own party, and the live store had only real ones. The invented consultancy
(`configs/example_parties.json`) is both packs' example material: installed, the examples' machine makes it with its
tax number, its name and its forint account; installed again, it changes nothing. Its four statements are a bank's
camt.053 XML files, which the statements' reader reads by code with every balance checking; a statements package takes
them free of charge. The consultancy issued four of the invented invoices of `golden_synthetic.json`, whose correct
reading (their expected values) the code pairs with the statements: three customers' payments with their three
invoices, while the office rent paid without an invoice and the bank's fees stay unpaired. The party goes only while
no case or record names it, and never one a person made. Invented data; no paid call.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jav.app import examples, parties, registrations
from jav.core import cfg, store
from jav.core.identity import person
from jav.core.process import cases
from jav.core.process.definition import StepDef
from jav.domains.finance import own_parties, party_examples, reconcile, reconcile_store
from jav.domains.finance import statement_package as sp, statement_table as st
from tests import test_reconcile_k2_129 as k2
from tests.test_flow_statement_table_136 import _run_all
from tests.test_process_turn_214 import define

registrations.load_all()
ANNA = "Minta Anna"
TAX = "12121216-2-42"
ACCOUNT = "121000284681357400000000"


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "parties.sqlite"):
        yield tmp_path


def _state(pack: str = "bank_statements") -> dict:
    [state] = examples.of(pack)["sets"]
    return state


def _party() -> dict:
    [party] = [p for p in parties.parties() if p["name"] == "Minta Tanácsadó Kft."]
    return party


def test_both_processes_install_the_invented_party_with_its_account(db) -> None:
    assert _state()["state"] == examples.MISSING
    examples.install("bank_statements", person(ANNA))
    state = _state()
    assert (state["state"], state["example"], state["title"]) == (examples.INSTALLED, True, "Minta Tanácsadó Kft.")
    assert _state("reconciliation")["state"] == examples.INSTALLED  # the same material
    party = _party()
    keys = {(i["kind"], i["key"]) for i in party["identities"]}
    assert {("tax", parties.tax_key(TAX)), ("account", ACCOUNT)} <= keys
    details = own_parties.accounts()[ACCOUNT]
    assert (details["kind"], details["currencies"], details["bank"]) == ("account", ["HUF"], "Példa Bank Zrt.")
    examples.install("reconciliation", person(ANNA))  # again: nothing new
    assert len(parties.parties()) == 1


def test_the_reconciliation_says_how_its_material_is_tried() -> None:
    shown = examples.of("reconciliation")
    assert shown["packets"] == [] and "Documents" in shown["note"] and "Bank statements" in shown["note"]


def test_the_invented_statements_are_a_banks_xml_files_read_by_code(db) -> None:
    files = examples.packet_files("bank_statements", "example_consultancy")
    assert [Path(f).name for f in files] == [f"2026{m}_{ACCOUNT}_camt053.xml" for m in ("0331", "0430", "0531", "0630")]
    closing = None
    for f in files:
        [account] = st.read(Path(f)).accounts
        s = account.statement
        assert st.checks_ok(account) and account.checks["running_balance"]["ok"] == len(s["transactions"])
        assert closing is None or s["opening_balance"] == closing  # each month opens with the one before it closing
        closing = s["closing_balance"]
    assert closing == "2238000.00"  # 500 000 + 1 270 000 - 180 000 + 508 000 + 150 000 - 4 x 2 500
    current = cfg.load(examples.DOCUMENTS_PREFIX + "bank_statements")["packets"]
    assert party_examples.example_packets({p["id"]: p["title"] for p in current}) == current  # what --set prints


def test_the_documents_process_offers_the_invoices_the_statements_pay() -> None:
    [packet] = [p for p in cfg.load(examples.DOCUMENTS_PREFIX + "documents")["packets"] if p["id"] == "own_party_invoices"]
    assert [d["file"] for d in packet["documents"]] == [
        "synthetic_out_hu_huf.pdf", "synthetic_out_hu_credit_note.pdf", "synthetic_out_en_distractors.pdf",
        "synthetic_out_hu_aam_person.pdf"]


def _invoices() -> dict[str, str]:
    """The consultancy's invoices as a correct reading gives them (the golden set's expected values); their ids."""
    cases_ = {c["id"]: c for c in cfg.load("golden_synthetic")["cases"]}
    out = {}
    for name in ("synthetic_out_hu_huf", "synthetic_out_hu_credit_note", "synthetic_out_en_distractors",
                 "synthetic_out_hu_aam_person"):
        fields = {"supplier_name": "Minta Tanácsadó Kft.", "supplier_tax_id": TAX, **cases_[name]["expected"]}
        out[k2._save(name, fields, doc_type="invoice_out")] = fields["invoice_number"]
    return out


def test_the_code_pairs_three_payments_with_the_invented_invoices(db) -> None:
    examples.install("bank_statements", person(ANNA))
    party = _party()["id"]
    folder = Path(examples.packet_files("bank_statements", "example_consultancy")[0]).parent
    survey = sp.survey([folder], party_id=party, period_start="2026-03-01", period_end="2026-06-30")
    assert [r["chosen"] for r in survey["statements"]] == [True] * 4 and survey["pdfs"] == []
    view = sp.create(name="Invented statements", party_id=party, period_start="2026-03-01", period_end="2026-06-30",
                     paths=[folder], statements=[r["id"] for r in survey["statements"]], pdfs=[], actor="tester")
    _run_all(view["workpackage_id"])
    saved = reconcile_store.statements()
    assert len(saved) == 4 and all(s["verified"] for s in saved)
    numbers = _invoices()
    result = reconcile.propose(reconcile_store.snapshot())
    lines = {ln["id"]: ln for s in saved for ln in s["lines"]}
    proposed = sorted((lines[c["line_id"]]["memo"], numbers[c["invoice_id"]]) for c in result["candidates"] if c["proposed"])
    assert proposed == [("AB003", "AB003"), ("ABCD0005", "ABCD0005"), ("ABCD0011", "ABCD0011")]


def test_the_party_goes_unless_a_case_keeps_it(db) -> None:
    examples.install("bank_statements", person(ANNA))
    party = _party()["id"]
    cases.start("holder", define(StepDef(id="a", kind="turn_note")), {"scope": {"party": party}}, person(ANNA))
    with pytest.raises(examples.ExampleInUse):
        examples.remove("reconciliation", person(ANNA))
    with cases.transaction() as c:
        c.execute("DELETE FROM process_cases WHERE case_id='holder'")
    examples.remove("reconciliation", person(ANNA))
    assert _state()["state"] == examples.MISSING and parties.parties() == [] and ACCOUNT not in own_parties.accounts()


def test_a_party_a_person_made_is_not_the_examples(db) -> None:
    parties.create("Minta Tanácsadó Kft.", identities=[("tax", parties.tax_key(TAX), TAX)], actor=person(ANNA))
    state = _state()
    assert (state["state"], state["example"]) == (examples.PARTIAL, False)  # its account is not the party's yet
    with pytest.raises(examples.ExampleRefused):
        examples.install("bank_statements", person(ANNA))
    with pytest.raises(examples.ExampleRefused):
        examples.remove("bank_statements", person(ANNA))
    assert len(parties.parties()) == 1 and ACCOUNT not in own_parties.accounts()
