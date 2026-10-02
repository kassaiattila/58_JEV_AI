"""Per-field token probabilities of a structured GPT answer (091: GPT field confidence, the owner's decision of
2026-10-02: token probability and code evidence, the weaker counts).

The extraction answers with one JSON object (native structured output). With the provider's token log-probabilities,
each top-level value is measured on the tokens that print it, from its opening quote to its closing quote (for a
string; the token with the opening quote is where text is chosen over null). Three measures are kept, so the paid
measurement can choose among them without a new call:

- `joint`: the product of the value's token probabilities, the probability of exactly this value;
- `min`: the weakest token;
- `first`: the first token (for a string, the choice of text over null).

This is the model's own distribution, not a calibrated probability like JEV's; how it combines with the code's
evidence, and its band, live in `configs/policy.json`. Nested values (the line-item lists) are not measured here.
"""

from __future__ import annotations

import math
from typing import Any

_WS = " \t\r\n"


def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i] in _WS:
        i += 1
    return i


def _string_end(text: str, i: int) -> int | None:
    """The index after the closing quote of the string opening at `i`; None if it is cut."""
    j = i + 1
    while j < len(text):
        if text[j] == "\\":
            j += 2
        elif text[j] == '"':
            return j + 1
        else:
            j += 1
    return None


def _composite_end(text: str, i: int) -> int | None:
    """The index after the bracket closing the object or list opening at `i`; None if it is cut."""
    depth, j = 0, i
    while j < len(text):
        c = text[j]
        if c == '"':
            end = _string_end(text, j)
            if end is None:
                return None
            j = end
            continue
        if c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return None


def value_spans(text: str) -> dict[str, tuple[int, int]]:
    """`{key: (start, end)}` of the top-level string and literal values of a JSON object (a string with its quotes).
    Lists and objects are skipped; a value cut off at the end is left out. A malformed answer gives what was read."""
    spans: dict[str, tuple[int, int]] = {}
    i = _skip_ws(text, 0)
    if i >= len(text) or text[i] != "{":
        return spans
    i += 1
    while True:
        i = _skip_ws(text, i)
        if i >= len(text) or text[i] != '"':
            return spans
        key_end = _string_end(text, i)
        if key_end is None:
            return spans
        key = text[i + 1:key_end - 1]
        i = _skip_ws(text, key_end)
        if i >= len(text) or text[i] != ":":
            return spans
        i = _skip_ws(text, i + 1)
        if i >= len(text):
            return spans
        if text[i] == '"':
            end = _string_end(text, i)
            if end is None:
                return spans
            spans[key] = (i, end)
        elif text[i] in "{[":
            end = _composite_end(text, i)
            if end is None:
                return spans
        else:
            end = i
            while end < len(text) and text[end] not in ",}" + _WS:
                end += 1
            if end >= len(text):  # a literal is complete only once something follows it
                return spans
            spans[key] = (i, end)
        i = _skip_ws(text, end)
        if i >= len(text) or text[i] != ",":
            return spans
        i += 1


def field_probabilities(tokens: list[dict[str, Any]] | None, fields: list[str] | None = None) -> dict[str, dict[str, float | int]]:
    """`{field: {"joint", "min", "first", "n"}}` for the top-level values of the answer the tokens print (`fields`:
    only these). Without tokens: {} (not measurable, never invented)."""
    if not tokens:
        return {}
    text, starts = "", []
    for t in tokens:
        starts.append(len(text))
        text += t.get("token") or ""
    out: dict[str, dict[str, float | int]] = {}
    for field, (start, end) in value_spans(text).items():
        if fields is not None and field not in fields:
            continue
        lps = [float(t.get("logprob") or 0.0) for t, s in zip(tokens, starts, strict=True)
               if s < end and s + len(t.get("token") or "") > start]
        if not lps:
            continue
        out[field] = {"joint": round(math.exp(sum(lps)), 4), "min": round(math.exp(min(lps)), 4),
                      "first": round(math.exp(lps[0]), 4), "n": len(lps)}
    return out


__all__ = ["field_probabilities", "value_spans"]
