"""JAV - TypeSafe System One alapú alkalmazáslogika."""

from __future__ import annotations

import sys

# A projekt magyar szöveggel dolgozik, a Windows-konzol viszont cp1252-n indul,
# ami elrontja az ékezeteket. A kimenetet itt egyszer UTF-8-ra állítjuk, hogy
# minden belépési pont (script, notebook, teszt) egységesen viselkedjen.
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        try:
            _reconfigure(encoding="utf-8")
        except (OSError, ValueError):  # átirányított vagy lezárt stream
            pass

from jav.config import (  # noqa: E402  (a stream-beállítás megelőzi az importot)
    API_KEY_ENV_VARS,
    ENV_FILE,
    PROJECT_ROOT,
    MissingAPIKeyError,
    get_api_key,
    make_async_client,
    make_client,
)

__all__ = [
    "API_KEY_ENV_VARS",
    "ENV_FILE",
    "PROJECT_ROOT",
    "MissingAPIKeyError",
    "get_api_key",
    "make_async_client",
    "make_client",
]
