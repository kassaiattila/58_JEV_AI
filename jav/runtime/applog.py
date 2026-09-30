"""Operations log (063): a permanent, rotating log file of the local service and the worker under `runs/logs/`.

Until now the only trace of errors was the redirected output of `scripts/dev.ps1`, which was emptied at every start,
the worker wrote nothing per task, and an internal error turned into a 404 / 422 response left no trace at all. Now:
- `setup(name)`: the root logger writes to `runs/logs/<name>.log` (rotated every 5 MB, 5 old copies kept);
- `uvicorn_config(name)`: the same for the service's (uvicorn's) own loggers, so the traceback of a 500 lands here
  too.
The log does not go into git (`runs/`); we deliberately do not log personal data (file names and ids we do).

075 (repeated security audit, S04): every handler masks the secret values of the environment and `.env` (keys,
tokens, passwords) in the message, its arguments and the whole exception chain, and `redact()` does the same for error
texts stored elsewhere (the worker's item errors). Defence in depth: the provider SDKs mask their own keys too.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from jav.config import ENV_FILE, PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / "runs" / "logs"
MAX_BYTES = 5_000_000
BACKUPS = 5
FORMAT = "%(asctime)s %(levelname)s %(name)s [%(process)d] %(message)s"
MASK = "***"
_SECRET_NAME = re.compile(r"(?i)key|token|secret|passw|pwd")  # the same rule as the data guard's `.env` reading
_SECRET_MIN_LEN = 12


@lru_cache(maxsize=1)
def _secret_pattern() -> re.Pattern[str] | None:
    """One pattern for every secret value (plain, JSON-escaped and bytes-repr forms), longest first."""
    from jav.data_guard import read_env_secrets  # deferred: the data guard is a tool module, loaded only when logging

    values = set(read_env_secrets(ENV_FILE).values())
    values |= {v for name, v in os.environ.items() if _SECRET_NAME.search(name) and len(v) >= _SECRET_MIN_LEN}
    variants = {form for v in values for form in (v, json.dumps(v)[1:-1], repr(v.encode())[2:-1]) if form}
    if not variants:
        return None
    return re.compile("|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True)))


def reset_secrets() -> None:
    """Forget the cached secret values (tests; after the environment changed)."""
    _secret_pattern.cache_clear()


def redact(text: str) -> str:
    """The text with every known secret value replaced by `***`."""
    pattern = _secret_pattern()
    return pattern.sub(MASK, text) if pattern is not None and text else text


class SecretFilter(logging.Filter):
    """Masks secrets in the formatted message and in the cached exception and stack text of a record. The record is
    changed in place, so every handler after this one sees the masked form."""

    def filter(self, record: logging.LogRecord) -> bool:
        if _secret_pattern() is None:
            return True
        record.msg, record.args = redact(record.getMessage()), None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


def log_path(name: str) -> Path:
    return LOG_DIR / f"{name}.log"


def setup(name: str, *, level: int = logging.INFO) -> Path:
    """The process's root logger also writes to `runs/logs/<name>.log` (once; a repeated call does not duplicate)."""
    path = log_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) and Path(h.baseFilename) == path for h in root.handlers):
        handler = logging.handlers.RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
        handler.setFormatter(logging.Formatter(FORMAT))
        handler.addFilter(SecretFilter())
        root.addHandler(handler)
    root.setLevel(level)
    for noisy in ("httpx", "httpx2", "httpcore"):  # per-call HTTP noise; the typesafe_sdk line keeps the request id
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return path


def uvicorn_config(name: str) -> dict[str, Any]:
    """The uvicorn logging config: its own output stays, and everything (the `jav.*` loggers too) goes to the rotating
    file."""
    from uvicorn.config import LOGGING_CONFIG

    path = log_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg: dict[str, Any] = {**LOGGING_CONFIG, "handlers": dict(LOGGING_CONFIG["handlers"]), "loggers": dict(LOGGING_CONFIG["loggers"])}
    cfg["formatters"] = {**LOGGING_CONFIG["formatters"], "file": {"format": FORMAT}}
    cfg["handlers"]["file"] = {"class": "logging.handlers.RotatingFileHandler", "filename": str(path), "maxBytes": MAX_BYTES,
                               "backupCount": BACKUPS, "encoding": "utf-8", "formatter": "file"}
    cfg["filters"] = {**LOGGING_CONFIG.get("filters", {}), "redact_secrets": {"()": SecretFilter}}
    for handler_name, handler in cfg["handlers"].items():
        cfg["handlers"][handler_name] = {**handler, "filters": [*handler.get("filters", []), "redact_secrets"]}
    cfg["loggers"]["uvicorn"] = {**cfg["loggers"]["uvicorn"], "handlers": [*cfg["loggers"]["uvicorn"].get("handlers", []), "file"]}
    cfg["root"] = {"handlers": ["file"], "level": "INFO"}
    return cfg
