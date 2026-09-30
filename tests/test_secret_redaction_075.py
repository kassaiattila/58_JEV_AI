"""075 (repeated security audit, S04): a provider key must not leak into exceptions, logs or stored error texts.

The SDK (typesafe-sdk >= 0.7.1) validates the key early and masks it in connection errors; the project's own logs and
stored item errors mask every secret from the environment as defence in depth. Synthetic keys only, no network.
"""

from __future__ import annotations

import logging
import traceback

import httpx2
import pytest
from typesafe_sdk._core.config import resolve_and_validate_api_key
from typesafe_sdk._core.errors import TypeSafeError
from typesafe_sdk._core.transport import RequestState, prepare

from jav.adapters.jev import _error_slugs
from jav.runtime import applog

FAKE_KEY = "SYNTHETIC-NOT-A-REAL-KEY-0123456789"


@pytest.fixture
def fake_secret(monkeypatch):
    monkeypatch.setenv("JAV_TEST_API_KEY", FAKE_KEY)
    applog.reset_secrets()
    yield FAKE_KEY
    applog.reset_secrets()


def _chain_text(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc))


def test_sdk_rejects_a_malformed_key_without_echoing_it():
    bad = "SYNTHETIC\x01KEY-0123456789"
    with pytest.raises(TypeSafeError) as caught:
        resolve_and_validate_api_key(bad)
    assert bad not in _chain_text(caught.value)


def test_sdk_connection_error_masks_the_key_in_the_whole_chain():
    from typesafe_sdk._core.config import Config

    conf = Config.resolve(FAKE_KEY, "http://127.0.0.1:1", None, 1.0, None)
    request = prepare(conf, "POST", "/v1/test", {}, None, None, dict)
    with pytest.raises(Exception) as caught:
        with RequestState(request).attempt() as headers:
            raise httpx2.LocalProtocolError(f"Illegal header value {headers['authorization']!r}")
    assert FAKE_KEY not in _chain_text(caught.value)
    assert FAKE_KEY not in str(_error_slugs(caught.value))


def test_redact_masks_plain_and_escaped_forms(fake_secret):
    assert applog.redact(f"Bearer {fake_secret}") == "Bearer ***"
    assert fake_secret not in applog.redact(repr(fake_secret.encode()))
    assert applog.redact("nothing secret here") == "nothing secret here"


def test_log_file_masks_message_args_and_chained_traceback(fake_secret, tmp_path, monkeypatch):
    monkeypatch.setattr(applog, "LOG_DIR", tmp_path)
    root = logging.getLogger()
    before = list(root.handlers)
    path = applog.setup("redaction-test")
    try:
        log = logging.getLogger("jav.test.redaction")
        log.error("call failed with %s", fake_secret)
        try:
            try:
                raise RuntimeError(f"inner {fake_secret}")
            except RuntimeError as inner:
                raise ValueError("outer") from inner
        except ValueError:
            log.exception("item failed")
    finally:
        for handler in [h for h in root.handlers if h not in before]:
            handler.close()
            root.removeHandler(handler)
    text = path.read_text(encoding="utf-8")
    assert "call failed with ***" in text
    assert "inner ***" in text
    assert fake_secret not in text


def test_uvicorn_config_masks_every_handler(fake_secret):
    cfg = applog.uvicorn_config("redaction-test")
    assert "redact_secrets" in cfg["filters"]
    for name, handler in cfg["handlers"].items():
        assert "redact_secrets" in handler.get("filters", []), name


def test_worker_error_text_is_masked(fake_secret):
    from jav.runtime.worker import error_text

    text = error_text(RuntimeError(f"connect failed: Bearer {fake_secret}"))
    assert text == "RuntimeError: connect failed: Bearer ***"
    assert len(error_text(RuntimeError("x" * 1000), limit=300)) == 300
