"""141 (backlog F-EHC-trial; DECISIONS 141): a CIB bank statement read by code, from its PDF's text layer or from the
bank's fixed-width text export.

The owner's decision: the sports club's statements first, read by code. The CIB statement prints its account, period, opening balance,
every line with a signed amount and the running balance, the counterparty's account and name, the memo, the totals
and the closing balance; the PDF's text layer and the text export lay them out the same way, so one profile of the
statement table reader (`layout: text`) reads both without any AI service, and the balances check every line. A PDF no
profile knows stays a PDF for the type recognition and extraction of a statement package.

Synthetic statements only: a made-up account number and IBAN (wrong check digits), made-up partners, shaped like the
2026 CIB statements (a page break inside the lines, a SEPA transfer in euro, the bank's fee lines).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jav import parties, reconcile, statement_package as sp, statement_table as st, store, work
from tests.test_flow_statement_table_136 import _run_all

GIRO = "11112223-33334444-55556666"  # made up, wrong check digits
DIGITS = GIRO.replace("-", "")
IBAN = "HU00 1111 2223 3333 4444 5555 6666"
FOOTER = ["CIB Bank Zrt. H-1027 Budapest, Example utca 1–3.",
          "Nyilvántartó cégbíróság: Example Cégbíróság Cégjegyzékszám: Cg. 00-00-000000",
          "999/9999/F, III/99. BIC (SWIFT) kód: CIBHHUHB"]
LINES = [  # (first line, second line, continuation lines): booked, kind; amount; balance
    ("2026.05.04.   Bejövő giro jóváírás; GIRO2605040001   250.000,00   1.250.000,00",
     "2026.05.04.   99998887-77776666-55554444", ["EXAMPLE MEMBER", "Közlemény: Membership fee 2026"]),
    ("2026.05.06.   Kimenő azonnali utalás; AZKIG26050600001   -120.000,00   1.130.000,00",
     "2026.05.06.   HU00 9999 8888 7777 6666 5555 4444",
     ["EXAMPLE SUPPLIER KFT.", "Közlemény: INV-2026-0042", "Bank által megfizetett tranzakciós illeték: 540,00 HUF"]),
    ("2026.05.06.   Jutalék; AZKIG26050600001   -540,00   1.129.460,00",
     "2026.05.06.   AD-Bankközi átutalás GIRO-n; HUF 540,00", ["MINADFKT1 H1Fz; Bank által megfizetett tranzakciós",
                                                             "illeték: 0,00 HUF;"]),
    ("2026.05.20.   Terhelés EGT-n belüli (SEPA) deviza; SPKSKI2A100C1   -397.000,00   732.460,00",
     "2026.05.20.   EUR 1000,000/SIR- 397,0000; Reservation #G-2026-07 Example Spo",
     ["Kedvezményezett IBAN számlaszáma: SI56000000000000000", "Kedvezményezett neve: EXAMPLE HOTEL d.o.o",
      "Közlemény: Reservation #G-2026-07 Example Sport Club", "Bank által megfizetett tranzakciós illeték: 0,00 HUF"]),
    ("2026.05.29.   Jutalék; HZF2605290   -2.460,00   730.000,00",
     "2026.05.29.   HS-Havi számlavezetési díj; MINHSFHH1HCORP H05W", ["Bank által megfizetett tranzakciós; illeték: 0,00 HUF"]),
]


def _pdf_lines(kind: str = "BANKSZÁMLA KIVONAT", lines=LINES, *, giro: str | None = GIRO, currency: str = "HUF",
               opening: str = "1.000.000,00", closing: str = "730.000,00", debit: str = "- 520.000,00",
               credit: str = "250.000,00", period: str = "2026.05.01 - 2026.05.29.") -> list[str]:
    """The lines the PDF reader gives for a CIB statement, with a page break after the third line."""
    head = ["SORSZÁM:   12", "OLDALSZÁM:   1", "ÜGYFÉLSZOLGÁLAT", "CIB24 azonosító:   12345678   STMC", "EXAMPLE SPORT CLUB",
            f"{kind}   EXAMPLETOWN", "SZÁMLATULAJDONOS: EXAMPLE SPORT CLUB", "EXAMPLE UTCA 1.", "SZÁMLA:   1111 222233 334",
            f"IDŐSZAK:   {period}   2026", f"DEVIZANEM:   {currency}", "SZÁMLA TÍPUS:   Pénzforgalmi bankszámla",
            *([f"GIRO SZÁM:   {giro}"] if giro else []), f"IBAN SZÁM:   {IBAN}", f"NYITÓ EGYENLEG:   {opening}",
            "KÖNYVELÉSI/ TRANZAKCIÓK   TERHELÉSEK(-)/   EGYENLEG", "ÉRTÉKNAP   JÓVÁÍRÁSOK"]
    body: list[str] = []
    for n, (first, second, more) in enumerate(lines):
        if n == 3:  # the page's footer and the next page's header inside the lines
            body += [*FOOTER, "SORSZÁM:   12", kind, "OLDALSZÁM:   2", "SZÁMLA:   1111 222233 334", f"IDŐSZAK:   {period}",
                     "KÖNYVELÉSI/ TRANZAKCIÓK   TERHELÉSEK(-)/   EGYENLEG", "ÉRTÉKNAP   JÓVÁÍRÁSOK"]
        body += [first, second, *more]
    tail = [f"ÖSSZESEN FORGALOM   TERHELÉS:   {debit}   JÓVÁÍRÁS:   {credit}", f"ZÁRÓ EGYENLEG:   {closing}",
            "ELŐJEGYZETT BETÉTKAMAT:   0,00   HITELKERET:   0,00", f"ELÉRHETŐ EGYENLEG:   {closing}", *FOOTER]
    return head + body + tail


def _columns(first: str) -> str:
    """A first line laid out in the text export's fixed columns."""
    booked, rest = first.split("   ", 1)
    kind, amount, balance = rest.rsplit("   ", 2)
    return f" {booked}  {kind:<78}{amount:>15}{balance:>21}    "


