"""The translation between the flows' typed questions and OpenAI's Decisions API (265, plan L; glossary: OpenAI
Decisions).

Plain-language summary: the flows ask JEV's three kinds of typed question (a yes/no Noul, a Choice among labelled
options, a graded Score) about a shared state. OpenAI Decisions asks the same three kinds (`predicate`, `choice`,
`score`) about a shared input, so a request is translated question by question and the answer back into JEV's answer
shape. Every call site, band and rule then reads a Decisions answer as it reads JEV's. Pure functions: nothing here
calls a provider.

What differs, and how it is bridged:
- A Noul's descriptions of its yes and no outcomes have no field of their own: they follow its instructions as text.
- A Choice option's and a Score level's description must be text: a JSON description (`what / not_for / examples`) is
  written out key by key; a Score level is labelled with its index, as JEV's levels are.
- JSON instructions (the G path's, the native reader's) go as an `input_json` part of the question; the shared state as
  an `input_json` part of the input when it fits the API's limits (256 KiB, 10 000 values, 32 levels), else as JSON
  text.
- A refused question (`refusal`) has no JEV counterpart: the request counts as unanswered (`Refused`), as a JEV failure
  does, and the flow raises its to-do.

API facts (developers.openai.com/api/reference/resources/decisions/methods/create, read 2026-11-01): 1-400 questions
per request, 2-255 unique choices, 2-10 score levels; answers in question order, each with the question's name.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from typesafe_sdk import Choice, Noul, Score, SystemOneResponse

from jav.ai.jev import InvalidJevResponse, Question

MAX_QUESTIONS = 400
CHOICES = (2, 255)
LEVELS = (2, 10)
JSON_MAX_BYTES = 256 * 1024
JSON_MAX_VALUES = 10_000
JSON_MAX_DEPTH = 32
STATE_MODES = ("json", "text")


class Unfit(ValueError):
    """A request the API's limits do not admit (too many questions, options or levels)."""


class Refused(RuntimeError):
    """The service declined to answer some questions of the request (`names`)."""

    def __init__(self, names: list[str]) -> None:
        super().__init__(f"refused: {', '.join(names)}")
        self.names = names


class DecisionsResponse(SystemOneResponse):
    """JEV's answer shape, with the prompt cache's token counts Decisions reports (its price depends on them)."""

    cached_tokens: int = 0
    cache_write_tokens: int = 0


# --- text and JSON parts --------------------------------------------------------------------------------------------

