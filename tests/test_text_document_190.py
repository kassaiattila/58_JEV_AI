"""190 (plan 189 A2b): a document given as text, laid out like a PDF, and the extraction flow's text entry.

A pack that names `text` or `table` among its `inputs` reads an email's own text or a text or table file; the text is
laid out by the PDF reader's own line and cell builder, so the extraction sees it as it sees a PDF. Every existing pack
reads PDFs only, and its run enters at `load_pdf` as before. Synthetic texts and stand-in clients only; no paid call.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import Workbook
from typesafe_sdk import Noul

from jav.flows import flow
from jav.ai import extract_llm, typepack
from jav.documents import text_document
from jav.core import store
from jav.ai import jev as jev_mod
from jav.ai.models import JevCall
from tests.test_no_jev_085 import _FakeAgent

MINUTES = ("Jegyzokonyv\n\nKeszult a Minta Hockey Club kozgyulesen.\nDatum:   2026-03-04\tHelyszin:   Budapest\n"
           "Levezeto elnok:  Kiss Peter\n")
MINUTES_OUT = {"organization_name": "Minta Hockey Club", "document_kind": "jegyzokonyv", "meeting_type": "kozgyules",
               "meeting_date": "2026-03-04", "location": "Budapest", "chair_name": "Kiss Peter"}


@pytest.fixture()
def db(tmp_path: Path):
    with store.use_store(tmp_path / "t190.sqlite"):
        yield tmp_path


@pytest.fixture()
def text_pack(monkeypatch):
    """The meeting minutes' pack, as if it read text too (no existing pack does)."""
    pack = typepack.get("meeting_minutes").model_copy(update={"inputs": ("pdf", "text")})
    monkeypatch.setattr(flow, "get_pack", lambda key: pack if key == pack.key else typepack.get(key))
    return pack


class _Jev:
    def __init__(self) -> None:
        self.asked = 0

    def ask(self, request_id, state, questions, **_kw):
        self.asked += 1
        nouls = {q: SimpleNamespace(noul=0.05) for q, v in questions.items() if isinstance(v, Noul)}
        return SimpleNamespace(response=SimpleNamespace(nouls=nouls, model="jev-test"),
                               call=JevCall(request_id=request_id, n_questions=len(questions), state_chars=0))


# --- the layout -----------------------------------------------------------------------------------------------------


def test_three_spaces_or_a_tab_split_cells_and_fewer_do_not():
    doc = text_document.layout_text("Datum:   2026-03-04\tHelyszin: Budapest\nKiss  Peter elnok\n\n\nVege")
    assert [ln.text for ln in doc.layout] == ["Datum:   2026-03-04   Helyszin: Budapest", "Kiss Peter elnok", "Vege"]
    assert [[c.text for c in ln.cells] for ln in doc.layout] == [["Datum:", "2026-03-04", "Helyszin: Budapest"],
                                                                  ["Kiss Peter elnok"], ["Vege"]]
    assert [ln.no for ln in doc.layout] == [1, 2, 3] and {ln.page for ln in doc.layout} == {1}
    assert doc.text_source == "text" and doc.page_count == 1 and doc.text == "\n".join(doc.lines)


def test_the_cells_keep_their_columns_like_a_pdf_line():
    doc = text_document.layout_text("Szallito:      Vevo:\nMinta Kft.     Proba Bt.")
    first, second = doc.layout
    assert [c.text for c in second.cells] == ["Minta Kft.", "Proba Bt."]
    assert first.cells[1].x0 == second.cells[1].x0  # the second column starts at the same place on both lines


def test_an_empty_text_has_no_text_source():
    doc = text_document.layout_text(" \n\t\n")
    assert doc.layout == [] and doc.text == "" and doc.text_source is None


