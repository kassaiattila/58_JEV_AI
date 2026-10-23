"""160 (review AI-2): a candidate list the finder itself cut counts as cut.

076 made "none" on a cut list its own to-do, counting the distinct candidates code found against the options JEV got.
But the money finder already cuts its list (100 amounts on the number-heavy utility bills, 250 elsewhere) and the
quantity finder at 80, so the count started from the cut list: 131 amounts on a utility bill counted as 100 found,
100 sent, nothing cut, and a "none" there opened no to-do although the right amount may have been among the 31 left
out. The count now starts before the finder's cut; the list sent to JEV is unchanged, so no cache key moves. Fake
client, made-up amounts.
"""

from __future__ import annotations

from pathlib import Path

from jav import policy
from jav.core import store
from jav.adapters.jev import JevAdapter
from jav.candidates import find_all
from jav.jev_select import select_fields
from jav.models import FlowState, LineLayout
from jav.typepack import get as get_pack
from tests.test_select_presence import FakeClient

PACK = get_pack("villamos_energia_szamla")


def _lines(n: int) -> list[LineLayout]:
    return [LineLayout(no=i + 1, page=1, text=f"Dij {1000 + i * 3},00 Ft") for i in range(n)]


def _picks(tmp_path: Path, lines: list[LineLayout]):
    client = FakeClient(pick_none={"gross_total"})
    jev = JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")
    cands = find_all(lines, PACK.candidate_profile, text_labels=PACK.text_labels)
    with store.use_store(tmp_path / "t.sqlite"):
        picks, _ = select_fields(jev, lines, cands, run_id="r", pack=PACK)
    return picks, client


def test_the_money_finders_own_cut_is_counted(tmp_path):
    picks, client = _picks(tmp_path, _lines(131))
    gross = picks["gross_total"]
    assert gross.n_options == 100 and gross.n_candidates == 131 and gross.truncated
    sent = next(r for r in client.requests if "gross_total" in r["questions"])["questions"]["gross_total"]
    assert len(sent.criteria) - 1 == 100  # JEV still gets the same 100 amounts
    state = FlowState(source_path="x.pdf", case_id="c", arm="S", doc_type=PACK.key, picks=picks)
    policy.apply_pick_policy(state)
    assert "pick:none_on_cut_list:gross_total:100/131" in state.review_reasons


def test_a_list_under_the_cap_is_not_cut(tmp_path):
    picks, _ = _picks(tmp_path, _lines(40))
    gross = picks["gross_total"]
    assert gross.n_candidates == gross.n_options == 40 and not gross.truncated
