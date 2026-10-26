"""192 (plan F-quote-package B5, DECISIONS 191, 192): the quote a person composes from its proposal, and its approval.

The owner asked for a page where the request and its data can be seen and the quote changed on their basis. The draft
starts from the proposal (or from the requested items alone); every change is saved at once, priced by code and
recorded in the decision journal, and a change sent from a stale page is refused. A line outside the price list, or a
price or discount of a person's own, needs a note; a line the proposal marked "to check" holds the approval until a
person confirms or changes its item (the owner's choice, DECISIONS 192). The approval is a version of the package's
own; reopening it needs a reason. Synthetic emails, a stand-in JEV and match; no paid call.
"""

from __future__ import annotations

import copy

import pytest

from jav.app import package_release, work
from jav.core import decisions, store
from jav.domains.quotes import price_lists, quote_draft, invented_golden, quote_proposal
from jav.runtime import worker
from tests import test_email_text_follow_up_190 as follow
from tests.test_email_text_follow_up_190 import OUT, _package, _run
from tests.test_quote_package_191 import _case, _next

env = follow.env  # the 190 fixture: a mailbox package of one quote request email, a stand-in JEV and GPT

ITEMS = [{"description": "24 colos monitor", "quantity": 3, "unit": "db"},
         {"description": "laptop", "quantity": 2, "unit": "db"},
         {"description": "irodai kavefozo", "quantity": 1, "unit": "db"}]
ANSWERS = {"24 colos monitor": {"mark": "sure", "sku": "HW-MON-24", "candidates": ["HW-MON-24"]},
           "laptop": {"mark": "check", "sku": "HW-NB-15B", "candidates": ["HW-NB-15B", "HW-NB-14P"]},
           "irodai kavefozo": {"mark": "not_listed", "sku": None, "candidates": []}}


def _answer(requested, _context, _prices, *, engine, run_id, **_kw):
    return {**ANSWERS[requested["description"]], "engine": engine, "method": "jev"}


@pytest.fixture()
def quote(env, tmp_path, monkeypatch):
    monkeypatch.setitem(OUT, "requested_items", copy.deepcopy(ITEMS))
    monkeypatch.setattr(quote_proposal.quote_match, "match", _answer)
    source = _package(env)
    _run_id, item = _run(source)
    made = price_lists.add("Invented 2026", "p.xlsx", invented_golden.write_price_list(tmp_path / "p.xlsx").read_bytes(),
                           actor="anna")
    price_lists.activate(made["price_list"], 1, actor="anna")
    wp_id = _case(source, item["item_id"], "Office")  # 231 (A3d): the quote of a case of the IT quote's process pack
    return {"wp": wp_id, "price_list": made["price_list"]}


def _proposed(wp_id: str) -> None:
    quote_proposal.request(wp_id, actor="anna")
    worker.run_worker(once=True)
    assert quote_proposal.current(wp_id)["state"] == "done"


def _sent(view: dict, lines: list[dict] | None = None, **changes) -> dict:
    """The draft as the page sends it back: its editable parts."""
    draft = view["draft"]
    out = {"price_list": draft["price_list"], "version": draft["version"], "header": dict(draft["header"]),
           "lines": [{k: line.get(k) for k in quote_draft.EDITABLE} for line in (lines or draft["lines"])]}
    return {**out, **changes}


def _done(wp_id: str) -> dict:
    """The proposal's draft with every line resolved: the laptop confirmed, the coffee machine a line of its own."""
    _proposed(wp_id)
    v = quote_draft.start(wp_id, source="proposal", actor="anna", expected_state=0)
    lines = copy.deepcopy(v["draft"]["lines"])
    lines[1]["checked"] = True
    lines[2].update(description="Irodai kavefozo (sajat beszerzes)", unit="db", unit_price="45 000",
                    note="Not in the price list: purchase price plus 10 percent")
    return quote_draft.save(wp_id, _sent(v, lines), actor="bela", expected_state=v["state"])


