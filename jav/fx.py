"""130 (backlog F-reconciliation, K3): the official MNB daily exchange rates, fetched once and kept in the store.

A card payment of a foreign-currency invoice is booked in forints, and the statement does not print the original amount,
so the reconciliation compares the line with the invoice amount converted at the MNB rate (DECISIONS 128: the official
daily rate, downloaded automatically and kept locally). This module owns that rate table:

- **Fetching** (`ensure`): only the days a reconciliation needs, in one `GetExchangeRates` call per gap, with every
  attempt logged (`fx_fetches`). Only dates and currency codes leave the machine. The service answers over plain HTTP
  only (DECISIONS 130), so a response is refused as a whole when a rate is not positive, is outside the request or
  changes by more than `max_day_change` from the previous published day; nothing of it is stored then. A failed or
  refused attempt is not repeated within `retry_after_minutes`.
- **Resolving** (`resolve`, `table`): a day's rate is the rate published for that day; a day without a publication
  (weekend, holiday) takes the latest published day within `lookback_days`, but only when every day in between was
  covered by a successful fetch, so a day that was simply never fetched is never mistaken for a holiday. A fetch covers
  the days before the day it ran on: the rate of the fetch day itself may still be published later.
- **Offline by default in views:** `table(fetch=False)` only reads the store; the processing and the command line
  fetch (`fetch=True`). A test never reaches the network: `use_transport` installs a stand-in, and the test setup
  installs one that refuses.

The rates are stored exactly as published (forints per `unit` units, `unit` 100 for JPY); `resolve` gives forints per
one unit as a `Decimal`. Parameters are data (`configs/fx.json`).
"""

from __future__ import annotations

import contextlib
import contextvars
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Iterator
from xml.sax.saxutils import escape

from jav import cfg, store

Transport = Callable[[str, bytes, dict[str, str], float], bytes]
_SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
_MNB_NS = "http://www.mnb.hu/webservices/"

store.register_schema("fx", """
CREATE TABLE IF NOT EXISTS fx_rates (
    source      TEXT NOT NULL,      -- mnb
    currency    TEXT NOT NULL,      -- ISO 4217 code
    day         TEXT NOT NULL,      -- the day the rate was published for (YYYY-MM-DD)
    unit        INTEGER NOT NULL,   -- the rate is for this many units of the currency (JPY: 100)
    rate        TEXT NOT NULL,      -- forints per `unit` units, as published (canonical decimal string)
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (source, currency, day)
);
CREATE TABLE IF NOT EXISTS fx_fetches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    currencies  TEXT NOT NULL,      -- the requested codes, sorted, comma separated
    start_day   TEXT NOT NULL,
    end_day     TEXT NOT NULL,
    status      TEXT NOT NULL,      -- ok | failed | refused
    days        INTEGER NOT NULL DEFAULT 0,   -- published days received (ok only)
    error       TEXT,               -- why it failed or was refused (no response content)
    fetched_at  TEXT NOT NULL
);
""")


class FxUnavailableError(RuntimeError):
    """The rate service could not be reached, answered with an error, or sent a response that could not be read."""


class FxRefusedError(ValueError):
    """A response that was read but failed the plausibility check; nothing of it is stored."""


@dataclass(frozen=True)
class Rate:
    currency: str
    day: date          # the day asked for
    rate_day: date     # the published day used (the same day, or an earlier one for a day without a publication)
    per_unit: Decimal  # forints per one unit of the currency
    source: str


def _conf() -> dict[str, Any]:
    return dict(cfg.load("fx"))


def config_hash() -> str:
    return cfg.config_hash("fx")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- the transport (a test installs a stand-in) --------------------------------------------------------------------


def _urllib_transport(url: str, body: bytes, headers: dict[str, str], timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - the configured MNB address
        return response.read()


_transport: contextvars.ContextVar[Transport | None] = contextvars.ContextVar("fx_transport", default=None)


@contextlib.contextmanager
def use_transport(transport: Transport) -> Iterator[None]:
    """Route every rate request through `transport` (url, body, headers, timeout) -> response bytes."""
    token = _transport.set(transport)
    try:
        yield
    finally:
        _transport.reset(token)


# --- the request and the response ----------------------------------------------------------------------------------


def envelope(start: date, end: date, currencies: Iterable[str]) -> bytes:
    """The SOAP 1.1 request of `GetExchangeRates`: two dates and the currency codes, nothing else."""
    codes = ",".join(sorted(set(currencies)))
    return ('<?xml version="1.0" encoding="utf-8"?>'
            f'<soap:Envelope xmlns:soap="{_SOAP_NS}" xmlns:web="{_MNB_NS}"><soap:Body><web:GetExchangeRates>'
            f"<web:startDate>{start.isoformat()}</web:startDate><web:endDate>{end.isoformat()}</web:endDate>"
            f"<web:currencyNames>{escape(codes)}</web:currencyNames>"
            "</web:GetExchangeRates></soap:Body></soap:Envelope>").encode("utf-8")


def _xml(data: bytes | str):
    from defusedxml import ElementTree

    return ElementTree.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)


