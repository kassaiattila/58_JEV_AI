"""Administration plane - offline: models.json feeds the config, call-site catalogue generation, the admin report
builds."""

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
    # 067 (066 Á45): every configured call site gets a page, the 8 hand-written ones among them
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
    assert "invoice: PASS" in rep and "doc_detect: PASS" in rep and "email_intent: PASS" in rep  # the invoice graph is type-independent (type packs)
    assert "native: PASS" in rep


def test_preflight_contract_gate_includes_native_and_rejects_its_drift(monkeypatch):
    import copy

    from jav import flow_native, preflight

    summary = preflight.flow_lint_summary()
    assert {name for name, _passed, _failures in summary} == {
        "invoice", "doc_detect", "email_intent", "document_learning", "email_learning", "native", "statement_table"}
    assert all(passed for _name, passed, _failures in summary)
    changed = copy.deepcopy(flow_native.CONTRACT)
    changed["steps"] = [step for step in changed["steps"] if step[0] != "publish_native"]
    monkeypatch.setattr(flow_native, "CONTRACT", changed)
    summary = preflight.flow_lint_summary()
    native = next(row for row in summary if row[0] == "native")
    assert not native[1] and native[2] > 0
    assert all(passed for name, passed, _failures in summary if name != "native")


def test_write_state_is_generated_snapshot(tmp_path):
    """docs/STATE.md: generated header + the full admin report; the handoff references it."""
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
    """070: the handoff is an internal working document; a fresh clone does not have it, which is a notice, not an
    error."""
    from jav import preflight

    monkeypatch.setattr(preflight, "HANDOFFS", tmp_path / "nincs")
    ok, msg = preflight.handoff_status()
    assert ok and "nincs helyi átadó" in msg


def test_preflight_names_the_failed_tests(monkeypatch, tmp_path):
    """086: an intermittent failure could not be identified from the summary line alone."""
    from types import SimpleNamespace

    from jav import preflight

    monkeypatch.setattr(preflight, "PREFLIGHT_RUNS", tmp_path / "preflight")  # 092: the raw output is kept there

    out = ("....F.\n=========================== short test summary info ===========================\n"
           "FAILED tests/test_a.py::test_x - AssertionError: boom\nERROR tests/test_b.py::test_y\n"
           "1 failed, 5 passed, 1 error in 3.10s\n")
    monkeypatch.setattr(preflight.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=out, stderr="", returncode=1))
    ok, summary = preflight.run_pytest()
    assert not ok
    assert summary.startswith("1 failed, 5 passed, 1 error in 3.10s; FAILED tests/test_a.py::test_x, ERROR tests/test_b.py::test_y; log: ")
