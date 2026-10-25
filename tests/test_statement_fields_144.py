"""144 (DECISIONS 144): the readers keep a statement line's facts beyond the money, and no full card number.

The owner's decisions: every field the sources print that the readers dropped (the bank's reference, the order id, the
parties' end-to-end id, a card purchase's card, day and time, the terminal and the authorisation code, the exchange rate
and the fee); a card number masked to its first six and last four digits when it is read; the statements read again
for free. A later reading of the same statement (the same lines) replaces the earlier one without a to-do. And the
Erste Excel export, sent to the camt.053 reader since 141 because its root declares a `camt` prefix, is a ledger export
again. Synthetic data only: made-up accounts, the public test card number 4111 1111 1111 1111 and made-up partners.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jav.core import card_numbers
from jav.domains.finance import reconcile, statement_months as sm, statement_table as st
from jav.domains.finance import reconcile_store
from tests import test_statement_camt_141 as camt
from tests import test_statement_cib_141 as cib
from tests import test_statement_erste_137 as erste
from tests import test_statement_table_136 as table

CARD = "4111 1111 1111 1111"  # the public test card number (right check digit)
MASKED = "411111xxxxxx1111"


@pytest.fixture(autouse=True)
def pdf_text(monkeypatch):
    """The PDF's text layer: the synthetic 'PDF' files hold their lines as plain text."""
    monkeypatch.setattr(st, "_pdf_lines", lambda path: Path(path).read_text(encoding="utf-8").splitlines())


# --- a card number ------------------------------------------------------------------------------------------------------


def test_a_card_number_is_masked_to_its_first_six_and_last_four_digits():
    assert card_numbers.masked(CARD) == MASKED
    assert card_numbers.masked("4111111111111111") == MASKED
    assert card_numbers.masked("411111XXXXXX1111") == MASKED  # already masked by the bank
    assert card_numbers.masked("0000 XXXX XXXX 0000") == "0000xxxxxxxx0000"  # a statement printing fewer digits
    assert card_numbers.masked("4111 1111 1111 1112") is None  # a wrong check digit is no card number
    assert card_numbers.mask_text(f"{CARD} 20260105 101500; 12.00 EUR") == f"{MASKED} 20260105 101500; 12.00 EUR"
    assert card_numbers.mask_text("paid 20260105 101500 4111111111111111") == f"paid 20260105 101500 {MASKED}"


def test_what_only_looks_like_a_card_number_is_left_alone():
    iban = "HU42 1177 3016 4111 1111 1111 1111"  # four groups inside a longer grouped number
    assert card_numbers.mask_text(iban) == iban
    run = "20260105 101500 999999999.99 HUF"  # a date, a time and an amount side by side
    assert card_numbers.mask_text(run) == run
    assert card_numbers.mask_text("41111111111111112") == "41111111111111112"  # seventeen digits


# --- the Erste Excel export is a ledger export again -----------------------------------------------------------------------


def test_an_excel_export_declaring_a_camt_prefix_is_read_as_the_ledger_export(tmp_path):
    path = erste._export(tmp_path, "20260630", erste.JUNE)
    xml = path.read_bytes().replace(b"<Workbook xmlns=", b'<Workbook xmlns:camt="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02" xmlns=')
    path.write_bytes(xml)
    assert not st._is_camt(xml)
    reading = st.read(path)
    assert reading.profile == "erste_ledger_hu" and len(reading.accounts[0].statement["transactions"]) == 4


def test_a_camt_document_is_still_known_by_its_root(tmp_path):
    data = camt._camt()
    assert st._is_camt(data) and st._is_camt(b"<!-- an export -->\n" + data)


# --- the CIB statement ---------------------------------------------------------------------------------------------------


CIB_LINES = [
    ("2026.05.04.   Bejövő giro jóváírás; GIRO2605040001   250.000,00   1.250.000,00",
     "2026.05.04.   99998887-77776666-55554444",
     ["EXAMPLE MEMBER", "Közlemény: Membership fee 2026", "Partnerek közti egyedi azonosító: E2E-2026-0001",
      "Megbízás azonosító: ORD2026050400001"]),
    ("2026.05.06.   Kártyaterhelés; NAV/12345678   -120.000,00   1.130.000,00",
     f"2026.05.06.   {CARD} 20260505 101530; 120000.00 HUF", []),
    ("2026.05.06.   Jutalék; AZKIG26050600001   -540,00   1.129.460,00",
     "2026.05.06.   AD-Bankközi átutalás GIRO-n; HUF 540,00", ["Bank által megfizetett tranzakciós; illeték: 0,00 HUF"]),
    ("2026.05.20.   Terhelés EGT-n belüli (SEPA) deviza; SPKSKI2A100C1   -397.000,00   732.460,00",
     "2026.05.20.   EUR 1000,000/SIR- 397,0000; Reservation #G-2026-07 Example Spo",
     ["Kedvezményezett IBAN számlaszáma: SI56000000000000000", "Kedvezményezett neve: EXAMPLE HOTEL d.o.o",
      "Közlemény: Reservation #G-2026-07 Example Sport Club"]),
    ("2026.05.29.   Jutalék; Díj: 2.460,00 HUF   -2.460,00   730.000,00",
     "2026.05.29.   HS-Havi számlavezetési díj; MINHSFHH1HCORP H05W", []),
]


