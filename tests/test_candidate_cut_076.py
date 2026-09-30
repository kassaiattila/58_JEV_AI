"""A cut candidate list is counted, and "none" on a cut list is its own to-do (076).

The repeated audit's acceptance condition: the candidates of a field are counted (found / sent / skipped), and when the
list JEV saw was cut (the cap of 250 options, or the request size budget) and JEV answered "none", the right value may
have been among the skipped ones, so a person has to look. Offline, with a fake client; the values are made up.
"""

from __future__ import annotations

from pathlib import Path

from jav import policy, store
from jav.adapters.jev import JevAdapter
from jav.candidates import MAX_OPTIONS, Candidate
from jav.jev_select import select_fields
from jav.models import FieldPick, FlowState
from tests.test_select_presence import LINES, FakeClient, _cands


def _many_dates(n: int) -> list[Candidate]:
    return [Candidate(kind="date", label=f"20{10 + i // 300:02d}-{1 + i // 28 % 12:02d}-{1 + i % 28:02d}",
                      raw=f"d{i}", line_no=3, context="L03") for i in range(n)]


def test_found_and_sent_candidates_are_counted_and_the_cut_is_visible(tmp_path: Path):
    cands = {**_cands(), "date": _many_dates(MAX_OPTIONS + 12)}
    client = FakeClient(pick_none={"issue_date"})
    jev = JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")
    with store.use_store(tmp_path / "t.sqlite"):
        picks, _ = select_fields(jev, LINES, cands, run_id="r")

    p = picks["issue_date"]
    assert p.n_candidates == MAX_OPTIONS + 12
    assert p.n_options <= MAX_OPTIONS and p.truncated  # the cap, or the size budget cut it further
    sent = next(r for r in client.requests if "issue_date" in r["questions"])["questions"]["issue_date"]
    assert len(sent.criteria) - 1 == p.n_options  # what was counted as sent is what JEV got (+ none)
    small = picks["supplier_tax_id"]
    assert (small.n_candidates, small.n_options, small.truncated) == (2, 2, False)


def _state(**picks: FieldPick) -> FlowState:
    return FlowState(source_path="x.pdf", case_id="c", arm="S", picks=picks)


def test_none_on_a_cut_list_opens_its_own_to_do():
    st = _state(invoice_number=FieldPick(field="invoice_number", label=None, confidence=0.8, n_options=250,
                                         n_candidates=312, request_id="header"))
    policy.apply_pick_policy(st)
    assert "pick:none_on_cut_list:invoice_number:250/312" in st.review_reasons
    assert "pick:none:invoice_number" in st.review_reasons  # the required-field reason stays next to it


def test_a_value_chosen_from_a_cut_list_or_none_on_a_whole_list_adds_no_cut_reason():
    st = _state(
        invoice_number=FieldPick(field="invoice_number", label="A-1", confidence=0.99,
                                 probabilities={"A-1": 0.99, "none": 0.01}, n_options=250, n_candidates=312,
                                 request_id="header"),
        due_date=FieldPick(field="due_date", label=None, confidence=0.95, n_options=3, n_candidates=3, request_id="header"),
        issue_date=FieldPick(field="issue_date", label=None, confidence=0.95, n_options=3, request_id="header"),  # old state
    )
    policy.apply_pick_policy(st)
    assert not [r for r in st.review_reasons if r.startswith("pick:none_on_cut_list")]
