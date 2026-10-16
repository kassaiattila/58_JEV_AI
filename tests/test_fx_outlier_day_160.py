"""160 (review M-9): a mistyped date (a 2004 issue date among 2026 invoices) no longer stops the exchange rate refresh.

The missing days were fetched in one span from the earliest to the latest; a single far-off date made it longer than
the allowed span, the fetch raised an uncaught error, and every package's reconciliation refresh failed with it. The
missing days are now fetched in spans no longer than the allowed one, each on its own. Stand-in transport, no request
leaves the machine."""

from __future__ import annotations

from datetime import date

from jav import fx
from tests.test_fx_130 import WEEK, Service, db  # noqa: F401 - the fixture is used by name


def test_a_far_off_day_is_fetched_on_its_own_and_the_others_still_get_their_rates(db):  # noqa: F811
    service = Service(WEEK)
    with fx.use_transport(service):
        result = fx.ensure([("USD", date(2026, 10, 1)), ("USD", date(2004, 3, 2))])
        rates = fx.table([("USD", date(2026, 10, 1))])
    assert result["status"] == "ok"
    assert sorted((c["start"][:4], c["end"][:4]) for c in service.calls) == [("2004", "2004"), ("2026", "2026")]
    assert rates["USD"]["2026-10-01"]["rate"] == "326.18"


def test_a_failed_span_is_reported_while_the_other_span_is_stored(db):  # noqa: F811
    class HalfDown(Service):
        def __call__(self, url, body, headers, timeout):
            if "<web:startDate>2004" in body.decode("utf-8"):
                self.calls.append({"start": "2004", "end": "2004"})
                raise OSError("down")
            return super().__call__(url, body, headers, timeout)

    service = HalfDown(WEEK)
    with fx.use_transport(service):
        result = fx.ensure([("USD", date(2026, 10, 1)), ("USD", date(2004, 3, 2))])
        rates = fx.table([("USD", date(2026, 10, 1))])
    assert result["status"] == "failed" and len(service.calls) == 2
    assert rates["USD"]["2026-10-01"]["rate"] == "326.18"
