"""200 (Q-belepo-idopont-jev): a text field whose meaning asks for a normalised date and time (the ticket's event time,
"written as YYYY-MM-DDTHH:MM") is evidenced by the line that prints the same date and the same time in any form.

Every ticket's correct event time ("2026-01-22T21:00", printed "2026.01.22 21:00") got a "not printed" to-do: the
code's source check looked for the value letter for letter, as for any text. Dates are matched in code before any
question (CLAUDE.md §4); a text value in the ISO date-time form now goes through the shared date reader, and its time
must stand on the same line. Synthetic lines only."""

from jav.jev_verify import find_evidence
from jav.models import LineLayout


def _lines(texts):
    return [LineLayout(no=i + 1, page=1, text=t) for i, t in enumerate(texts)]


TICKET = ["Belépőjegy", "Ferencváros - Újpest", "Időpont: 2026.01.22 21:00", "Kapu: B Szektor: B2 Sor: 4 Szék: 17"]


def test_a_normalised_date_and_time_is_found_in_its_printed_form():
    assert find_evidence("event_datetime", "2026-01-22T21:00", _lines(TICKET), kind="text") == ["L03: Időpont: 2026.01.22 21:00"]
    assert find_evidence("event_datetime", "2026-01-22 21:00", _lines(TICKET), kind="text")


def test_other_printed_forms_of_the_date_and_time():
    for line in ("2026. január 22. 21:00", "22.01.2026 21.00", "Kezdés: 2026-01-22, 21:00 óra"):
        assert find_evidence("event_datetime", "2026-01-22T21:00", _lines([line]), kind="text"), line


def test_the_same_date_at_another_time_is_not_evidence():
    assert find_evidence("event_datetime", "2026-01-22T20:00", _lines(TICKET), kind="text") == []
    assert find_evidence("event_datetime", "2026-01-23T21:00", _lines(TICKET), kind="text") == []


def test_the_time_must_stand_on_the_dates_line():
    lines = _lines(["Dátum: 2026.01.22", "Nyitás: 19:00, kezdés 21:00"])
    assert find_evidence("event_datetime", "2026-01-22T21:00", lines, kind="text") == []


def test_a_plain_text_value_is_still_matched_letter_for_letter():
    assert find_evidence("event_name", "Ferencváros - Újpest", _lines(TICKET), kind="text") == ["L02: Ferencváros - Újpest"]
    assert find_evidence("event_name", "Ferencváros - Debrecen", _lines(TICKET), kind="text") == []
