"""265 (code review AI-13): a narrower option context is a parameter, the shared site is never changed.

The selection site is cached and shared (`site_for`). A request over its size budget built its Choices with a narrower
context per option by changing the site's `option_context_max` for the call and setting it back afterwards, so another
thread building a Choice at the same time could read the narrower value. The narrower context is now passed to
`build_choice`; the option texts are the same as before. Synthetic candidates, no AI call.
"""

from __future__ import annotations

from jav.ai.jev_select import site_for
from jav.ai.models import Candidate

CONTEXT = "L01: 'Invoice date: 2022-04-12, payment due: 2022-04-26'"


def _cand() -> Candidate:
    return Candidate(kind="date", label="2022-04-12", raw="2022-04-12", line_no=1, context=CONTEXT)


def test_a_narrower_context_is_used_for_the_call_and_the_site_stays_as_it_was() -> None:
    site = site_for("invoice_foreign")
    before = site.option_context_max
    narrow = site.build_choice("issue_date", [_cand()], 12)
    assert narrow.criteria["2022-04-12"] == f"printed as '2022-04-12' at {CONTEXT[:12]}"
    assert site.option_context_max == before


def test_without_a_narrower_context_the_option_text_is_the_sites() -> None:
    site = site_for("invoice_foreign")
    limit = site.option_context_max
    expected = CONTEXT if limit is None else CONTEXT[:limit]
    assert site.build_choice("issue_date", [_cand()]).criteria["2022-04-12"] == f"printed as '2022-04-12' at {expected}"
