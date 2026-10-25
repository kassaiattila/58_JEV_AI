"""231 (plan stage C, C2d): three general fixes of a process case's page, made for the pairing case.

- The next step of a special element shown on several tabs (each with its own `show`) opens on the tab that shows it.
- A step whose capability waits for a person's decisions says so (`by_person`), so its page stops asking again by
  itself while it waits.
- Reopening the case's approved own version reopens the step that was done with it (a capability's `own_version`),
  and a case closed as done opens again: until now only a workflow's step was reopened (the quote had the same gap).
"""

from __future__ import annotations

import json

from jav.app import case_views, process_runtime
from jav.core.process import engine
from jav.domains.quotes import quote_draft
from tests import test_document_result_174 as rows
from tests.test_quote_case_231 import _drive, out  # noqa: F401 - the fixture
from tests.test_quote_path_231 import ACTOR, FIXTURE, golden  # noqa: F401 - the fixture


def _tab(tab_id: str, *elements: dict) -> dict:
    return {"id": tab_id, "elements": [{"step": None, "data": None, **e} for e in elements]}


def test_the_next_step_opens_on_the_tab_that_shows_it():
    nxt = {"element": "pairing", "show": "decide", "code": "reconcile_pair", "params": {}}
    tabs = [_tab("invoices", {"type": "pairing", "show": "invoices", "step": "pair", "data": {"next": nxt}}),
            _tab("pairing", {"type": "pairing", "show": "decide", "step": "pair"}),
            _tab("history", {"type": "timeline"})]
    assert case_views._next(tabs, ["pair"]) == {"code": "reconcile_pair", "params": {}, "tab": "pairing"}
    without_show = {k: v for k, v in nxt.items() if k != "show"}
    tabs[0]["elements"][0]["data"] = {"next": without_show}
    assert case_views._next(tabs, ["pair"])["tab"] == "invoices"  # the first tab of the element, as before


def test_a_closed_quote_reopened_opens_its_compose_step_again(golden, out):  # noqa: F811 - the shared fixtures
    cases, _seen = golden
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    case = next(c for c in cases if "letter" in recorded.get(c.id, {}))  # one that closes on the package's path
    case_id = process_runtime.start_case("it_quote", {"record": {"workpackage_id": rows.WP, "item_id": rows._id(case.id)}},
                                         name=f"Quote {case.id}", actor=ACTOR)
    state, _letter = _drive(case_id)
    assert state["status"] == "closed" and state["steps"]["compose"]["state"] == "done"
    page = case_views.view(case_id)
    assert page["steps"]["compose"]["by_person"] is True and page["steps"]["match"]["by_person"] is False
    quote_draft.reopen(case_id, note="a price changed", actor=ACTOR)
    state = engine.state(case_id)
    assert state["status"] == "open" and state["steps"]["compose"]["state"] == "running"
    assert state["steps"]["match"]["state"] == "done"  # the step before it stays done
