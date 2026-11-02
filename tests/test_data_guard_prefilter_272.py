r"""272 (K4, the rest of TOOL-07): the data guard's pre-filter finds every line the line-by-line scan would report.

265 (TOOL-07) made the tracked tree's scan look first for the lines that could hold a finding, searching each file's
whole text, and claimed no pattern crosses a line break. The key-variable pattern does (`\s*` around `=`), and a
search that does not overlap could let a match starting on one line swallow the start of a key on the next one, which
the line-by-line scan reports: that line was never scanned. Now the whole-text search finds a pattern at every
position (overlapping), so it is a superset of the line-by-line scan; the card number's cheaper pattern uses the
card numbers' own separators. Invented text; nothing is committed.
"""

from __future__ import annotations

import random

from jav.core import card_numbers
from jav.devtools import data_guard as dg

GUARD = dg.Guard(dg.load_config(), env_secrets={}, env_sources=())
FAKE = "abcdefghijklmnopqrstuvwx"  # an invented, key-shaped value


def _reported(text: str) -> set[int]:
    return {n for n, line in enumerate(text.splitlines(), start=1) if GUARD.scan_line("x.py", n, line)}


def test_a_key_after_a_line_ending_in_its_variable_is_scanned() -> None:
    text = f"OPENAI_API_KEY=\nTYPESAFE_API_KEY={FAKE}\nplain\n"
    assert _reported(text) == {2}
    assert 2 in GUARD.lines_to_scan(text)


def test_the_pre_filter_is_a_superset_of_the_line_scan() -> None:
    rng = random.Random(272)
    parts = ["OPENAI_API_KEY=", "TYPESAFE_API_KEY=", "AZURE_DI_KEY: '", FAKE, "4111 1111 1111 1111", "1234-5678",
             "name@invented.example", "plain words", "=", " ", "\t", "12345678-2-41", "'"]
    for _ in range(300):
        text = "".join(rng.choice(parts) + rng.choice(["", "\n", " "]) for _ in range(rng.randint(1, 12)))
        assert _reported(text) <= set(GUARD.lines_to_scan(text)), repr(text)


def test_the_card_number_s_wider_pattern_uses_its_separators() -> None:
    for sep in card_numbers.SEPARATORS:
        assert dg._WIDER["card_number"].search(f"1234{sep}5678")
