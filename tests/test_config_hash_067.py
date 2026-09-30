"""066 Á18: a futáshoz rögzített konfiguráció-azonosító (`config_hash`) minden olyan beállítást fedjen, amely az
eredményt befolyásolja, és a generált dokumentáció ugyanazt az azonosítót mutassa, amelyet a kód a hívásnaplóba ír.

A rések a 066-os jelentés szerint: a G-kar kivonatoló utasítás- és sémafájlja; az alap magyar számla típuscsomagja
a hívási helyek azonosítójából kimaradt; a részletes típus kérdésénél a csomagleírások; a feladatjavaslat utasítása; a
szabályfájl (policy) azonosítója egy mentett eredménynél sem tárolódott.
"""

from __future__ import annotations

import pytest

from jav import cfg, docsgen, email_tasks, policy, typepack
from jav.config import PROMPTS_DIR
from jav.jev_select import site_for as select_site
from jav.jev_verify import site_for as verify_site


def test_combine_is_order_sensitive_and_short():
    assert cfg.combine("a", "b") != cfg.combine("b", "a")
    assert len(cfg.combine("a")) == cfg.HASH_LEN


def test_pack_hash_covers_its_prompt_and_schema_files(monkeypatch):
    pack = typepack.get("invoice_hu")
    files = (pack.prompt_file, *pack.schema_files)
    assert pack.config_hash == cfg.combine(cfg.config_hash("type:invoice_hu"), *(cfg.file_digest(PROMPTS_DIR / f) for f in files))
    real = cfg.file_digest
    monkeypatch.setattr(cfg, "file_digest", lambda p: "más" if p.name == pack.prompt_file else real(p))
    typepack.get.cache_clear()
    try:
        assert typepack.get("invoice_hu").config_hash != pack.config_hash
    finally:
        monkeypatch.setattr(cfg, "file_digest", real)
        typepack.get.cache_clear()


@pytest.mark.parametrize("key", ["invoice_hu", "invoice_foreign", "viz_szamla"])
def test_select_and_verify_hashes_include_the_pack(key):
    pack = typepack.get(key)
    if pack.select_callsite:
        assert select_site(key).config_hash == cfg.combine(cfg.config_hash(f"callsite:{pack.select_callsite}"), pack.config_hash)
    names = verify_site(key).hash_names
    assert f"callsite:{pack.verify_callsite}" in names
    assert verify_site(key).config_hash == cfg.combine(cfg.config_hash(*names), pack.config_hash)


def test_detail_question_hash_covers_the_pack_descriptions():
    from jav import detect_detail

    assert detect_detail.config_hash() == cfg.combine(cfg.config_hash("callsite:detect_detail"), typepack.catalog_hash())
    assert typepack.catalog_hash() == cfg.combine(*(typepack.get(k).config_hash for k in sorted(typepack.keys())))


def test_email_task_hash_covers_its_prompt():
    assert email_tasks.CONFIG_HASH == cfg.combine(cfg.config_hash("email_tasks"),
                                                  cfg.file_digest(PROMPTS_DIR / email_tasks.PROMPT_FILE))


def test_saved_datapoints_record_the_policy_too():
    from jav import flow

    site = select_site("invoice_hu").config_hash
    assert flow.datapoint_config_hash(site) == cfg.combine(site, policy.CONFIG_HASH)


@pytest.mark.parametrize("name", sorted(docsgen.CALLSITES))
def test_generated_docs_show_the_hashes_the_code_writes(name):
    shown = docsgen.code_hashes(name)
    assert shown, name
    for label, h in shown.items():
        assert f"`{h}`" in docsgen.callsite_md(name), (name, label)
