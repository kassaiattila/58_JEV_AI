"""264 (plan E, F6; the owner's decision of 2026-10-31: the small lists the one list too): the mailbox schedules are a
list of the service - what each reads, how often, whether it is on, when it runs next and how its last download
ended - each opening its own page; a schedule's page lists its own downloads. Synthetic mailboxes, no Outlook."""
from __future__ import annotations

import pytest

from jav.app import datasets
from jav.core import store
from jav.domains.email import mailbox


@pytest.fixture()
def db(tmp_path):
    with store.use_store(tmp_path / "s.sqlite"):
        yield


def _q(name: str, scope: dict[str, str] | None = None, **query):
    return datasets.query(name, scope or {}, datasets.Query(**query))


def test_the_schedules_are_a_list_each_opening_its_page(db):
    on = mailbox.create_schedule(mailbox.MailboxRequest(accounts=["office@example.com"], since_days=3), actor="Synthetic owner")
    off = mailbox.create_schedule(mailbox.MailboxRequest(accounts=["billing@example.com"], since_days=7), actor="Synthetic owner",
                                  interval_min=1440)
    mailbox.update_schedule(off["id"], actor="Synthetic owner", enabled=False)
    page = _q("mailbox_schedules")
    cols = {c["key"]: c for c in page["columns"]}
    assert cols["label"]["link"] == "settings" and cols["label"]["section"] == "mailboxes"
    assert cols["interval_min"].get("group") and cols["state"].get("group") and cols["state"].get("badge")
    rows = {r["_key"]: r for r in page["rows"]}
    assert set(rows) == {on["id"], off["id"]}
    assert (rows[on["id"]]["state"], rows[on["id"]]["interval_min"]) == ("on", "60")
    assert (rows[off["id"]]["state"], rows[off["id"]]["interval_min"]) == ("off", "1440")
    assert rows[on["id"]]["_request"]["accounts"] == ["office@example.com"]  # the interface writes the label from it


def test_a_schedule_s_page_lists_its_own_downloads(db):
    sch = mailbox.create_schedule(mailbox.MailboxRequest(accounts=["office@example.com"], since_days=3), actor="Synthetic owner")
    own = mailbox.request_pull(mailbox.MailboxRequest(accounts=["office@example.com"], since_days=3), actor="Synthetic owner",
                               schedule_id=sch["id"], dedup_key="own")
    other = mailbox.request_pull(mailbox.MailboxRequest(accounts=["other@example.com"], since_days=3), actor="Synthetic owner")
    assert {r["_key"] for r in _q("mailbox_pulls")["rows"]} == {own["id"], other["id"]}
    assert [r["_key"] for r in _q("mailbox_pulls", {"schedule_id": sch["id"]})["rows"]] == [own["id"]]
    cols = {c["key"]: c for c in _q("mailbox_pulls")["columns"]}
    assert cols["status"].get("group") and cols["actor"].get("group")
