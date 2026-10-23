"""191 (plan F-quote-package B3, DECISIONS 191): the quote as a kind of work package, started from a quote request.

The owner's decisions of 2026-10-21: the quote can be chosen as a kind of work, as the reconciliation and the data
extraction can; its request is an email or a document already processed and read as a quote request, from any package.
A request's parts (the email's own text, its attachments) were each extracted on their own; the request puts them
together field by field with the part each value came from, and its gaps are judged on the whole request, not on each
part. Synthetic emails and rows, a stand-in JEV and a stand-in GPT; no paid call.
"""

from __future__ import annotations

import pytest

from jav.app import logic_packs, package_scope, work, workflow_steps
from jav.core import store
from jav.domains.quotes import price_lists, invented_golden, quote_package, quote_request
from tests import test_document_result_174 as rows
from tests import test_email_text_follow_up_190 as follow
from tests.test_email_text_follow_up_190 import OUT, _package, _run

env = follow.env  # the 190 fixture: a mailbox package of one quote request email, a stand-in JEV and GPT

FORM = {"customer_name": "Minta Vevo Zrt.", "contact_phone": "+36 20 000 1234",
        "requested_items": [{"description": "Laptop 14 colos", "quantity": 5, "unit": "db"}]}


def _part(kind: str, **values) -> quote_request.Part:
    return quote_request.Part(kind=kind, name=kind, item_id=None, doc_id=kind, values=values)


# --- putting the parts together ----------------------------------------------------------------------------------------


def test_a_header_field_comes_from_the_first_part_that_has_it_and_the_items_from_the_first_attachment_with_rows():
    text = _part("email_text", customer_name="Minta Kft.", deadline="2026-11-20",
                 requested_items=[{"description": "monitor", "quantity": 3, "unit": "db"}])
    form = _part("attachment", customer_name="Minta Vevo Zrt.", contact_phone="+36 20 000 1234", requested_items=[])
    sheet = _part("attachment", requested_items=[{"description": "laptop", "quantity": 5, "unit": "db"}])
    fields, sources, items, items_from = quote_request.merge([text, form, sheet])
    assert fields["customer_name"] == "Minta Kft." and sources["customer_name"] == 0
    assert fields["contact_phone"] == "+36 20 000 1234" and sources["contact_phone"] == 1
    assert fields["reference"] is None and "reference" not in sources
    assert (items, items_from) == ([{"description": "laptop", "quantity": 5, "unit": "db"}], 2)
    # without an attachment that has rows, the email's text gives the items
    assert quote_request.merge([text, form])[2:] == ([{"description": "monitor", "quantity": 3, "unit": "db"}], 0)
    # the measurement compares the same merge
    assert quote_request.merged([text.values, form.values, sheet.values])["requested_items"] == items


# --- reading a request from the store ----------------------------------------------------------------------------------


def test_a_processed_quote_request_email_reads_as_one_request(env):
    wp_id = _package(env)
    _run_id, item = _run(wp_id)
    request = quote_request.read(wp_id, item["item_id"])
    assert (request.kind, request.title) == ("email", "Ajanlatkeres monitorra")
    assert [p.kind for p in request.parts] == ["email_text"]
    assert request.fields["customer_name"] == OUT["customer_name"] and request.sources["customer_name"] == 0
    assert [(i["description"], i["quantity"]) for i in request.items] == [("24 colos monitor", "3")]  # stored as text, as every amount and quantity
    listed = quote_package.candidates()
    assert [(c["workpackage_id"], c["item_id"], c["customer_name"], c["items"]) for c in listed] == [
        (wp_id, item["item_id"], OUT["customer_name"], 1)]
    assert quote_package.candidates(q="monitorra") and quote_package.candidates(q="no such text") == []


def test_an_attachment_read_as_a_request_joins_its_email(env):
    wp_id = _package(env)
    _run_id, email = _run(wp_id)
    with store.connect() as c:  # a request form attached to the email, processed in a later run of the package
        c.execute("INSERT INTO workpackage_items(workpackage_id, item_id, kind, source_path, sha256, added_revision,"
                  " parent_item_id) VALUES (?,?,?,?,?,?,?)", (wp_id, rows._id("form"), "document",
                                                            "C:/synthetic/form.pdf", rows._id("form"), 1, email["item_id"]))
    rows._run("run-form", {"form": FORM}, at="2026-11-03T08:00:00+00:00", wp=wp_id, doc_type="quote_request")
    request = quote_request.read(wp_id, email["item_id"])
    assert [p.kind for p in request.parts] == ["email_text", "attachment"]
    assert request.fields["contact_phone"] == "+36 20 000 1234" and request.sources["contact_phone"] == 1
    assert request.fields["customer_name"] == OUT["customer_name"]  # the email's text comes first
    assert request.items_from == 1 and request.items[0]["description"] == "Laptop 14 colos"
    # the attachment is not a request of its own: it is part of its email's
    assert [c["item_id"] for c in quote_package.candidates()] == [email["item_id"]]


def test_a_document_read_as_a_request_is_one_on_its_own(rows_db):
    rows._run("run-doc", {"kerdoiv": FORM}, at="2026-11-03T08:00:00+00:00", doc_type="quote_request")
    rows._run("run-inv", {"szamla": rows._inv("INV-1")}, at="2026-11-03T08:00:00+00:00", wp=rows.OTHER)
    request = quote_request.read(rows.WP, rows._id("kerdoiv"))
    assert (request.kind, request.title, [p.kind for p in request.parts]) == ("document", "kerdoiv.pdf", ["document"])
    assert [c["item_id"] for c in quote_package.candidates()] == [rows._id("kerdoiv")]
    with pytest.raises(quote_request.RequestNotFound):
        quote_request.read(rows.OTHER, rows._id("szamla"))  # an invoice is no quote request


