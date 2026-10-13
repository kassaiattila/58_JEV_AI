"""153 (review F7): a day's bounds take each midnight's own offset, so a summer-time change day is 23 or 25 hours.

`activity.day_bounds` used today's offset for any day, so "My work today" for a day across a summer-time change was
shifted by an hour. Runs where the machine's time zone changes its offset in the year; skipped elsewhere.
"""

from datetime import date, datetime, timedelta

import pytest

from jav import activity


def _change_days(year: int) -> list[date]:
    days, d = [], date(year, 1, 1)
    while d.year == year:
        offset = datetime.combine(d, datetime.min.time()).astimezone().utcoffset()
        if datetime.combine(d + timedelta(days=1), datetime.min.time()).astimezone().utcoffset() != offset:
            days.append(d)
        d += timedelta(days=1)
    return days


def test_a_summer_time_change_day_is_not_24_hours():
    days = _change_days(2026)
    if not days:
        pytest.skip("the machine's time zone has no summer time")
    for d in days:
        lo, hi = activity.day_bounds(d.isoformat())
        hours = (datetime.fromisoformat(hi) - datetime.fromisoformat(lo)) / timedelta(hours=1)
        assert hours in (23, 25), (d, hours)
    lo, hi = activity.day_bounds("2026-06-15")
    assert (datetime.fromisoformat(hi) - datetime.fromisoformat(lo)) == timedelta(days=1)
