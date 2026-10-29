"""The language a person's request is displayed in, and the service's texts in it (231, stage F, D4; the owner's decision
of 2026-10-29: downloads and file names follow the interface's language).

The service's labels (field and document type names, column captions, recipe texts) have English source texts, as the
interface's own do; the interface's Hungarian dictionary (`ui/src/i18n/hu-native.json`) gives their Hungarian, both
for the interface and for what the service makes for a person: a download, a file name, the order of a sorted column.
The language is the requesting interface's: the `jav-language` cookie the interface sets when its language changes,
which every request of the page carries, a download link too. A process without a request (the worker, the command
line) and a request without the cookie get Hungarian, the interface's default.

Layer: core. `use()` sets the language for a block (the service's middleware, for a request); `text()` gives a source
text in it, with its `{{name}}` slots filled as the interface's `t()` fills them.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import Any, Iterator

from jav.core.config import UI_ENGLISH, UI_HUNGARIAN
from jav.core.user_messages import fill

LANGUAGES = ("hu", "en")
DEFAULT = "hu"
COOKIE = "jav-language"
_language: ContextVar[str] = ContextVar("jav_display_language", default=DEFAULT)


def current() -> str:
    """The language of the request being served, Hungarian outside one."""
    return _language.get()


@contextmanager
def use(language: str | None) -> Iterator[str]:
    """Display in `language` within the block; an unknown or missing one is Hungarian."""
    chosen = language if language in LANGUAGES else DEFAULT
    token = _language.set(chosen)
    try:
        yield chosen
    finally:
        _language.reset(token)


@lru_cache(maxsize=1)
def _hungarian() -> dict[str, str]:
    return json.loads(UI_HUNGARIAN.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _english() -> dict[str, str]:
    """The interface's English for its English sources: mostly the source itself, but a named variant (a source that
    differs only to keep two Hungarian texts apart, e.g. "Issue date (field)") shows its plain English."""
    return json.loads(UI_ENGLISH.read_text(encoding="utf-8"))


def text(source: str, language: str | None = None, **params: Any) -> str:
    """`source` in `language` (by default the request's), from the interface's dictionaries (a text they do not know
    stays as it is); each `{{name}}` filled from `params`."""
    chosen = language or current()
    shown = (_english() if chosen == "en" else _hungarian()).get(source, source)
    return fill(shown, {k: str(v) for k, v in params.items()}) if params else shown
