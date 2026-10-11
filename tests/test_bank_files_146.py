"""146 (backlog D-bank-files; the owner's request of 2026-10-11): which bank files the system processes, as data.

The owner asked for a transparent, recorded description of exactly which bank files the system can process today, in
the user guide and in the interface, generated from the configuration so that it cannot go stale. The catalogue
(`configs/bank_files.json`, `jav/bank_files.py`) names each kind of file's reader; these tests keep it honest:

- every reader profile and every bank statement type pack has exactly one entry, and every entry's reader exists;
- a code profile's listed statement and line facts are exactly what the reader gives on synthetic files (the readers'
  own tests' files, enriched with a row of every kind the profile reads);
- an AI type's facts and checks come from its type pack, and what it does not read is the rest of a statement line;
- `docs/BANK_FILES.md` is the generated text, and the service serves the catalogue with the field labels.

Synthetic data only: the readers' test files (made-up accounts and partners, the public test card number).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jav import bank_files as bf, cfg, statement_table as st, typepack
from tests import test_statement_camt_141 as camt
from tests import test_statement_cib_141 as cib
from tests import test_statement_erste_137 as erste
from tests import test_statement_fields_144 as f144
from tests import test_statement_table_136 as table


@pytest.fixture(autouse=True)
def pdf_text(monkeypatch):
    """The PDF's text layer: the synthetic 'PDF' files hold their lines as plain text."""
    monkeypatch.setattr(st, "_pdf_lines", lambda path: Path(path).read_text(encoding="utf-8").splitlines())


def _entries() -> dict[str, dict]:
    return {e["id"]: e for e in bf.catalogue()["files"]}


def _by_profile() -> dict[str, dict]:
    return {e["reader"]["profile"]: e for e in bf.catalogue()["files"] if "profile" in e["reader"]}


# --- every reader is described once ------------------------------------------------------------------------------------


def test_every_reader_profile_and_bank_statement_type_pack_has_one_entry():
    assert bf.problems() == []
    readers = [tuple(e["reader"].items())[0] for e in bf.catalogue()["files"]]
    assert len(readers) == len(set(readers))
    profiles = {p["name"] for p in cfg.load("statement_tables")["profiles"]}
    assert {name for kind, name in readers if kind == "profile"} == profiles
    ai = {k for k in typepack.keys() if typepack.get(k).parent == "bank_statement" and {"S", "G"} & set(typepack.get(k).arms)}
    assert ai == {"statement_cib", "statement_erste"}
    assert {name for kind, name in readers if kind == "type"} == ai


def test_a_reader_without_an_entry_is_still_listed_and_named(monkeypatch):
    conf = cfg.load("bank_files")
    conf = {**conf, "files": [e for e in conf["files"] if e["id"] not in ("revolut", "erste_pdf_ai")]}
    monkeypatch.setattr(bf, "_config", lambda: conf)
    listed = {e["id"]: e for e in bf.catalogue()["files"]}
    assert not listed["revolut_consolidated_hu"]["described"] and listed["revolut_consolidated_hu"]["read_by"] == "code"
    assert listed["revolut_consolidated_hu"]["bank"] == "Revolut"
    assert not listed["statement_erste"]["described"] and listed["statement_erste"]["read_by"] == "ai"
    assert bf.problems() == ["profile revolut_consolidated_hu has no entry in configs/bank_files.json",
                             "type pack statement_erste has no entry in configs/bank_files.json"]


def test_an_entry_naming_an_unknown_reader_field_or_check_is_refused(monkeypatch):
    conf = cfg.load("bank_files")
    first = conf["files"][0]
    for bad, message in (({"reader": {"profile": "nobody_hu"}}, "no reader profile"),
                         ({"reader": {"type": "invoice_hu"}}, "no bank statement type pack"),
                         ({"reads": ["booking_date", "shoe_size"]}, "unknown field"),
                         ({"checks": ["vibes"]}, "unknown check")):
        broken = {**conf, "files": [{**first, **bad}, *conf["files"][1:]]}
        monkeypatch.setattr(bf, "_config", lambda broken=broken: broken)
        with pytest.raises(bf.BankFilesError, match=message):
            bf.catalogue()


# --- a code profile lists exactly what its reader gives ------------------------------------------------------------------


def _cib_card() -> list[str]:
    lines = [ln.replace("KÁRTYASZÁM: 0000 XXXX XXXX 0000", f"KÁRTYASZÁM: {f144.CARD}")
             .replace("0000 0000 0000 0000 00000000 000000", f"{f144.CARD} 20260114 093000") for ln in cib.CARD]
    at = lines.index("2026.01.05.   2026.01.05.   JÓVÁÍRÁS   120.000,00") + 1
    lines[at:at] = ["Közlemény: Card repayment January"]
    return lines


def _erste_pdf() -> list[str]:
    pdf = list(erste.PDF_JUNE)
    at = pdf.index("Kártyaszám - Tr.időpont   999999xxxxxx9999 - 2026.05.31") + 1
    pdf[at:at] = ["Terminál - eng.kód Trtip   T0001 - 123456 - vásár."]
    return pdf


def _camt_with_references() -> bytes:
    refs = ("<TxDtls><Refs><TxId>A1BC000000000000001</TxId><EndToEndId>E2E-77</EndToEndId></Refs>"
            "<RltdDts><AccptncDtTm>2026-06-04T10:15:30</AccptncDtTm></RltdDts>")
    transfer = camt._entry("NKIP", "DBIT", "12000.00", "2026-06-04", "80709.00",
                           party=("Example Supplier Kft.", "HU00999988877777666655554444"), memo="INV-0001",
                           info="Jutalék összege: : 300 HUF + 450 HUF").replace("<TxDtls>", refs)
    return camt._camt([camt.ENTRIES[0], transfer, *camt.ENTRIES[2:]])


