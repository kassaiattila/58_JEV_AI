"""167 (review S-5): who changed or deleted a mailbox schedule is recorded.

The service required a chosen name for both, but dropped it: the schedule kept only its creator. A change now records
who made it and when on the schedule (`changed_by`, `changed_at`; `updated_at` also moves with every download), and a
change or a deletion is written to the service log with the name. Synthetic addresses only.
"""

import logging

import pytest

from jav.domains.email import mailbox
from jav.core import store

REQ = mailbox.MailboxRequest(accounts=["office@example.com"], since_days=3)


def test_the_creator_is_the_first_to_have_changed_it(tmp_path):
    with store.use_store(tmp_path / "s.sqlite"):
        sch = mailbox.create_schedule(REQ, actor="anna")
        assert (sch["actor"], sch["changed_by"]) == ("anna", "anna") and sch["changed_at"]


def test_a_change_records_who_made_it(tmp_path, caplog):
    with store.use_store(tmp_path / "s.sqlite"):
        sch = mailbox.create_schedule(REQ, actor="anna")
        with caplog.at_level(logging.INFO, logger="jav.domains.email.mailbox"):
            after = mailbox.update_schedule(sch["id"], actor="bela", enabled=False)
        assert (after["actor"], after["changed_by"], after["enabled"]) == ("anna", "bela", False)
        assert f"mailbox schedule {sch['id']} changed by bela" in caplog.text
        assert "office@example.com" not in caplog.text


def test_a_deletion_is_logged_with_who_made_it(tmp_path, caplog):
    with store.use_store(tmp_path / "s.sqlite"):
        sch = mailbox.create_schedule(REQ, actor="anna")
        with caplog.at_level(logging.INFO, logger="jav.domains.email.mailbox"):
            mailbox.delete_schedule(sch["id"], actor="bela")
        assert f"mailbox schedule {sch['id']} deleted by bela" in caplog.text
        with pytest.raises(KeyError):
            mailbox.schedule(sch["id"])


def test_a_change_or_deletion_needs_a_name(tmp_path):
    with store.use_store(tmp_path / "s.sqlite"):
        sch = mailbox.create_schedule(REQ, actor="anna")
        with pytest.raises(TypeError):
            mailbox.update_schedule(sch["id"], enabled=False)  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            mailbox.delete_schedule(sch["id"])  # type: ignore[call-arg]


def test_the_service_passes_the_chosen_name_on(tmp_path, caplog):
    from fastapi.testclient import TestClient

    from jav.service import api

    c = TestClient(api.create_app(store_path=tmp_path / "api.sqlite"), base_url="http://127.0.0.1:8930")
    sid = c.post("/api/mailbox/schedules", json={"request": {"accounts": ["office@example.com"], "since_days": 3}},
                 headers={"X-Actor": "anna"}).json()["id"]
    assert c.patch(f"/api/mailbox/schedules/{sid}", json={"enabled": False}).status_code == 422  # no name: refused
    changed = c.patch(f"/api/mailbox/schedules/{sid}", json={"enabled": False}, headers={"X-Actor": "bela"}).json()
    assert changed["changed_by"] == "bela"
    with caplog.at_level(logging.INFO, logger="jav.domains.email.mailbox"):
        assert c.post(f"/api/mailbox/schedules/{sid}/delete", json={}, headers={"X-Actor": "bela"}).status_code == 200
    assert f"mailbox schedule {sid} deleted by bela" in caplog.text


def test_a_store_from_before_gets_the_columns(tmp_path):
    path = tmp_path / "s.sqlite"
    with store.use_store(path):
        sch = mailbox.create_schedule(REQ, actor="anna")
        with store.connect() as c:
            c.execute("ALTER TABLE mailbox_schedules DROP COLUMN changed_by")
            c.execute("ALTER TABLE mailbox_schedules DROP COLUMN changed_at")
    store._initialized.pop(str(path), None)  # a new process: the structure check runs again
    with store.use_store(path):
        assert mailbox.schedule(sch["id"])["changed_by"] is None
        assert mailbox.update_schedule(sch["id"], actor="bela", interval_min=120)["changed_by"] == "bela"