def _text_export(lines=LINES) -> bytes:
    """The same statement as the bank's fixed-width text export: cp1250, CRLF, a page header in the lines."""
    page = ["#1111-222233-334/00000012", "", " CIB Bank Zrt.", " " + "-" * 128, " BIC (SWIFT) kód: CIBHHUHB", "",
            " " * 48 + "ELEKTRONIKUS BANKSZÁMLA KIVONAT", " " * 80 + "CIB24 AZONOSÍTÓ:   12345678",
            " SZÁMLATULAJDONOS:  EXAMPLE SPORT CLUB", "",
            " SZÁMLA:            1111 222233 334" + " " * 40 + "SORSZÁM:    0000012"]
    out = [*page, " IDŐSZAK:           2026.05.01. - 2026.05.29." + " " * 30 + "OLDALSZÁM:        1",
           " DEVIZANEM:         HUF", " SZÁMLA TÍPUS:      Pénzforgalmi bankszámla", f" GIRO SZÁM:         {GIRO}",
           f" IBAN SZÁM:         {IBAN}", "", " " + "-" * 128, " NYITÓ EGYENLEG:" + " " * 80 + "1.000.000,00",
           " " + "-" * 128, " KÖNYVELÉSI/               TRANZAKCIÓK" + " " * 50 + "TERHELÉSEK(-)/            EGYENLEG",
           " ÉRTÉKNAP" + " " * 80 + "JÓVÁÍRÁSOK", ""]
    for n, (first, second, more) in enumerate(lines):
        if n == 3:
            out += [*page, " IDŐSZAK:           2026.05.01. - 2026.05.29." + " " * 30 + "OLDALSZÁM:        2", ""]
        booked, text = second.split("   ", 1)
        text = text.replace("; ", ";      ")  # the export pads inside a description where the PDF does not
        out += [_columns(first), f" {booked}  {text}", *(" " * 14 + m for m in more), ""]
    out += [" " + "-" * 128, " ÖSSZESEN FORGALOM    TERHELÉS:             -520.000,00" + " " * 20 + "JÓVÁÍRÁS:     250.000,00",
            " " + "-" * 128, " " * 80 + "ZÁRÓ EGYENLEG:          730.000,00"]
    return "\r\n".join(out).encode("cp1250")


