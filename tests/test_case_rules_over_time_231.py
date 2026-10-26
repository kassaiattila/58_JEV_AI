"""231 (stage D, D-a; the reassessment after D0 of 2026-10-26, F04, P03, T05): a rule key added after a case started
keeps the value it came with, and a decision replays with the rules it was made with.

A case reads its rule files as it started; a key added to a file since (same main version) is taken from the file so
newer code reads what it expects. Until D-a it came from the file as it is now: a key added with 5 (R2) and changed to
9 later (R3) read 9 in an old case, and a decision made under R2 replayed with 9. Now a missing key takes the value of
the first version of the file that had it after the case started, and a decision records the rules it read (their
content stored by fingerprint), so its replay reads them again. A new key that changes the business meaning is a new
main version (`docs/guides/CONFIGS.md`). Invented quote requests; no paid call.
"""

from __future__ import annotations

from jav.app import capabilities
from jav.core import cfg, rulebook, store, trace
from jav.domains.quotes import quote_letter
from tests.test_case_keeps_versions_231 import _change, _minor, _start, configs  # noqa: F401 - the fixture
from tests.test_quote_path_231 import golden  # noqa: F401 - the fixture the configs fixture uses


def _process_start() -> None:
    """What a service or worker does at its start: its configs' snapshot stored (`jav.runtime.preload`)."""
    with store.connect() as c:
        store.begin_immediate(c)
        rulebook.store_in(c, rulebook.current())


def test_a_key_added_after_the_start_keeps_the_value_it_came_with(configs) -> None:  # noqa: F811
    (cases_, _seen), copy = configs
    r1 = cfg.version("quotes")
    old = _start(cases_[0])
    r2 = _minor(r1)
    _change(copy, r2, d0e_surcharge=5)  # R2: a new key, 5
    _process_start()
    with capabilities.case_rules(old):
        assert cfg.load("quotes")["draft"]["d0e_surcharge"] == 5
        facts = quote_letter.paragraph_facts("short")
        with store.connect() as c:
            row_id = trace.record_in(c, quote_letter.LETTER_CHECK, subject=("quote_letter", f"{old}:1"), inputs=facts,
                                     outcome=[], keys={"quotes.json": ["letter.max_chars"]}, case_id=old)
    _change(copy, _minor(r2), d0e_surcharge=9)  # R3: the same key, 9
    _process_start()
    with capabilities.case_rules(old):
        assert cfg.load("quotes")["draft"]["d0e_surcharge"] == 5  # not 9: the value it came with
        assert cfg.version("quotes") == r1
    newer = _start(cases_[0], "After R3")
    with capabilities.case_rules(newer):
        assert cfg.load("quotes")["draft"]["d0e_surcharge"] == 9
    recorded = next(r for r in trace.rows(case_id=old) if r["id"] == row_id)
    entry = next(e for e in recorded["rules"] if e["file"] == "quotes.json")
    assert entry.get("kept") and entry.get("effective_sha256")
    assert trace.recorded_overlay(recorded).base["quotes"].data["draft"]["d0e_surcharge"] == 5  # the replay reads R2's
    assert trace.replay(recorded) == []
