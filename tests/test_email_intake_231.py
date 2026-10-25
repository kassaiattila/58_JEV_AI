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
    assert (offer["pack"], offer["title"], offer["starts"]) == ("it_quote", "IT quote", "case")  # C1b: by itself
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


# --- 231 (C1b): an email read as a quote request starts its IT quote case by itself ------------------------------------


def _taken(pack: str = "it_quote") -> dict[tuple[str, str], tuple[str, str | None]]:
    from jav.core import store

    with store.connect() as c:
        return {(r["workpackage_id"], r["item_id"]): (r["state"], r["case_id"]) for r in c.execute(
            "SELECT * FROM intake_starts WHERE pack_id=?", (pack,))}


def test_a_new_email_starts_its_case_once_and_its_paid_step_waits_for_a_person(env):
    from jav.core.process import engine

    wp_id = _package(env)
    run_id, item = _run(wp_id)  # the worker's first turn remembered the store's emails then (none yet)
    [started] = intake.start_due()
    assert started["record"] == {"workpackage_id": wp_id, "item_id": item["item_id"]}
    case_id = started["case_id"]
    assert _taken()[(wp_id, item["item_id"])] == ("started", case_id)
    assert intake.start_due() == []  # once
    engine.turn(case_id, wake=True)
    steps = engine.state(case_id)["steps"]
    assert steps["request"]["state"] == "done"
    assert steps["match"]["phase"] == "awaiting_start"  # the paid match waits for a person's start
    [offer] = corrections.item_result(run_id, item["item_id"])["intake"]
    assert offer["starts"] == "case" and [c["id"] for c in offer["cases"]] == [case_id]


def test_the_emails_there_before_the_intake_looked_start_no_case(env):
    from jav.core import store

    _run(_package(env))
    with store.connect() as c:
        c.execute("DELETE FROM intake_starts")  # as if the intake had never looked: the emails there now came before it
    assert intake.start_due() == []
    assert set(_taken().values()) == {("before", None), ("since", None)}


def test_an_email_a_person_started_a_case_from_starts_no_other(env):
    wp_id = _package(env)
    _, item = _run(wp_id)
    case_id = _case(wp_id, item["item_id"])  # a person started one from it first
    assert intake.start_due() == []
    assert _taken()[(wp_id, item["item_id"])] == ("had_case", None) and case_id


def test_the_worker_s_turn_looks_at_most_once_a_minute_per_store(env, monkeypatch):
    calls = []
    monkeypatch.setattr(intake, "start_due", lambda: calls.append(1) or [])
    monkeypatch.setattr(intake, "_last_tick", {})
    assert intake.tick(now=1000.0) == 0 and calls == [1]
    intake.tick(now=1030.0)
    assert calls == [1]
    intake.tick(now=1061.0)
    assert calls == [1, 1]