def test_a_cib_statement_keeps_its_references_identifiers_and_a_card_charges_details(tmp_path):
    a = cib._only(st.read(cib._pdf(tmp_path, "cib.pdf", cib._pdf_lines(lines=CIB_LINES))))
    incoming, card, fee, sepa, monthly = a.statement["transactions"]
    assert (incoming["bank_reference"], incoming["end_to_end_id"], incoming["order_id"]) == (
        "GIRO2605040001", "E2E-2026-0001", "ORD2026050400001")
    assert (card["bank_reference"], card["card_number"], card["purchase_date"], card["transaction_time"]) == (
        "NAV/12345678", MASKED, "2026-05-05", "10:15:30")
    assert card["memo"] == f"{MASKED} 20260505 101530; 120000.00 HUF"  # the detail row stays, masked
    assert (fee["bank_reference"], sepa["bank_reference"]) == ("AZKIG26050600001", "SPKSKI2A100C1")
    assert "bank_reference" not in monthly  # "Díj: 2.460,00 HUF" after the semicolon is no reference
    assert st.checks_ok(a)


def test_a_cib_credit_card_statement_names_the_card_of_each_purchase(tmp_path):
    lines = [ln.replace("KÁRTYASZÁM: 0000 XXXX XXXX 0000", f"KÁRTYASZÁM: {CARD}")
             .replace("0000 0000 0000 0000 00000000 000000", f"{CARD} 20260114 093000") for ln in cib.CARD]
    a = cib._only(st.read(cib._pdf(tmp_path, "card.pdf", lines)))
    payment, shop, cloud = a.statement["transactions"]
    assert "card_number" not in payment  # the account's payment stands before the card's head
    assert (shop["card_number"], shop["counterparty_name"]) == (MASKED, "EXAMPLE SHOP BUDAPEST")
    assert (cloud["card_number"], cloud["purchase_date"], cloud["transaction_time"], cloud["counterparty_name"]) == (
        MASKED, "2026-01-14", "09:30:00", "EXAMPLE CLOUD INC")
    assert st.checks_ok(a)
    a = cib._only(st.read(cib._pdf(tmp_path / "masked", "card.pdf", cib.CARD)))
    assert a.statement["transactions"][1]["card_number"] == "0000xxxxxxxx0000"


# --- the camt.053 statement and the Erste PDF companion -------------------------------------------------------------------


def test_a_camt_entry_keeps_its_card_block_references_and_charges(tmp_path):
    refs = ("<TxDtls><Refs><TxId>A1BC000000000000001</TxId><EndToEndId>E2E-77</EndToEndId></Refs>"
            "<RltdDts><AccptncDtTm>2026-06-04T10:15:30</AccptncDtTm></RltdDts>")
    transfer = camt._entry("NKIP", "DBIT", "12000.00", "2026-06-04", "80709.00", party=("Example Supplier Kft.", "HU00999988877777666655554444"),
                           memo="INV-0001", info="Jutalék összege: : 300 HUF + 450 HUF").replace("<TxDtls>", refs)
    transfer = transfer.replace("<Chrgs>", '<Chrgs><Amt Ccy="HUF">450.00</Amt><Tp><Prtry><Id>TRAX</Id></Prtry></Tp></Chrgs><Chrgs>')
    entries = [camt.ENTRIES[0], transfer, *camt.ENTRIES[2:]]
    (tmp_path / "june.xml").write_bytes(camt._camt(entries))
    a = cib._only(st.read(tmp_path / "june.xml"))
    card, transfer_line, incoming, _fee = a.statement["transactions"]
    assert (card["card_number"], card["purchase_date"], card["transaction_time"]) == ("999999xxxxxx9999", "2026-05-31", "10:00")
    assert (card["terminal"], card["authorisation_code"], card["exchange_rate"]) == ("X", "123456", "394.11 HUF/EUR")
    assert (transfer_line["bank_reference"], transfer_line["end_to_end_id"], transfer_line["transaction_time"]) == (
        "A1BC000000000000001", "E2E-77", "10:15:30")
    assert transfer_line["fee"] == "300 HUF + 450 HUF"  # the bank's own text before its charges
    assert "fee" not in incoming and "bank_reference" not in incoming
    assert st.checks_ok(a)


def test_the_erste_pdf_companion_gives_the_card_block_to_the_export_line(tmp_path):
    pdf = [ln for ln in erste.PDF_JUNE]
    at = pdf.index("Kártyaszám - Tr.időpont   999999xxxxxx9999 - 2026.05.31") + 1
    pdf[at:at] = ["Terminál - eng.kód Trtip   - 123456 - vásár."]
    a = erste._only(st.read(erste._export(tmp_path, "20260630", erste.JUNE, pdf=pdf)))
    card = a.statement["transactions"][0]
    assert (card["card_number"], card["purchase_date"], card["authorisation_code"], card["exchange_rate"]) == (
        "999999xxxxxx9999", "2026-05-31", "123456", "394.11 HUF/EUR")
    assert "terminal" not in card  # the PDF printed none