def test_the_draft_starts_from_the_proposal_line_by_line(quote):
    wp_id = quote["wp"]
    _proposed(wp_id)
    v = quote_draft.start(wp_id, source="proposal", actor="anna", expected_state=0)
    lines = v["draft"]["lines"]
    assert [(ln["row"], ln["sku"], ln["mark"], ln["quantity"]) for ln in lines] == [
        (0, "HW-MON-24", "sure", "3"), (1, "HW-NB-15B", "check", "2"), (2, None, "not_listed", "1")]
    assert lines[1]["candidates"] == ["HW-NB-15B", "HW-NB-14P"] and lines[2]["description"] == "irodai kavefozo"
    assert v["draft"]["header"]["customer_name"] == "Minta Szolgaltato Kft."
    assert v["draft"]["header"]["deadline"] == "2026-11-20"
    assert sorted((b["code"], b["row"]) for b in v["blockers"]) == [("quote:line_no_item", 2), ("quote:line_unchecked", 1)]
    priced = [ln["priced"] for ln in v["lines"]]
    assert priced[0]["net"] == "164700" and priced[1]["net"] == "758000" and priced[2] is None  # 3 x 54 900, 2 x 379 000
    assert v["totals"] is None  # not every line is priced yet
    # D0-b: the draft's decisions are its case's composition step's
    assert v["state"] > 0 and [h["action"] for h in decisions.history(quote_draft.KIND, f"{wp_id}:compose")] == ["start"]
    assert _next(wp_id)["code"] == "quote_compose"


def test_the_draft_can_start_from_the_requested_items_alone(quote):
    v = quote_draft.start(quote["wp"], source="request", actor="anna", expected_state=0)
    assert [(ln["sku"], ln["mark"], ln["description"]) for ln in v["draft"]["lines"]] == [
        (None, None, "24 colos monitor"), (None, None, "laptop"), (None, None, "irodai kavefozo")]
    assert [b["code"] for b in v["blockers"]] == ["quote:line_no_item"] * 3
    with pytest.raises(quote_draft.QuoteDraftError, match="no proposal"):  # none was asked
        quote_draft.start(quote["wp"], source="proposal", actor="anna", expected_state=v["state"], replace=True)
    with pytest.raises(quote_draft.QuoteDraftError, match="already has a draft"):
        quote_draft.start(quote["wp"], source="request", actor="anna", expected_state=v["state"])


def test_a_person_confirms_or_changes_a_line_to_check_and_gives_a_note_for_a_price_of_their_own(quote):
    wp_id = quote["wp"]
    _proposed(wp_id)
    v = quote_draft.start(wp_id, source="proposal", actor="anna", expected_state=0)
    lines = copy.deepcopy(v["draft"]["lines"])
    lines[1]["sku"] = "HW-NB-14P"  # a person's choice of the item counts as checked
    lines[2].update(description="Irodai kavefozo", unit="db", unit_price="45 000")
    v2 = quote_draft.save(wp_id, _sent(v, lines), actor="bela", expected_state=v["state"])
    assert v2["draft"]["lines"][1]["checked_by"] == "bela"
    assert [(b["code"], b["row"]) for b in v2["blockers"]] == [("quote:line_note_missing", 2)]
    assert v2["lines"][2]["priced"]["manual_price"] is True and v2["lines"][2]["priced"]["unit_price"] == "45000"
    lines = copy.deepcopy(v2["draft"]["lines"])
    lines[1]["sku"] = "HW-NB-15B"
    lines[2]["note"] = "Not in the price list"
    lines[0]["unit_price"] = "50 000"  # under the list's 54 900: a price of a person's own, so a note too
    v3 = quote_draft.save(wp_id, _sent(v2, lines), actor="bela", expected_state=v2["state"])
    assert [(b["code"], b["row"]) for b in v3["blockers"]] == [("quote:line_note_missing", 0)]
    lines = copy.deepcopy(v3["draft"]["lines"])
    lines[0]["unit_price"] = None
    v4 = quote_draft.save(wp_id, _sent(v3, lines), actor="bela", expected_state=v3["state"])
    assert v4["blockers"] == []
    # 164 700 + 758 000 + 45 000 = 967 700 net; 27 percent VAT on the net total, in whole forints
    assert v4["totals"] == {"net": "967700", "vat": "261279", "gross": "1228979"} and v4["currency"] == "HUF"
    assert _next(wp_id)["code"] == "quote_approve"


def test_unchecking_a_line_to_check_holds_the_approval_again(quote):
    v = _done(quote["wp"])
    assert v["blockers"] == []
    lines = copy.deepcopy(v["draft"]["lines"])
    lines[1]["checked"] = False
    v2 = quote_draft.save(quote["wp"], _sent(v, lines), actor="bela", expected_state=v["state"])
    assert [(b["code"], b["row"]) for b in v2["blockers"]] == [("quote:line_unchecked", 1)]
    assert v2["draft"]["lines"][1]["checked_by"] is None


def test_a_change_from_a_stale_page_is_a_version_conflict(quote):
    v = quote_draft.start(quote["wp"], source="request", actor="anna", expected_state=0)
    quote_draft.save(quote["wp"], _sent(v), actor="anna", expected_state=v["state"])
    with pytest.raises(work.RevisionConflict):
        quote_draft.save(quote["wp"], _sent(v), actor="bela", expected_state=v["state"])


