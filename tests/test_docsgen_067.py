"""066 Á45: a generált hívásihely-dokumentáció a 24 beállított hívási helyből csak a 8 kézzel leírtat mutatta, és az
állapot-pillanatkép az üres etalonfájlt „0/0 = 0.0%”-ként írta ki (mintha minden eset rossz lenne)."""

from __future__ import annotations

import pytest

from jav import admin, cfg, docsgen

ALL = [n.split(":", 1)[1] for n in cfg.all_names() if n.startswith("callsite:")]


def test_every_configured_callsite_is_documented():
    assert sorted(docsgen.all_callsites()) == sorted(ALL)
    assert set(docsgen.CALLSITES) <= set(ALL)


@pytest.mark.parametrize("name", ALL)
def test_each_page_shows_the_hash_the_code_writes(name):
    shown = docsgen.code_hashes(name)
    assert shown, name
    page = docsgen.callsite_md(name)
    for h in shown.values():
        assert f"`{h}`" in page


def test_empty_golden_result_reads_as_no_cases():
    assert admin.score_text(0, 0) == "nincs eset"
    assert admin.score_text(3, 4) == "3/4 = 75.0%"
