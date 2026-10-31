"""265 (code review APPW-03): the facts are frozen only with every disagreement settled.

"Settle the disagreements first" lived only in the freeze form's start values: the freeze itself checked the units'
state, so a disagreement placed after the page was loaded (a retried step offering another value) was frozen unseen,
and a form sent anyway went through. Now the freeze counts the open disagreements in its own write transaction, and
the shared form refuses an action whose start says it cannot be sent. Invented data; no paid call.
"""

from __future__ import annotations

import pytest

from jav.app import case_views, field_check
from tests.test_field_check_231 import ANNA, case  # noqa: F401 - the shared fixture


def test_a_freeze_with_an_open_disagreement_is_refused(case) -> None:  # noqa: F811
    view = field_check.view(case, "check")
    assert any(c["open"] for c in view["claims"])
    with pytest.raises(field_check.FieldCheckError, match="disagreement"):
        field_check.freeze(case, "check", cover_start="2027-01-01", expected_state=view["state"], actor=ANNA)
    [claim] = [c for c in view["claims"] if c["open"]]
    field_check.keep(case, "check", claim["claim_key"], actor=ANNA)
    assert field_check.freeze(case, "check", cover_start="2027-01-01", expected_state=view["state"], actor=ANNA)


def test_the_shared_form_refuses_an_action_its_start_blocks(case) -> None:  # noqa: F811
    view = field_check.view(case, "check")
    with pytest.raises(case_views.CaseError, match="Settle the disagreements first"):
        case_views.act(case, "check", "freeze", ANNA, values={"cover_start": "2027-01-01", "expected_state": view["state"]})
