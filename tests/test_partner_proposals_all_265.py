"""265 (code review SEC-07): recording every partner proposal skips a bad one, and restoring names only the restored.

"Record all" caught only a proposal recorded meanwhile; one with a tax number too long or an empty name raised half
way, and a repeat stopped at the same place. Now such a proposal is skipped and counted. Restoring dismissed proposals
named every key asked for, restored or not; now only the restored ones. Synthetic data; no AI call.
"""

from __future__ import annotations

import pytest

from jav.app import partners
from jav.core import store


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "partners.sqlite"):
        yield tmp_path


def test_a_bad_proposal_is_skipped_and_the_rest_recorded(db, monkeypatch) -> None:
    shown = [{"key": "good", "name": "Example Kft", "tax_number": "12345676-2-41", "roles": ["supplier"]},
             {"key": "bad", "name": "", "tax_number": "1" * 300, "roles": ["supplier"]}]
    monkeypatch.setattr(partners, "suggestions", lambda limit=50: shown)
    out = partners.accept_suggestions(None, "anna")
    assert len(out["created"]) == 1 and out["skipped"] == 1


def test_restoring_names_only_what_was_dismissed(db, monkeypatch) -> None:
    monkeypatch.setattr(partners, "suggestions", lambda limit=50: [{"key": "k1", "name": "A", "tax_number": None, "roles": []}])
    partners.dismiss_suggestions(["k1"], "anna")
    assert partners.restore_suggestions(["k1", "never-dismissed"], "anna") == {"restored": ["k1"]}


def test_recording_every_proposal_is_one_transaction(db, monkeypatch) -> None:
    """272 (K4, the rest of APPR-13 and SEC-07): each proposal was recorded in a transaction of its own, so a stop half
    way left part of the list recorded. Now one transaction, each proposal in a savepoint of its own: a bad one is
    rolled back to its savepoint and skipped, the others are recorded together; two proposals of one tax number are
    one partner, as before."""
    shown = [{"key": "a", "name": "Example Kft", "tax_number": "12345676-2-41", "roles": ["supplier"]},
             {"key": "bad", "name": "", "tax_number": "1" * 300, "roles": ["supplier"]},
             {"key": "b", "name": "Other Kft", "tax_number": None, "roles": ["customer"]},
             {"key": "a2", "name": "Example Kft.", "tax_number": "12345676-2-41", "roles": ["supplier"]}]
    monkeypatch.setattr(partners, "suggestions", lambda limit=50: shown)
    assert partners.listing() == []  # the store opened (its first opening runs its own migrations)
    began: list[int] = []
    real = store.begin_immediate
    monkeypatch.setattr(store, "begin_immediate", lambda c: began.append(1) or real(c))
    out = partners.accept_suggestions(None, "anna")
    assert len(began) == 1
    assert len(out["created"]) == 2 and out["skipped"] == 2
    assert sorted(p["name"] for p in partners.listing()) == ["Example Kft", "Other Kft"]
