"""137 (backlog F-erste-reader, DECISIONS 137): a bank's Excel 2003 XML export, one statement per account and month,
completed from the same month's PDF statement by code.

The owner's decision: "XML + PDF by code". The Erste export lists every line with its partner, account and memo, but
no balance, and a card line names no merchant; the month's PDF statement prints the balances, the merchant and a
foreign purchase's original amount. Both are read without any AI service. The exports and the PDF lines here are
synthetic: a made-up account number (wrong check digits) and made-up partners, shaped like the 2026 Erste files.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from jav import reconcile, statement_table as st, store, work
from tests.test_flow_statement_table_136 import _run_all

OWN = "11112223-33334444-55556666"  # made up, wrong check digits
DIGITS = OWN.replace("-", "")
NS = "urn:schemas-microsoft-com:office:spreadsheet"
HEADER = ["Kivonat sorszáma", "Könyvelés dátuma", "Értéknap", "Számlaszám", "Partner neve", "Partner számlaszáma", "Összeg",
          "Terhelés vagy jóváírás (T/J)", "Tranzakció típusa", "Közlemény"]
JUNE = [["E 6/2026", "2026-06-02", "2026-06-02", OWN, "Kártya Használat", "", Decimal("-7291.00"), "T", "Kártya Használat", ""],
        ["E 6/2026", "2026-06-04", "2026-06-04", OWN, "Example Supplier Kft.", "99998887-77776666-55554444", Decimal("-12000.00"),
         "T", "AZONNALI ÁTUTALÁS BANKON KÍVÜLRE NETBANKON", "INV-0001"],
        ["E 6/2026", "2026-06-10", "2026-06-10", OWN, "Example Customer Zrt.", "", Decimal("50000.00"), "J",
         "BANKON KÍVÜLI AZONNALI ÁTUTALÁS JÓVÁÍRÁSA", "S-2026-17"],
        ["E 6/2026", "2026-06-30", "2026-06-30", OWN, "", "", Decimal("-753.00"), "T", "HAVI SZÁMLAVEZETÉSI DÍJ", ""]]
MAY = [["E 5/2026", "2026-05-12", "2026-05-12", OWN, "Kártya Használat", "", Decimal("-1500.00"), "T", "Kártya Használat", ""]]
PAGE_BREAK = ["Ez a bankszámlakivonat egyúttal számviteli bizonylatként is szolgál, az ebben feltüntetett tételek",
              "forgalmi adóról szóló törvény értelmében mentesek az általános forgalmi adó alól.", "Bankszámlakivonat",
              "Eredeti példány", "Ügyfél neve, címe   EXAMPLE KFT.", f"Bankszámlaszám   {OWN}", "BANKSZÁMLA FORGALMAK",
              "Könyvelés   Értéknap   Tranzakció megnevezése   Referencia   Összeg(+/-)   Egyenleg   Illeték (HUF)",
              "dátuma   (PTI+KPTI)"]
PDF_JUNE = ["Bankszámlakivonat", "Ügyfél neve, címe   EXAMPLE KFT.   Kivonat száma   E 2026/6",
            "Számla megnevezése   Időszak   2026.06.01. – 2026.06.30.",
            f"Bankszámlaszám   {OWN}   Devizanem   HUF", "BANKSZÁMLA FORGALMAK",
            "Könyvelés   Értéknap   Tranzakció megnevezése   Referencia   Összeg(+/-)   Egyenleg   Illeték (HUF)",
            "dátuma   (PTI+KPTI)", "Nyitó egyenleg", "2026.06.01.   100.000",
            "2026.06.02.   2026.06.02. KÁRTYA HASZNÁLAT   -7.291   92.709   (0,00)", "( - )",
            "Kártyaszám - Tr.időpont   999999xxxxxx9999 - 2026.05.31", "Elfogadó   EXAMPLE CLOUD INC",
            *PAGE_BREAK,
            "Tr.összeg - Árfolyam   20.00 USD -   18.50 EUR -", "394.11 HUF/EUR",
            "2026.06.04.   2026.06.04. AZONNALI ÁTUTALÁS   -12.000   80.709   (54,00)",
            "Partner számlatulajdonos:   EXAMPLE SUPPLIER KFT.", "Közlemény:   INV-0001",
            "2026.06.10.   2026.06.10. JÓVÁÍRÁS   50.000   130.709   ( - )",
            "2026.06.30.   2026.06.30. HAVI SZÁMLAVEZETÉSI DÍJ   -753   129.956   (0,00)", "( - )",
            "20.044", "Összes terhelés", "Összes Jóváírás   50.000", "Záró egyenleg   129.956", "Felhasználható egyenleg   129.956"]


def _cell(value) -> str:
    if isinstance(value, Decimal):
        return f'<Cell><Data ss:Type="Number">{value}</Data></Cell>'
    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        return f'<Cell><Data ss:Type="DateTime">{value}T00:00:00.000</Data></Cell>'
    return f'<Cell><Data ss:Type="String">{value}</Data></Cell>' if value else "<Cell/>"


def _xml(rows: list[list], *, prolog: str = "") -> bytes:
    body = "".join("<Row>" + "".join(_cell(v) for v in r) + "</Row>" for r in [HEADER, *rows])
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n{prolog}<?mso-application progid="Excel.Sheet"?>\n'
            f'<Workbook xmlns="{NS}" xmlns:ss="{NS}"><Worksheet ss:Name="Kivonat"><Table>{body}</Table></Worksheet>'
            "</Workbook>").encode("utf-8")


def _export(folder: Path, day: str, rows: list[list], *, pdf: list[str] | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}_{DIGITS}_excel.xml"
    path.write_bytes(_xml(rows))
    if pdf is not None:
        (folder / "pdf").mkdir(exist_ok=True)
        (folder / "pdf" / f"{day}_{DIGITS}_S.pdf").write_text("\n".join(pdf), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def pdf_text(monkeypatch):
    """The PDF's text layer: the synthetic 'PDF' files hold their lines as plain text."""
    monkeypatch.setattr(st, "_pdf_lines", lambda path: Path(path).read_text(encoding="utf-8").splitlines())


