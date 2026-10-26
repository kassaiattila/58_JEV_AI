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

231 (stage D, D-c6): a sentence a person reads that is not an error - a problem a check lists - is built with
`said(...)` the same way (`Said`: a `str` with its template and parameters), with where it applies (`within`, another
`Said`, shown before it: "rule x@1: row 2: ..."); `said_fields` gives the service's form of it.
"""

from __future__ import annotations

import re
from typing import Any, TypeVar

E = TypeVar("E", bound=BaseException)

_SLOT = re.compile(r"\{\{(\w+)\}\}")


def fill(template: str, params: dict[str, str]) -> str:
    """The template with each `{{name}}` replaced by its parameter (the interface's `t()` does the same)."""
    return _SLOT.sub(lambda m: params[m.group(1)], template)


def _values(template: str, params: dict[str, Any]) -> dict[str, str]:
    """The parameters as text; a slot without a parameter or a parameter without a slot is a programming error."""
    values = {k: str(v) for k, v in params.items()}
    slots = set(_SLOT.findall(template))
    if slots - values.keys():
        raise KeyError(f"missing parameter(s) for the message template: {sorted(slots - values.keys())}")
    if values.keys() - slots:
        raise TypeError(f"parameter(s) not in the message template: {sorted(values.keys() - slots)}")
    return values


def explained(exc_type: type[E], template: str, /, *args: Any, **params: Any) -> E:
    """An exception of `exc_type` whose message is `template` filled with `params` (each turned into text), carrying
    `template` and `params` for the interface. Further positional arguments go to the exception after the message
    (for example the blockers of `work.NotReady`). A slot without a parameter or a parameter without a slot is a
    programming error."""
    values = _values(template, params)
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


class Said(str):
    """231 (stage D, D-c6): a sentence a person reads (a problem a check lists): the filled English text, a `str` as
    such problems were before, with its template and parameters for the interface's language and where it applies
    (`within`, shown before it)."""

    template: str
    params: dict[str, str]
    within: Said | None


def _said(template: str, values: dict[str, str], within: Said | None) -> Said:
    text = fill(template, values)
    out = Said(f"{within}: {text}" if within is not None else text)
    out.template, out.params, out.within = template, values, within
    return out


def said(template: str, /, *, within: Said | None = None, **params: Any) -> Said:
    """The sentence `template` filled with `params`, said within `within` (a literal template, as `explained`'s)."""
    return _said(template, _values(template, params), within)


def inside(outer: Said, inner: Said) -> Said:
    """`inner` said within `outer` too (the outermost first)."""
    return _said(inner.template, inner.params, inside(outer, inner.within) if inner.within is not None else outer)


def said_from(exc: BaseException, *, within: Said | None = None) -> Said:
    """An error as a sentence a person reads: one built by `explained` keeps its template; another its text."""
    template = getattr(exc, "template", None)
    if isinstance(template, str):
        return _said(template, dict(getattr(exc, "params", {}) or {}), within)
    return _said(str(exc).replace("{{", "{ {"), {}, within)


def said_fields(text: str) -> dict[str, Any]:
    """A sentence in the service's form: its text, and for a `Said` its template, parameters and where it applies."""
    if not isinstance(text, Said):
        return {"text": str(text)}
    return {"text": str(text), "template": text.template, "params": dict(text.params),
            "within": said_fields(text.within) if text.within is not None else None}