def test_numbers_are_read_by_the_hungarian_habit_and_a_wrong_line_is_refused(quote):
    v = quote_draft.start(quote["wp"], source="request", actor="anna", expected_state=0)
    lines = copy.deepcopy(v["draft"]["lines"])
    lines[0].update(sku="HW-MON-24", quantity="2,5")
    v2 = quote_draft.save(quote["wp"], _sent(v, lines), actor="anna", expected_state=v["state"])
    assert v2["draft"]["lines"][0]["quantity"] == "2.5" and v2["lines"][0]["priced"]["net"] == "137250"
    for change, message in (({"quantity": "sok"}, "not a number"), ({"unit_price": "-5"}, "negative"),
                            ({"sku": "NO-SUCH"}, "not in the price list"), ({"discount_percent": "100"}, "discount")):
        bad = copy.deepcopy(v2["draft"]["lines"])
        bad[0].update(change)
        with pytest.raises(quote_draft.QuoteDraftError, match=message):
            quote_draft.save(quote["wp"], _sent(v2, bad), actor="anna", expected_state=v2["state"])
    new = {k: None for k in quote_draft.EDITABLE} | {"quantity": "0", "sku": "HW-KB-MS", "checked": False}
    v3 = quote_draft.save(quote["wp"], _sent(v2, [*v2["draft"]["lines"], new]), actor="anna", expected_state=v2["state"])
    added = v3["draft"]["lines"][3]
    assert added["id"] and added["row"] is None and added["mark"] is None  # a line a person added gets its own id
    assert ("quote:line_no_quantity", added["id"]) in {(b["code"], b["line"]) for b in v3["blockers"]}


def test_the_approval_is_a_version_of_its_own_and_reopening_needs_a_reason(quote):
    wp_id = quote["wp"]
    v = _done(wp_id)
    with pytest.raises(work.RevisionConflict):
        quote_draft.approve(wp_id, fingerprint="0" * 64, actor="anna")
    approved = quote_draft.approve(wp_id, fingerprint=v["fingerprint"], actor="anna")
    assert approved["version"] == 1 and approved["approved_by"] == "anna"
    assert _next(wp_id) == {"code": "quote_approved", "label": "Approved: version 1", "stage": "result",
                            "params": {"version": 1}}
    assert package_release.own_approval(wp_id)["active"]["version"] == 1
    kept = quote_draft.approved_version(wp_id, 1)["quote"]
    assert kept["totals"]["gross"] == "1228979" and kept["price_list"]["version"] == 1
    assert [ln["sku"] for ln in kept["lines"]] == ["HW-MON-24", "HW-NB-15B", None]
    with pytest.raises(quote_draft.QuoteDraftError, match="approved"):  # an approved quote is not changed
        quote_draft.save(wp_id, _sent(quote_draft.view(wp_id)), actor="anna", expected_state=v["state"])
    with pytest.raises(quote_draft.QuoteDraftError, match="reason"):
        quote_draft.reopen(wp_id, note=" ", actor="anna")
    after = quote_draft.reopen(wp_id, note="The customer asked for four monitors", actor="anna")
    assert after["approval"]["active"] is None
    assert after["approval"]["versions"][0]["reopen_note"] == "The customer asked for four monitors"
    lines = copy.deepcopy(after["draft"]["lines"])
    lines[0]["quantity"] = "4"
    v2 = quote_draft.save(wp_id, _sent(after, lines), actor="anna", expected_state=after["state"])
    assert quote_draft.approve(wp_id, fingerprint=v2["fingerprint"], actor="anna")["version"] == 2
    events = [e["action"] for e in work.workpackage_events(wp_id) if e["action"].startswith("quote_")]
    assert events == ["quote_approve", "quote_reopen", "quote_approve"]


def test_a_blocked_draft_is_not_approved(quote):
    v = quote_draft.start(quote["wp"], source="request", actor="anna", expected_state=0)
    with pytest.raises(work.NotReady) as refused:
        quote_draft.approve(quote["wp"], fingerprint=v["fingerprint"], actor="anna")
    assert {b["code"] for b in refused.value.blockers} == {"quote:line_no_item"}


