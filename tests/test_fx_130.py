"""130 (backlog F-reconciliation, K3): the MNB daily exchange rates, fetched once and kept in the store.

The owner's decisions (DECISIONS 128, 130): the official MNB daily rate, downloaded automatically and kept locally; the
service answers over plain HTTP only, which is accepted because only dates and currency codes leave the machine, the
responses pass a plausibility check and a rate only shapes a proposal a person decides on. No test reaches the network:
every request goes to a stand-in transport.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from xml.sax.saxutils import escape

import pytest

from jav import cfg, fx, store

NOW = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)


def _response(days: dict[str, dict[str, tuple[int, str]]]) -> bytes:
    """A GetExchangeRates answer as the service sends it: the rate document as escaped text."""
    inner = "".join(f'<Day date="{d}">' + "".join(f'<Rate unit="{u}" curr="{c}">{r}</Rate>' for c, (u, r) in rates.items())
                    + "</Day>" for d, rates in days.items())
    inner = f"<MNBExchangeRates>{inner}</MNBExchangeRates>" if days else ""
    return ('<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
            '<GetExchangeRatesResponse xmlns="http://www.mnb.hu/webservices/"><GetExchangeRatesResult>'
            f"{escape(inner)}</GetExchangeRatesResult></GetExchangeRatesResponse></s:Body></s:Envelope>").encode("utf-8")


class Service:
    """A stand-in for the MNB service: answers from a fixed rate table, filtered to the requested days and codes."""

    def __init__(self, rates: dict[str, dict[str, tuple[int, str]]], *, fail: Exception | None = None):
        self.rates, self.fail, self.calls = rates, fail, []

    def __call__(self, url, body, headers, timeout):
        text = body.decode("utf-8")
        start = text.split("<web:startDate>")[1].split("<")[0]
        end = text.split("<web:endDate>")[1].split("<")[0]
        codes = text.split("<web:currencyNames>")[1].split("<")[0].split(",")
        self.calls.append({"url": url, "start": start, "end": end, "codes": codes, "headers": headers, "body": text})
        if self.fail is not None:
            raise self.fail
        return _response({d: {c: v for c, v in r.items() if c in codes} for d, r in self.rates.items() if start <= d <= end})


# A week of USD and EUR rates; 2026-10-03/04 is a weekend (no publication).
WEEK = {
    "2026-09-29": {"USD": (1, "325,10"), "EUR": (1, "366,00")},
    "2026-09-30": {"USD": (1, "326,00000"), "EUR": (1, "366,31000")},
    "2026-10-01": {"USD": (1, "326,18"), "EUR": (1, "368,32")},
    "2026-10-02": {"USD": (1, "326,94000"), "EUR": (1, "367,87000")},
    "2026-10-05": {"USD": (1, "327,98000"), "EUR": (1, "367,73000")},
    "2026-10-06": {"USD": (1, "324,98"), "EUR": (1, "365,38")},
}


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(fx, "_now", lambda: NOW)
    with store.use_store(tmp_path / "fx.sqlite"):
        yield


def _rows(sql: str) -> list[dict]:
    with store.connect() as c:
        return [dict(r) for r in c.execute(sql)]


# --- the request and the response ----------------------------------------------------------------------------------


def test_the_request_carries_only_two_dates_and_the_currency_codes():
    body = fx.envelope(date(2026, 9, 25), date(2026, 10, 6), ["USD", "EUR", "USD"]).decode("utf-8")
    assert "<web:startDate>2026-09-25</web:startDate>" in body and "<web:endDate>2026-10-06</web:endDate>" in body
    assert "<web:currencyNames>EUR,USD</web:currencyNames>" in body
    payload = body.split("<web:GetExchangeRates>")[1].split("</web:GetExchangeRates>")[0]
    assert payload.count("<web:") == 3


def test_the_response_is_read_with_its_decimal_comma_and_unit():
    rows = fx.parse(_response({"2026-10-05": {"EUR": (1, "367,73000"), "JPY": (100, "207,78000")}}))
    assert rows == [(date(2026, 10, 5), "EUR", 1, Decimal("367.73000")), (date(2026, 10, 5), "JPY", 100, Decimal("207.78000"))]
    assert fx.canonical(Decimal("367.73000")) == "367.73" and fx.canonical(Decimal("326")) == "326"


def test_an_empty_result_means_no_publication():
    assert fx.parse(_response({})) == []


@pytest.mark.parametrize("raw", [b"not xml", b"<a><b/></a>", _response({"2026-10-05": {"EUR": (1, "n/a")}})])
def test_an_unreadable_response_is_a_named_error(raw):
    with pytest.raises(fx.FxUnavailableError):
        fx.parse(raw)


def test_a_test_never_reaches_the_network(db):
    with pytest.raises(AssertionError, match="live exchange rate request"):
        fx.fetch(date(2026, 10, 1), date(2026, 10, 2), ["USD"])


# --- fetching and the plausibility check -----------------------------------------------------------------------------


def test_a_fetch_stores_the_published_days_and_logs_the_attempt(db):
    service = Service(WEEK)
    with fx.use_transport(service):
        assert fx.fetch(date(2026, 9, 29), date(2026, 10, 6), ["USD", "EUR"]) == 6
    assert service.calls[0]["url"] == "http://www.mnb.hu/arfolyamok.asmx"
    assert service.calls[0]["headers"]["SOAPAction"].endswith('/GetExchangeRates"')
    stored = {(r["currency"], r["day"]): r["rate"] for r in _rows("SELECT * FROM fx_rates")}
    assert stored[("EUR", "2026-10-05")] == "367.73" and len(stored) == 12
    [log] = _rows("SELECT * FROM fx_fetches")
    assert (log["status"], log["days"], log["currencies"]) == ("ok", 6, "EUR,USD")


@pytest.mark.parametrize("rates, why", [
    ({"2026-10-01": {"USD": (1, "326,18")}, "2026-10-02": {"USD": (1, "380,00")}}, "day-to-day change"),
    ({"2026-10-01": {"USD": (1, "0")}}, "non-positive"),
    ({"2026-10-01": {"USD": (0, "326,18")}}, "non-positive"),
])
def test_an_implausible_response_is_refused_as_a_whole(db, rates, why):
    with fx.use_transport(Service(rates)), pytest.raises(fx.FxRefusedError, match=why):
        fx.fetch(date(2026, 10, 1), date(2026, 10, 2), ["USD"])
    assert _rows("SELECT * FROM fx_rates") == []
    assert [r["status"] for r in _rows("SELECT * FROM fx_fetches")] == ["refused"]


def test_the_change_is_also_checked_against_the_stored_previous_day(db):
    with fx.use_transport(Service({"2026-10-01": {"USD": (1, "326,18")}})):
        fx.fetch(date(2026, 10, 1), date(2026, 10, 1), ["USD"])
    with fx.use_transport(Service({"2026-10-02": {"USD": (1, "250,00")}})), pytest.raises(fx.FxRefusedError):
        fx.fetch(date(2026, 10, 2), date(2026, 10, 2), ["USD"])


def test_a_rate_outside_the_request_is_refused(db):
    def answer(url, body, headers, timeout):
        return _response({"2026-10-01": {"USD": (1, "326,18"), "CHF": (1, "400,00")}})

    with fx.use_transport(answer), pytest.raises(fx.FxRefusedError, match="outside the request"):
        fx.fetch(date(2026, 10, 1), date(2026, 10, 1), ["USD"])


def test_an_unreachable_service_is_logged_as_failed(db):
    with fx.use_transport(Service(WEEK, fail=OSError("down"))), pytest.raises(fx.FxUnavailableError):
        fx.fetch(date(2026, 10, 1), date(2026, 10, 2), ["USD"])
    [log] = _rows("SELECT * FROM fx_fetches")
    assert log["status"] == "failed" and "OSError" in log["error"]


# --- resolving a day -------------------------------------------------------------------------------------------------


def test_a_published_day_resolves_to_its_own_rate_per_unit(db):
    with fx.use_transport(Service({**WEEK, "2026-10-05": {**WEEK["2026-10-05"], "JPY": (100, "207,78")}})):
        fx.fetch(date(2026, 9, 29), date(2026, 10, 6), ["USD", "JPY"])
    rate = fx.resolve("USD", date(2026, 10, 1))
    assert (rate.rate_day, rate.per_unit, rate.source) == (date(2026, 10, 1), Decimal("326.18"), "mnb")
    assert fx.resolve("JPY", date(2026, 10, 5)).per_unit == Decimal("2.0778")


def test_a_weekend_day_takes_the_last_published_day_when_the_days_between_were_fetched(db):
    with fx.use_transport(Service(WEEK)):
        fx.fetch(date(2026, 9, 29), date(2026, 10, 6), ["USD"])
    rate = fx.resolve("USD", date(2026, 10, 4))
    assert rate.rate_day == date(2026, 10, 2) and rate.per_unit == Decimal("326.94")


def test_a_day_never_fetched_is_unknown_not_a_holiday(db):
    with fx.use_transport(Service(WEEK)):
        fx.fetch(date(2026, 9, 29), date(2026, 10, 2), ["USD"])
    assert fx.resolve("USD", date(2026, 10, 2)) is not None
    assert fx.resolve("USD", date(2026, 10, 4)) is None  # 10-03 and 10-04 were never asked for


def test_a_fetch_does_not_vouch_for_its_own_day(db, monkeypatch):
    monkeypatch.setattr(fx, "_now", lambda: datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc))
    with fx.use_transport(Service({d: r for d, r in WEEK.items() if d < "2026-10-05"})):
        fx.fetch(date(2026, 10, 1), date(2026, 10, 5), ["USD"])
    assert fx.resolve("USD", date(2026, 10, 4)).rate_day == date(2026, 10, 2)
    assert fx.resolve("USD", date(2026, 10, 5)) is None  # the morning's fetch: the day's rate may come later


def test_the_lookback_is_limited(db, monkeypatch):
    real = dict(cfg.load("fx"))
    monkeypatch.setattr(fx, "_conf", lambda: {**real, "lookback_days": 1})
    with fx.use_transport(Service(WEEK)):
        fx.fetch(date(2026, 9, 29), date(2026, 10, 6), ["USD"])
    assert fx.resolve("USD", date(2026, 10, 3)).rate_day == date(2026, 10, 2)
    assert fx.resolve("USD", date(2026, 10, 4)) is None


# --- ensure and table --------------------------------------------------------------------------------------------------


def test_ensure_fetches_the_gap_once_and_then_reads_the_store(db):
    service = Service(WEEK)
    with fx.use_transport(service):
        first = fx.ensure([("USD", date(2026, 10, 4)), ("EUR", date(2026, 10, 1))])
        second = fx.ensure([("USD", date(2026, 10, 4)), ("EUR", date(2026, 10, 1))])
    assert first["status"] == "ok" and second == {"fetched": False, "status": "complete"}
    assert len(service.calls) == 1 and sorted(service.calls[0]["codes"]) == ["EUR", "USD"]
    assert service.calls[0]["start"] <= "2026-09-24" and service.calls[0]["end"] == "2026-10-04"


def test_ensure_skips_unhandled_currencies_and_future_days(db):
    service = Service(WEEK)
    with fx.use_transport(service):
        assert fx.ensure([("CHF", date(2026, 10, 1)), ("USD", NOW.date() + timedelta(days=3))])["status"] == "complete"
    assert service.calls == []


def test_a_failed_fetch_is_not_repeated_within_the_retry_time(db, monkeypatch):
    service = Service(WEEK, fail=OSError("down"))
    with fx.use_transport(service):
        assert fx.ensure([("USD", date(2026, 10, 1))])["status"] == "failed"
        assert fx.ensure([("USD", date(2026, 10, 1))])["status"] == "recently_tried"
        monkeypatch.setattr(fx, "_now", lambda: NOW + timedelta(minutes=61))
        service.fail = None
        assert fx.ensure([("USD", date(2026, 10, 1))])["status"] == "ok"
    assert len(service.calls) == 2


def test_table_reads_the_store_and_fetches_only_when_asked(db):
    needed = [("USD", date(2026, 10, 4)), ("EUR", date(2026, 10, 5))]
    assert fx.table(needed) == {}
    with fx.use_transport(Service(WEEK)):
        got = fx.table(needed, fetch_missing=True)
    assert got == {"EUR": {"2026-10-05": {"rate": "367.73", "rate_day": "2026-10-05", "source": "mnb"}},
                   "USD": {"2026-10-04": {"rate": "326.94", "rate_day": "2026-10-02", "source": "mnb"}}}
    assert fx.table(needed) == got  # offline afterwards


def test_status_counts_without_rates(db):
    with fx.use_transport(Service(WEEK)):
        fx.fetch(date(2026, 9, 29), date(2026, 10, 6), ["USD"])
    s = fx.status()
    assert s["currencies"]["USD"] == {"days": 6, "first": "2026-09-29", "last": "2026-10-06"}
    assert s["attempts"][0]["status"] == "ok"
