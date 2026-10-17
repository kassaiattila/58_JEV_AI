"""167 (review AI-11): the invoice flow's own description matches its graph.

The module docstring's diagram lacked the `ground` step, and the contract's note (published in FLOW.md) claimed an
agreement gate between the S and G paths ("agreement = auto, difference = review") that the graph does not have: one
run takes one path. No model call.
"""

from __future__ import annotations

import re

from jav import flow


def test_the_docstring_diagram_names_every_step_of_the_graph():
    doc = flow.__doc__ or ""
    missing = [step for step, _phase in flow.CONTRACT["steps"] if not re.search(rf"\b{step}\b", doc)]
    assert missing == []


def test_the_note_says_one_path_per_run_and_no_agreement_gate():
    note = flow.CONTRACT["doc_note"]
    assert "exactly one of them" in note and "no agreement gate" in note
    assert "invoice_foreign" in note  # the type packs stay named (tests/test_typepack.py)


def test_the_graph_has_no_edge_between_the_two_paths():
    """The claim the note makes: no step of one path leads into a step of the other."""
    s_path = {"find_candidates", "jev_select", "normalize_picks"}
    g_path = {"extract_llm", "jev_verify", "code_verify", "normalize_llm"}
    crossing = [(a, b) for a, b, *_ in flow.TRANSITIONS if (a in s_path and b in g_path) or (a in g_path and b in s_path)]
    assert crossing == []
