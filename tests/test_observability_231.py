"""231 (stage E, E4; the owner's decisions of 2026-10-29: the measurements into a local file, off by default).

An attribute reaches a sink only when its name is none of the forbidden ones and its value is a number, a yes or no or
a short code: a document's text, a request, a file's name or path and an email address never do. Every call written to
the call log is measured there; the local file sink writes each measurement as one OpenTelemetry-shaped line, and the
service configuration switches it on (by default it is off). The call sites time through one helper: the clock is read
directly nowhere else. Invented values; an empty store; nothing runs and no AI is asked.
"""

from __future__ import annotations

import json
import re

import pytest

from jav.core import cfg, config, observability, store
from jav.core.config import PROJECT_ROOT


@pytest.fixture
def seen():
    got: list[observability.Measurement] = []
    observability.set_observer(got.append)
    try:
        yield got
    finally:
        observability.set_observer(None)


def test_only_safe_attributes_reach_a_sink() -> None:
    kept = observability.clean({
        "provider": "jev", "tokens": 12, "cost_usd": 0.01, "cached": False, "model": "gpt-5.1-mini",
        "document_text": "Számla 1234", "request": "{...}", "file_name": "a.pdf", "email": "anna@example.com",
        "step": "C:/Users/anna/Documents/a.pdf", "note": "anna@example.com", "label": "a sentence with spaces"})
    assert kept == {"provider": "jev", "tokens": 12, "cost_usd": 0.01, "cached": False, "model": "gpt-5.1-mini"}


def test_every_call_written_to_the_call_log_is_measured(tmp_path, seen) -> None:
    with store.use_store(tmp_path / "s.sqlite"):
        store.ledger_add(run_id="r1", step="detect", provider="jev", model="jev-1", input_tokens=10, output_tokens=2,
                         cost_usd=0.001, seconds=1.5, cached=False)
        store.ledger_add(run_id="r1", step="detect", provider="jev", model=None, input_tokens=None, output_tokens=None,
                         cost_usd=None, seconds=None, error="Timeout")
    assert [(m.operation, m.seconds, m.outcome) for m in seen] == [("call.detect", 1.5, "ok"), ("call.detect", 0.0, "error")]
    assert seen[0].attributes == {"provider": "jev", "model": "jev-1", "input_tokens": 10, "output_tokens": 2,
                                  "cost_usd": 0.001, "cached": False}


def test_the_file_sink_writes_a_span_a_line_and_nothing_forbidden(tmp_path) -> None:
    sink = observability.FileSink(tmp_path / "metrics")
    observability.set_observer(sink)
    try:
        observability.observe(observability.Measurement("call.extract", 2.25, "ok", 1,
                                                        {"provider": "gpt", "file_name": "secret.pdf"}, 1793260800.0))
        with pytest.raises(ValueError):
            with observability.measured("step.read", attributes={"email": "anna@example.com"}):
                raise ValueError("the error goes on")
    finally:
        observability.set_observer(None)
    [day] = list((tmp_path / "metrics").glob("*.jsonl"))
    first, second = [json.loads(line) for line in day.read_text(encoding="utf-8").splitlines()]
    assert first == {"name": "call.extract", "start_time": "2026-10-29T08:00:00.000+00:00", "duration_s": 2.25,
                     "status": {"code": "OK", "outcome": "ok"}, "attributes": {"provider": "gpt", "attempts": 1}}
    assert second["status"] == {"code": "ERROR", "outcome": "error"} and second["attributes"] == {"attempts": 1}
    assert "secret" not in day.read_text(encoding="utf-8") and "example.com" not in day.read_text(encoding="utf-8")


def test_the_configuration_switches_the_local_file_on_and_it_is_off_by_default(tmp_path, monkeypatch) -> None:
    assert observability.use_config() is False and observability._observer is None
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: {**real(name), "metrics": {"enabled": True, "folder": "m"}}
                        if name == "service" else real(name))
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    try:
        assert observability.use_config() is True
        with store.use_store(tmp_path / "s.sqlite"):
            store.ledger_add(run_id="r1", step="ocr", provider="tesseract", model=None, input_tokens=None,
                             output_tokens=None, cost_usd=None, seconds=0.5)
    finally:
        observability.set_observer(None)
    assert len(list((tmp_path / "m").glob("*.jsonl"))) == 1


def test_the_call_sites_time_through_the_helper() -> None:
    read = {}
    for path in sorted((PROJECT_ROOT / "jav").rglob("*.py")):
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if rel.startswith(("jav/devtools/", "jav/evals/")) or rel == "jav/core/observability.py":
            continue
        if n := len(re.findall(r"perf_counter\(", path.read_text(encoding="utf-8"))):
            read[rel] = n
    assert read == {"jav/documents/ocr.py": 2}  # a page reading's own two-decimal figure in its result
