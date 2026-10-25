"""Connectors (231, plan stage C, C2a; glossary: Connector): the external services the system asks, and the one way to
ask them.

Plain-language summary: each external service is described once, as data (`configs/connectors.json`): its address,
what leaves the machine, the price of one question, how long to wait for an answer, how many times a failed question
is asked again, how many questions a minute it may get and the largest answer read. Every question goes through
`ask`, which keeps to that description and writes each attempt into the call log under the connector's name. A test
never reaches the network: the test setup installs a stand-in that refuses, and a test that needs an answer installs
its own (`use_transport`).

- `Connector`, `of(name)`, `catalogue()`: one service's description, checked when it is read (`ConnectorError`).
- `ask(name, body, *, purpose)`: one question (`body` None: a GET without one); returns the answer's bytes. Raises
  `ConnectorUnavailable` with its `reason`: `unreachable` (not reached, or an error answer; `error` names the
  transport's error class), `too_large` (an answer over the size limit) or `busy` (the rate limit is reached; nothing
  was sent).
- A connector of `kind: lookup` asks without changing the other system. A free one is a repeatable call of the call
  log (an answer lost after sending is a plain failure, asked again later); a priced one reserves its price from the
  running work's budget and is refused outside one. A message that changes another system is not a connector's
  question: it goes through the process core's handover record.

Layer: shared core (an adapter beside the call log); the domains read their connector's name from their own rule file.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import logging
import secrets
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterator, Literal

from jav.core import calls, cfg, store
from jav.core.clock import utc_now as _now

__all__ = ["Connector", "ConnectorError", "ConnectorUnavailable", "Transport", "ask", "catalogue", "of", "use_transport"]

log = logging.getLogger(__name__)

Transport = Callable[[str, bytes | None, dict[str, str], float], bytes]
KINDS = ("lookup",)
RUN_PREFIX = "connector:"  # the call log's run of a connector's questions: `connector:<name>`


class ConnectorError(ValueError):
    """A connector that is not described, or whose description does not fit the rules."""


class ConnectorUnavailable(RuntimeError):
    """The question got no usable answer: `reason` is `unreachable`, `too_large` or `busy`; `error` names the
    transport's error class for `unreachable`."""

    def __init__(self, name: str, reason: Literal["unreachable", "too_large", "busy"], error: str | None = None):
        super().__init__(f"connector {name}: {reason}" + (f" ({error})" if error else ""))
        self.name, self.reason, self.error = name, reason, error


@dataclass(frozen=True)
class Connector:
    name: str
    what: str
    kind: str
    url: str
    headers: dict[str, str]
    sends: tuple[str, ...]
    price_usd: Decimal
    timeout_s: float
    retries: int
    retry_wait_s: float
    max_per_minute: int
    max_response_bytes: int

    @property
    def free(self) -> bool:
        return self.price_usd == 0