def _readings(tmp_path: Path) -> dict[str, list[st.Reading]]:
    (tmp_path / "camt").mkdir()
    (tmp_path / "camt" / "june.xml").write_bytes(_camt_with_references())
    (tmp_path / "revolut").mkdir()
    return {
        "cib_text_hu": [st.read(cib._pdf(tmp_path / "cib", "cib.pdf", cib._pdf_lines())),
                        st.read(cib._pdf(tmp_path / "cib144", "cib.pdf", cib._pdf_lines(lines=f144.CIB_LINES)))],
        "cib_card_text_hu": [st.read(cib._pdf(tmp_path / "card", "card.pdf", _cib_card()))],
        "erste_ledger_hu": [st.read(erste._export(tmp_path / "erste", "20260630", erste.JUNE, pdf=_erste_pdf()))],
        "camt053": [st.read(tmp_path / "camt" / "june.xml")],
        "revolut_consolidated_hu": [st.read(table._workbook(tmp_path / "revolut"))],
    }


def _given(readings: list[st.Reading]) -> tuple[set[str], set[str]]:
    """The statement facts and the line facts the readings hold a value for."""
    header, lines = set(), set()
    for reading in readings:
        for account in reading.accounts:
            s = account.statement
            header |= {f for f in bf.HEADER_FIELDS if s.get(f) not in (None, "")}
            for line in s["transactions"]:
                lines |= {f for f in bf.line_fields() if line.get(f) not in (None, "")}
    return header, lines


def test_each_code_profile_lists_exactly_the_facts_its_reader_gives(tmp_path):
    entries = _by_profile()
    readings = _readings(tmp_path)
    assert set(readings) == set(entries)
    for profile, rs in readings.items():
        assert {r.profile for r in rs} == {profile}
        header, lines = _given(rs)
        entry = entries[profile]
        assert set(entry["header"]) == header, profile
        assert set(entry["reads"]) == lines, profile
        assert entry["not_read"] == [f for f in bf.line_fields() if f not in lines], profile


def test_a_code_profiles_kind_and_file_types_come_from_its_configuration():
    e = _entries()
    assert (e["cib_account"]["suffixes"], e["cib_account"]["encodings"]) == ([".pdf", ".txt"], ["utf-8", "cp1250"])
    assert e["cib_card"]["kinds"] == ["credit_card"] and e["cib_account"]["kinds"] == ["bank_account"]
    assert e["erste_export"]["suffixes"] == [".xml", ".pdf"] and e["camt053"]["suffixes"] == [".xml"]
    assert e["revolut"]["suffixes"] == [".xlsx", ".csv"]
    version = cfg.version("statement_tables")
    assert all(x["version"] == f"statement_tables {version}" for x in e.values() if x["read_by"] == "code")


# --- an AI type's facts come from its type pack ----------------------------------------------------------------------------


def test_an_ai_type_reads_its_type_packs_fields_and_checks_by_its_validators():
    for entry in (e for e in bf.catalogue()["files"] if e["read_by"] == "ai"):
        pack = typepack.get(entry["reader"]["type"])
        assert entry["reads"] == [f for f in pack.list_fields["transactions"] if f not in bf.IMPLIED_FIELDS]
        assert entry["header"] == [f for f in bf.HEADER_FIELDS if f in pack.fields]
        assert entry["checks"] == ["running_balance", "closing_balance", "totals", "period_dates"]
        assert entry["kinds"] == ["bank_account", "credit_card"] and entry["suffixes"] == [".pdf"]
        assert {"card_number", "bank_reference", "original_amount"} <= set(entry["not_read"])
        assert entry["version"] == f"{pack.key} {pack.version}"


def test_the_line_facts_are_the_tabular_type_packs_without_the_implied_ones():
    fields = bf.line_fields()
    assert fields[:4] == ["booking_date", "value_date", "amount", "running_balance"]
    assert "direction" not in fields and "original_currency" not in fields and "fee" in fields


# --- the document and the service --------------------------------------------------------------------------------------------


def test_the_codebase_document_is_the_generated_text():
    assert bf.DOC.read_text(encoding="utf-8") == bf.markdown(), "run: python -m jav.cli docs"


def test_the_document_names_every_file_its_reader_and_what_no_reader_knows():
    text = bf.markdown()
    for e in bf.catalogue()["files"]:
        assert f"`{e['reader'].get('profile') or e['reader'].get('type')}`" in text
    assert "## Files no reader knows" in text and "OTP" in text
    assert "end-to-end id" in text and "account number" in text  # field names as words


def test_the_service_serves_the_catalogue_with_the_field_labels(tmp_path):
    from fastapi.testclient import TestClient

    from jav.api import create_app
    from tests.test_api import BASE

    client = TestClient(create_app(store_path=tmp_path / "s.sqlite"), base_url=BASE)
    r = client.get("/api/bank-files")
    assert r.status_code == 200
    body = r.json()
    labels = cfg.load("field_labels")
    assert body["labels"]["booking_date"] == labels["columns"]["booking_date"]
    assert body["labels"]["opening_balance"] == labels["fields"]["opening_balance"]
    assert set(body["labels"]) >= set(bf.line_fields()) | set(bf.HEADER_FIELDS)
    assert [e["id"] for e in body["files"]] == [e["id"] for e in bf.catalogue()["files"]]
    assert json.dumps(body).count("described") == len(body["files"])
