"""231 (plan stage C, C1c; DECISIONS 231): the email routing as a process pack's case.

A case of the email routing process reads the email packages its scope names (`sources`): its routing step proposes
the package each emailed document belongs to, waits while a person decides, and is done once every attachment it can
route is decided; the case then closes. Its tabs show the email packages, the decisions and what went where (the
routing's own element) and the cases started from an item of those packages. A routing package made before (until
C1c its own kind of package) is taken over as such a case with its decisions. Synthetic emails and results; no AI call.
"""

from __future__ import annotations

from jav.app import case_views, process_runtime, work
from jav.core.process import engine
from jav.domains.email import email_routing
from tests.test_email_routing_181 import _invoice, _items, _mailbox, _party, _result, db  # noqa: F401 - the fixture

PACK = "mail_routing"


def _sources(db) -> tuple[str, dict[str, str]]:  # noqa: F811
    _party()
    wp, ids = _mailbox(db, {"m1": ("invoice.pdf", "inbox"), "m2": ("unknown.pdf", "inbox")})
    _result(wp, ids["m1"], "invoice_hu", _invoice())
    _result(wp, ids["m2"], "invoice_hu", _invoice(buyer_tax_id="13570008-1-13", buyer_name="Someone Else Kft."))
    return wp, ids


def _element(page: dict, tab: str, kind: str) -> dict:
    return next(e for t in page["tabs"] if t["id"] == tab for e in t["elements"] if e["type"] == kind)


def test_a_routing_case_waits_for_the_decisions_and_closes_when_every_one_is_made(db) -> None:  # noqa: F811
    wp, ids = _sources(db)
    case_id = process_runtime.start_case(PACK, {"sources": [wp]}, name="June emails", actor="Example Person")
    engine.turn(case_id, wake=True)
    step = engine.state(case_id)["steps"]["route"]
    assert (step["state"], step["waiting_for"]) == ("running", "routing")
    page = case_views.view(case_id)
    assert [t["id"] for t in page["tabs"]] == ["emails", "routing", "routed", "cases", "history"]
    shown = _element(page, "routing", "file_placement")
    assert shown["show"] == "decide" and {i["file"] for i in shown["data"]["items"]} == {"invoice.pdf", "unknown.pdf"}
    email_routing.accept_clear(case_id, actor="Example Person")
    email_routing.reject(case_id, [ids["m2"]], actor="Example Person")
    engine.turn(case_id, wake=True)
    state = engine.state(case_id)
    assert state["steps"]["route"]["state"] == "done" and state["status"] == "closed"
    assert _items(email_routing.view(case_id))["invoice.pdf"]["decision"]["decision"] == "accepted"


def _old_routing(wp: str) -> str:
    """A routing package as the email routing made one until C1c: its own kind, its email packages in its scope."""
    from jav.app import package_scope
    from jav.core import store

    routing = work.create_workpackage(name="Routing", source_kind="email_routing", source_ref=None, owner="tester")["id"]
    with store.connect() as c:
        store.begin_immediate(c)
        package_scope.save(c, routing, parts={"emails": [wp]}, actor="tester")
    return routing


def test_a_routing_package_made_before_is_taken_over_with_its_decisions(db) -> None:  # noqa: F811
    wp, ids = _sources(db)
    routing = _old_routing(wp)
    email_routing.accept_clear(routing, actor="Example Person")
    listed = process_runtime.adopt_all(actor="tester")  # without write: only listed
    assert [(r["pack"], r["workpackage_id"], r["scope"], r["result"]) for r in listed] == [
        (PACK, routing, {"sources": [wp]}, "to adopt")]
    assert work.get(routing)["source_kind"] == "email_routing"
    assert [r["result"] for r in process_runtime.adopt_all(actor="tester", write=True)] == ["adopted"]
    assert work.get(routing)["source_kind"] == process_runtime.CONTAINER
    assert process_runtime.adopt_all(actor="tester", write=True) == []  # its kind is the container's now
    view = email_routing.view(routing)  # the decisions stay where they were
    assert _items(view)["invoice.pdf"]["decision"]["decision"] == "accepted" and view["sources"][0]["id"] == wp
    step = engine.state(routing)["steps"]["route"]
    assert (step["state"], step["waiting_for"]) == ("running", "routing")  # one attachment is still to decide
    email_routing.reject(routing, [ids["m2"]], actor="Example Person")
    engine.turn(routing, wake=True)
    assert engine.state(routing)["status"] == "closed"


def test_a_routing_case_lists_the_cases_started_from_its_emails(db) -> None:  # noqa: F811
    wp, _ids = _sources(db)
    email = next(i["item_id"] for i in work.get(wp)["items"] if i["kind"] == "email")
    case_id = process_runtime.start_case(PACK, {"sources": [wp]}, name="June emails", actor="Example Person")
    quote = process_runtime.start_case("it_quote", {"record": {"workpackage_id": wp, "item_id": email}}, name="IT quote: Example",
                                       actor="Example Person")
    process_runtime.start_case("it_quote", {"record": {"workpackage_id": "wp-000000000000", "item_id": "x"}},
                               name="Another", actor="Example Person")  # from another package: not listed
    [started] = _element(case_views.view(case_id), "cases", "started_cases")["data"]
    assert (started["id"], started["process"], started["record"]["item_id"]) == (quote, "IT quote", email)


def test_a_case_s_container_is_in_the_case_list_not_the_batches(db) -> None:  # noqa: F811
    """A case's next step names its parameters as every package's does (the list once failed on a case without them);
    U2a (the owner's decision of 2026-10-28: one work list) the case is listed among the cases, and the list of every
    document batch leaves its container out (the email package it reads stays there)."""
    from jav.app import datasets, work_views
    from jav.app.tablequery import Query

    wp, _ids = _sources(db)
    case_id = process_runtime.start_case(PACK, {"sources": [wp]}, name="June emails", actor="Example Person")
    batches = {r["_key"] if "_key" in r else r["id"] for r in datasets.query("workpackages", {}, Query(limit=100))["rows"]}
    assert case_id not in batches and wp in batches
    assert case_id in {r["_key"] for r in datasets.query("cases", {}, Query(limit=100))["rows"]}
    assert isinstance(work_views.workpackage_view(case_id)["next"]["params"], dict)
