"""A forráskereső publikus szerződése, hálózat nélkül."""
from types import SimpleNamespace

import pytest

from jav.adapters.jev import JevUnavailableError
from jav.source_find import SearchPolicy, find_source


def reply(line="L000001", present=.98):
    return SimpleNamespace(
        choices={"where": SimpleNamespace(choice=line, probabilities={line: 1.0})},
        nouls={"exists": SimpleNamespace(noul=present), "supports": SimpleNamespace(noul=present)},
        model_dump=lambda **kw: {"model": "fake", "line": line, "present": present},
    )


def test_present_invoice_retains_exact_source_and_raw_decisions():
    calls = []
    text = "Teszt számla\nFizetendő: 12000 HUF\n"

    def ask(step, state, questions):
        calls.append((step, state, questions))
        return reply()

    result = find_source(text, "What is the payable amount?", ask, SearchPolicy())
    assert result.status == "candidate"
    assert result.coverage_complete
    assert result.candidates[0].line_ids == ["L000000", "L000001"]
    assert result.candidates[0].quote == text.rstrip("\n")
    assert text[result.candidates[0].start:result.candidates[0].end] == result.candidates[0].quote
    assert len(calls) == 2
    assert result.decisions[0]["response"]["present"] == .98


def test_absence_is_not_overridden_by_a_confident_choice():
    calls = []

    def ask(*args):
        calls.append(args)
        return reply("L000000", .01)

    result = find_source("Meeting location: Budapest", "What is the bank account?", ask, SearchPolicy())
    assert result.status == "absent"
    assert not result.candidates
    assert len(calls) == 1


def test_noninvoice_answer_after_255_lines_is_reached_without_truncation():
    text = "\n".join([f"Archive entry {i}" for i in range(260)] + ["Meeting chair: Example Person"])
    seen = set()

    def ask(step, state, questions):
        if "source_excerpt" in state:
            return reply()
        seen.update(state["source_lines"])
        selected = next((key for key, value in state["source_lines"].items() if "Meeting chair" in value), None)
        return reply(selected or next(iter(state["source_lines"])), .99 if selected else .01)

    result = find_source(text, "Who chairs the meeting?", ask, SearchPolicy())
    assert result.status == "candidate" and result.coverage_complete
    assert len(seen) == 261
    assert result.candidates[0].selected_line == "L000260"
    assert result.candidates[0].quote.endswith("Meeting chair: Example Person")


@pytest.mark.parametrize("presence,support", [(.5, .99), (.99, .01), (.99, .5)])
def test_partial_answer_or_unsupported_selection_stays_uncertain(presence, support):
    def ask(step, *args):
        return reply("L000000", support if "support" in step else presence)

    result = find_source("Age requirement: at least 18", "Are minors allowed with permission?", ask, SearchPolicy())
    assert result.status == "uncertain" and not result.candidates


@pytest.mark.parametrize("text,query,policy", [
    ("x" * 10001, "query", SearchPolicy()),
    ("\n".join(["a"] * 20), "query", SearchPolicy(window_lines=3, max_windows=2)),
    ("text", "q" * 1001, SearchPolicy()),
])
def test_bounds_fail_before_any_external_request(text, query, policy):
    def forbidden(*args):
        pytest.fail("The preflight limit must reject before calling the model")

    with pytest.raises(ValueError):
        find_source(text, query, forbidden, policy)


def test_provider_failure_cannot_be_reported_as_absent_or_complete():
    def ask(step, *args):
        if step == "source_find_1":
            raise JevUnavailableError("timeout")
        return reply("L000000", .01)

    result = find_source("a\nb\nc\nd", "query", ask, SearchPolicy(window_lines=3))
    assert result.status == "incomplete" and not result.coverage_complete
    assert result.windows_completed == 1 and result.windows_total == 2
    assert result.errors == [{"window": 1, "reason": "timeout"}]
    assert len(result.decisions) == 1


def test_blank_text_is_unreadable_not_evidence_of_absence():
    def forbidden(*args):
        pytest.fail("Blank source needs no model")

    result = find_source("\r\n  \n", "query", forbidden, SearchPolicy())
    assert result.status == "unreadable" and not result.coverage_complete


def test_long_blank_gaps_do_not_bypass_request_bounds():
    text = "First fact\n" + "\n" * 200 + "Second fact"

    def ask(step, state, questions):
        if "source_excerpt" in state:
            assert len(state["source_excerpt"]) <= 100
        return reply(next(iter(state.get("source_lines", {"L000000": ""}))))

    result = find_source(text, "query", ask, SearchPolicy(window_chars=100))
    assert result.coverage_complete
    assert len(result.candidates) == 2


def test_window_context_preserves_short_exact_quote_and_context_offsets():
    text = "Amounts include VAT\nItem A\nItem B\nTotal\n120 EUR\nEnd"
    calls = []
    def ask(step, state, questions):
        calls.append(state)
        return reply("L000004")
    result = find_source(text, "Gross total?", ask, SearchPolicy(support_context="window"))
    assert result.status == "candidate"
    evidence = result.candidates[0]
    assert evidence.quote == "Total\n120 EUR\nEnd"
    assert calls[1]["source_excerpt"] == evidence.quote
    assert calls[1]["source_context"] == text
    decision = result.decisions[1]
    assert text[decision["context_start"]:decision["context_end"]] == calls[1]["source_context"]
    assert len(calls[1]["source_context"]) <= SearchPolicy().window_chars


def test_legacy_support_stays_excerpt_only_and_context_cannot_bypass_absence():
    calls = []
    def ask(step, state, questions):
        calls.append(state)
        return reply("L000000")
    find_source("Fact", "query", ask, SearchPolicy())
    assert "source_context" not in calls[1]
    calls.clear()
    def absent(step, state, questions):
        calls.append(state)
        return reply("L000000", .1)
    result = find_source("Fact", "query", absent, SearchPolicy(support_context="window"))
    assert result.status == "absent" and len(calls) == 1
