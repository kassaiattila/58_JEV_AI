"""Type-independent JEV source search; it yields candidates, not business facts.

It walks the whole text in overlapping windows. Besides the Choice's relative ranking,
a presence Noul and a separate check of the selected excerpt are needed. The raw answer
is kept; the experimental thresholds come from outside. No automatic data extraction.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typesafe_sdk import Choice, Noul, SystemOneResponse

from jav.adapters.jev import JevUnavailableError

PROMPTS = Path(__file__).resolve().parents[1] / "configs/experiments/source_find.json"
Ask = Callable[[str, object, dict], SystemOneResponse]


class SearchPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    present_min: float = Field(default=.8, gt=0, le=1)
    absent_max: float = Field(default=.2, ge=0, lt=1)
    window_lines: int = Field(default=128, ge=3, le=255)
    window_chars: int = Field(default=10000, ge=100, le=16000)
    max_windows: int = Field(default=12, ge=1, le=64)
    query_chars: int = Field(default=1000, ge=1, le=1000)
    support_context: Literal["excerpt", "window"] = "excerpt"

    @model_validator(mode="after")
    def ordered_thresholds(self):
        if self.absent_max >= self.present_min:
            raise ValueError("absent_max must be below present_min")
        return self


class SourceCandidate(BaseModel):
    line_ids: list[str]
    selected_line: str
    start: int
    end: int
    quote: str
    window: int
    presence: float
    support: float
    relevance: dict[str, float]


class SearchResult(BaseModel):
    source_sha256: str
    query: str
    config_sha256: str
    status: Literal["candidate", "absent", "uncertain", "unreadable", "incomplete"]
    coverage_complete: bool
    windows_total: int
    windows_completed: int
    candidates: list[SourceCandidate] = Field(default_factory=list)
    decisions: list[dict] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)


def _lines(text: str) -> list[dict]:
    lines, offset = [], 0
    for index, raw in enumerate(text.splitlines(keepends=True)):
        content = raw.rstrip("\r\n")
        if content.strip():
            lines.append(dict(id=f"L{index:06d}", text=content, start=offset, end=offset + len(content)))
        offset += len(raw)
    return lines


def _windows(lines: list[dict], policy: SearchPolicy) -> list[list[dict]]:
    windows, start = [], 0
    while start < len(lines):
        window, size, end = [], 0, start
        while end < len(lines) and len(window) < policy.window_lines:
            line = lines[end]
            cost = len(line["text"]) + len(line["id"]) + 3
            if cost > policy.window_chars:
                raise ValueError("source line exceeds window_chars; split explicitly before searching")
            span_size = line["end"] - lines[start]["start"]
            if max(size + cost, span_size) > policy.window_chars:
                break
            window.append(line)
            size += cost
            end += 1
        windows.append(window)
        if len(windows) > policy.max_windows:
            raise ValueError("source exceeds max_windows; no requests were sent")
        # One line of overlap; guaranteed progress on a single very long line.
        start = end if end == len(lines) else max(start + 1, end - 1)
    return windows


def find_source(text: str, query: str, ask: Ask, policy: SearchPolicy,
                *, prompts: dict | None = None) -> SearchResult:
    """At most one source candidate per window for the query, with the original character offsets.

    A candidate is only the result of the source search. The exists/support value is not
    document correctness and not a calibrated probability for automatic acceptance.
    Exceeding a limit raises an error before any call; a service error gives a partial result.
    """
    if not query.strip() or len(query) > policy.query_chars:
        raise ValueError("query must be nonempty and within query_chars")
    prompts = prompts if prompts is not None else json.loads(PROMPTS.read_text(encoding="utf-8"))
    rules = {key: prompts[key] for key in ("where", "exists", "supports")}
    windows = _windows(_lines(text), policy)
    signature = json.dumps({"rules": rules, "policy": policy.model_dump()}, sort_keys=True, ensure_ascii=False)
    result = SearchResult(source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(), query=query,
                          config_sha256=hashlib.sha256(signature.encode("utf-8")).hexdigest(),
                          status="unreadable", coverage_complete=False, windows_total=len(windows), windows_completed=0)
    if not windows:
        return result
    uncertain = False
    for index, window in enumerate(windows):
        state = {"query": query, "source_lines": {row["id"]: row["text"] for row in window}}
        questions = {"where": Choice(instructions=rules["where"], criteria={row["id"]: row["text"] for row in window}),
                     "exists": Noul(instructions=rules["exists"])}
        try:
            response = ask(f"source_find_{index}", state, questions)
            result.decisions.append(dict(window=index, stage="search", response=response.model_dump(mode="json")))
            presence = response.nouls["exists"].noul
            if presence >= policy.present_min:
                selected = response.choices["where"].choice
                position = next(i for i, row in enumerate(window) if row["id"] == selected)
                neighbors = window[max(0, position - 1):position + 2]
                start, end = neighbors[0]["start"], neighbors[-1]["end"]
                quote = text[start:end]
                support_state = {"query": query, "source_excerpt": quote}
                context_start, context_end = start, end
                if policy.support_context == "window":
                    context_start, context_end = window[0]["start"], window[-1]["end"]
                    support_state["source_context"] = text[context_start:context_end]
                checked = ask(f"source_support_{index}", support_state,
                              {"supports": Noul(instructions=rules["supports"])})
                result.decisions.append(dict(window=index, stage="support", context_start=context_start,
                                             context_end=context_end, response=checked.model_dump(mode="json")))
                support = checked.nouls["supports"].noul
                if support >= policy.present_min:
                    candidate = SourceCandidate(line_ids=[row["id"] for row in neighbors], selected_line=selected,
                                                start=start, end=end, quote=quote, window=index,
                                                presence=presence, support=support,
                                                relevance=response.choices["where"].probabilities)
                    if not any(c.start == start and c.end == end for c in result.candidates):
                        result.candidates.append(candidate)
                else:
                    uncertain = True
            elif presence > policy.absent_max:
                uncertain = True
            result.windows_completed += 1
        except JevUnavailableError as exc:
            result.errors.append(dict(window=index, reason=exc.reason))
            break  # after a service error no further budget is spent
    result.coverage_complete = result.windows_completed == result.windows_total
    result.status = ("incomplete" if not result.coverage_complete else "candidate" if result.candidates
                     else "uncertain" if uncertain else "absent")
    return result