def _decimal(text: str | None) -> Decimal:
    """A published rate: a decimal comma, any number of decimals ("367,73000")."""
    try:
        value = Decimal(str(text or "").strip().replace(",", "."))
    except InvalidOperation as exc:
        raise FxUnavailableError("unreadable rate") from exc
    if not value.is_finite():
        raise FxUnavailableError("unreadable rate")
    return value


def canonical(value: Decimal) -> str:
    """A rate as a plain decimal string without trailing zeros ("367.73000" -> "367.73")."""
    text = format(value.normalize(), "f")
    return text if "." not in text else text.rstrip("0").rstrip(".")


def parse(response: bytes) -> list[tuple[date, str, int, Decimal]]:
    """The (day, currency, unit, rate) rows of a `GetExchangeRates` response. The rates come as an XML document inside a
    string element; an empty document means no publication in the requested days."""
    try:
        outer = _xml(response)
    except Exception as exc:  # defusedxml raises its own and ElementTree's errors
        raise FxUnavailableError("the response is not XML") from exc
    result = next((el for el in outer.iter() if el.tag.rsplit("}", 1)[-1] == "GetExchangeRatesResult"), None)
    if result is None:
        raise FxUnavailableError("the response has no exchange rate result")
    text = (result.text or "").strip()
    if not text:
        return []
    try:
        inner = _xml(text)
    except Exception as exc:
        raise FxUnavailableError("the exchange rate result is not XML") from exc
    rows = []
    for day_el in inner.iter("Day"):
        try:
            day = date.fromisoformat(day_el.attrib.get("date", ""))
        except ValueError as exc:
            raise FxUnavailableError("a published day without a valid date") from exc
        for rate_el in day_el.iter("Rate"):
            try:
                unit = int(rate_el.attrib.get("unit", ""))
            except ValueError as exc:
                raise FxUnavailableError("a rate without a valid unit") from exc
            rows.append((day, str(rate_el.attrib.get("curr", "")), unit, _decimal(rate_el.text)))
    return rows


def plausible(rows: list[tuple[date, str, int, Decimal]], *, start: date, end: date, currencies: set[str],
              previous: dict[str, Decimal]) -> None:
    """Refuses a response (`FxRefusedError`) with a rate outside the request, a non-positive rate or unit, two rates
    for one day, or a change of more than `max_day_change` from the previous published day (`previous`: the stored
    rate per unit before `start`, per currency)."""
    limit = Decimal(str(_conf()["max_day_change"]))
    seen: set[tuple[date, str]] = set()
    last = dict(previous)
    for day, currency, unit, rate in sorted(rows):
        if currency not in currencies or not start <= day <= end:
            raise FxRefusedError(f"a rate outside the request: {currency} {day.isoformat()}")
        if unit <= 0 or rate <= 0:
            raise FxRefusedError(f"a non-positive rate or unit: {currency} {day.isoformat()}")
        if (day, currency) in seen:
            raise FxRefusedError(f"two rates for one day: {currency} {day.isoformat()}")
        seen.add((day, currency))
        per_unit = rate / unit
        before = last.get(currency)
        if before is not None and abs(per_unit / before - 1) > limit:
            raise FxRefusedError(f"a day-to-day change above {limit}: {currency} {day.isoformat()}")
        last[currency] = per_unit


# --- the store ------------------------------------------------------------------------------------------------------


def _log(c, *, source: str, currencies: Iterable[str], start: date, end: date, status: str, days: int = 0,
         error: str | None = None) -> None:
    c.execute("INSERT INTO fx_fetches(source, currencies, start_day, end_day, status, days, error, fetched_at)"
              " VALUES (?,?,?,?,?,?,?,?)", (source, ",".join(sorted(set(currencies))), start.isoformat(), end.isoformat(),
                                            status, days, error, _now().isoformat(timespec="seconds")))