def test_a_newer_price_list_version_is_a_warning_and_the_draft_can_switch_to_it(quote):
    v = _done(quote["wp"])
    price_lists.change_settings(quote["price_list"], 1, discounts=[{"category": "hardware", "min_quantity": "2", "percent": "5"}],
                                currency="HUF", vat_percent="27", actor="anna")
    price_lists.activate(quote["price_list"], 2, actor="anna")
    stale = quote_draft.view(quote["wp"])
    assert [(w["code"], w.get("version")) for w in stale["warnings"]] == [("quote:price_list_superseded", 2)]
    switched = quote_draft.save(quote["wp"], _sent(stale, version=2), actor="anna", expected_state=stale["state"])
    assert switched["warnings"] == [] and switched["lines"][0]["priced"]["discount_percent"] == "5"
    assert switched["lines"][0]["priced"]["net"] == "156465"  # 3 x 54 900 less 5 percent
    with pytest.raises(quote_draft.QuoteDraftError, match="not active"):  # back to the retired version: refused
        quote_draft.save(quote["wp"], _sent(switched, version=1), actor="anna", expected_state=switched["state"])
    assert v["draft"]["version"] == 1


def test_a_cases_quote_is_not_deleted_while_its_case_exists(quote):
    """231 (A3d): the quote lives in its case's container, which is not deleted while the case exists (only hidden)."""
    wp_id = quote["wp"]
    _done(wp_id)
    with pytest.raises(work.NotReady):
        work.delete_workpackage(wp_id, actor="anna")
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM quote_drafts WHERE workpackage_id=?", (wp_id,)).fetchone()[0] == 1


def test_the_service_composes_approves_and_reopens_the_quote(quote, tmp_path):
    from fastapi.testclient import TestClient

    from jav.service.api import create_app

    wp_id = quote["wp"]
    _proposed(wp_id)
    human = {"X-Actor": "teszt.elek"}
    with TestClient(create_app(store_path=tmp_path / "q.sqlite"), base_url="http://127.0.0.1:8930") as c:
        shown = c.get(f"/api/cases/{wp_id}").json()["tabs"][1]["elements"][1]["data"]["quote"]
        assert shown["draft"]["draft"] is None and shown["draft"]["state"] == 0
        started = c.post(f"/api/workpackages/{wp_id}/quote/draft/start", headers=human,
                         json={"source": "proposal", "expected_state": 0})
        assert started.status_code == 200
        v = started.json()
        lines = copy.deepcopy(v["draft"]["lines"])
        lines[1]["checked"] = True
        lines[2].update(unit_price="45000", note="Own purchase", description="Kavefozo", unit="db")
        saved = c.put(f"/api/workpackages/{wp_id}/quote/draft", headers=human,
                      json={"draft": _sent(v, lines), "expected_state": v["state"]})
        assert saved.status_code == 200 and saved.json()["blockers"] == []
        stale = c.put(f"/api/workpackages/{wp_id}/quote/draft", headers=human,
                      json={"draft": _sent(v, lines), "expected_state": v["state"]})
        assert stale.status_code == 409
        bad = copy.deepcopy(lines)
        bad[0]["quantity"] = "sok"
        refused = c.put(f"/api/workpackages/{wp_id}/quote/draft", headers=human,
                        json={"draft": _sent(v, bad), "expected_state": saved.json()["state"]})
        assert refused.status_code == 422
        approved = c.post(f"/api/workpackages/{wp_id}/quote/approve", headers=human,
                          json={"fingerprint": saved.json()["fingerprint"]})
        assert approved.status_code == 200 and approved.json()["approval"]["active"]["version"] == 1
        kept = c.get(f"/api/workpackages/{wp_id}/quote/versions/1").json()
        assert kept["quote"]["totals"]["net"] == "967700" and kept["approved_by"] == "teszt.elek"
        assert c.post(f"/api/workpackages/{wp_id}/quote/reopen", headers=human, json={"note": ""}).status_code == 422
        reopened = c.post(f"/api/workpackages/{wp_id}/quote/reopen", headers=human, json={"note": "New quantities"})
        assert reopened.status_code == 200 and reopened.json()["approval"]["active"] is None
        assert c.get(f"/api/workpackages/{wp_id}/quote/versions/9").status_code == 404


def test_a_draft_from_the_request_is_priced_from_the_list_its_process_names(quote, tmp_path):
    """231 (B0): the draft step's catalogue (a process pack's resource) names the list; by default the newest one."""
    newer = price_lists.add("Newer 2027", "n.xlsx", invented_golden.write_price_list(tmp_path / "n.xlsx").read_bytes(),
                            actor="anna")
    price_lists.activate(newer["price_list"], 1, actor="anna")
    named = quote_draft.start(quote["wp"], source="request", actor="anna", expected_state=0, catalogue=quote["price_list"])
    assert named["draft"]["price_list"] == quote["price_list"]
    newest = quote_draft.start(quote["wp"], source="request", actor="anna", expected_state=named["state"], replace=True)
    assert newest["draft"]["price_list"] == newer["price_list"]