def _only(reading: st.Reading) -> st.Account:
    [account] = reading.accounts
    return account


def test_the_xml_export_is_one_statement_per_account_and_month_without_balances(tmp_path):
    a = _only(st.read(_export(tmp_path, "20260630", JUNE)))
    s = a.statement
    assert (a.key, a.currency, a.balances, a.title) == (f"{DIGITS}:HUF:2026-06-01", "HUF", "none", "…6666 E 6/2026")
    assert (s["account_no"], s["period_start"], s["period_end"]) == (OWN, "2026-06-01", "2026-06-30")
    assert (s["opening_balance"], s["closing_balance"], s["total_debit"], s["total_credit"]) == (None, None, "20044.00", "50000.00")
    card, transfer, incoming, fee = s["transactions"]
    assert (card["counterparty_name"], card["description"], card["amount"], card["direction"]) == (None, "Kártya Használat", "7291.00", "debit")
    assert (transfer["counterparty_name"], transfer["counterparty_account"], transfer["memo"]) == (
        "Example Supplier Kft.", "99998887-77776666-55554444", "INV-0001")
    assert (incoming["direction"], fee["running_balance"], fee["original_amount"]) == ("credit", None, None)
    assert a.checks["running_balance"] is None and a.checks["closing_balance"] is None and not st.checks_ok(a)
    [row] = st.survey(st.read(_export(tmp_path, "20260630", JUNE)))["accounts"]
    assert (row["balance_checked"], row["companion"], row["lines"]) == (False, None, 4)


def test_the_months_pdf_adds_the_balances_the_merchant_and_the_original_amount(tmp_path):
    a = _only(st.read(_export(tmp_path, "20260630", JUNE, pdf=PDF_JUNE)))
    s = a.statement
    assert a.balances == "companion" and a.source["companion"]["file"] == f"20260630_{DIGITS}_S.pdf"
    assert (s["opening_balance"], s["closing_balance"]) == ("100000.00", "129956.00")
    card, transfer, _incoming, fee = s["transactions"]
    assert (card["counterparty_name"], card["original_amount"], card["original_currency"], card["running_balance"]) == (
        "EXAMPLE CLOUD INC", "20.00", "USD", "92709.00")
    assert (transfer["counterparty_name"], transfer["original_currency"]) == ("Example Supplier Kft.", None)  # the export's name
    assert fee["running_balance"] == "129956.00"
    assert a.checks["running_balance"] == {"ok": 4, "lines": 4} and a.checks["closing_balance"] is True
    assert a.companion_problems == [] and st.checks_ok(a)


def test_a_line_missing_from_the_pdf_is_a_finding(tmp_path):
    pdf = [line for line in PDF_JUNE if "HAVI SZÁMLAVEZETÉSI DÍJ" not in line]
    a = _only(st.read(_export(tmp_path, "20260630", JUNE, pdf=pdf)))
    assert a.companion_problems == ["line 4: not on the PDF statement"] and not st.checks_ok(a)
    assert a.checks["running_balance"] == {"ok": 3, "lines": 4}
    other = _only(st.read(_export(tmp_path / "other", "20260630", JUNE, pdf=[*PDF_JUNE[:-5], "2026.06.30.   2026.06.30. KAMAT   9   129.965   ( - )", *PDF_JUNE[-5:]])))
    assert other.companion_problems == ["PDF line 5: not in the export"]


