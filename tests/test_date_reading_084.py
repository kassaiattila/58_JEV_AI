"""084 date reading (the owner's report of 2026-10-01): one shared, flexible and safe date reader.

A hotel invoice printed its issue date as "Issued : 04-DEC-22 21:52". Neither the machine path nor a selection on the
page image could read it: the shared date reader knew only four-digit years and a few forms, and manual input took
only YYYY-MM-DD. Every path now reads dates through `jav/dates.py`:

- month names and abbreviations in Hungarian, English, German, French, Spanish and Italian, in any letter case, with
  or without accents, with ordinal endings;
- a two-digit year by a fixed rule; separators: dot, hyphen, slash, space; a time or a weekday next to the date does
  not disturb it;
- the order of day and month in an all-numeric date comes from the number above 12, then from the document's other
  dates; a slash date that neither decides is flagged, never guessed.

Synthetic text only, no model calls.
"""

from datetime import date

import pytest

from jav import dates

TODAY = date(2026, 10, 1)


def _read(raw, **kw):
    got = dates.read_date(raw, today=TODAY, **kw)
    return got.value, got.ambiguous


# --- the reader ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [
    "04-DEC-22",
    "Issued : 04-DEC-22 21:52",
    "04-Dec-2022",
    "4 December 2022",
    "4th December, 2022",
    "4th of December 2022",
    "December 4, 2022",
    "Dec. 4th, 2022",
    "DEC 04 2022",
    "Sun, 04 Dec 2022 21:52:00",
    "04DEC22",
    "2022-12-04",
    "2022-12-04T21:52:00",
    "2022.12.04.",
    "2022. 12. 04.",
    "2022/12/04",
    "2022. december 4.",
    "2022. dec. 4.",
    "2022 DECEMBER 04",
    "4. Dezember 2022",
    "4 décembre 2022",
    "4 decembre 2022",
    "4 de diciembre de 2022",
    "4 dicembre 2022",
    "04.12.2022",
    "04.12.22",
    "4-12-2022",
    "04-12-22",
])
def test_every_common_form_of_one_date(raw):
    assert _read(raw) == (date(2022, 12, 4), False)


@pytest.mark.parametrize("raw, expected", [
    ("2022. március 4.", date(2022, 3, 4)),
    ("2022. marcius 4.", date(2022, 3, 4)),
    ("2022. MÁRC. 4.", date(2022, 3, 4)),
    ("4. März 2022", date(2022, 3, 4)),
    ("4 Maerz 2022", date(2022, 3, 4)),
    ("4 févr. 2022", date(2022, 2, 4)),
    ("4 août 2022", date(2022, 8, 4)),
    ("4 Jänner 2022", date(2022, 1, 4)),
    ("4 mayo 2022", date(2022, 5, 4)),
    ("4 mai 2022", date(2022, 5, 4)),
    ("4 maggio 2022", date(2022, 5, 4)),
    ("2022. május 4.", date(2022, 5, 4)),
    ("4 sept. 2022", date(2022, 9, 4)),
    ("4 szept. 2022", date(2022, 9, 4)),
    ("4 ottobre 2022", date(2022, 10, 4)),
    ("Okt 4, 2022", date(2022, 10, 4)),
])
def test_month_names_in_six_languages(raw, expected):
    assert _read(raw) == (expected, False)


@pytest.mark.parametrize("raw, expected", [
    ("04-DEC-85", date(1985, 12, 4)),  # later than next year: the 20th century (a date of birth on an ID document)
    ("04-DEC-27", date(2027, 12, 4)),  # next year is still this century (a due date)
    ("04-DEC-28", date(1928, 12, 4)),
    ("01.01.00", date(2000, 1, 1)),
])
def test_a_two_digit_year_by_a_fixed_rule(raw, expected):
    assert _read(raw) == (expected, False)


@pytest.mark.parametrize("raw, expected", [
    ("25/12/2022", date(2022, 12, 25)),  # the day is above 12
    ("12/25/2022", date(2022, 12, 25)),  # the month comes first: the second number is above 12
    ("04/04/2022", date(2022, 4, 4)),  # both readings are the same day
    ("12-25-2022", date(2022, 12, 25)),
])
def test_a_number_above_12_decides_the_order(raw, expected):
    assert _read(raw) == (expected, False)