@pytest.fixture(autouse=True)
def pdf_text(monkeypatch):
    """The PDF's text layer: the synthetic 'PDF' files hold their lines as plain text."""
    monkeypatch.setattr(st, "_pdf_lines", lambda path: Path(path).read_text(encoding="utf-8").splitlines())


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "s.sqlite"):
        yield tmp_path


def _pdf(folder: Path, name: str, lines: list[str]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _only(reading: st.Reading) -> st.Account:
    [account] = reading.accounts
    return account


# --- the statement ---------------------------------------------------------------------------------------------------------


def test_a_cib_pdf_statement_is_read_by_code_with_its_balances_and_partners(tmp_path):
    reading = st.read(_pdf(tmp_path, f"{DIGITS}_20260529.pdf", _pdf_lines()))
    a = _only(reading)
    s = a.statement
    assert (reading.profile, reading.institution) == ("cib_text_hu", "CIB")
    assert (a.key, a.title, a.currency, a.balances) == (f"{DIGITS}:HUF:2026-05-01", "…6666 12", "HUF", "export")
    assert (s["account_no"], s["account_iban"], s["period_start"], s["period_end"]) == (
        GIRO, IBAN.replace(" ", ""), "2026-05-01", "2026-05-29")
    assert (s["opening_balance"], s["closing_balance"], s["total_debit"], s["total_credit"]) == (
        "1000000.00", "730000.00", "520000.00", "250000.00")
    incoming, transfer, fee, sepa, monthly = s["transactions"]
    assert (incoming["direction"], incoming["amount"], incoming["running_balance"], incoming["value_date"]) == (
        "credit", "250000.00", "1250000.00", "2026-05-04")
    assert (incoming["description"], incoming["counterparty_name"], incoming["counterparty_account"], incoming["memo"]) == (
        "Bejövő giro jóváírás", "EXAMPLE MEMBER", "99998887-77776666-55554444", "Membership fee 2026")
    assert (transfer["counterparty_name"], transfer["counterparty_account"], transfer["memo"]) == (
        "EXAMPLE SUPPLIER KFT.", "HU00999988887777666655554444", "INV-2026-0042")
    assert (fee["description"], fee["counterparty_name"], fee["memo"]) == (
        "Jutalék", None, "AD-Bankközi átutalás GIRO-n; HUF 540,00")
    assert (sepa["counterparty_name"], sepa["counterparty_account"], sepa["memo"]) == (
        "EXAMPLE HOTEL d.o.o", "SI56000000000000000", "Reservation #G-2026-07 Example Sport Club")
    assert (sepa["original_amount"], sepa["original_currency"], sepa["direction"]) == ("1000.00", "EUR", "debit")
    assert (monthly["running_balance"], monthly["original_amount"]) == ("730000.00", None)
    assert a.checks == {"running_balance": {"ok": 5, "lines": 5}, "total_row": True, "closing_balance": True}
    assert a.problems == [] and st.checks_ok(a)


def test_the_text_export_of_the_same_month_gives_the_same_statement(tmp_path):
    from_pdf = _only(st.read(_pdf(tmp_path, "s.pdf", _pdf_lines())))
    path = tmp_path / f"{DIGITS}_20260529_0000012.txt"
    path.write_bytes(_text_export())
    from_text = _only(st.read(path))
    assert from_text.statement == from_pdf.statement
    assert (from_text.key, from_text.title, st.checks_ok(from_text)) == (from_pdf.key, from_pdf.title, True)


def test_a_wrong_running_balance_or_closing_balance_is_a_finding(tmp_path):
    lines = [(LINES[0][0].replace("1.250.000,00", "1.250.001,00"), *LINES[0][1:]), *LINES[1:]]
    a = _only(st.read(_pdf(tmp_path, "s.pdf", _pdf_lines(lines=lines, closing="730.001,00"))))
    assert a.checks["running_balance"] == {"ok": 3, "lines": 5}  # the wrong line and the one after it
    assert a.checks["closing_balance"] is False and not st.checks_ok(a)


def test_an_investment_account_and_an_account_without_a_giro_number_are_read_too(tmp_path):
    lines = [("2026.05.15.   Security trading; ADV/2605150001   2.000.000,00   2.000.032,86",
              "2026.05.15.   E-BANK Bef. jegy visszavásárlás", []),
             ("2026.05.15.   25A; FED/2605150002   -2.000.000,00   32,86", "2026.05.15.", [])]
    a = _only(st.read(_pdf(tmp_path, "s.pdf", _pdf_lines("BEFEKTETÉSI ÜGYFÉLSZÁMLA KIVONAT", lines, giro=None,
                                                          opening="32,86", closing="32,86", debit="- 2.000.000,00",
                                                          credit="2.000.000,00"))))
    assert (a.key, a.statement["account_no"], a.statement["account_iban"]) == (
        f"{DIGITS}:HUF:2026-05-01", None, IBAN.replace(" ", ""))
    assert [t["memo"] for t in a.statement["transactions"]] == ["E-BANK Bef. jegy visszavásárlás", None]
    assert st.checks_ok(a)


def test_a_pdf_no_profile_knows_stays_a_pdf(tmp_path):
    other = _pdf(tmp_path / "f", "other-bank.pdf", ["Bankszámlakivonat", "Nyitó egyenleg", "2026.05.01.   100.000"])
    with pytest.raises(st.StatementTableError, match="no statement"):
        st.read(other)
    _pdf(tmp_path / "f", f"{DIGITS}_20260529.pdf", _pdf_lines())
    (tmp_path / "f" / "notes.txt").write_text("not a statement", encoding="utf-8")
    reading = st.read(tmp_path / "f")
    assert [a.source["file"] for a in reading.accounts] == [f"{DIGITS}_20260529.pdf"]
    assert reading.skipped == []  # an unknown PDF may be extracted, a text file may be a note: neither is listed


# --- the statement package ------------------------------------------------------------------------------------------------


def _june() -> list[str]:
    june = [("2026.06.10.   Kimenő azonnali utalás; AZKIG26061000001   -30.000,00   700.000,00",
             "2026.06.10.   99997776-66665555-44443333", ["EXAMPLE COACH", "Közlemény: INV-2026-0050"])]
    return _pdf_lines(lines=june, opening="730.000,00", closing="700.000,00", debit="- 30.000,00", credit="0,00",
                      period="2026.06.01 - 2026.06.30.")


def test_a_statement_package_reads_the_cib_pdfs_by_code_and_extracts_none(db):
    party = parties.create("Example Sport Club", identities=[], actor="tester")["id"]
    folder = db / "cib"
    _pdf(folder, f"{DIGITS}_20260529.pdf", _pdf_lines())
    _pdf(folder, f"{DIGITS}_20260630.pdf", _june())
    _pdf(folder, "other-bank-2026-05.pdf", ["not a statement"])
    survey = sp.survey([folder], party_id=party, period_start="2026-01-01", period_end="2026-12-31")
    rows = sorted(survey["statements"], key=lambda r: r["period_start"])
    assert [(r["period_start"], r["rank"], r["balance_checked"], r["chosen"]) for r in rows] == [
        ("2026-05-01", "code_checked", True, True), ("2026-06-01", "code_checked", True, True)]
    assert [p["file"] for p in survey["pdfs"]] == ["other-bank-2026-05.pdf"]  # the CIB PDFs are not offered for extraction
    view = sp.create(name="Example statements", party_id=party, period_start="2026-01-01", period_end="2026-12-31",
                     paths=[folder], statements=[r["id"] for r in rows], pdfs=[], actor="tester")
    run_id = _run_all(view["workpackage_id"])
    assert work.get_run(run_id)["status"] == "done"
    saved = sorted((s for s in reconcile.statements()), key=lambda s: s["period_start"])
    assert [(s["period_start"], s["verified"], len(s["lines"])) for s in saved] == [("2026-05-01", True, 5),
                                                                                      ("2026-06-01", True, 1)]
    assert {reconcile.statement_account(s) for s in saved} == {DIGITS}
    assert parties.resolver().account(DIGITS) == party
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM invocations").fetchone()[0] == 0  # no AI call