def test_a_pdf_of_another_account_is_a_finding(tmp_path):
    pdf = [line.replace(OWN, "11112223-33334444-55556667") for line in PDF_JUNE]
    a = _only(st.read(_export(tmp_path, "20260630", JUNE, pdf=pdf)))
    assert "the PDF statement is of another account" in a.companion_problems


def test_a_folder_reads_every_export_and_lists_what_it_skipped(tmp_path):
    _export(tmp_path, "20260529", MAY)
    _export(tmp_path, "20260630", JUNE, pdf=PDF_JUNE)
    (tmp_path / "notes.txt").write_text("not an export", encoding="utf-8")
    (tmp_path / "broken.xml").write_text("<Workbook", encoding="utf-8")
    reading = st.read(tmp_path)
    assert [(a.key, a.balances) for a in reading.accounts] == [(f"{DIGITS}:HUF:2026-05-01", "none"),
                                                               (f"{DIGITS}:HUF:2026-06-01", "companion")]
    assert reading.file_name == tmp_path.name and [s["file"] for s in reading.skipped] == ["broken.xml"]
    survey = st.survey(reading)
    assert [a["period_start"] for a in survey["accounts"]] == ["2026-05-01", "2026-06-01"] and survey["skipped"] == 1


def test_an_xml_with_a_document_type_declaration_is_refused(tmp_path):
    path = tmp_path / f"20260630_{DIGITS}_excel.xml"
    path.write_bytes(_xml(JUNE, prolog='<!DOCTYPE Workbook [<!ENTITY x "boom">]>\n'))
    with pytest.raises(st.StatementTableError):
        st.read(path)


def test_the_statement_file_keeps_both_sources(tmp_path):
    reading = st.read(_export(tmp_path, "20260630", JUNE, pdf=PDF_JUNE))
    [path] = st.derive(reading, [f"{DIGITS}:HUF:2026-06-01"], out_dir=tmp_path / "derived")
    content = st.load_derived(path.read_bytes())
    assert content["source"]["file"] == f"20260630_{DIGITS}_excel.xml" and content["balances"] == "companion"
    assert content["companion"]["file"] == f"20260630_{DIGITS}_S.pdf" and len(content["companion"]["sha256"]) == 64
    assert content["companion_problems"] == [] and content["statement"]["transactions"][0]["original_currency"] == "USD"
    assert "/" not in path.name and path.name.endswith(".json")


# --- as a work package ----------------------------------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "s.sqlite"):
        yield tmp_path


def test_the_months_run_free_and_a_month_without_pdf_has_one_to_do(db):
    folder = db / "erste"
    _export(folder, "20260529", MAY)
    _export(folder, "20260630", JUNE, pdf=PDF_JUNE)
    keys = [a.key for a in st.read(folder).accounts]
    wp = work.create_from_statement_table(folder, keys, name="Erste 2026", owner="tester")
    run_id = _run_all(wp["id"])
    paths = {i["item_id"]: Path(i["source_path"]).name for i in wp["items"]}
    statuses = {}
    for item in work.get_run(run_id)["items"]:
        reasons = sorted(r["reason"] for r in work.item_reasons(run_id, item["item_id"])["run"])
        statuses[paths[item["item_id"]]] = (item["final_status"], reasons)
    june = next(v for k, v in statuses.items() if "2026-06-01" in k)
    may = next(v for k, v in statuses.items() if "2026-05-01" in k)
    assert june == ("done", []) and may == ("needs_review", ["statement_table:balance_unchecked"])
    with store.connect() as c:
        values = [json.loads(r["datapoints"]) for r in c.execute("SELECT datapoints FROM datapoints")]
    assert {reconcile.account_key(v["account_no"]) for v in values} == {reconcile.account_key(OWN)}
    card = next(t for v in values for t in v["transactions"] if t.get("original_currency"))
    assert (card["original_amount"], card["counterparty_name"]) == ("20", "EXAMPLE CLOUD INC")  # the store's money form


def test_the_service_surveys_a_folder(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from jav import api
    from tests.test_api import BASE, HUMAN

    folder = tmp_path / "erste"
    _export(folder, "20260630", JUNE, pdf=PDF_JUNE)
    client = TestClient(api.create_app(store_path=tmp_path / "w.sqlite"), base_url=BASE)
    with store.use_store(tmp_path / "w.sqlite"):
        r = client.post("/api/statement-tables/survey", headers=HUMAN, json={"path": str(folder)})
        assert r.status_code == 200, r.text
        assert [a["balance_checked"] for a in r.json()["accounts"]] == [True] and "EXAMPLE CLOUD" not in r.text
