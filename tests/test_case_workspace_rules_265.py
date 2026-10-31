"""265 (code review X-22): the reconciliation workspace is built with the case's own rules, whoever asks for it.

A reconciliation case's page runs with the case's rules over the files (its own values and its kept copies of the rule
files, `capabilities.case_rules`), but the case list asked each case's next step with the files alone: the list showed a
next step computed with other rules, and the shared kept workspace was built again each time the other side asked
(the marks differed). Now the workspace is always built and marked with the case's rules, and a case's own values are
part of its mark. Synthetic data only; no AI call.
"""

from __future__ import annotations

from contextlib import contextmanager

from jav.app import capabilities
from jav.core import cfg
from jav.domains.finance import reconcile_package as rp
from tests.test_list_speed_140 import _workspace_package, db, fresh_caches  # noqa: F401 - the shared fixtures

CASE_VALUES = cfg.Overlay({"reconcile": {"window.days_after_due": 7}})


def _as_a_case(monkeypatch, wp: str, overlay: cfg.Overlay = CASE_VALUES) -> list[object]:
    seen: list[object] = []
    real = rp._workspace

    @contextmanager
    def case_rules(case_id):
        with cfg.overlay(overlay if case_id == wp else None):
            yield

    def counted(wp_id):
        seen.append(cfg.current_overlay())
        return real(wp_id)

    monkeypatch.setattr(capabilities, "case_rules", case_rules)
    monkeypatch.setattr(rp, "_workspace", counted)
    return seen


def test_the_list_builds_a_case_s_workspace_with_the_case_s_rules(db, monkeypatch):  # noqa: F811
    wp, _statement, _invoice = _workspace_package()
    seen = _as_a_case(monkeypatch, wp)
    rp.package_view(wp, keep_seconds=rp.LIST_KEEP_SECONDS)  # the case list: no case context of its own
    assert seen == [CASE_VALUES]


def test_the_page_and_the_list_share_one_kept_workspace(db, monkeypatch):  # noqa: F811
    wp, _statement, _invoice = _workspace_package()
    seen = _as_a_case(monkeypatch, wp)
    with capabilities.case_rules(wp):  # the case's page
        page = rp.kept_workspace(wp)
    listed = rp.kept_workspace(wp)  # the list, outside the case's context
    with capabilities.case_rules(wp):
        again = rp.kept_workspace(wp)
    assert len(seen) == 1 and listed is page and again is page


def test_a_case_s_own_values_are_part_of_its_mark(db, monkeypatch):  # noqa: F811
    wp, _statement, _invoice = _workspace_package()
    seen = _as_a_case(monkeypatch, wp)
    first = rp.kept_workspace(wp)
    monkeypatch.setattr(capabilities, "case_rules", _rules_of(cfg.Overlay({"reconcile": {"window.days_after_due": 9}})))
    second = rp.kept_workspace(wp)
    assert len(seen) == 2 and second is not first


def _rules_of(overlay: cfg.Overlay):
    @contextmanager
    def case_rules(_case_id):
        with cfg.overlay(overlay):
            yield

    return case_rules
