"""Errors a person sees, in the interface's language (167, review 160 U-1).

An exception raised for a person (a refused correction, an approval that is not ready, a workflow step that cannot
start) is built with `explained(...)`: its message is an English template with `{{name}}` slots — the same form as the
interface's own labels — and the parameters that fill it. The local service sends the template and the parameters next
to the filled message, and the interface translates the template like any of its labels (`ui/src/i18n`), so the
Hungarian interface no longer shows the service's English text. `str(exc)` stays the filled English message, for the
log, the command line and the existing callers.

Every template must be a translated interface label: an identity entry in `ui/src/i18n/en-native.json` and a
Hungarian one in `hu-native.json` (checked by `tests/test_user_messages_167.py`). A template is a single literal, so
the check can find it; the values go into the parameters, never into the template.
"""

from __future__ import annotations

import re
from typing import Any, TypeVar

E = TypeVar("E", bound=BaseException)

_SLOT = re.compile(r"\{\{(\w+)\}\}")


def fill(template: str, params: dict[str, str]) -> str:
    """The template with each `{{name}}` replaced by its parameter (the interface's `t()` does the same)."""
    return _SLOT.sub(lambda m: params[m.group(1)], template)


def explained(exc_type: type[E], template: str, /, *args: Any, **params: Any) -> E:
    """An exception of `exc_type` whose message is `template` filled with `params` (each turned into text), carrying
    `template` and `params` for the interface. Further positional arguments go to the exception after the message
    (for example the blockers of `work.NotReady`). A slot without a parameter or a parameter without a slot is a
    programming error."""
    values = {k: str(v) for k, v in params.items()}
    slots = set(_SLOT.findall(template))
    if slots - values.keys():
        raise KeyError(f"missing parameter(s) for the message template: {sorted(slots - values.keys())}")
    if values.keys() - slots:
        raise TypeError(f"parameter(s) not in the message template: {sorted(values.keys() - slots)}")
    exc = exc_type(fill(template, values), *args)
    exc.template = template  # type: ignore[attr-defined]
    exc.params = values  # type: ignore[attr-defined]
    return exc


def message_fields(exc: BaseException) -> dict[str, Any]:
    """The template and parameters of an exception built by `explained`, for the service's error response; empty for
    any other exception (the interface then shows the message as it is)."""
    template = getattr(exc, "template", None)
    if not isinstance(template, str):
        return {}
    return {"template": template, "params": dict(getattr(exc, "params", {}) or {})}
