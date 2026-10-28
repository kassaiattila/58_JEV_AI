"""231 (stage U, U1e; the owner's decision of 2026-10-28): an invented mailbox, downloaded as a real one is.

A mailbox download reads Outlook, so the mailbox process and the email routing could not be tried on invented emails.
The invented consultancy's mailbox (`configs/example_mailboxes.json`, an address on the reserved `.example` domain) is
read by the invented bridge instead of the Outlook script: the free preview counts its messages in the requested
folders and period, and a download sends each to the system's own temporary email receiver with its key, its invoice
attachments saved where the Outlook bridge saves them, so the package of the fresh emails is made as for a real
download. A second download finds nothing new; a folder the bridge cannot read and a request naming an invented and a
real mailbox together are refused. Invented data; no AI call.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from jav.app import registrations, work
from jav.core import store
from jav.domains.email import emails, ingest_server, mailbox, mailbox_bridge, mailbox_examples

registrations.load_all()
ADDRESS = "iroda@minta-tanacsado.example"
SPRING_TO_AUTUMN = {"received_from": date(2026, 3, 1), "received_to": date(2026, 10, 31)}


def _request(folders: tuple[str, ...] = ("Inbox", "Sent Items"), **period) -> mailbox.MailboxRequest:
    return mailbox.MailboxRequest(accounts=[ADDRESS], folders=list(folders), **(period or SPRING_TO_AUTUMN))


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ingest_server, "BRIDGE_DATA_ROOT", tmp_path / "bridge" / "data")
    monkeypatch.setattr(emails, "BRIDGE_DATA_ROOT", tmp_path / "bridge" / "data")
    with store.use_store(tmp_path / "mail.sqlite"):
        yield {"inbox": tmp_path / "inbox"}


def test_the_preview_counts_the_invented_messages_of_the_folders_and_the_period() -> None:
    assert mailbox_bridge.count(_request())["eligible"] == 4
    assert mailbox_bridge.count(_request(("Inbox",)))["eligible"] == 2  # a payment notice and a quote request
    assert mailbox_bridge.count(_request(received_from=date(2026, 6, 1), received_to=date(2026, 6, 30)))["eligible"] == 1


def test_a_download_goes_through_the_receiver_into_a_package_as_a_real_one(env) -> None:
    result = mailbox.fetch(_request(), actor="Minta Anna", inbox_root=env["inbox"])
    assert (result["stored"], result["new"], result["exit_code"]) == (4, 4, 0)
    wp = work.get(result["workpackage"])
    messages = [emails.load_message_dir(Path(i["source_path"]).parent) for i in wp["items"] if i["kind"] == "email"]
    assert sorted(m.subject for m in messages) == ["Ajánlatkérés hálózatfelújításra", "Számla: ABCD0005",
                                                   "Számla: ABCD0011", "Utalás: ABCD0005"]
    assert {m.subject for m in messages if m.folder == "sent"} == {"Számla: ABCD0005", "Számla: ABCD0011"}
    files = sorted(Path(a.path).name for m in messages for a in m.attachments if a.path)
    assert files == ["ABCD0005.pdf", "ABCD0011.pdf", "keroiv_halozat.pdf"]
    assert all(Path(a.path).is_relative_to(ingest_server.BRIDGE_DATA_ROOT) for m in messages for a in m.attachments)
    again = mailbox.fetch(_request(), actor="Minta Anna", inbox_root=env["inbox"])
    assert (again["duplicate"], again["workpackage"]) == (4, None)  # nothing new the second time


def test_a_folder_the_bridge_cannot_read_and_a_mixed_request_are_refused() -> None:
    with pytest.raises(mailbox_bridge.BridgeError, match="Archive"):
        mailbox_bridge.count(_request(("Inbox", "Archive")))
    mixed = mailbox.MailboxRequest(accounts=[ADDRESS, "iroda@minta.hu"], **SPRING_TO_AUTUMN)
    with pytest.raises(mailbox_bridge.BridgeError, match="invented"):
        mailbox_bridge.count(mixed)


def test_the_quote_request_is_the_golden_sets_email_with_its_printed_form() -> None:
    [box] = mailbox_examples.load().mailboxes
    quote = next(m for m in mailbox_examples.messages(box) if m["entry_id"].endswith("quote_request"))
    assert quote["from"] == "it@pelda.hu" and [name for name, _rows in quote["attachments"]] == ["keroiv_halozat.pdf"]
    assert quote["to"] == [ADDRESS] and quote["folder"] == "Inbox"


def test_the_mailbox_and_the_routing_say_how_they_are_tried() -> None:
    from jav.app import examples

    assert ADDRESS in examples.of("mailbox")["note"] and examples.of("mailbox")["sets"] == []
    routing = examples.of("mail_routing")
    assert [s["kind"] for s in routing["sets"]] == ["own_party"] and "mailbox" in routing["note"]
