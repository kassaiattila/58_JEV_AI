"""Operations log (063): a permanent, rotating log file of the local service and the worker under `runs/logs/`.

Until now the only trace of errors was the redirected output of `scripts/dev.ps1`, which was emptied at every start,
the worker wrote nothing per task, and an internal error turned into a 404 / 422 response left no trace at all. Now:
- `setup(name)`: the root logger writes to `runs/logs/<name>.log` (rotated every 5 MB, 5 old copies kept);
- `uvicorn_config(name)`: the same for the service's (uvicorn's) own loggers, so the traceback of a 500 lands here
  too.
The log does not go into git (`runs/`); we deliberately do not log personal data (file names and ids we do).
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Any

from jav.config import PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / "runs" / "logs"
MAX_BYTES = 5_000_000
BACKUPS = 5
FORMAT = "%(asctime)s %(levelname)s %(name)s [%(process)d] %(message)s"


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
    cfg["loggers"]["uvicorn"] = {**cfg["loggers"]["uvicorn"], "handlers": [*cfg["loggers"]["uvicorn"].get("handlers", []), "file"]}
    cfg["root"] = {"handlers": ["file"], "level": "INFO"}
    return cfg
