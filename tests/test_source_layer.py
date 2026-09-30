"""Word layer and page image (045 K3b, B1): reading keeps the word boxes, the layer is normalised and content-addressed,
the run saves it, and the page image is made from the hash-protected source. Synthetic PDF, no calls."""

import json
from pathlib import Path

import pytest

from jav import source_layer, store
from jav.ocr import _to_pdftext
from jav.pdf import build_layout, read_pdf
from tests.pdfgen import INVOICE_LINES, write_text_pdf


@pytest.fixture()
def pdf(tmp_path: Path) -> Path:
    return write_text_pdf(tmp_path / "szamla.pdf", INVOICE_LINES)


def test_read_pdf_keeps_word_boxes_page_size_and_line_numbers(pdf):
    doc = read_pdf(pdf)
    assert doc.page_sizes == [(595.0, 842.0)]
    words = doc.words[0]
    assert all({"x0", "x1", "top", "bottom", "line_no"} <= set(w) for w in words)
    number = next(w for w in words if w["text"] == "MINTA-2026-001")
    assert "MINTA-2026-001" in doc.layout[number["line_no"] - 1].text


def test_layout_is_unchanged_by_word_annotation():
    """The JEV request is built from the lines: the 045 extension must not change them (cache, closed measurements)."""
    pages = [[{"text": "Brutto", "x0": 10, "x1": 40, "top": 100, "bottom": 110},
              {"text": "12 700", "x0": 200, "x1": 240, "top": 100.5, "bottom": 110}]]
    first = build_layout(json.loads(json.dumps(pages)))
    annotated = json.loads(json.dumps(pages))
    again = build_layout(annotated)
    assert [ln.model_dump() for ln in first] == [ln.model_dump() for ln in again]
    assert {w["line_no"] for w in annotated[0]} == {1}


def test_layer_is_normalized_ordered_and_content_addressed(pdf):
    doc = read_pdf(pdf)
    layer = source_layer.build("d" * 64, doc.words, doc.page_sizes, text_source="pdf", engine="pdfplumber")
    assert layer is not None and layer.pages[0].width_pt == 595.0
    assert all(0 <= w.x0 < w.x1 <= 1 and 0 <= w.y0 < w.y1 <= 1 for w in layer.words)
    assert [w.id for w in layer.words] == list(range(len(layer.words)))
    assert [w.line_no for w in layer.words] == sorted(w.line_no for w in layer.words)
    again = source_layer.build("d" * 64, read_pdf(pdf).words, doc.page_sizes, text_source="pdf", engine="pdfplumber")
    assert again.layer_id == layer.layer_id
    line = layer.words_on_line(2)
    assert [w.text for w in line] == ["Szamlaszam:", "MINTA-2026-001"]
    assert source_layer.build("d" * 64, [], [], text_source=None, engine=None) is None


def test_layer_save_and_load_roundtrip(pdf, tmp_path):
    with store.use_store(tmp_path / "w.sqlite"):
        layer_id = source_layer.save_from_pdftext("e" * 64, read_pdf(pdf))
        assert layer_id and source_layer.save_from_pdftext("e" * 64, read_pdf(pdf)) == layer_id  # idempotent
        back = source_layer.load(layer_id)
        assert back is not None and back.doc_id == "e" * 64 and len(back.words) > 20
        assert source_layer.load("nincs") is None


def test_old_ocr_cache_without_words_gives_no_layer(tmp_path):
    data = {"page_count": 1, "engine": "native", "engine_version": "5", "signals": {},
            "layout": [{"no": 1, "page": 1, "text": "SZAMLA MINTA", "cells": [{"text": "SZAMLA MINTA", "x0": 1, "x1": 2}]}]}
    old = _to_pdftext(tmp_path / "x.pdf", data, cached=True)
    assert old.words == [] and old.page_sizes == []
    assert source_layer.build("f" * 64, old.words, old.page_sizes, text_source="ocr", engine="native") is None
    new = _to_pdftext(tmp_path / "x.pdf", {**data, "words": [[{"text": "SZAMLA", "x0": 10, "x1": 50, "top": 5, "bottom": 15,
                                                                "line_no": 1}]], "page_sizes": [[100, 200]]}, cached=True)
    layer = source_layer.build("f" * 64, new.words, new.page_sizes, text_source="ocr", engine="native")
    assert layer is not None and layer.words[0].x0 == 0.1 and layer.words[0].y1 == 0.075


def test_worker_run_saves_the_layer(tmp_path):
    from jav import work
    from jav.adapters import jev as jev_mod
    from jav.runtime import worker
    from tests.test_runtime_worker import FakeClient

    folder = tmp_path / "be"
    folder.mkdir()
    write_text_pdf(folder / "a.pdf", INVOICE_LINES)
    adapter = jev_mod.JevAdapter(client=FakeClient(), cache_dir=tmp_path / "cache", model="jev-1.13.0")
    with store.use_store(tmp_path / "w.sqlite"), jev_mod.use_adapter(adapter):
        wp = work.create_from_folder(folder, name="x")
        work.assign_recipe(wp["id"], "invoice-extraction", params={"arm": "S"}, expected_revision=0, actor="t")
        r = work.readiness(wp["id"])
        work.start_run(wp["id"], mode="shadow", expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")
        worker.run_worker(once=True)
        with store.connect() as c:
            rows = c.execute("SELECT doc_id, text_source FROM source_layers").fetchall()
        assert [(r["doc_id"], r["text_source"]) for r in rows] == [(wp["items"][0]["item_id"], "pdf")]
