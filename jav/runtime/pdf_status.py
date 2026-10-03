"""A worker's PDF protection report, tied to a live process instance and a short lease.

The service must not mistake its own reader settings for the worker's protection.
A dedicated operating-system lock prevents a recycled PID or a recent report from a
previous worker becoming evidence for a new worker. No application database changes.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from jav import isolated_pdf
from jav.runtime import lock

log = logging.getLogger(__name__)
REPORT_INTERVAL_S = 2.0
MAX_AGE_S = 10.0


def report_path(store_path: Path) -> Path:
    return store_path.with_name("worker-pdf-status.json")


def _owner_path(store_path: Path, instance: str) -> Path:
    return store_path.parent / "pdf-status" / f"{instance}.lock"


@contextmanager
def publish(store_path: Path) -> Iterator[None]:
    """Publish while holding the worker lock; refresh even during a long document read."""
    instance = uuid.uuid4().hex
    owner = lock.hold(_owner_path(store_path, instance))
    stopped = threading.Event()
    target = report_path(store_path)
    temporary = target.with_suffix(f".{instance}.tmp")

    def write() -> None:
        try:
            report = {**isolated_pdf.protection_status(), "schema": 1, "instance": instance,
                      "reported_at": time.time(), "max_age_s": MAX_AGE_S}
            temporary.write_text(json.dumps(report, allow_nan=False), encoding="utf-8")
            os.replace(temporary, target)
        except (OSError, ValueError):
            # Old reports expire. Failure to report must never imply protection or stop a job.
            log.exception("could not publish the worker PDF protection state")

    def refresh() -> None:
        while not stopped.wait(REPORT_INTERVAL_S):
            write()

    thread = threading.Thread(target=refresh, name="jav-pdf-status", daemon=True)
    try:
        write()  # overwrite a previous worker's report before accepting any job
        thread.start()
        yield
    finally:
        stopped.set()
        if thread.ident is not None:
            thread.join()
        lock.release(owner)


def worker_status(store_path: Path, *, running: bool, now: float | None = None) -> dict[str, Any]:
    """Read-only evidence. Missing/invalid reports are unknown; expired/dead reports stale."""
    unknown: dict[str, Any] = {
        "state": "unknown", "reason": "report_missing" if running else "worker_not_running",
        "configured": None, "effective_memory_mb": None, "helper_pid": None,
        "process_pid": None, "observed_at": None, "reported_at": None, "max_age_s": MAX_AGE_S,
    }
    try:
        report = json.loads(report_path(store_path).read_text(encoding="utf-8"))
        if not isinstance(report, dict) or report.get("schema") != 1:
            raise ValueError("unsupported report")
        instance = report.get("instance")
        stamp = report.get("reported_at")
        if not isinstance(instance, str) or not re.fullmatch(r"[0-9a-f]{32}", instance):
            raise ValueError("invalid instance")
        if type(stamp) not in (int, float) or not math.isfinite(stamp):
            raise ValueError("invalid time")
        if report.get("state") not in {"protected", "unprotected", "unknown", "stale"}:
            raise ValueError("invalid protection state")
        configured = report.get("configured")
        if not isinstance(configured, dict) or type(configured.get("isolated")) is not bool or (
            type(configured.get("memory_mb")) is not int or configured["memory_mb"] < 0
            or type(configured.get("require_memory_limit")) is not bool
        ):
            raise ValueError("missing settings")
        observed = report.get("observed_at")
        if type(observed) not in (int, float) or not math.isfinite(observed) or not isinstance(report.get("reason"), str):
            raise ValueError("missing observation")
        if report["state"] == "protected" and (
            type(report.get("effective_memory_mb")) is not int or report["effective_memory_mb"] <= 0
            or configured.get("isolated") is not True
            or report["effective_memory_mb"] != configured.get("memory_mb")
            or type(report.get("helper_pid")) is not int or report["helper_pid"] <= 0
        ):
            raise ValueError("inconsistent protection")
        age = (time.time() if now is None else now) - stamp
        reason = None
        if not running:
            reason = "worker_not_running"
        elif not lock.is_held(_owner_path(store_path, instance)):
            reason = "worker_instance_ended"
        elif age < 0 or age > MAX_AGE_S or observed > stamp or stamp - observed > MAX_AGE_S:
            reason = "report_expired"
        if reason:
            report = {**report, "state": "stale", "reason": reason, "effective_memory_mb": None}
        if report["state"] != "protected":
            report["effective_memory_mb"] = None
        return {**report, "max_age_s": MAX_AGE_S}
    except FileNotFoundError:
        return unknown
    except (OSError, ValueError, TypeError):
        return {**unknown, "reason": "report_invalid"}
