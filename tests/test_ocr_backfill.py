"""Backfilling word data in the old OCR cache (048): only when the lines are identical; the text must not change."""

import json

from jav import ocr
from jav.pdf import PdfText

WORDS = [[{"text": "Számla", "x0": 10.0, "x1": 50.0, "top": 10.0, "bottom": 20.0, "line_no": 0}]]


def _cached(lines: list[str]) -> dict:
    return {"path": "x.pdf", "page_count": 1, "engine": "native", "engine_version": "t", "config_hash": "h",
            "signals": {"mean_conf": 0.9, "low_conf_ratio": 0.0}, "layout": [{"text": t, "cells": []} for t in lines]}


def test_words_are_backfilled_only_when_the_lines_match(tmp_path, monkeypatch):
    fresh = PdfText(path="x.pdf", text="Számla", lines=["Számla"], words=WORDS, page_sizes=[(595.0, 842.0)])
    monkeypatch.setattr(ocr, "ocr_pdf", lambda *a, **k: fresh)
    f = tmp_path / "c.json"
    f.write_text(json.dumps(_cached(["Számla"])), encoding="utf-8")
    out = ocr._backfill_words(tmp_path / "x.pdf", _cached(["Számla"]), f, psm=None, eng="native")
    assert out["words"] == WORDS and out["page_sizes"] == [[595.0, 842.0]] and out["words_backfilled"]
    assert json.loads(f.read_text(encoding="utf-8"))["words"] == WORDS  # the cache file was extended too

    g = tmp_path / "d.json"
    g.write_text(json.dumps(_cached(["Szamla"])), encoding="utf-8")
    same = ocr._backfill_words(tmp_path / "x.pdf", _cached(["Szamla"]), g, psm=None, eng="native")
    assert "words" not in same and "words" not in json.loads(g.read_text(encoding="utf-8"))  # lines differ: no change


def test_escalated_text_without_words_gets_the_local_word_layer(monkeypatch):
    monkeypatch.delenv(ocr.ENGINE_ENV, raising=False)
    monkeypatch.setitem(ocr.ESCALATION, "enabled", True)
    monkeypatch.setitem(ocr.ESCALATION, "engine", "azure_di")

    def fake_ocr(path, page_count=None, use_cache=True, psm=None, engine_name=None):
        if engine_name == "azure_di":  # old Azure cache: text present, word data missing
            return PdfText(path=str(path), text="Számla", lines=["Számla"], text_source="ocr",
                           ocr={"engine": "azure_di", "mean_conf": 0.99, "low_conf_ratio": 0.0})
        return PdfText(path=str(path), text="Szamla", lines=["Szamla"], text_source="ocr", words=WORDS, page_sizes=[(595.0, 842.0)],
                       ocr={"engine": "native", "mean_conf": 0.8, "low_conf_ratio": 0.15})

    monkeypatch.setattr(ocr, "ocr_pdf", fake_ocr)
    pdf, escalated = ocr.ocr_with_escalation("gyenge.pdf")
    assert escalated and pdf.lines == ["Számla"]  # the text stays Azure's
    assert pdf.words == WORDS and pdf.page_sizes == [(595.0, 842.0)] and pdf.ocr["words_from"] == "native"
