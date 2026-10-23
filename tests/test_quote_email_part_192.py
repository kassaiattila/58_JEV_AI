"""192 (plan F-quote-package B6a, DECISIONS 191, 192): a quote request shows under its email, and a quote starts there.

An email read as a quote request shows, on its own page in the mailbox package, the request put together from its
parts (the email's text and its attachments, each value with the part it came from), what the whole request still
lacks, and the quotes already made from it; a quote starts from there. The email's page is the email domain's; the
quotes domain adds its part through the shared item part registry, so the email code names no quote. The next step's
name says the extraction reads the email's own text too when the type reads text. Synthetic emails, a stand-in JEV and
GPT; no paid call.
"""

from __future__ import annotations

from jav import corrections, item_kinds, quote_package
from jav.domains.email import mailbox
from tests import test_email_text_follow_up_190 as follow
from tests.test_email_text_follow_up_190 import OUT, _package, _run

env = follow.env  # the 190 fixture: a mailbox package of one quote request email, a stand-in JEV and GPT


def test_the_quotes_domain_adds_its_part_to_an_email_item():
    parts = item_kinds.item_parts("email")
    assert [(p.name, p.module) for p in parts] == [("quote_request", "jav.quote_package")]
    assert item_kinds.item_parts("document") == []


def test_an_email_read_as_a_quote_request_shows_its_request_and_its_quotes(env):
    wp_id = _package(env)
    run_id, item = _run(wp_id)
    result = corrections.item_result(run_id, item["item_id"])
    part = result["parts"]["quote_request"]
    assert part["request"]["fields"]["customer_name"] == "Minta Szolgaltato Kft."
    assert [i["description"] for i in part["request"]["items"]] == ["24 colos monitor"]
    assert part["request"]["parts"][0]["kind"] == "email_text"
    assert part["gaps"] == [] and part["quotes"] == []
    assert part["source"] == {"workpackage_id": wp_id, "item_id": item["item_id"]}
    made = quote_package.create(name="Monitors", source=wp_id, item_id=item["item_id"], actor="anna")
    again = corrections.item_result(run_id, item["item_id"])["parts"]["quote_request"]
    assert again["quotes"] == [{"id": made["workpackage_id"], "name": "Monitors"}]


def test_a_request_that_lacks_something_as_a_whole_says_so(env, monkeypatch):
    monkeypatch.setitem(OUT, "customer_name", None)
    monkeypatch.setitem(OUT, "requested_items", [])
    wp_id = _package(env)
    run_id, item = _run(wp_id)
    part = corrections.item_result(run_id, item["item_id"])["parts"]["quote_request"]
    assert [g["code"] for g in part["gaps"]] == ["quote:no_customer", "quote:no_items"]


def test_an_email_that_is_no_quote_request_has_no_such_part(env, monkeypatch):
    wp_id = _package(env)
    run_id, item = _run(wp_id)

    def not_one(*_args):
        raise quote_package.quote_request.RequestNotFound("not a quote request")

    monkeypatch.setattr(quote_package.quote_request, "read", not_one)
    assert "quote_request" not in corrections.item_result(run_id, item["item_id"]).get("parts", {})


def test_the_next_step_of_a_type_that_reads_the_email_text_names_the_email_too():
    labels = mailbox.next_flow_labels()
    assert labels["m2:quote_request"] == "Adatkinyerés a levélből és a csatolmányokból (Ajánlatkérés)"
    assert labels["m2:invoice_hu"].startswith("Adatkinyerés a csatolmányból (")
    assert (mailbox.reads_text("m2:quote_request"), mailbox.reads_text("m2:invoice_hu"), mailbox.reads_text("human:inbox"),
            mailbox.reads_text(None)) == (True, False, False, False)


def test_the_emails_result_says_its_next_step_reads_the_text(env):
    wp_id = _package(env)
    run_id, item = _run(wp_id)
    assert corrections.item_result(run_id, item["item_id"])["email"]["result"]["next_flow_reads_text"] is True
