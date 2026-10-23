"""190 (plan 189 A2f; the owner's decision of 2026-10-21 'a setting, on by default'): an email's own text is extracted
as the item's follow-up stage.

When an email's route is a data extraction whose type pack reads text (the quote request) and the recipe's
`email_text` setting is on, the email flow names a follow-up: the extraction flow on the email's own text (its From,
Date and Subject lines, then its text without the quoted earlier messages). The worker runs it under
`<item>-invoice`, ties its document to the email, and raises its to-dos on the email's item, so they show with the
email and hold back the run's approval. Each email reserves 0.03 USD OpenAI for it. A run started before the setting
existed extracts nothing (its frozen recipe has no such setting). Synthetic emails, a stand-in JEV and a stand-in GPT;
no paid call.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from typesafe_sdk import Choice, Score, SystemOneResponse

from jav.domains.email import emails, ingest_server, mailbox
from jav import extract_llm, work, work_readiness, work_recipes, work_runs
from jav.documents import text_document
from jav.core import store
from jav.adapters import jev as jev_mod
from jav.domains.email.emails import EmailMessage
from jav.domains.email.flow_email import text_follow_up
from jav.runtime import worker
from tests.test_mailbox import REQ, FakeBridge
from tests.test_no_jev_085 import _FakeAgent

BODY = ("Jo napot!\n\nArajanlatot kernenk 3 db 24 colos monitorra.\nAz ajanlatot 2026. november 20-ig kernenk.\n\n"
        "Udvozlettel:\nTeszt Elek\nMinta Szolgaltato Kft.\n\nOn Mon, X wrote:\n> 10 db laptop")
MAILS = [{"message_id": "EID-Q1", "account": "iroda@minta.hu", "from": "teszt.elek@minta.hu", "sender": "Teszt Elek",
          "to": ["iroda@minta.hu"], "subject": "Ajanlatkeres monitorra", "body_preview": BODY,
          "received": "2026-11-02T10:00:00", "attachments": []}]
OUT = {"customer_name": "Minta Szolgaltato Kft.", "contact_name": "Teszt Elek", "contact_email": "teszt.elek@minta.hu",
       "deadline": "2026-11-20", "requested_items": [{"description": "24 colos monitor", "quantity": 3, "unit": "db"}]}


class QuoteJev:
    """The intent is a quote request (0.97); every yes/no question 0.02; every level question its lowest level."""

    def __init__(self) -> None:
        self.requests: list[str] = []

    def system_one(self, *, state, questions, model):
        self.requests.append(",".join(sorted(questions)))
        answers = {}
        for qid, q in questions.items():
            if isinstance(q, Choice):
                keys = list(q.criteria)
                pick = "quote_request" if "quote_request" in keys else keys[0]
                answers[qid] = {"type": "choice", "choice": pick, "confidence": 0.97,
                                "probabilities": {k: (0.97 if k == pick else round(0.03 / max(len(keys) - 1, 1), 4)) for k in keys}}
            elif isinstance(q, Score):
                probs = {"0": 0.9, "1": 0.1}
                answers[qid] = {"type": "score", "score": 0.1, "confidence": 0.9, "probabilities": probs,
                                "legend": {str(i): c for i, c in enumerate(q.criteria)}}
            else:
                answers[qid] = {"type": "noul", "noul": 0.02}
        return SystemOneResponse.model_validate_json(json.dumps({"model": "jev-1.13.0", "usage": {"input_tokens": 400,
                                                                 "output_tokens": 5}, "answers": answers}))


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ingest_server, "BRIDGE_DATA_ROOT", tmp_path / "bridge" / "data")
    monkeypatch.setattr(emails, "BRIDGE_DATA_ROOT", tmp_path / "bridge" / "data")
    client = QuoteJev()
    adapter = jev_mod.JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")
    with store.use_store(tmp_path / "q.sqlite"), jev_mod.use_adapter(adapter), \
            extract_llm.use_agent_factory(lambda pack: _FakeAgent(pack, OUT)):
        yield {"inbox": tmp_path / "inbox", "client": client}


def _package(env) -> str:
    return mailbox.fetch(REQ, actor="teszt", runner=FakeBridge(MAILS), inbox_root=env["inbox"])["workpackage"]


def _revision(wp_id: str) -> int:
    a = work_recipes.current_assignment(wp_id)
    return a["revision"] if a else 0


def _run(wp_id: str, mode: str = "apply") -> tuple[str, dict]:
    ready = work_readiness.readiness(wp_id)
    run_id = work_runs.start_run(wp_id, mode=mode, expected_assignment_revision=_revision(wp_id), input_hash=ready["input_hash"],
                            actor="t")["run_id"]
    worker.run_worker(once=True)
    run = work_runs.get_run(run_id)
    return run_id, run["input"]["items"][0]


# --- the follow-up the email flow names ----------------------------------------------------------------------------


def test_the_email_as_a_document_has_its_head_and_its_own_text():
    msg = EmailMessage(message_id="m", sender="teszt.elek@minta.hu", sender_name="Teszt Elek", subject="Ajanlatkeres",
                       received_at="2026-11-02T10:00:00", body=BODY)
    text = emails.document_text(msg)
    assert text.split("\n")[:4] == ["From: Teszt Elek <teszt.elek@minta.hu>", "Date: 2026-11-02T10:00:00",
                                     "Subject: Ajanlatkeres", ""]
    assert "24 colos monitor" in text and "laptop" not in text  # the quoted earlier message is left out
    assert emails.document_text(msg.model_copy(update={"body": " \n "})) == ""


def test_only_a_route_to_a_text_reading_pack_names_a_follow_up():
    msg = EmailMessage(message_id="m", subject="s", body=BODY)
    follow = text_follow_up(msg, "m2:quote_request")
    assert follow == {"flow": "invoice", "params": {"doc_type": "quote_request", "source_text": emails.document_text(msg)}}
    assert text_follow_up(msg, "m2:invoice_hu") is None  # an invoice is extracted from its attachment
    assert text_follow_up(msg, "human:inbox") is None and text_follow_up(msg, "m2:needs_ocr") is None
    assert text_follow_up(msg.model_copy(update={"body": ""}), "m2:quote_request") is None


# --- the worker runs it ----------------------------------------------------------------------------------------------


def test_a_quote_request_email_gets_its_text_extracted_and_its_to_dos(env):
    wp_id = _package(env)
    run_id, item = _run(wp_id)
    own = work_runs.flow_run_id(run_id, item["item_id"])
    result = store.email_result(own)
    assert result["intent"] == "quote_request" and result["next_flow"] == "m2:quote_request"
    text = emails.document_text(emails.load_message_dir(Path(item["source_path"]).parent))
    doc_id = text_document.text_digest(text)
    with store.connect() as c:
        doc = c.execute("SELECT source_email, doc_type, has_text FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        points = c.execute("SELECT run_id, doc_type, arm FROM datapoints WHERE doc_id=?", (doc_id,)).fetchall()
    assert tuple(doc) == (result["message_id"], "quote_request", 1)
    assert [tuple(p) for p in points] == [(f"{own}-invoice", "quote_request", "G")]
    # the stand-in GPT left the tax number, the phone and the reference out; the stand-in JEV calls nothing wrong, so
    # the code's checks are what remain: every item has a description and a positive quantity
    run_item = next(i for i in work_runs.get_run(run_id)["items"] if i["item_id"] == item["item_id"])
    assert work_runs.item_reasons(run_id, item["item_id"], item)["run"] == []
    assert (run_item["status"], run_item["final_status"]) == ("done", "done")
    assert any("requested_items__missing_rows" in r for r in env["client"].requests)  # the verification was asked
    assert work_runs.approve_run(run_id, actor="t")["approval"] == "approved"


def test_its_to_dos_are_the_emails_and_hold_back_the_approval(env, monkeypatch):
    # 192 (DECISIONS 192): a part's gap (no item) is a note now; a doubt about a value that is there is the to-do
    monkeypatch.setitem(OUT, "customer_tax_number", "12345678-1-12")  # fails the tax number's check digit
    wp_id = _package(env)
    run_id, item = _run(wp_id)
    reasons = [r["reason"] for r in work_runs.item_reasons(run_id, item["item_id"], item)["run"]]
    assert any(r.startswith("validator:") and r.endswith(":customer_tax_number") for r in reasons)
    run_item = next(i for i in work_runs.get_run(run_id)["items"] if i["item_id"] == item["item_id"])
    assert run_item["final_status"] == "needs_review"
    with pytest.raises(work.NotReady, match="open review reasons"):
        work_runs.approve_run(run_id, actor="t")


def test_with_the_setting_off_the_text_is_not_extracted(env):
    wp_id = _package(env)
    a = work_recipes.current_assignment(wp_id)
    work_recipes.assign_recipe(wp_id, a["recipe_id"], params={**a["params"], "email_text": "off"}, expected_revision=a["revision"],
                       actor="t")
    run_id, item = _run(wp_id)
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM datapoints").fetchone()[0] == 0
    assert store.email_result(work_runs.flow_run_id(run_id, item["item_id"]))["next_flow"] == "m2:quote_request"


def test_every_email_reserves_the_extraction_while_the_setting_is_on():
    r = next(x for x in work_recipes.recipes() if x["id"] == "processing")
    on = work_readiness.item_budget(r, {"email_text": "extract"}, "email")
    off = work_readiness.item_budget(r, {"email_text": "off"}, "email")
    assert on["openai"] - off.get("openai", Decimal(0)) == Decimal("0.03") and on["jev"] == off["jev"]
    assert work_readiness.item_budget(r, {}, "email") == on  # an older assignment counts with the default (on)
    assert work_readiness.item_budget(r, {}, "document") == work_readiness.item_budget(r, {"email_text": "off"}, "document")


def test_a_run_started_before_the_setting_extracts_nothing():
    assert worker._with_defaults({"params": {}}, {"jev": "on"}) == {"jev": "on"}
    assert worker._with_defaults({"params": {"email_text": {"default": "extract"}}}, {}) == {"email_text": "extract"}
    assert worker._with_defaults({"params": {"email_text": {"default": "extract"}}}, {"email_text": "off"}) == {"email_text": "off"}
