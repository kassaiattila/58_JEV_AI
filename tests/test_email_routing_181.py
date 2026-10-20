"""The email routing (181, plan 170 L5; DECISIONS 181: proposals a person accepts).

Guarantees tested:
- each emailed document is placed by its result: an incoming invoice of an own party (its buyer's tax number), an
  outgoing one from a sent email (its supplier's), a bank statement by its account; a contract is only listed;
- the proposal is the open package whose scope fits (role, party, the day in its period), else a new package for the
  party, the day's month and the role;
- what cannot be placed is a blocker with its reason (no result, no own party, a suspicious email); since 183 an
  incoming invoice in a sent email is proposed with a note (`tests/test_email_routing_183.py`);
- accepting adds the document to the package or makes the new package with its scope; one new package per party,
  month and role in one acceptance; rejecting and undoing are recorded in the package's log; the package is done once
  every routable document is decided; a workflow's routing step routes the email packages of the steps it waits for.
Synthetic files and results only; no AI call.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from jav import email_routing, logic_packs, package_scope, parties, registrations, store, work, workflow_steps
from jav.mailbox import SUSPICIOUS_ATTACHMENT
from jav.models import account_key

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc).isoformat(timespec="seconds")
OWN_TAX = "12345678-2-41"
OWN_ACCOUNT = "11112223-33334444-55556666"  # made up


@pytest.fixture
def db(tmp_path):
    registrations.load_all()
    with store.use_store(tmp_path / "s.sqlite"):
        yield tmp_path


def _party() -> str:
    """The own party, by its tax number and its account (the identities' keys as the store keeps them)."""
    return parties.create("Example Kft.", identities=[("tax", parties.tax_key(OWN_TAX), OWN_TAX),
                                                       ("account", account_key(OWN_ACCOUNT), OWN_ACCOUNT)], actor="tester")["id"]


def _email(root: Path, name: str, attachment: str, *, folder: str = "inbox") -> tuple[Path, Path]:
    d = root / "inbox" / "office" / name
    d.mkdir(parents=True)
    (d / "message.json").write_text(json.dumps({"message_id": name, "sender": "billing@example.com", "subject": f"About {name}",
                                                "received_at": "2026-06-20T10:00:00", "folder": folder,
                                                "attachments": [{"filename": attachment}]}), encoding="utf-8")
    pdf = d / attachment
    pdf.write_bytes(b"%PDF-1.4\n% synthetic " + name.encode() + b"\n%%EOF\n")
    return d / "message.json", pdf


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mailbox(root: Path, mails: dict[str, tuple[str, str]]) -> tuple[str, dict[str, str]]:
    """An email package of the given emails ({name: (attachment, folder)}); returns its id and each attachment's id."""
    wp = work.create_workpackage(name="Office mailbox", source_kind="mailbox", source_ref="office", owner="tester")
    made = {n: _email(root, n, a, folder=f) for n, (a, f) in mails.items()}
    wp = work.add_items(wp["id"], [m for m, _ in made.values()], kind="email", expected_revision=0)
    email_ids = {Path(i["source_path"]).resolve(): i["item_id"] for i in wp["items"]}
    parents = {pdf: email_ids[m.resolve()] for m, pdf in made.values()}
    work.add_items(wp["id"], list(parents), kind="document", expected_revision=wp["revision"], parents=parents)
    return wp["id"], {n: _sha(pdf) for n, (_, pdf) in made.items()}


def _result(wp_id: str, doc_id: str, doc_type: str, values: dict, *, suspicious: bool = False) -> None:
    """A finished live run of the email package that read the attachment (as the worker would store it)."""
    run_id = f"run-{doc_id[:12]}"
    flow = work.flow_run_id(run_id, doc_id)
    with store.connect() as c:
        c.execute("INSERT INTO runs(run_id, workpackage_id, dedup_key, mode, assignment_revision, recipe_id, recipe_version,"
                  " recipe_hash, recipe, params, input, input_hash, status, approval, actor, created_at)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (run_id, wp_id, run_id, "apply", 1, "processing", 1, "h", "{}", "{}", "{}", "h", "done", "approved", "t", NOW))
        c.execute("INSERT INTO run_items(run_id, item_id, status, final_status, flow_run_id, updated_at) VALUES (?,?,?,?,?,?)",
                  (run_id, doc_id, "done", "done", flow, NOW))
    store.insert_datapoints(run_id=flow, doc_id=doc_id, doc_type=doc_type, arm="G", datapoints=values, field_conf={},
                            validation=[], route="auto", review_reasons=[], final_status="done")
    if suspicious:
        store.review_enqueue(subject_kind="document", subject_id=doc_id, run_id=flow, reasons=[SUSPICIOUS_ATTACHMENT])


def _invoice(**over) -> dict:
    return {"invoice_number": "INV-1", "supplier_name": "Example Supplier Kft.", "supplier_tax_id": "87654321-2-42",
            "buyer_name": "Example Kft.", "buyer_tax_id": OWN_TAX, "gross_total": "1000", "currency": "HUF",
            "issue_date": "2026-06-10", "fulfillment_date": "2026-06-08", **over}


def _items(view: dict) -> dict[str, dict]:
    return {i["file"]: i for i in view["items"]}


def test_the_routing_is_a_logic_pack_and_a_step_kind_of_the_email_domain() -> None:
    registrations.load_all()
    pack = logic_packs.of("email_routing")
    assert pack is not None and not pack.has_runs and pack.module == "jav.email_routing" and pack.outputs == ()
    assert workflow_steps.of("routing").package_kinds == ("email_routing",) and not workflow_steps.of("routing").paid


def test_each_emailed_document_is_placed_and_proposed(db) -> None:
    party = _party()
    wp, ids = _mailbox(db, {"m1": ("invoice.pdf", "inbox"), "m2": ("sold.pdf", "sent"), "m3": ("statement.pdf", "inbox"),
                            "m4": ("contract.pdf", "inbox"), "m5": ("unknown.pdf", "inbox"), "m6": ("late.pdf", "inbox"),
                            "m7": ("odd.pdf", "inbox"), "m8": ("bought.pdf", "sent")})
    _result(wp, ids["m1"], "invoice_hu", _invoice())
    _result(wp, ids["m2"], "invoice_out", _invoice(supplier_name="Example Kft.", supplier_tax_id=OWN_TAX, buyer_name="Client Kft.",
                                                    buyer_tax_id="12121216-2-42", fulfillment_date="2026-06-30"))
    _result(wp, ids["m3"], "statement_cib", {"account_no": OWN_ACCOUNT, "period_start": "2026-06-01", "period_end": "2026-06-30",
                                             "currency": "HUF", "transactions": []})
    _result(wp, ids["m4"], "contract", {"parties": "x"})
    _result(wp, ids["m5"], "invoice_hu", _invoice(buyer_name="Someone Else Kft.", buyer_tax_id="13570008-1-13"))
    _result(wp, ids["m7"], "invoice_hu", _invoice(), suspicious=True)
    _result(wp, ids["m8"], "invoice_hu", _invoice(invoice_number="INV-8"))
    # m6 has no result yet
    june = package_scope.set_scope  # an existing package of June's incoming invoices
    target = work.create_workpackage(name="June incoming", source_kind="folder", source_ref=None, owner="tester")
    june(target["id"], party_id=party, period_start="2026-06-01", period_end="2026-06-30", role_name="incoming_invoices",
         actor="tester")
    made = email_routing.create(name="Routing", sources=[wp], actor="tester")
    view = email_routing.view(made["workpackage_id"])
    items = _items(view)
    assert items["invoice.pdf"]["placement"] | {"party": None} == {"routable": True, "role": "incoming_invoices",
                                                                  "role_title": "Incoming invoices", "party_id": party,
                                                                  "party": None, "day": "2026-06-08", "problem": None,
                                                                  "note": None}  # 183: the note
    assert items["invoice.pdf"]["proposal"]["target"] == {"id": target["id"], "name": "June incoming"}
    assert items["invoice.pdf"]["email"]["subject"] == "About m1"
    assert items["sold.pdf"]["placement"]["role"] == "outgoing_invoices"
    assert items["sold.pdf"]["proposal"]["new"] == {"name": "Example Kft. · 2026-06 · Outgoing invoices", "party": "Example Kft.",
                                                    "party_id": party, "period_start": "2026-06-01",
                                                    "period_end": "2026-06-30", "role": "outgoing_invoices"}
    assert items["statement.pdf"]["placement"]["role"] == "statements" and items["statement.pdf"]["placement"]["day"] == "2026-06-30"
    assert not items["contract.pdf"]["placement"]["routable"] and items["contract.pdf"]["proposal"] is None
    assert {f: items[f]["placement"]["problem"] for f in ("unknown.pdf", "late.pdf", "odd.pdf", "bought.pdf")} == {
        "unknown.pdf": "not_own", "late.pdf": "no_result", "odd.pdf": "suspicious", "bought.pdf": None}
    # 183 (DECISIONS 183): an incoming invoice in a sent email is proposed, with a note (it was a blocker)
    assert items["bought.pdf"]["placement"]["note"] == "sent_incoming" and items["bought.pdf"]["proposal"]["target"]["id"] == target["id"]
    assert view["counts"] == {"attachments": 8, "routable": 7, "decided": 0, "blocked": 3, "clear": 4, "accepted": 0}
    assert view["sources"] == [{"id": wp, "name": "Office mailbox"}]


def test_accepting_adds_the_documents_and_makes_the_new_packages(db) -> None:
    party = _party()
    wp, ids = _mailbox(db, {"m1": ("invoice.pdf", "inbox"), "m2": ("other.pdf", "inbox"), "m3": ("sold.pdf", "sent"),
                            "m4": ("unknown.pdf", "inbox")})
    _result(wp, ids["m1"], "invoice_hu", _invoice())
    _result(wp, ids["m2"], "invoice_hu", _invoice(invoice_number="INV-2", fulfillment_date="2026-06-25"))
    _result(wp, ids["m3"], "invoice_out", _invoice(supplier_name="Example Kft.", supplier_tax_id=OWN_TAX, buyer_tax_id="12121216-2-42"))
    _result(wp, ids["m4"], "invoice_hu", _invoice(buyer_tax_id="13570008-1-13", buyer_name="Someone Else Kft."))
    routing = email_routing.create(name="Routing", sources=[wp], actor="tester")["workpackage_id"]
    assert email_routing.LOGIC.next_step(routing)["code"] == "routing_decide"
    view = email_routing.accept_clear(routing, actor="Example Person", titles={"incoming_invoices": "Eingangsrechnungen"})
    items = _items(view)
    # the two June invoices went into one new package of incoming invoices, with its scope, named in the interface's language
    new_in = items["invoice.pdf"]["decision"]["target"]
    assert items["other.pdf"]["decision"]["target"] == new_in and items["invoice.pdf"]["decision"]["made"] == 1
    assert items["other.pdf"]["decision"]["made"] == 0
    package = work.get(new_in)
    assert package["name"] == "Example Kft. · 2026-06 · Eingangsrechnungen"
    assert work.get(items["sold.pdf"]["decision"]["target"])["name"] == "Example Kft. · 2026-06 · Outgoing invoices"
    assert {i["item_id"] for i in package["items"]} == {ids["m1"], ids["m2"]}
    scope = package_scope.scope_of(new_in)
    assert (scope["party_id"], scope["period_start"], scope["role"], scope["from"]) == (party, "2026-06-01", "incoming_invoices", "own")
    assert items["sold.pdf"]["decision"]["target"] != new_in
    assert items["invoice.pdf"]["held"] is True
    assert view["counts"]["decided"] == 3 and view["counts"]["accepted"] == 3
    # the blocked one goes where a person chooses, or is not routed
    with pytest.raises(email_routing.RoutingError, match="no proposal"):
        email_routing.accept(routing, [ids["m4"]], actor="Example Person")
    assert not email_routing.LOGIC.approved(routing)
    view = email_routing.reject(routing, [ids["m4"]], actor="Example Person")
    assert email_routing.LOGIC.approved(routing) and email_routing.LOGIC.next_step(routing)["code"] == "routing_done"
    view = email_routing.undo(routing, ids["m4"], actor="Example Person")
    assert _items(view)["unknown.pdf"]["decision"] is None
    view = email_routing.accept(routing, [ids["m4"]], actor="Example Person", target=new_in)
    assert _items(view)["unknown.pdf"]["decision"]["target"] == new_in
    actions = [e["action"] for e in work.workpackage_events(routing)]
    assert actions == ["routing_accept"] * 3 + ["routing_reject", "routing_undo", "routing_accept"]


def test_a_routing_package_needs_an_email_package_and_refuses_documents(db) -> None:
    folder = work.create_workpackage(name="Folder", source_kind="folder", source_ref=None, owner="tester")
    with pytest.raises(email_routing.RoutingError, match="has no email"):
        email_routing.create(name="Routing", sources=[folder["id"]], actor="tester")
    with pytest.raises(email_routing.RoutingError, match="at least one"):
        email_routing.create(name="Routing", sources=[], actor="tester")
    wp, _ = _mailbox(db, {"m1": ("invoice.pdf", "inbox")})
    routing = email_routing.create(name="Routing", sources=[wp], actor="tester")["workpackage_id"]
    assert email_routing.LOGIC.next_step(routing)["code"] == "routing_decide"  # no result yet: a blocker to decide
    with pytest.raises(ValueError, match="no documents of its own"):
        work.add_to_package(routing, [db / "inbox" / "office" / "m1" / "invoice.pdf"], expected_revision=0, actor="tester")
    work.delete_workpackage(routing, actor="tester")
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM workpackage_scopes").fetchone()[0] == 0  # 186: the shared scope


def test_an_email_package_offers_its_routing_and_names_the_routing_packages(db) -> None:
    from jav import work_views

    wp, _ = _mailbox(db, {"m1": ("invoice.pdf", "inbox"), "m2": ("other.pdf", "inbox")})
    assert work_views.workpackage_view(wp)["routing_offer"] == {"attachments": 2, "routings": []}
    routing = email_routing.create(name="June routing", sources=[wp], actor="tester")["workpackage_id"]
    assert work_views.workpackage_view(wp)["routing_offer"]["routings"] == [{"id": routing, "name": "June routing"}]
    page = work_views.workpackage_view(routing)
    assert page["routing"]["counts"]["attachments"] == 2 and page["next"]["code"] == "routing_decide"
    empty = work.create_workpackage(name="No attachment", source_kind="mailbox", source_ref="x", owner="tester")
    assert "routing_offer" not in work_views.workpackage_view(empty["id"])


def test_a_workflows_routing_step_routes_the_email_package_of_the_step_it_waits_for(db) -> None:
    from jav import workflows

    party = _party()
    wp, ids = _mailbox(db, {"m1": ("invoice.pdf", "inbox")})
    _result(wp, ids["m1"], "invoice_hu", _invoice())
    assert workflows.template_needs(workflows.template("mailbox_routing")) == []
    made = workflows.create(template_id="mailbox_routing", party_id=None, period_start=None, period_end=None,
                            steps={"emails": {"source": {"kind": "package", "workpackage_id": wp}},
                                   "routing": {"source": {"kind": "none"}}}, actor="tester")
    steps = {s["id"]: s for s in made["steps"]}
    assert steps["emails"]["status"] == "approved"  # its live run is approved
    routing = steps["routing"]["package"]["id"]
    assert steps["routing"]["state"] == "started" and steps["routing"]["status"] == "review"
    assert email_routing.sources_of(routing) == [wp]
    email_routing.accept_clear(routing, actor="tester")
    view = workflows.view(made["workflow"]["id"])
    assert {s["id"]: s["status"] for s in view["steps"]}["routing"] == "approved" and view["done"] == 2
    assert package_scope.scope_of(email_routing.view(routing)["items"][0]["decision"]["target"])["party_id"] == party
