"""227 (backlog Q-reconcile-rule-fingerprint; DECISIONS 224, the owner's choice "only a change of content warns"): what
changed since a reconciliation's approval.

An approved statement holds the fingerprint of the reconciliation's rule file and the engine's version, and its
fingerprint (176) covers them. Comparing that fingerprint alone made every approved statement look changed whenever
the rule file changed, even with the same invoices, lines and results. The statement's answer now says what changed:
its content (a warning) or only the rules it was computed with (a note). Synthetic documents and made-up accounts
only; no AI call, no network.
"""

from __future__ import annotations

import pytest

from jav.domains.finance import reconcile, reconcile_statement as rs
from tests import test_api
from tests import test_reconcile_k2_129 as k2
from tests.test_reconcile_statement_145 import _world

env = test_api.env


@pytest.fixture
def db(tmp_path):
    from jav.core import store

    with store.use_store(tmp_path / "r.sqlite"):
        yield


def _approve(wp_id: str) -> str:
    view = rs.current(wp_id)
    rs.approve(wp_id, fingerprint=view["fingerprint"], actor="Reviewer")
    return view["fingerprint"]


def test_a_draft_has_nothing_to_compare(db):
    wp_id, _inv, _ids = _world()
    assert rs.current(wp_id)["since_approval"] is None


def test_an_unchanged_approval_reports_no_change(db):
    wp_id, _inv, _ids = _world()
    _approve(wp_id)
    assert rs.current(wp_id)["since_approval"] == {"content_changed": False, "rules_changed": False}


def test_a_changed_rule_file_is_a_note_not_a_change_of_content(db, monkeypatch):
    wp_id, _inv, _ids = _world()
    approved = _approve(wp_id)
    monkeypatch.setattr(reconcile, "config_hash", lambda: "0" * 16)
    view = rs.current(wp_id)
    assert view["fingerprint"] != approved  # the approval's own fingerprint stays as it was formed (176)
    assert view["since_approval"] == {"content_changed": False, "rules_changed": True}


def test_a_new_engine_version_is_a_note_not_a_change_of_content(db, monkeypatch):
    wp_id, _inv, _ids = _world()
    _approve(wp_id)
    monkeypatch.setattr(reconcile, "ENGINE_VERSION", f"{reconcile.ENGINE_VERSION}-next")
    assert rs.current(wp_id)["since_approval"] == {"content_changed": False, "rules_changed": True}


def test_a_document_processed_again_changes_the_content(db):
    wp_id, inv, _ids = _world()
    _approve(wp_id)
    k2._save("unpaid", k2._invoice(number="INV-0003", amount="350.00", payment_iban=None, supplier_name="Nobody Kft."),
             run_id=k2.RUN)
    assert rs.current(wp_id)["since_approval"] == {"content_changed": True, "rules_changed": False}
    assert inv["unpaid"]


def test_the_content_fingerprint_leaves_out_only_the_rules(db):
    wp_id, _inv, _ids = _world()
    content = rs.current(wp_id)["statement"]
    other = {**content, "config_hash": "0" * 16, "engine_version": "next"}
    assert rs.content_fingerprint(other) == rs.content_fingerprint(content)
    assert rs.content_fingerprint({**content, "party": "Someone else"}) != rs.content_fingerprint(content)
    older = {k: v for k, v in content.items() if k not in ("config_hash", "engine_version")}
    assert rs.content_fingerprint(older) == rs.content_fingerprint(content)  # a statement without the keys compares too


def test_the_service_answer_carries_what_changed(env):
    from tests.test_api import HUMAN

    c = env["client"]
    wp_id, _inv, _ids = _world()
    assert c.get(f"/api/workpackages/{wp_id}/reconcile/statement").json()["since_approval"] is None
    view = c.get(f"/api/workpackages/{wp_id}/reconcile/statement").json()
    r = c.post(f"/api/workpackages/{wp_id}/reconcile/approve", headers=HUMAN, json={"fingerprint": view["fingerprint"]})
    assert r.status_code == 200
    assert r.json()["since_approval"] == {"content_changed": False, "rules_changed": False}
