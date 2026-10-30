"""261 (plan B, B2; the owner's decisions of 2026-10-29): a process's settings say the value a new case uses and where
it comes from - the process's own value, else the installation's default, else the released file's - the same value
a case's start keeps (`process_settings.effective_rules`). F07 (the review of 2026-10-29): the settings page showed the
file's value while an installation default was in use. Real rule files, an empty store; nothing runs and no AI is asked.
"""

from __future__ import annotations

import pytest

from jav.app import process_packs, process_settings, registrations, rule_defaults
from jav.core import cfg, store

registrations.load_all()

PACK, FILE, KEY = "it_quote", "quotes", "draft.max_lines"
RULE = f"{FILE}.{KEY}"


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "settings.sqlite"):
        rule_defaults.use()
        rule_defaults._forget()
        try:
            yield tmp_path
        finally:
            cfg.use_defaults(None)
            rule_defaults._forget()


def _shown() -> dict:
    return next(r for r in process_settings.view(PACK)["rules"] if r["key"] == RULE)


def _used() -> int:
    return process_settings.effective_rules(process_packs.load(PACK))[0].get(FILE, {}).get(KEY)


def test_the_settings_say_the_value_a_new_case_uses_and_where_it_comes_from(db) -> None:
    released = _shown()["file_value"]
    assert (_shown()["value"], _shown()["origin"]) == (released, "file")
    rule_defaults.propose(FILE, KEY, 320, "anna")
    rule_defaults.activate(FILE, KEY, 1, "anna")
    shown = _shown()
    assert (shown["value"], shown["origin"], shown["installation_value"]) == (320, "installation", 320) == (_used(), "installation", 320)
    process_settings.propose(PACK, RULE, 350, "anna", kind=process_settings.RULE)
    process_settings.activate(PACK, RULE, 1, "anna", kind=process_settings.RULE)
    assert (_shown()["value"], _shown()["origin"]) == (350, "process") and _used() == 350
    process_settings.retire(PACK, RULE, "anna", kind=process_settings.RULE)
    assert (_shown()["value"], _shown()["origin"]) == (320, "installation") and _used() == 320
    process_settings.propose(PACK, RULE, 360, "anna", kind=process_settings.RULE)  # a draft changes nothing yet
    shown = _shown()
    assert (shown["value"], shown["origin"]) == (320, "installation") and _used() == 320
    assert [v["value"] for v in shown["versions"] if v["state"] == "draft"] == [360]
