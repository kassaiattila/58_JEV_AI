"""The observability sink (213, P1a; the plug-in points of plan 212 P0).

Plain-language summary: how long an operation took and how it ended can be sent to one sink, switched off by default;
the sink receives only the operation's kind, its duration, its outcome category and its attempt count, never a case
id, document content, file name or address, and a sink that fails never stops the work.

229 (plan structure stage 1, SZ2a): moved from the process core to the shared core, so every layer measures through
the same place.

231 (stage E, E4; the owner's decisions of 2026-10-29: the measurements into a local file, switched off by default): a
measurement has the shape of an OpenTelemetry span (its name, its start, its duration, its status and attributes); an
attribute passes only when its name is none of the forbidden ones (`FORBIDDEN`: a document's text, a request or a
response, a file's name or path, an email address, a subject or a body) and its value is a number, a yes or no, or a
short code with no address or path in it (`clean`). Every paid or reading call is measured where it is written to the
call log (`store.ledger_add`), and the call sites time it through one helper (`start`, `since`). A long-running
process names the local file sink when the service configuration switches it on (`use_config`: `configs/service.json`
`metrics.enabled`), one JSON line a measurement in `runs/metrics/<day>.jsonl` under the installation's data folder.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# E4: an attribute whose name holds any of these never reaches a sink
FORBIDDEN = ("text", "content", "request", "response", "prompt", "body", "subject", "file", "path", "email", "address",
             "name", "case", "document", "query", "answer")
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.:+-]{0,80}$")  # a code: no address, no path, no sentence


def clean(attributes: Mapping[str, object] | None) -> dict[str, object]:
    """The attributes a sink may receive: a name none of `FORBIDDEN` is part of, and a number, a yes or no, or a short
    code; everything else is left out."""
    out: dict[str, object] = {}
    for key, value in (attributes or {}).items():
        lowered = str(key).lower()
        if any(word in lowered for word in FORBIDDEN):
            continue
        if isinstance(value, bool) or (isinstance(value, (int, float)) and value == value):
            out[str(key)] = value
        elif isinstance(value, str) and _SAFE_VALUE.fullmatch(value):
            out[str(key)] = value
    return out


@dataclass(frozen=True)
class Measurement:
    """What the observability sink receives, and nothing else (E4: its attributes already cleaned)."""

    operation: str
    seconds: float
    outcome: str
    attempts: int = 1
    attributes: Mapping[str, object] = field(default_factory=dict)
    started_at: float = 0.0  # E4: when it began (seconds since the epoch; 0: not known)


Observer = Callable[[Measurement], None]

_observer: Observer | None = None


def set_observer(fn: Observer | None) -> None:
    """Installs the observability sink (None: switched off, the default)."""
    global _observer
    _observer = fn


def observe(measurement: Measurement) -> None:
    if _observer is None:
        return
    try:
        _observer(Measurement(measurement.operation, measurement.seconds, measurement.outcome, measurement.attempts,
                              clean(measurement.attributes), measurement.started_at))
    except Exception:  # noqa: BLE001 - observability never stops the work; the failure is logged
        log.exception("the observability sink failed on %s", measurement.operation)


@contextmanager
def measured(operation: str, *, attempts: int = 1, attributes: Mapping[str, object] | None = None) -> Iterator[None]:
    """Measures the block: its duration and "ok", or "error" when it raises (the error goes on)."""
    started, began = time.perf_counter(), time.time()
    outcome = "error"
    try:
        yield
        outcome = "ok"
    finally:
        observe(Measurement(operation, time.perf_counter() - started, outcome, attempts, attributes or {}, began))


def start() -> float:
    """E4: the start of a timed call (the helper every call site times through)."""
    return time.perf_counter()


def since(started: float) -> float:
    """E4: the seconds since `start()`, as the call log keeps them (to the millisecond)."""
    return round(time.perf_counter() - started, 3)


def span(measurement: Measurement) -> dict[str, object]:
    """E4: a measurement in the shape of an OpenTelemetry span."""
    began = measurement.started_at or (time.time() - measurement.seconds)
    return {"name": measurement.operation,
            "start_time": datetime.fromtimestamp(began, timezone.utc).isoformat(timespec="milliseconds"),
            "duration_s": round(measurement.seconds, 3),
            "status": {"code": "ERROR" if measurement.outcome == "error" else "OK", "outcome": measurement.outcome},
            "attributes": {**dict(measurement.attributes), "attempts": measurement.attempts}}


class FileSink:
    """E4: one JSON line a measurement, a file a day, in `folder`; written under a lock, so the threads of one process
    never mix their lines."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._lock = threading.Lock()

    def __call__(self, measurement: Measurement) -> None:
        line = json.dumps(span(measurement), ensure_ascii=False, allow_nan=False)
        path = self.folder / f"{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
        with self._lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")


def use_config() -> bool:
    """E4: a long-running process names the local file sink when the service configuration switches it on (by default
    it is off). Returns whether it is on."""
    from jav.core import cfg
    from jav.core.config import RUNS_DIR

    metrics = cfg.load("service").get("metrics") or {}
    on = bool(metrics.get("enabled"))
    set_observer(FileSink(RUNS_DIR / str(metrics.get("folder") or "metrics")) if on else None)
    return on