def _previous(c, source: str, currencies: Iterable[str], before: date) -> dict[str, Decimal]:
    out = {}
    for currency in currencies:
        r = c.execute("SELECT unit, rate FROM fx_rates WHERE source=? AND currency=? AND day<? ORDER BY day DESC LIMIT 1",
                      (source, currency, before.isoformat())).fetchone()
        if r is not None:
            out[currency] = Decimal(r["rate"]) / int(r["unit"])
    return out


def fetch(start: date, end: date, currencies: Iterable[str]) -> int:
    """One `GetExchangeRates` call for [start, end]; stores the published days and logs the attempt. Returns the number
    of published days received. Raises `FxUnavailableError` (not reached, an error answer, unreadable) or
    `FxRefusedError` (implausible); both are logged and store no rate."""
    conf = _conf()
    source = conf["source"]
    codes = sorted({str(c).upper() for c in currencies})
    if not codes:
        return 0
    if end < start or (end - start).days > int(conf["max_span_days"]):
        raise ValueError("invalid or too long date span")
    transport = _transport.get() or _urllib_transport
    headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"{source["soap_action"]}"'}
    try:
        try:
            raw = transport(source["url"], envelope(start, end, codes), headers, float(source["timeout_s"]))
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise FxUnavailableError(f"the rate service could not be reached: {type(exc).__name__}") from exc
        rows = parse(raw)
        with store.connect() as c:
            plausible(rows, start=start, end=end, currencies=set(codes),
                      previous=_previous(c, source["name"], codes, start))
            store.begin_immediate(c)
            fetched_at = _now().isoformat(timespec="seconds")
            for day, currency, unit, rate in rows:
                c.execute("INSERT INTO fx_rates(source, currency, day, unit, rate, fetched_at) VALUES (?,?,?,?,?,?)"
                          " ON CONFLICT(source, currency, day) DO UPDATE SET unit=excluded.unit, rate=excluded.rate,"
                          " fetched_at=excluded.fetched_at",
                          (source["name"], currency, day.isoformat(), unit, canonical(rate), fetched_at))
            days = len({day for day, *_ in rows})
            _log(c, source=source["name"], currencies=codes, start=start, end=end, status="ok", days=days)
        return days
    except FxRefusedError as exc:
        with store.connect() as c:
            _log(c, source=source["name"], currencies=codes, start=start, end=end, status="refused", error=str(exc)[:200])
        raise
    except FxUnavailableError as exc:
        with store.connect() as c:
            _log(c, source=source["name"], currencies=codes, start=start, end=end, status="failed", error=str(exc)[:200])
        raise


def _covered_days(c, source: str, currency: str) -> set[date]:
    """The days a successful fetch of the currency vouches for: from its start to the day before it ran (or its end)."""
    days: set[date] = set()
    for r in c.execute("SELECT currencies, start_day, end_day, fetched_at FROM fx_fetches WHERE source=? AND status='ok'",
                       (source,)):
        if currency not in r["currencies"].split(","):
            continue
        start, end = date.fromisoformat(r["start_day"]), date.fromisoformat(r["end_day"])
        ran = datetime.fromisoformat(r["fetched_at"]).date()
        last = min(end, ran - timedelta(days=1))
        d = start
        while d <= last:
            days.add(d)
            d += timedelta(days=1)
    return days


def _published(c, source: str, currency: str, start: date, end: date) -> dict[date, Decimal]:
    return {date.fromisoformat(r["day"]): Decimal(r["rate"]) / int(r["unit"]) for r in c.execute(
        "SELECT day, unit, rate FROM fx_rates WHERE source=? AND currency=? AND day BETWEEN ? AND ?",
        (source, currency, start.isoformat(), end.isoformat()))}


def _resolve(day: date, published: dict[date, Decimal], covered: set[date], lookback: int) -> tuple[date, Decimal] | None:
    for back in range(lookback + 1):
        d = day - timedelta(days=back)
        if d in published:
            return d, published[d]
        if d not in covered:
            return None  # never fetched: it may have had a publication
    return None


def resolve(currency: str, day: date) -> Rate | None:
    """The rate of `currency` for `day` from the store, or None when it is not known (see the module notes)."""
    conf = _conf()
    source, lookback = conf["source"]["name"], int(conf["lookback_days"])
    with store.connect() as c:
        published = _published(c, source, currency, day - timedelta(days=lookback), day)
        found = _resolve(day, published, _covered_days(c, source, currency), lookback)
    return Rate(currency, day, found[0], found[1], source) if found else None


