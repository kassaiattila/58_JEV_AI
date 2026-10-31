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