def test_a_revolut_line_keeps_its_fee(tmp_path):
    accounts = table._by_title(st.read(table._workbook(tmp_path)))
    huf = accounts[("Személyes számla", "HUF", 1)].statement["transactions"]
    assert [ln.get("fee") for ln in huf] == [None, None, "10.00 HUF", None]


# --- no full card number leaves a reader, and none reaches the reconciliation ------------------------------------------------


def test_a_full_card_number_in_any_text_is_masked_when_read(tmp_path):
    lines = [("2026.05.04.   Bejövő giro jóváírás; GIRO2605040001   250.000,00   1.250.000,00", "2026.05.04.",
              [f"EXAMPLE {CARD}", f"Közlemény: card {CARD} refund"]),
             *CIB_LINES[1:]]
    a = cib._only(st.read(cib._pdf(tmp_path, "cib.pdf", cib._pdf_lines(lines=lines))))
    first = a.statement["transactions"][0]
    assert CARD not in str(a.statement) and "4111111111111111" not in str(a.statement)
    assert first["memo"] == f"card {MASKED} refund"


def test_the_reconciliation_masks_a_card_number_an_extraction_kept_and_keeps_the_lines_id():
    raw = {"booking_date": "2026-05-06", "direction": "debit", "amount": "100.00", "memo": f"{CARD} 20260505 101530"}
    [plain] = reconcile.with_line_ids("s" * 64, [raw])
    shown = reconcile_store._masked(plain)
    assert shown["id"] == plain["id"] and shown["memo"] == f"{MASKED} 20260505 101530"


# --- a later reading of the same statement replaces the earlier one ---------------------------------------------------------


def _st(sid: str, *, seq: int, lines: list[dict] | None = None) -> dict:
    lines = lines if lines is not None else [{"id": f"{sid}:1", "booking_date": "2026-01-05", "amount": "100.00", "direction": "debit"},
                                             {"id": f"{sid}:2", "booking_date": "2026-01-20", "amount": "250.00", "direction": "credit"}]
    return {"id": sid, "doc_type": "statement_table", "account": "117730161234567800000000", "currency": "HUF",
            "period_start": "2026-01-01", "period_end": "2026-01-31", "verified": True, "lines": lines, "seq": seq}


def test_a_later_reading_of_the_same_statement_replaces_the_earlier_with_its_decisions():
    first, again = _st("first-reading-0000", seq=1), _st("again-reading-0000", seq=5)
    res = sm.resolve([again, first], {})
    assert res.replaced == {first["id"]: sm.Replacement(first["id"], again["id"], "reread")} and res.conflicts == []
    assert res.line_map == {"first-reading-0000:1": "again-reading-0000:1", "first-reading-0000:2": "again-reading-0000:2"}
    kept = sm.resolve([again, first], {sm.pair_key(first["id"], again["id"]): first["id"]})  # a person's choice wins
    assert set(kept.replaced) == {again["id"]}


def test_the_survey_offers_a_new_reading_of_a_stored_statement_in_its_place(tmp_path):
    from jav.app import parties
    from jav.core import store
    from jav.domains.finance import statement_package as sp
    from tests.test_flow_statement_table_136 import _run_all

    with store.use_store(tmp_path / "s.sqlite"):
        party = parties.create("Example Kft.", identities=[], actor="tester")["id"]
        old = tmp_path / "old"
        erste._export(old, "20260630", erste.JUNE, pdf=erste.PDF_JUNE)
        _run_all(sp.create_from_statement_table(old, [f"{erste.DIGITS}:HUF:2026-06-01"], name="Erste June", owner="tester")["id"])
        [stored] = reconcile_store.statements()
        pdf = list(erste.PDF_JUNE)  # the same month, the reader now keeps the authorisation code too
        at = pdf.index("Kártyaszám - Tr.időpont   999999xxxxxx9999 - 2026.05.31") + 1
        pdf[at:at] = ["Terminál - eng.kód Trtip   - 123456 - vásár."]
        erste._export(tmp_path / "new", "20260630", erste.JUNE, pdf=pdf)
        [row] = sp.survey([tmp_path / "new"], party_id=party, period_start="2026-06-01", period_end="2026-06-30")["statements"]
        assert row["id"] != stored["id"] and not row["in_store"] and row["chosen"]
        assert [r["id"] for r in row["replaces"]] == [stored["id"]] and row["replaced_by"] is None and row["conflicts"] == []


def test_other_lines_or_another_period_stay_a_conflict():
    first = _st("first-reading-0000", seq=1)
    other = _st("other-reading-0000", seq=2, lines=[{"id": "o:1", "booking_date": "2026-01-05", "amount": "100.00", "direction": "debit"}])
    assert sm.resolve([first, other], {}).conflicts == [(first["id"], other["id"])]