def _missing(c, source: str, currency: str, days: set[date], lookback: int, today: date) -> set[date]:
    """The days to fetch so that every one of `days` can be resolved (none in the future)."""
    if not days:
        return set()
    lo, hi = min(days) - timedelta(days=lookback), max(days)
    published = _published(c, source, currency, lo, hi)
    covered = _covered_days(c, source, currency)
    out: set[date] = set()
    for day in days:
        if day > today or _resolve(day, published, covered, lookback) is not None:
            continue
        for back in range(lookback + 1):
            d = day - timedelta(days=back)
            if d in published:
                break
            if d not in covered:
                out.add(d)
    return out


def _recently_tried(c, source: str, currencies: Iterable[str], start: date, end: date, minutes: int) -> bool:
    since = (_now() - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    wanted = set(currencies)
    for r in c.execute("SELECT currencies, start_day, end_day FROM fx_fetches WHERE source=? AND fetched_at>=?",
                       (source, since)):
        if (wanted <= set(r["currencies"].split(",")) and r["start_day"] <= start.isoformat()
                and end.isoformat() <= r["end_day"]):
            return True
    return False


def ensure(needed: Iterable[tuple[str, date]]) -> dict[str, Any]:
    """Fetch what is missing for the (currency, day) pairs, at most one call, and never twice within
    `retry_after_minutes` for the same span. Never raises for the service: a failure is logged and reported."""
    conf = _conf()
    source, lookback = conf["source"]["name"], int(conf["lookback_days"])
    allowed = set(conf["currencies"])
    by_currency: dict[str, set[date]] = {}
    for currency, day in needed:
        if currency in allowed:
            by_currency.setdefault(currency, set()).add(day)
    today = _now().date()
    with store.connect() as c:
        missing = {cur: _missing(c, source, cur, days, lookback, today) for cur, days in by_currency.items()}
    missing = {cur: days for cur, days in missing.items() if days}
    if not missing:
        return {"fetched": False, "status": "complete"}
    start, end = min(min(d) for d in missing.values()), max(max(d) for d in missing.values())
    with store.connect() as c:
        if _recently_tried(c, source, missing, start, end, int(conf["retry_after_minutes"])):
            return {"fetched": False, "status": "recently_tried"}
    try:
        days = fetch(start, end, missing)
    except FxRefusedError:
        return {"fetched": True, "status": "refused"}
    except FxUnavailableError:
        return {"fetched": True, "status": "failed"}
    return {"fetched": True, "status": "ok", "days": days}


def table(needed: Iterable[tuple[str, date]], *, fetch_missing: bool = False) -> dict[str, dict[str, dict[str, str]]]:
    """The resolved rates of the (currency, day) pairs as plain data for the reconciliation snapshot:
    {currency: {day: {"rate": forints per unit, "rate_day": the published day used, "source": "mnb"}}}. With
    `fetch_missing` the gaps are fetched first (`ensure`); otherwise only the store is read."""
    pairs = sorted({(str(cur), d) for cur, d in needed if cur})
    if fetch_missing:
        ensure(pairs)
    conf = _conf()
    source, lookback = conf["source"]["name"], int(conf["lookback_days"])
    out: dict[str, dict[str, dict[str, str]]] = {}
    with store.connect() as c:
        for currency in sorted({cur for cur, _ in pairs}):
            days = [d for cur, d in pairs if cur == currency]
            published = _published(c, source, currency, min(days) - timedelta(days=lookback), max(days))
            covered = _covered_days(c, source, currency)
            for day in days:
                found = _resolve(day, published, covered, lookback)
                if found:
                    out.setdefault(currency, {})[day.isoformat()] = {"rate": canonical(found[1]), "rate_day": found[0].isoformat(),
                                                                     "source": source}
    return out


def status() -> dict[str, Any]:
    """Counts for the command line: the stored days per currency and the latest attempts (no rates printed)."""
    with store.connect() as c:
        per_currency = {r["currency"]: {"days": r["n"], "first": r["first"], "last": r["last"]} for r in c.execute(
            "SELECT currency, COUNT(*) AS n, MIN(day) AS first, MAX(day) AS last FROM fx_rates GROUP BY currency ORDER BY currency")}
        attempts = [dict(r) for r in c.execute(
            "SELECT currencies, start_day, end_day, status, days, error, fetched_at FROM fx_fetches ORDER BY id DESC LIMIT 5")]
    return {"currencies": per_currency, "attempts": attempts, "config_hash": config_hash()}


__all__ = ["FxRefusedError", "FxUnavailableError", "Rate", "canonical", "config_hash", "ensure", "envelope", "fetch",
           "parse", "plausible", "resolve", "status", "table", "use_transport"]