def test_a_slash_date_that_nothing_decides_is_flagged_never_silently_resolved():
    # the earlier international reading (month first) stays the value, but a person has to check it
    assert _read("04/12/2022") == (date(2022, 4, 12), True)
    assert _read("04/12/22") == (date(2022, 4, 12), True)


@pytest.mark.parametrize("order, expected", [("dmy", date(2022, 12, 4)), ("mdy", date(2022, 4, 12))])
def test_the_document_order_decides_a_slash_or_hyphen_date(order, expected):
    assert _read("04/12/2022", order=order) == (expected, False)
    assert _read("04-12-2022", order=order) == (expected, False)


def test_a_dot_date_is_always_day_first():
    # no country writes month.day.year; the document order does not turn it around
    assert _read("04.12.2022", order="mdy") == (date(2022, 12, 4), False)


@pytest.mark.parametrize("raw", [
    None, "", "abc", "2022", "12.04", "Dec 2022", "31.02.2022", "2022.13.01", "2022.02.30",
    "1.2.3.4", "10.10.10.10", "12.04.20225", "112.04.2022", "123.45", "28.000", "4 marketing 2022",
    "+36 30 123 4567", "06-30-123-4567", "13/13/2022", "1500.12.04", "Total 1500 Dec 4", "04.12.2122",
])
def test_no_date_is_read_out_of_other_text(raw):
    assert _read(raw) == (None, False)


def test_a_date_is_never_cut_out_of_a_longer_number():
    assert dates.find_dates_in("Ref 112.04.2022", today=TODAY) == []
    assert dates.find_dates_in("Ref 12.04.20225", today=TODAY) == []


def test_every_date_of_a_line_in_order():
    hits = dates.find_dates_in("Period: 01.11.2022 - 30.11.2022, due Dec 15, 2022", today=TODAY)
    assert [h.value for h in hits] == [date(2022, 11, 1), date(2022, 11, 30), date(2022, 12, 15)]
    assert [h.raw for h in hits] == ["01.11.2022", "30.11.2022", "Dec 15, 2022"]


def test_a_flagged_hit_also_carries_the_other_reading():
    hit = dates.find_dates_in("04/12/2022", today=TODAY)[0]
    assert (hit.value, hit.ambiguous, hit.alt) == (date(2022, 4, 12), True, date(2022, 12, 4))
    assert dates.find_dates_in("25/12/2022", today=TODAY)[0].alt is None


def test_ocr_tolerance_reads_a_comma_as_a_dot_in_a_year_first_date():
    assert dates.find_dates_in("2022,12,04", today=TODAY) == []
    assert dates.find_dates_in("2022,12,04", ocr=True, today=TODAY)[0].value == date(2022, 12, 4)


# --- the document's order -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("texts, expected", [
    (["Date: 25/12/2022", "Due: 04/01/2023"], "dmy"),
    (["Date: 12/25/2022", "Due: 01/04/2023"], "mdy"),
    (["Date: 25-12-2022"], "dmy"),
    (["Date: 04/01/2023"], None),  # nothing decides
    (["25/12/2022", "12/25/2022"], None),  # contradictory evidence
    (["25.12.2022"], None),  # a dot date is day first anyway and is no evidence for a slash date
    (["2022-12-25"], None),
])
def test_the_document_order_comes_from_its_unambiguous_dates(texts, expected):
    assert dates.document_date_order(texts) == expected


# --- manual input --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [
    "2022-12-04", "2022.12.04.", "2022. 12. 04.", "04-DEC-22", "4 December 2022", "04.12.2022", "04.12.22",
    " 2022.12.04 21:52 ", "2022. december 4.",
])
def test_manual_input_takes_every_unambiguous_form(raw):
    assert dates.read_date_input(raw, today=TODAY) == "2022-12-04"


def test_manual_input_refuses_an_ambiguous_slash_date_instead_of_guessing():
    with pytest.raises(dates.AmbiguousDate):
        dates.read_date_input("04/12/2022", today=TODAY)


@pytest.mark.parametrize("raw", ["abc", "2022.13.01", "2022-12-04 / 2022-12-05", "12.04", "2022-12-04 12345"])
def test_manual_input_refuses_text_that_is_not_one_date(raw):
    with pytest.raises(ValueError) as exc:
        dates.read_date_input(raw, today=TODAY)
    assert not isinstance(exc.value, dates.AmbiguousDate)