def _decimal(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _read(name: str, raw: dict[str, Any]) -> Connector:
    problems = []
    if raw.get("kind") not in KINDS:
        problems.append(f"its kind is one of {', '.join(KINDS)}")
    url = str(raw.get("url") or "")
    if not url.startswith(("http://", "https://")):
        problems.append("its address is an http or https address")
    sends = raw.get("sends")
    if not isinstance(sends, list) or not sends or not all(isinstance(s, str) and s.strip() for s in sends):
        problems.append("it names what leaves the machine")
    price = _decimal(raw.get("price_usd"))
    if price is None or price < 0:
        problems.append("its price is an amount of at least 0")
    whole = {key: raw.get(key) for key in ("retries", "max_per_minute", "max_response_bytes")}
    for key, value in whole.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < (0 if key == "retries" else 1):
            problems.append(f"its {key} is a whole number of at least {0 if key == 'retries' else 1}")
    seconds = {key: raw.get(key) for key in ("timeout_s", "retry_wait_s")}
    for key, value in seconds.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < (0 if key == "retry_wait_s" else 1):
            problems.append(f"its {key} is a number of seconds")
    headers = raw.get("headers") or {}
    if not isinstance(headers, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in headers.items()):
        problems.append("its headers are texts")
    if not str(raw.get("what") or "").strip():
        problems.append("it says what the service is")
    if problems:
        raise ConnectorError(f"connector {name}: " + "; ".join(problems))
    return Connector(name=name, what=str(raw["what"]), kind=str(raw["kind"]), url=url, headers=dict(headers),
                     sends=tuple(sends), price_usd=Decimal(str(raw["price_usd"])), timeout_s=float(raw["timeout_s"]),
                     retries=int(raw["retries"]), retry_wait_s=float(raw["retry_wait_s"]),
                     max_per_minute=int(raw["max_per_minute"]), max_response_bytes=int(raw["max_response_bytes"]))


def _described() -> dict[str, Any]:
    return dict(cfg.load("connectors")["connectors"])


def of(name: str) -> Connector:
    """The connector described as `name`; `ConnectorError` if there is none or its description does not fit."""
    described = _described()
    if name not in described:
        raise ConnectorError(f"no connector {name} is described")
    return _read(name, described[name])


def catalogue() -> list[Connector]:
    """Every described connector, by name."""
    return [_read(name, raw) for name, raw in sorted(_described().items())]


# --- the transport (a test installs a stand-in) --------------------------------------------------------------------


def _network(limit: int) -> Transport:
    def send(url: str, body: bytes | None, headers: dict[str, str], timeout: float) -> bytes:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - a described connector's address
            return response.read(limit + 1)

    return send


_transport: contextvars.ContextVar[Transport | None] = contextvars.ContextVar("connector_transport", default=None)


@contextlib.contextmanager
def use_transport(transport: Transport) -> Iterator[None]:
    """Route every connector's question through `transport` (url, body, headers, timeout) -> the answer's bytes."""
    token = _transport.set(transport)
    try:
        yield
    finally:
        _transport.reset(token)


# --- asking ---------------------------------------------------------------------------------------------------------


def _busy(connector: Connector) -> bool:
    since = (_now() - timedelta(minutes=1)).isoformat(timespec="seconds")
    with store.connect() as c:
        asked = c.execute("SELECT COUNT(*) FROM invocations WHERE provider=? AND created_at>=?",
                          (connector.name, since)).fetchone()[0]
    return asked >= connector.max_per_minute


def _ask_once(connector: Connector, body: bytes | None, *, purpose: str, run_id: str) -> bytes:
    if _busy(connector):
        raise ConnectorUnavailable(connector.name, "busy")
    transport = _transport.get() or _network(connector.max_response_bytes)
    answer: list[bytes] = []

    def question() -> calls.Outcome:
        try:
            raw = transport(connector.url, body, dict(connector.headers), connector.timeout_s)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise ConnectorUnavailable(connector.name, "unreachable", type(exc).__name__) from exc
        if len(raw) > connector.max_response_bytes:
            raise ConnectorUnavailable(connector.name, "too_large")
        answer.append(raw)
        return calls.Outcome(response={"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
                             cost_usd=connector.price_usd)

    scope = None
    if not connector.free:
        ctx = calls.current()
        if ctx is None or ctx.budget_scope is None:
            raise calls.BudgetExceeded(f"connector {connector.name} costs {connector.price_usd} USD a question:"
                                       " it is asked only within a budget")
        scope = ctx.budget_scope
    calls.invoke(run_id=run_id, step_id=f"{purpose}:{secrets.token_hex(6)}", provider=connector.name, model=None,
                 max_cost_usd=connector.price_usd, fn=question, budget_scope=scope,
                 request_hash=hashlib.sha256(body or b"").hexdigest(), repeatable=connector.free)
    return answer[0]


def ask(name: str, body: bytes | None, *, purpose: str, run_id: str | None = None) -> bytes:
    """One question to the connector `name` (see the module notes); `purpose` names the asking work in the call log
    (its step), `run_id` its run (by default the connector's own, `connector:<name>`). An unreached service is asked
    again up to `retries` times, `retry_wait_s` apart; each attempt is its own call log row."""
    connector = of(name)
    for attempt in range(connector.retries + 1):
        try:
            return _ask_once(connector, body, purpose=purpose, run_id=run_id or f"{RUN_PREFIX}{name}")
        except ConnectorUnavailable as exc:
            if exc.reason != "unreachable" or attempt == connector.retries:
                raise
            log.info("connector %s not reached (%s); asking again (%d of %d)", name, exc.error, attempt + 1,
                     connector.retries)
            time.sleep(connector.retry_wait_s)
    raise AssertionError("unreachable")  # the loop returns or raises