def test_a_given_text_is_identified_by_its_digest():
    assert text_document.text_digest("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_input_kinds_by_suffix():
    assert [text_document.input_kind(n) for n in ("a.pdf", "a.PDF", "a.txt", "a.xlsx", "a.csv", "a.docx")] == [
        "pdf", "pdf", "text", "table", "table", "pdf"]


# --- table and text files -------------------------------------------------------------------------------------------


def test_a_workbook_row_becomes_one_line_its_cells_three_spaces_apart(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.title = "Igenyek"
    sheet.append(["Megnevezes", "Mennyiseg", "Egyseg"])
    sheet.append(["Uzleti laptop", 12, "db"])
    sheet.append([None, None, None])
    sheet.append(["Telepites", 1.5, "ora"])
    book.save(tmp_path / "lista.xlsx")
    text = text_document.read_file(tmp_path / "lista.xlsx")
    assert text.split("\n") == ["Megnevezes   Mennyiseg   Egyseg", "Uzleti laptop   12   db", "Telepites   1.5   ora"]
    assert [c.text for c in text_document.layout_text(text).layout[1].cells] == ["Uzleti laptop", "12", "db"]


def test_a_workbook_of_two_sheets_names_each_sheet(tmp_path):
    book = Workbook()
    book.active.title = "Hardver"
    book.active.append(["Monitor", 2])
    book.create_sheet("Szolgaltatas").append(["Telepites", 1])
    book.save(tmp_path / "ket_lap.xlsx")
    assert text_document.read_file(tmp_path / "ket_lap.xlsx").split("\n") == [
        "Hardver", "Monitor   2", "Szolgaltatas", "Telepites   1"]


def test_a_csv_and_a_text_file(tmp_path):
    (tmp_path / "a.csv").write_text("Tetel,Darab\nEger,5\n", encoding="utf-8")
    (tmp_path / "a.txt").write_bytes("﻿Kedves Csapat,\n5 db monitor".encode())
    assert text_document.read_file(tmp_path / "a.csv").split("\n") == ["Tetel   Darab", "Eger   5"]
    assert text_document.read_file(tmp_path / "a.txt") == "Kedves Csapat,\n5 db monitor"


def test_a_pdf_is_not_a_text_file(tmp_path):
    with pytest.raises(text_document.TextDocumentError):
        text_document.read_file(tmp_path / "a.pdf")


# --- the type pack's switch -----------------------------------------------------------------------------------------


def test_every_pack_before_the_quote_request_reads_pdf_only():
    keys = [k for k in typepack.keys() if k != "quote_request"]  # 190 (A2e): the first pack that reads text
    assert {k: typepack.get(k).inputs for k in keys} == dict.fromkeys(keys, ("pdf",))


def test_an_unknown_input_kind_is_refused(monkeypatch):
    from jav.core import cfg

    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: {**real(name), "inputs": ["pdf", "fax"]} if name == "type:meghivo" else real(name))
    typepack.get.cache_clear()
    try:
        with pytest.raises(ValueError, match="inputs"):
            typepack.get("meghivo")
    finally:
        typepack.get.cache_clear()


def test_a_pack_that_reads_pdf_only_refuses_a_text():
    with pytest.raises(ValueError, match="does not read text input"):
        flow.build_app("message.json", "c", "G", tracker=False, doc_type="meeting_minutes", source_text=MINUTES)
    with pytest.raises(ValueError, match="does not read table input"):
        flow.build_app("lista.xlsx", "c", "G", tracker=False, doc_type="invoice_hu")


# --- the extraction flow from a text --------------------------------------------------------------------------------


def _run(text: str, **kw):
    app = flow.build_app("inbox/box/m1/message.json", "c190", "G", tracker=False, doc_type="meeting_minutes",
                         source_text=text, **kw)
    action, _, state = app.run(halt_after=flow.TERMINALS)
    return action.name, state.data


def test_a_text_runs_the_g_path_from_load_text(db, text_pack, monkeypatch):
    jev = _Jev()
    monkeypatch.setattr(jev_mod, "get_adapter", lambda: jev)
    prompts: list[str] = []

    class Agent(_FakeAgent):
        def run_sync(self, prompt, **kw):
            prompts.append(prompt)
            return super().run_sync(prompt, **kw)

    with extract_llm.use_agent_factory(lambda pack: Agent(pack, MINUTES_OUT)):
        terminal, state = _run(MINUTES)
    assert terminal in ("done", "needs_review") and jev.asked == 1
    assert state.doc_id == text_document.text_digest(MINUTES) and state.text_source == "text"
    assert state.text.split("\n")[2] == "Datum:   2026-03-04   Helyszin:   Budapest"
    assert prompts == [extract_llm.USER_PREFIX + state.text]
    assert state.record.extra["organization_name"] == "Minta Hockey Club"
    assert "meeting_date" not in state.verdicts.unsupported  # printed on the text's own lines
    assert state.source_layer_id is None
    with store.connect() as c:
        doc = c.execute("SELECT has_text, page_count FROM documents WHERE doc_id=?", (state.doc_id,)).fetchone()
    assert tuple(doc) == (1, 1)


def test_an_empty_text_is_a_to_do_without_any_call(db, text_pack, monkeypatch):
    monkeypatch.setattr(jev_mod, "get_adapter", lambda: pytest.fail("JEV was asked about an empty text"))
    with extract_llm.use_agent_factory(lambda pack: pytest.fail("GPT was asked about an empty text")):
        terminal, state = _run("\n \n")
    assert terminal == "needs_review" and state.review_reasons[0] == "text:empty" and state.record is None
