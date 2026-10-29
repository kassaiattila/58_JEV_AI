"""231 (stage U, U4a; the owner's decisions of 2026-10-29): the installation's defaults over the rule files.

A person saves the installation's own value of a key a process may set as a draft; made active by the process values'
rule, it lies over the file for the work outside a case (once a long-running process names the defaults to the config
reader), while a case's context and the files-alone context read on without it. A case keeps the defaults active at
its start among its own values, under the process's own value of the same key; setting the default aside brings the
file's value back for the cases that start after. A key no process may set, or a value out of its bounds, is refused.
Real rule files, an empty store; nothing runs and no AI is asked.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jav.app import capabilities, process_packs, process_settings, registrations, rule_defaults
from jav.core import cfg, store
from jav.service.api import create_app

registrations.load_all()

FILE, KEY = "quotes", "draft.max_lines"


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "defaults.sqlite"):
        rule_defaults.use()
        rule_defaults._forget()
        try:
            yield tmp_path
        finally:
            cfg.use_defaults(None)
            rule_defaults._forget()


def _lines() -> int:
    return cfg.load(FILE)["draft"]["max_lines"]


def test_an_active_default_lies_over_the_file_outside_a_case(db) -> None:
    file_value = _lines()
    rule_defaults.propose(FILE, KEY, 40, "anna", note="shorter quotes")
    assert _lines() == file_value  # a draft changes nothing
    rule_defaults.activate(FILE, KEY, 1, "anna")
    assert _lines() == 40
    with cfg.overlay(None):  # the files alone
        assert _lines() == file_value
    with cfg.overlay(cfg.Overlay({"policy": {}})):  # a case's context: its values only (it kept none of these)
        assert _lines() == file_value
    assert cfg.current_overlay().refs[FILE][KEY] == {"setting": f"default:{FILE}.{KEY}", "version": 1}
    with capabilities.case_rules("wp-000000000000"):  # a package that is no case reads the defaults
        assert _lines() == 40
    rule_defaults.retire(FILE, KEY, "anna")
    assert _lines() == file_value


def test_a_case_keeps_the_defaults_of_its_start_under_the_process_s_own_value(db) -> None:
    pack = process_packs.load("it_quote")
    rule_defaults.propose(FILE, KEY, 40, "anna")
    rule_defaults.activate(FILE, KEY, 1, "anna")
    values, refs = process_settings.effective_rules(pack)
    assert values[FILE][KEY] == 40 and refs[FILE][KEY]["setting"] == f"default:{FILE}.{KEY}"
    process_settings.propose("it_quote", f"{FILE}.{KEY}", 25, "anna", kind=process_settings.RULE)
    process_settings.activate("it_quote", f"{FILE}.{KEY}", 1, "anna", kind=process_settings.RULE)
    values, refs = process_settings.effective_rules(pack)
    assert values[FILE][KEY] == 25 and refs[FILE][KEY]["setting"] != f"default:{FILE}.{KEY}"  # the process's own wins
    kept = capabilities.case_overlay({capabilities.RULES: values, capabilities.RULE_REFS: refs})
    rule_defaults.retire(FILE, KEY, "anna")
    with cfg.overlay(kept):
        assert _lines() == 25  # the case reads what it kept


def test_a_key_no_process_may_set_or_a_value_out_of_bounds_is_refused(db) -> None:
    with pytest.raises(rule_defaults.DefaultError, match="no default"):
        rule_defaults.propose("recipes", "max_item_usd_by_kind.document", 5, "anna")
    with pytest.raises(rule_defaults.DefaultError, match="between"):
        rule_defaults.propose(FILE, KEY, 0, "anna")


def test_the_process_values_rule_says_who_makes_a_default_active(db, monkeypatch) -> None:
    rule_defaults.propose(FILE, KEY, 40, "anna")
    monkeypatch.setattr(process_settings, "policy", lambda: {"activation": process_settings.SECOND_PERSON, "owners": []})
    with pytest.raises(process_settings.SettingRefused):
        rule_defaults.activate(FILE, KEY, 1, "anna")
    view = rule_defaults.activate(FILE, KEY, 1, "bela")
    entry = next(k for k in view["keys"] if k["id"] == f"{FILE}.{KEY}")
    assert (entry["value"], entry["active"], entry["versions"][0]["activated_by"]) == (40, 1, "bela")


def test_the_service_names_the_active_defaults(db) -> None:
    rule_defaults.propose(FILE, KEY, 40, "anna")
    rule_defaults.activate(FILE, KEY, 1, "anna")
    with TestClient(create_app(store_path=store.current_path()), base_url="http://127.0.0.1:8930") as c:
        assert c.get("/api/health").json()["own_defaults"] == [f"{FILE}.{KEY}"]
