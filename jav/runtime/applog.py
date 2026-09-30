"""Üzemi napló (063): a helyi szolgáltatás és a feldolgozó állandó, forgó naplófájlja a `runs/logs/` alatt.

Eddig a hibák nyoma csak a `scripts/dev.ps1` átirányított kimenetében volt, amely minden indításkor kiürült, a
feldolgozó feladatonként semmit nem írt, a 404 / 422 válaszra fordított belső hiba pedig nyom nélkül maradt. Most:
- `setup(név)`: a gyökér-naplózó a `runs/logs/<név>.log` fájlba ír (5 MB-onként forgatva, 5 régi példány marad);
- `uvicorn_config(név)`: ugyanez a szolgáltatás (uvicorn) saját naplózóinak, hogy az 500-as hiba hibanyoma is ide kerüljön.
A napló nem kerül gitbe (`runs/`); személyes adatot nem naplózunk szándékosan (fájlnév és azonosító igen).
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
    """A folyamat gyökér-naplózója a `runs/logs/<név>.log` fájlba is írjon (egyszer; ismételt hívás nem duplikál)."""
    path = log_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) and Path(h.baseFilename) == path for h in root.handlers):
        handler = logging.handlers.RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
        handler.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(handler)
    root.setLevel(level)
    for noisy in ("httpx", "httpx2", "httpcore"):  # a hívásonkénti HTTP-sor duplikátuma (a typesafe_sdk sora a kérés-azonosítóval marad)
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return path


def uvicorn_config(name: str) -> dict[str, Any]:
    """Az uvicorn naplózási beállítása: a saját kimenete marad, és minden (a `jav.*` naplózók is) a forgó fájlba kerül."""
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