@pytest.fixture
def rows_db(tmp_path):
    with store.use_store(tmp_path / "quote-rows.sqlite"):
        with store.connect() as c:
            for wp in (rows.WP, rows.OTHER):
                c.execute("INSERT INTO workpackages(id, name, source_kind, created_at, updated_at) VALUES (?,?,?,?,?)",
                          (wp, "synthetic", "manual", rows.NOW, rows.NOW))
        yield


# --- the quote package -------------------------------------------------------------------------------------------------


def _price_list(tmp_path) -> None:
    made = price_lists.add("Invented 2026", "p.xlsx", invented_golden.write_price_list(tmp_path / "p.xlsx").read_bytes(),
                           actor="anna")
    price_lists.activate(made["price_list"], 1, actor="anna")


def test_a_quote_package_names_its_request_and_its_gaps(env, tmp_path):
    wp_id = _package(env)
    _run_id, item = _run(wp_id)
    with pytest.raises(quote_package.QuoteError):
        quote_package.create(name=" ", source=wp_id, item_id=item["item_id"], actor="anna")
    made = quote_package.create(name="Monitors for Minta", source=wp_id, item_id=item["item_id"], actor="anna")
    quote = work.get(made["workpackage_id"])
    assert (quote["source_kind"], quote["owner"], quote["name"]) == ("quote", "anna", "Monitors for Minta")
    assert package_scope.stored(quote["id"])["parts"] == {"request": {"workpackage_id": wp_id, "item_id": item["item_id"]}}
    view = quote_package.view(quote["id"])
    assert view["request"]["fields"]["customer_name"] == OUT["customer_name"]
    assert view["source"]["workpackage_name"] == work.get(wp_id)["name"]
    assert [b["code"] for b in view["blockers"]] == ["quote:no_price_list"]
    assert quote_package.next_step(quote["id"])["code"] == "quote_request_check"
    _price_list(tmp_path)
    view = quote_package.view(quote["id"])
    assert view["blockers"] == [] and [p["name"] for p in view["price_lists"]] == ["Invented 2026"]
    assert quote_package.next_step(quote["id"]) == {"code": "quote_propose", "label": "Ask for the proposal", "stage": "review"}
    assert not logic_packs.of("quote").approved(quote["id"])
    # the email it came from shows which quotes were made from it
    assert quote_package.candidates()[0]["quotes"] == [{"id": quote["id"], "name": quote["name"]}]


def test_a_request_that_can_no_longer_be_read_is_a_blocker(env):
    wp_id = _package(env)
    run_id, item = _run(wp_id)
    quote_id = quote_package.create(name="Monitors", source=wp_id, item_id=item["item_id"], actor="anna")["workpackage_id"]
    with store.connect() as c:
        c.execute("UPDATE workpackage_items SET removed_revision=1 WHERE workpackage_id=? AND item_id=?", (wp_id, item["item_id"]))
    view = quote_package.view(quote_id)
    assert view["request"] is None and [b["code"] for b in view["blockers"]] == ["quote:request_missing", "quote:no_price_list"]
    assert quote_package.next_step(quote_id)["code"] == "quote_request_missing"


def test_only_a_quote_request_can_start_a_quote(rows_db):
    with pytest.raises(quote_package.QuoteError):
        quote_package.create(name="x", source="wp-000000000000", item_id="nope", actor="anna")
    rows._run("run-inv", {"szamla": rows._inv("INV-1")}, at="2026-11-03T08:00:00+00:00")
    with pytest.raises(quote_package.QuoteError):
        quote_package.create(name="x", source=rows.WP, item_id=rows._id("szamla"), actor="anna")
    assert not [wp for wp in work.list_workpackages() if wp["source_kind"] == "quote"]


def test_the_quote_is_a_registered_logic_pack_and_a_kind_of_work():
    pack = logic_packs.of("quote")
    assert pack is not None and not pack.has_runs and pack.service == "jav.domains.quotes.api_quote_package"
    assert [(r.name, r.source) for r in pack.roles] == [("request", "linked_package"), ("price_list", "master_data")]
    assert workflow_steps.of("quote").package_kinds == ("quote",)
    templates = {t["id"]: t for t in __import__("jav.app.workflows", fromlist=["templates_view"]).templates_view()["templates"]}
    assert templates["quote"]["steps"] == [{"id": "quote", "kind": "quote"}]


def test_the_service_lists_the_requests_and_makes_a_quote(env, tmp_path):
    from fastapi.testclient import TestClient

    from jav.service.api import create_app

    wp_id = _package(env)
    _run_id, item = _run(wp_id)
    human = {"X-Actor": "teszt.elek"}
    # the env fixture's store (tests/test_email_text_follow_up_190.py)
    with TestClient(create_app(store_path=tmp_path / "q.sqlite"), base_url="http://127.0.0.1:8930") as c:
        listed = c.get("/api/quote-requests", params={"q": "monitor"}).json()["requests"]
        assert [r["item_id"] for r in listed] == [item["item_id"]]
        made = c.post("/api/quote-packages", headers=human, json={"name": "Monitors", "source": wp_id,
                                                                  "item_id": item["item_id"]})
        assert made.status_code == 201
        page = c.get(f"/api/workpackages/{made.json()['workpackage_id']}").json()
        assert page["quote"]["request"]["title"] == "Ajanlatkeres monitorra"
        assert page["next"]["code"] == "quote_request_check"
        bad = c.post("/api/quote-packages", headers=human, json={"name": "x", "source": wp_id, "item_id": "nope"})
        assert bad.status_code == 422
