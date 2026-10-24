"""The shared registries completed with the application's registrations (229, plan structure stage 1, MD1).

Plain-language summary: a few shared lists (what the logs record and people decide, the result checks, the flows the
worker runs) hold entries that the application and the domains register too. The shared code may not import the
layers above it, so the application hands over the call that makes every registration
(`jav.app.registrations.load_all`) when it is loaded, and a registry calls it the first time a full list is read. A
process that never loaded the application has no such call: reading a full list there is an error
(`RegistrationsMissing`), so a process that missed the application's registrations stops instead of running without
a check.

Layer: shared core; it imports nothing.
"""

from __future__ import annotations

from collections.abc import Callable

_completer: Callable[[], None] | None = None


class RegistrationsMissing(RuntimeError):
    """A full registry was read in a process that has not loaded the application's registrations."""


def set_completer(fn: Callable[[], None] | None) -> None:
    """The call that makes every registration of the application (None: none; a test's isolated registry)."""
    global _completer
    _completer = fn


def complete(what: str) -> None:
    """Makes every registration the application has, before a full list of `what` is read."""
    if _completer is None:
        raise RegistrationsMissing(f"the {what} are read before the application's registrations were loaded")
    _completer()


__all__ = ["RegistrationsMissing", "complete", "set_completer"]
