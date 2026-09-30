"""Shared request-size budget for the JEV call sites (S-path selector and G-path verifier): a request is fitted to the
call site's `request_char_budget` (characters), and if the server still returns `max_tokens_exceeded`, we retry
ONCE with a tighter budget.

Why it is needed: the character budget is only an estimate of the token limit (Hungarian text is ~2.5 characters per
token, but this depends on the text source - Azure DI text produced more tokens from the same number of characters than
tesseract's), so the limit can be exceeded even under the budget. The second attempt runs with `RETRY_BUDGET_FACTOR`
times the budget; if that does not fit either, the exception reaches the flow (`jev_unavailable:<reason>` reviews, the
flow does not fail). Two call sites spelt out the same thing by hand (CLAUDE.md §4: that is when it becomes a framework
module). The reduction is always visible in the raw run (`JevCall.state_chars`), and the failed first call is in the
ledger too.
"""

from __future__ import annotations

from typing import Any, Callable

from jav.adapters.jev import JevAdapter, JevUnavailableError

RETRY_BUDGET_FACTOR = 0.6  # budget of the second (only) retry, as a fraction of the original
TOKEN_LIMIT_MARK = "max_tokens_exceeded"  # the server's error type in JevUnavailableError.reason

Fit = Callable[[int | None], tuple[dict[str, Any], dict[str, Any]]]
Size = Callable[[dict[str, Any], dict[str, Any]], int]


def ask_within_budget(
    jev: JevAdapter, request_id: str, fit: Fit, budget: int | None, size: Size, **ask_kw: Any
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """`fit(budget)` → (state, questions) fitted to the budget; `jev.ask(...)`; on a token error, `fit(tighter)` once,
    where the tighter budget is the smaller of the SENT request's size (`size`, the call site's own measure) and the
    budget, × 0.6 - so the second request really is smaller even under a generous budget. Returns: (the call's result,
    the state sent, the questions sent) - the answer must be read with the question set actually sent. Without a budget
    (`budget=None`) there is no retry: there is nothing to tighten."""
    state, questions = fit(budget)
    try:
        return jev.ask(request_id, state, questions, **ask_kw), state, questions
    except JevUnavailableError as exc:
        if budget is None or TOKEN_LIMIT_MARK not in (exc.reason or ""):
            raise
        tight = max(1, int(min(budget, size(state, questions)) * RETRY_BUDGET_FACTOR))
        state, questions = fit(tight)
        return jev.ask(request_id, state, questions, **ask_kw), state, questions


def line_numbers(evidence: dict[str, list[str]]) -> set[int]:
    """The 1-based line numbers of the evidence lines (`Lnn: text`)."""
    out: set[int] = set()
    for hits in evidence.values():
        for h in hits:
            if h.startswith("L") and ":" in h:
                head = h[1 : h.index(":")]
                if head.isdigit():
                    out.add(int(head))
    return out
