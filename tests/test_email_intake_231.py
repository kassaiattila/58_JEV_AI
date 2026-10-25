"""231 (plan stage C, C1a; DECISIONS 231): an email offers the cases of the processes whose intake takes it.

An email read as a quote request shows, on its own page in the mailbox package, an offer of every process whose intake
takes emails and whose record step finds its record in this one (the IT quote): the record put together from the
email's parts (the email's text and its attachments, each value with the part it came from), what the record still
lacks, a name for the case and the cases already started from it. The email's page names no process: the offers come
from the process packs (`jav/app/intake.py`), the record's reading from its capability (until 231 C1a the quotes
domain's own item part, 192 B6a). The next step's name says the extraction reads the email's own text too when the type
reads text. Synthetic emails, a stand-in JEV and GPT; no paid call.
"""

from __future__ import annotations

from jav.app import corrections, intake, item_kinds
from jav.domains.email import mailbox
from jav.domains.quotes import quote_request
from tests import test_email_text_follow_up_190 as follow
from tests.test_email_text_follow_up_190 import OUT, _package, _run
from tests.test_quote_package_191 import _case

env = follow.env  # the 190 fixture: a mailbox package of one quote request email, a stand-in JEV and GPT


def test_no_domain_adds_its_own_part_to_an_email_item():
    assert item_kinds.item_parts("email") == [] and item_kinds.item_parts("document") == []


def test_an_email_read_as_a_quote_request_offers_an_it_quote_case_with_its_record(env):
    wp_id = _package(env)
    run_id, item = _run(wp_id)
    result = corrections.item_result(run_id, item["item_id"])
    [offer] = result["intake"]
    assert (offer["pack"], offer["title"], offer["starts"]) == ("it_quote", "IT quote", "offer")
    assert offer["record"] == {"workpackage_id": wp_id, "item_id": item["item_id"]}
    assert offer["preview"]["fields"]["customer_name"] == "Minta Szolgaltato Kft."
    assert [i["description"] for i in offer["preview"]["items"]] == ["24 colos monitor"]
    assert offer["preview"]["parts"][0]["kind"] == "email_text"
    assert offer["gaps"] == [] and offer["cases"] == []
    assert offer["label"] == "Minta Szolgaltato Kft."  # the customer the pack's partner link reads
    case_id = _case(wp_id, item["item_id"])  # 231 (A3d): a quote is a case of the IT quote's process pack
    [again] = corrections.item_result(run_id, item["item_id"])["intake"]
    assert again["cases"] == [{"id": case_id, "name": "Monitors"}]
    assert "parts" not in result


def test_a_record_that_lacks_something_as_a_whole_says_so(env, monkeypatch):
    monkeypatch.setitem(OUT, "customer_name", None)
    monkeypatch.setitem(OUT, "requested_items", [])
    wp_id = _package(env)
    run_id, item = _run(wp_id)
    [offer] = corrections.item_result(run_id, item["item_id"])["intake"]
    assert [g["code"] for g in offer["gaps"]] == ["quote:no_customer", "quote:no_items"]


def test_an_email_that_holds_no_record_of_a_process_offers_nothing(env, monkeypatch):
    wp_id = _package(env)
    run_id, item = _run(wp_id)

    def not_one(*_args, **_kwargs):
        raise quote_request.RequestNotFound("not a quote request")

    monkeypatch.setattr(quote_request, "read", not_one)
    assert corrections.item_result(run_id, item["item_id"])["intake"] == []
    assert intake.offers(wp_id, item["item_id"]) == []


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
