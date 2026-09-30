"""Adminisztrációs sík - offline: models.json a config-ban, callsite-katalógus generálás, admin-riport összeáll."""

from jav import cfg, config, docsgen


def test_models_config_drives_config_module():
    m = cfg.load("models")
    assert config.JEV_MODEL == m["jev"]["model"] and config.OPENAI_MODEL == m["openai"]["model"]
    assert config.JEV_USD_PER_MTOK == m["jev"]["usd_per_mtok_input"] and config.JEV_CACHE_VERSION == m["jev"]["cache_version"]
    assert config.OPENAI_USD_PER_MTOK[config.OPENAI_MODEL] == tuple(m["openai"]["usd_per_mtok"][config.OPENAI_MODEL])
    assert config.OPENAI_SETTINGS["temperature"] == 0.0 and config.TRACKER_PROJECTS["email_intent"] == "jav_email_intent"
    assert "models" in cfg.all_names()


def test_callsite_docs_generate(tmp_path):
    paths = docsgen.write_callsite_docs(tmp_path)
    names = {p.name for p in paths}
    # 067 (066 Á45): minden beállított hívási hely kap oldalt, a 8 kézzel leírt is köztük van
    assert names == {f"{n}.md" for n in docsgen.all_callsites()} | {"README.md"}
    assert {"detect.md", "email_intent.md", "select.md", "verify.md", "select_foreign.md", "verify_foreign.md", "select_utility.md", "verify_utility.md"} <= names
    md = (tmp_path / "email_intent.md").read_text(encoding="utf-8")
    assert "`intent` | choice" in md and "regiszter `configs/intents.json`" in md and "config_hash" in md
    sel = (tmp_path / "select.md").read_text(encoding="utf-8")
    assert "`supplier_tax_id` (parties)" in sel and "`currency` (money)" in sel
    ver = (tmp_path / "verify.md").read_text(encoding="utf-8")
    assert "`off_target` (mezőnként)" in ver and "`parties_swapped` (dokumentum)" in ver
    index = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "[`detect`](detect.md)" in index


def test_admin_report_sections():
    from jav.admin import admin_report

    rep = admin_report()
    for head in ("## Konfigok", "## Modellek", "## Burr-kontraktok", "## Adattár", "## Utolsó golden", "## Nyitott review-sor"):
        assert head in rep, head
    assert "invoice: PASS" in rep and "doc_detect: PASS" in rep and "email_intent: PASS" in rep  # a számla-gráf típus-független (típus-csomagok)


def test_write_state_is_generated_snapshot(tmp_path):
    """docs/STATE.md: generált fejléc + a teljes admin-riport; a handoff ezt hivatkozza."""
    from jav.admin import write_state

    out = write_state(tmp_path / "docs" / "STATE.md")
    text = out.read_text(encoding="utf-8")
    assert text.startswith("<!-- GENERÁLT: python -m jav.cli admin --write")
    assert "## Konfigok" in text and "## Nyitott review-sor" in text


def test_preflight_handoff_status_reads_latest(tmp_path, monkeypatch):
    from jav import preflight

    handoffs = tmp_path / "docs" / "handoffs"
    handoffs.mkdir(parents=True)
    for name in ("068-2026-09-29-handoff.md", "069-2026-09-29-handoff.md", "TEMPLATE.md"):
        (handoffs / name).write_text("x", encoding="utf-8")
    monkeypatch.setattr(preflight, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(preflight, "HANDOFFS", handoffs)
    handoff, num = preflight.latest_handoff()
    assert handoff is not None and handoff.name == "069-2026-09-29-handoff.md" and num == 69
    ok, msg = preflight.handoff_status()
    assert ok and "070" in msg


def test_preflight_without_local_handoffs_is_not_a_failure(tmp_path, monkeypatch):
    """070: az átadó belső munkaanyag; friss klónban nincs meg, ez jelzés, nem hiba."""
    from jav import preflight

    monkeypatch.setattr(preflight, "HANDOFFS", tmp_path / "nincs")
    ok, msg = preflight.handoff_status()
    assert ok and "nincs helyi átadó" in msg
