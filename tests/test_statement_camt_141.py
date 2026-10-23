"""141 (DECISIONS 141, the Erste account's source): a bank's ISO 20022 camt.053 statement read by code.

The owner chose the bank's XML statement over the Excel export: it prints the opening and closing balances, every
line's running balance, the counterparty's name and account, the memo and, for a card purchase, the merchant and the
original amount, so the month needs no PDF companion. The bank names a line's kind by its own code only; the Erste
codes' texts (as the Excel export prints them) are the profile's data, so the reconciliation sees the same kinds. A
statement's key is the account digits, the currency and the period's start, as for the Excel export of the same month.
Synthetic statements only: a made-up account (wrong check digits) and made-up partners.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jav import parties
from jav.core import store
from jav.domains.finance import reconcile, statement_package as sp, statement_table as st
from tests.test_flow_statement_table_136 import _run_all
from tests.test_statement_erste_137 import JUNE, _export

NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"
IBAN = "HU00111122233333444455556666"  # made up, wrong check digits; the 137 Erste tests' account
DIGITS = IBAN[4:]
CARD_INFO = ("Kártyaszám - Tr.időpont:999999xxxxxx9999 - 2026.05.31 10:00\nTerminál - eng.kód  Trtip:X - 123456 - vásár.\n"
             "Elfogadó:EXAMPLE CLOUD INC\nTr.összeg - Árfolyam:20.00 USD -         18.50 EUR -  394.11 HUF/EUR")


def _entry(code: str, ind: str, amount: str, day: str, balance: str, *, party: tuple[str, str] | None = None,
           memo: str | None = None, info: str | None = None) -> str:
    role = "Cdtr" if ind == "DBIT" else "Dbtr"
    parties_xml = (f"<RltdPties><{role}><Nm>{party[0]}</Nm></{role}><{role}Acct><Id><IBAN>{party[1]}</IBAN></Id></{role}Acct>"
                   f"</RltdPties>") if party else ""
    return (f'<Ntry><NtryRef>1</NtryRef><Amt Ccy="HUF">{amount}</Amt><CdtDbtInd>{ind}</CdtDbtInd><Sts>BOOK</Sts>'
            f"<BookgDt><Dt>{day}</Dt></BookgDt><ValDt><Dt>{day}</Dt></ValDt><BkTxCd><Prtry><Cd>{code}</Cd></Prtry></BkTxCd>"
            '<Chrgs><Amt Ccy="HUF">.00</Amt><Tp><Prtry><Id>PTI</Id><Issr>GOV</Issr></Prtry></Tp></Chrgs>'
            f'<NtryDtls><TxDtls><AmtDtls><PrtryAmt><Tp>POSTBALANCE</Tp><Amt Ccy="HUF">{balance}</Amt></PrtryAmt></AmtDtls>'
            f"{parties_xml}{f'<RmtInf><Ustrd>{memo}</Ustrd></RmtInf>' if memo else ''}"
            f"{f'<AddtlTxInf>{info}</AddtlTxInf>' if info else ''}</TxDtls></NtryDtls></Ntry>")


ENTRIES = [_entry("DPTD", "DBIT", "7291.00", "2026-06-02", "92709.00", info=CARD_INFO),
           _entry("NKIP", "DBIT", "12000.00", "2026-06-04", "80709.00",
                  party=("Example Supplier Kft.", "HU00999988877777666655554444"), memo="INV-0001"),
           _entry("BEIP", "CRDT", "50000.00", "2026-06-10", "130709.00", party=("Example Customer Zrt.", "HU00222233334444555566667777"),
                  memo="S-2026-17"),
           _entry("JD0Z", "DBIT", "753.00", "2026-06-30", "129956.00")]


def _camt(entries=ENTRIES, *, bic="GIBAHUHB", bank="EXAMPLE BANK ZRT.", opening="100000.00", closing="129956.00",
          debit="20044.00", credit="50000.00", prolog: str = "") -> bytes:
    def bal(code: str, amt: str, day: str) -> str:
        return (f'<Bal><Tp><CdOrPrtry><Cd>{code}</Cd></CdOrPrtry></Tp><Amt Ccy="HUF">{amt}</Amt>'
                f"<CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>{day}</Dt></Dt></Bal>")

    body =(f'<?xml version="1.0" encoding="UTF-8"?>{prolog}<Document xmlns="{NS}"><BkToCstmrStmt><GrpHdr><MsgId>1</MsgId>'
            "<CreDtTm>2026-07-01T00:00:00</CreDtTm></GrpHdr><Stmt><Id>E 6/2026</Id><CreDtTm>2026-07-01T00:00:00</CreDtTm>"
            "<FrToDt><FrDtTm>2026-06-01T00:00:00</FrDtTm><ToDtTm>2026-06-30T23:59:59</ToDtTm></FrToDt>"
            f"<Acct><Id><IBAN>{IBAN}</IBAN></Id><Ccy>HUF</Ccy><Nm>Example account</Nm>"
            f"<Svcr><FinInstnId><BIC>{bic}</BIC><Nm>{bank}</Nm></FinInstnId></Svcr></Acct>"
            f"{bal('OPBD', opening, '2026-06-01')}{bal('CLBD', closing, '2026-06-30')}"
            f"<TxsSummry><TtlCdtNtries><Sum>{credit}</Sum></TtlCdtNtries><TtlDbtNtries><Sum>{debit}</Sum></TtlDbtNtries></TxsSummry>"
            f"{''.join(entries)}</Stmt></BkToCstmrStmt></Document>")
    return body.encode("utf-8")


def _file(folder: Path, name: str = f"20260630_{DIGITS}_camt053.xml", data: bytes | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(_camt() if data is None else data)
    return path


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "s.sqlite"):
        yield tmp_path


def _only(reading: st.Reading) -> st.Account:
    [account] = reading.accounts
    return account


def test_a_camt_statement_is_read_with_its_balances_partners_and_the_banks_kind_names(tmp_path):
    reading = st.read(_file(tmp_path))
    a = _only(reading)
    s = a.statement
    assert (reading.profile, reading.institution) == ("camt053", "Erste")
    assert (a.key, a.title, a.currency, a.balances) == (f"{DIGITS}:HUF:2026-06-01", "…6666 E 6/2026", "HUF", "export")
    assert (s["account_iban"], s["period_start"], s["period_end"], s["opening_balance"], s["closing_balance"]) == (
        IBAN, "2026-06-01", "2026-06-30", "100000.00", "129956.00")
    card, transfer, incoming, fee = s["transactions"]
    assert (card["description"], card["counterparty_name"], card["original_amount"], card["original_currency"]) == (
        "Kártya Használat", "EXAMPLE CLOUD INC", "20.00", "USD")
    assert (transfer["counterparty_name"], transfer["counterparty_account"], transfer["memo"], transfer["running_balance"]) == (
        "Example Supplier Kft.", "HU00999988877777666655554444", "INV-0001", "80709.00")
    assert (incoming["direction"], incoming["counterparty_name"], fee["description"]) == (
        "credit", "Example Customer Zrt.", "HAVI SZÁMLAVEZETÉSI DÍJ")
    assert a.checks == {"running_balance": {"ok": 4, "lines": 4}, "total_row": True, "closing_balance": True}
    assert st.checks_ok(a)


def test_the_same_month_of_the_excel_export_has_the_same_key(tmp_path):
    camt = _only(st.read(_file(tmp_path / "camt")))
    excel = _only(st.read(_export(tmp_path / "excel", "20260630", JUNE)))
    assert camt.key == excel.key
    assert reconcile.account_key(camt.statement["account_iban"]) == reconcile.account_key(excel.statement["account_no"])


def test_another_banks_camt_statement_keeps_its_codes_and_names_its_bank(tmp_path):
    reading = st.read(_file(tmp_path, data=_camt(bic="EXMPHUHB", bank="EXAMPLE BANK ZRT.")))
    a = _only(reading)
    assert reading.institution == "EXAMPLE BANK ZRT."
    assert [t["description"] for t in a.statement["transactions"]] == ["DPTD", "NKIP", "BEIP", "JD0Z"]
    assert a.statement["transactions"][0]["counterparty_name"] is None  # its card details are not this bank's text
    assert st.checks_ok(a)


def test_a_wrong_running_balance_or_total_is_a_finding(tmp_path):
    entries = [*ENTRIES[:3], _entry("JD0Z", "DBIT", "753.00", "2026-06-30", "129957.00")]
    a = _only(st.read(_file(tmp_path, data=_camt(entries, debit="20045.00"))))
    assert a.checks["running_balance"] == {"ok": 3, "lines": 4} and a.checks["total_row"] is False
    assert not st.checks_ok(a)


def test_a_camt_file_with_a_document_type_declaration_is_refused(tmp_path):
    path = _file(tmp_path, data=_camt(prolog='<!DOCTYPE Document [<!ENTITY x "boom">]>'))
    with pytest.raises(st.StatementTableError):
        st.read(path)


def test_a_folder_reads_the_camt_statements_beside_an_excel_export(tmp_path):
    _file(tmp_path / "f")
    _export(tmp_path / "f", "20260529", [["E 5/2026", "2026-05-12", "2026-05-12", "11112223-33334444-55556666", "Kártya Használat",
                                          "", __import__("decimal").Decimal("-1500.00"), "T", "Kártya Használat", ""]])
    reading = st.read(tmp_path / "f")
    assert sorted(a.key for a in reading.accounts) == [f"{DIGITS}:HUF:2026-05-01", f"{DIGITS}:HUF:2026-06-01"]
    assert "camt053" in reading.profile.split(",") and reading.skipped == []


def test_a_statement_package_takes_the_camt_statements_and_saves_them_checked(db):
    party = parties.create("Example Kft.", identities=[], actor="tester")["id"]
    folder = db / "camt"
    _file(folder)
    survey = sp.survey([folder], party_id=party, period_start="2026-01-01", period_end="2026-12-31")
    [row] = survey["statements"]
    assert (row["rank"], row["balance_checked"], row["chosen"], survey["pdfs"]) == ("code_checked", True, True, [])
    view = sp.create(name="Example statements", party_id=party, period_start="2026-01-01", period_end="2026-12-31",
                     paths=[folder], statements=[row["id"]], pdfs=[], actor="tester")
    _run_all(view["workpackage_id"])
    [saved] = reconcile.statements()
    assert saved["verified"] and len(saved["lines"]) == 4 and reconcile.statement_account(saved) == DIGITS
