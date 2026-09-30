"""JAV - application logic built on TypeSafe System One."""

from __future__ import annotations

import sys

# The project works with Hungarian text, but the Windows console starts in cp1252,
# which garbles accented letters. Output is switched to UTF-8 once, here, so that
# every entry point (script, notebook, test) behaves the same way.
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        try:
            _reconfigure(encoding="utf-8")
        except (OSError, ValueError):  # redirected or closed stream
            pass

from jav.config import (  # noqa: E402  (the stream setup must precede the import)
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