def as_text(content: Any) -> str:
    """A JEV description (text, a JSON object, a list, or None) as the text Decisions takes: an object key by key, a
    list of plain values joined, anything deeper as compact JSON."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, Mapping):
        return "\n".join(f"{key}: {_inline(value)}" for key, value in content.items())
    if isinstance(content, list):
        return _inline(content)
    return json.dumps(content, ensure_ascii=False)


def _inline(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(v, (str, int, float, bool)) for v in value):
        return "; ".join(v if isinstance(v, str) else json.dumps(v) for v in value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _values(data: Any, depth: int = 1) -> tuple[int, int]:
    """(number of JSON values, deepest container level) of `data`."""
    if isinstance(data, Mapping):
        inner = [_values(v, depth + 1) for v in data.values()]
    elif isinstance(data, list):
        inner = [_values(v, depth + 1) for v in data]
    else:
        return 1, depth - 1
    return 1 + sum(n for n, _ in inner), max([depth, *(d for _, d in inner)])


def json_fits(data: Any) -> bool:
    """Whether `data` may be an `input_json` part: an object or a list of objects within the API's limits."""
    if not (isinstance(data, Mapping) or (isinstance(data, list) and all(isinstance(x, Mapping) for x in data))):
        return False
    if len(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > JSON_MAX_BYTES:
        return False
    count, depth = _values(data)
    return count <= JSON_MAX_VALUES and depth <= JSON_MAX_DEPTH


def _json_part(data: Any) -> dict[str, Any]:
    if json_fits(data):
        return {"type": "input_json", "data": data}
    return {"type": "input_text", "text": json.dumps(data, ensure_ascii=False)}


def _instructions(instructions: Any, after: list[str]) -> str | list[dict[str, Any]]:
    """A question's instructions: text stays text; JSON goes as a JSON part; `after` (outcome descriptions) follows."""
    parts: list[dict[str, Any]] = []
    if isinstance(instructions, str):
        if instructions:
            parts.append({"type": "input_text", "text": instructions})
    elif instructions is not None:
        parts.append(_json_part(instructions))
    parts += [{"type": "input_text", "text": text} for text in after if text]
    if all(p["type"] == "input_text" for p in parts):
        return "\n\n".join(p["text"] for p in parts)
    return parts


# --- questions ------------------------------------------------------------------------------------------------------

def _predicate(name: str, q: Noul) -> dict[str, Any]:
    criteria = q.criteria or {}
    after = []
    if criteria.get("true") is not None:
        after.append("True means: " + as_text(criteria["true"]))
    if criteria.get("false") is not None:
        after.append("False means: " + as_text(criteria["false"]))
    return {"type": "predicate", "name": name, "instructions": _instructions(q.instructions, after)}


def _choice(name: str, q: Choice) -> dict[str, Any]:
    labels = list(q.criteria)
    if not CHOICES[0] <= len(labels) <= CHOICES[1]:
        raise Unfit(f"choice {name!r} has {len(labels)} options; the API takes {CHOICES[0]}-{CHOICES[1]}")
    choices = []
    for label in labels:
        option: dict[str, Any] = {"value": label}
        text = as_text(q.criteria[label])
        if text:
            option["description"] = text
        choices.append(option)
    return {"type": "choice", "name": name, "instructions": _instructions(q.instructions, []), "choices": choices}


def _score(name: str, q: Score) -> dict[str, Any]:
    levels = list(q.criteria)
    if not LEVELS[0] <= len(levels) <= LEVELS[1]:
        raise Unfit(f"score {name!r} has {len(levels)} levels; the API takes {LEVELS[0]}-{LEVELS[1]}")
    return {"type": "score", "name": name, "instructions": _instructions(q.instructions, []),
            "levels": [{"label": str(i), "description": as_text(level)} for i, level in enumerate(levels)]}


def question(name: str, q: Question) -> dict[str, Any]:
    if isinstance(q, Noul):
        return _predicate(name, q)
    if isinstance(q, Choice):
        return _choice(name, q)
    if isinstance(q, Score):
        return _score(name, q)
    raise TypeError(f"question {name!r} is not a Noul, a Choice or a Score: {type(q).__name__}")


def request(state: object, questions: Mapping[str, Question], *, model: str, state_mode: str = "json") -> dict[str, Any]:
    """The Decisions request body of a JEV request (`model`, `input`, `questions`)."""
    if not 1 <= len(questions) <= MAX_QUESTIONS:
        raise Unfit(f"{len(questions)} questions; the API takes 1-{MAX_QUESTIONS} per request")
    if state_mode not in STATE_MODES:
        raise ValueError(f"unknown state mode {state_mode!r}; expected one of {STATE_MODES}")
    if isinstance(state, str):
        part = {"type": "input_text", "text": state}
    elif state_mode == "json":
        part = _json_part(state)
    else:
        part = {"type": "input_text", "text": json.dumps(state, ensure_ascii=False)}
    return {"model": model, "input": [{"role": "user", "content": [part]}],
            "questions": [question(name, q) for name, q in questions.items()]}


# --- answers --------------------------------------------------------------------------------------------------------

_KINDS = {Noul: "predicate", Choice: "choice", Score: "score"}


def _kind(q: Question) -> str:
    return next(kind for cls, kind in _KINDS.items() if isinstance(q, cls))


def answers_by_name(decision: Mapping[str, Any], questions: Mapping[str, Question]) -> dict[str, Mapping[str, Any]]:
    """The answers keyed by question name; an unnamed one takes the name of its question's position."""
    names = list(questions)
    found: dict[str, Mapping[str, Any]] = {}
    for i, answer in enumerate(decision.get("answers") or []):
        name = answer.get("name") or (names[i] if i < len(names) else None)
        if name is None or name in found:
            raise InvalidJevResponse("an answer without a question, or two answers to one question")
        found[name] = answer
    return found


def _level(p: Mapping[str, Any]) -> str:
    """A Score probability's level: the label the request gave it (its index, `_score`), else its value."""
    label = p.get("label")
    return str(int(label if label is not None else p["value"]))


def _answer(q: Question, a: Mapping[str, Any]) -> dict[str, Any]:
    """One answer in JEV's shape. A value missing, null or of another kind raises `KeyError`, `TypeError` or
    `ValueError` (the SDK builds its answer object without validating it)."""
    if isinstance(q, Noul):
        return {"type": "noul", "noul": float(a["probability"])}
    if isinstance(q, Choice):
        return {"type": "choice", "choice": str(a["choice"]), "confidence": float(a["confidence"]),
                "probabilities": {str(p["value"]): float(p["probability"]) for p in a["probabilities"]}}
    legend = {str(i): (level if level is not None else "") for i, level in enumerate(q.criteria)}
    return {"type": "score", "score": float(a["score"]), "confidence": float(a["confidence"]), "legend": legend,
            "probabilities": {_level(p): float(p["probability"]) for p in a["probabilities"]}}


def response(decision: Mapping[str, Any], questions: Mapping[str, Question]) -> dict[str, Any]:
    """JEV's answer shape (`SystemOneResponse` as JSON, with the prompt cache's token counts) of a Decisions answer.
    `Refused` if any question was declined; `InvalidJevResponse` if an answer is missing, of another kind, or lacks a
    value of its kind (so the flow raises its to-do instead of failing the item)."""
    found = answers_by_name(decision, questions)
    refused = [name for name, a in found.items() if a.get("type") == "refusal"]
    if refused:
        raise Refused(refused)
    out: dict[str, Any] = {}
    for name, q in questions.items():
        a = found.get(name)
        if a is None or a.get("type") != _kind(q):
            raise InvalidJevResponse(f"missing or another kind of answer to {name!r}")
        try:
            out[name] = _answer(q, a)
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidJevResponse(f"the answer to {name!r} lacks a value of its kind") from exc
    usage = decision.get("usage") or {}
    details = usage.get("input_tokens_details") or {}
    return {"model": decision.get("model") or "", "answers": out,
            "usage": {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")},
            "cached_tokens": int(details.get("cached_tokens") or 0),
            "cache_write_tokens": int(details.get("cache_write_tokens") or 0)}


def to_system_one(decision: Mapping[str, Any], questions: Mapping[str, Question]) -> DecisionsResponse:
    """`response`, validated as JEV's answer type (in JSON mode, as the SDK decodes: score levels are keys)."""
    return DecisionsResponse.model_validate_json(json.dumps(response(decision, questions), ensure_ascii=False))


__all__ = ["DecisionsResponse", "Refused", "Unfit", "as_text", "json_fits", "question", "request", "response",
           "to_system_one"]
