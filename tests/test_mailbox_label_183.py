"""183 (backlog N-angol-felulet-maradek): a mailbox package's source is named in the interface's language.

A download's label ("<mailbox> · <folders> · <period>") was put together in Hungarian in code (the last N days) and
stored as the package's source, so the English interface showed it in Hungarian. The label is English now, and a
mailbox package's page part gives the request of the download that made it, from which the interface writes the
source in its own language; a package no recorded download made has none (its stored source is shown as before).
Synthetic messages, fake JEV, no paid call.
"""

from jav import ingest_server, mailbox, work
from jav.runtime import worker

from tests.test_mailbox import MAILS, REQ, FakeBridge, env  # noqa: F401 - `env` is a fixture


def test_the_label_of_a_download_is_english():
    assert REQ.label() == "iroda@minta.hu · Inbox · last 7 days"
    ranged = mailbox.MailboxRequest(accounts=["a@b.hu"], folders=["Inbox", "Sent Items"], received_from="2026-09-01",
                                    received_to="2026-09-10")
    assert ranged.label() == "a@b.hu · Inbox, Sent Items · 2026-09-01–2026-09-10"


def test_a_mailbox_packages_page_gives_the_request_of_the_download_that_made_it(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ingest_server, "INBOX_ROOT", env["inbox"])
    monkeypatch.setattr(mailbox, "_subprocess_runner", FakeBridge(MAILS))
    p = mailbox.request_pull(REQ, actor="teszt")
    worker.run_worker(once=True)
    wp = work.get(mailbox.pull(p["id"])["result"]["workpackage"])
    assert mailbox.page_part(wp)["mailbox_request"] == REQ.model_dump(mode="json")


def test_a_package_no_recorded_download_made_has_no_request(env):  # noqa: F811
    res = mailbox.fetch(REQ, actor="teszt", runner=FakeBridge(MAILS), inbox_root=env["inbox"])
    assert mailbox.page_part(work.get(res["workpackage"]))["mailbox_request"] is None


def test_the_downloads_list_gives_each_rows_request_beside_its_label(env, monkeypatch):  # noqa: F811
    from jav import email_datasets

    monkeypatch.setattr(ingest_server, "INBOX_ROOT", env["inbox"])
    monkeypatch.setattr(mailbox, "_subprocess_runner", FakeBridge(MAILS))
    mailbox.request_pull(REQ, actor="teszt")
    _cols, rows = email_datasets.mailbox_pulls({})  # 185: the email domain's table
    assert rows[0]["label"] == REQ.label() and rows[0]["_request"] == REQ.model_dump(mode="json")
