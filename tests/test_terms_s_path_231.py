"""231 (stage F, F2c; the owner's decision of 2026-10-29): the terms and conditions' S path, described by data alone.

A non-invoice type gets an S path without code: its type pack names a select call site, the call site names the
candidate profile the S path reads with (`terms`, data in configs/candidate_profiles.json: the international profile
with a seller's labels, 'Cégnév:'), and the pack names the patterns of a field whose value is a whole printed line (its
title, `text_lines`). The G path is untouched: it stays the default, its evidence search reads with the pack's own
profile and without the whole lines, and its verify call site keeps its own glossary (its requests are pinned in
tests/test_request_keys_190.py). Invented text; no model call.
"""

from __future__ import annotations

import pytest

from jav.ai import typepack
from jav.ai.candidates import find_all, find_line_text
from jav.ai.jev_select import find_candidates, s_path_profile
from jav.ai.jev_verify import site_for as verify_site
from jav.core import cfg
from jav.documents.layout import CellLayout, LineLayout

KEY = "altalanos_szerzodesi_feltetelek"
TEXTS = ["Általános Szerződési Feltételek", "Cégnév: Minta Webáruház Korlátolt Felelősségű Társaság",
         "1. A jelen Általános Szerződési Feltételek a Minta Webáruház és a Vevő jogait és kötelezettségeit tartalmazzák.",
         "Hatályos: 2026. március 1-től"]
LINES = [LineLayout(no=i, page=1, text=t, cells=[CellLayout(text=t, x0=30, x1=500)]) for i, t in enumerate(TEXTS, 1)]


def test_the_pack_has_an_s_path_by_data_and_keeps_the_g_path_as_its_default():
    pack = typepack.get(KEY)
    assert pack.arms == ("S", "G") and pack.default_arm == "G"
    assert s_path_profile(pack) == "terms" and pack.candidate_profile == "intl"
    assert cfg.load(f"callsite:{pack.verify_callsite}")["own_glossary"] is True
    assert verify_site(KEY).glossary == cfg.load(f"callsite:{pack.verify_callsite}")["glossary"]


def test_the_title_is_a_whole_printed_line_and_a_sentence_mentioning_it_is_not():
    titles = [c.label for c in find_line_text(LINES, typepack.get(KEY).text_lines["document_title"])]
    assert titles == ["Általános Szerződési Feltételek"]


def test_the_s_path_reads_the_seller_after_its_label_and_the_g_path_reads_as_before():
    pack = typepack.get(KEY)
    s_path = find_candidates(LINES, pack)
    assert "Minta Webáruház Korlátolt Felelősségű Társaság" in {c.label for c in s_path["name"]}
    assert [c.label for c in s_path["text:document_title"]] == ["Általános Szerződési Feltételek"]
    g_path = find_all(LINES, pack.candidate_profile, text_labels=pack.text_labels)  # the evidence search's candidates
    assert "text:document_title" not in g_path
    assert "Minta Webáruház Korlátolt Felelősségű Társaság" not in {c.label for c in g_path["name"]}


def test_whole_lines_only_for_a_text_field(monkeypatch):
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: {**real(name), "text_lines": {"effective_date": ["hatályos"]}}
                        if name == f"type:{KEY}" else real(name))
    typepack.get.cache_clear()
    try:
        with pytest.raises(ValueError, match="only a `text` field"):
            typepack.get(KEY)
    finally:
        typepack.get.cache_clear()
