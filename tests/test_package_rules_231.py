"""231 (plan stage C, C3b1; DECISIONS 231): a package rule by name.

What a package adds to the processing of its items (a statement package: stop at a document that is no statement,
check the account, read the months once its run is approved) was its kind's, through its logic pack. A domain now also
registers it by name (`work.register_rule`), and a plain processing package whose stored scope names it (the scope
part `rule`) runs by it, so a process pack's step can own a processing package that reads statements without a kind
of its own. An unknown name is refused when it is asked (`KeyError`), never silently ignored. Synthetic packages only.
"""

from __future__ import annotations

import pytest

from jav.app import package_scope, registrations, work
from jav.core import store
from tests.statement_pdf import pdf_lines_as_text

registrations.load_all()


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "rules.sqlite"):
        yield


def _plain(name: str = "Plain") -> str:
    return work.create_workpackage(name=name, source_kind="manual", source_ref=None, owner="t")["id"]


def test_the_statements_rule_is_registered_by_name_as_well():
    from jav.domains.finance import statement_package

    assert work.rule_named("statements") is statement_package.RULE
    assert "statements" in work.rule_names()


def test_a_plain_package_whose_scope_names_a_rule_runs_by_it(db):
    from jav.domains.finance import statement_package

    wp = _plain()
    assert work.package_rule(wp) is None  # a plain package adds nothing
    with store.connect() as c:
        store.begin_immediate(c)
        package_scope.save(c, wp, parts={work.RULE_PART: "statements"}, actor="t")
    assert work.package_rule(wp) is statement_package.RULE


def test_a_statement_package_is_made_a_plain_package_of_its_rule(db, tmp_path, monkeypatch):
    """C3b5a: its logic pack went; a statement package runs by its rule, named in its scope."""
    from jav.domains.finance import statement_package
    from tests.test_workflows_146 import MONTH, _party, _statements

    pdf_lines_as_text(monkeypatch)  # as 146's
    wp = statement_package.make_for_case({"party": _party(), "period": list(MONTH),
                                          "source": {"kind": "folder", "folder": str(_statements(tmp_path / "erste"))}},
                                         "June statements", "t")
    assert work.get(wp)["source_kind"] == "manual" and work.rule_name(wp) == "statements"
    assert work.package_rule(wp) is statement_package.RULE


def test_an_unknown_rule_name_is_refused():
    with pytest.raises(KeyError, match="no package rule named 'nothing'"):
        work.rule_named("nothing")


def test_registering_the_same_rule_again_adds_nothing_and_another_one_is_an_error():
    rule = work.rule_named("statements")
    work.register_rule("statements", rule)  # the same: nothing changes
    with pytest.raises(ValueError, match="registered already"):
        work.register_rule("statements", work.PackageRule())


# --- 231 (C3b5a): what the statement logic pack gave its kind, a plain package gets from its rule ----------------------


def _statement_rule_package(party: str) -> str:
    wp = _plain("June statements")
    with store.connect() as c:
        store.begin_immediate(c)
        package_scope.save(c, wp, party_id=party, period_start="2026-06-01", period_end="2026-06-30",
                           role="statements", parts={work.RULE_PART: "statements"}, actor="t")
    return wp


def test_a_plain_package_of_the_statements_rule_shows_its_page_part_and_keeps_its_scope(db):
    from jav.app import parties, work_views

    party = parties.create("Example Kft.", identities=[], actor="t")["id"]
    wp = _statement_rule_package(party)
    view = work_views.workpackage_view(wp)
    assert view["statements"]["scope"]["party_id"] == party and view["statements"]["statements"] == []
    assert package_scope.scope_of(wp)["from"] == "logic_pack"  # the rule's own scope, shown as a logic pack's was
    with pytest.raises(package_scope.ScopeRefused):
        package_scope.set_scope(wp, party_id=party, period_start=None, period_end=None, role_name=None, actor="t")
    package_scope.clear_scope(wp, actor="t")
    assert package_scope.stored(wp)["party_id"] == party  # a person cannot take it away


def test_the_shared_adding_refuses_a_package_of_the_statements_rule(db, tmp_path):
    from jav.app import parties

    wp = _statement_rule_package(parties.create("Example Kft.", identities=[], actor="t")["id"])
    doc = tmp_path / "invoice.pdf"
    doc.write_bytes(b"%PDF-1.4\n% synthetic\n%%EOF\n")
    with pytest.raises(ValueError, match="through its survey"):
        work.add_to_package(wp, [doc], expected_revision=work.get(wp)["revision"], actor="t")


def test_a_role_holds_the_packages_of_its_rule():
    role = package_scope.Role("x", __name__, "X", lambda t, d: True, ("manual",), rule="statements")
    assert role.holds("manual", "statements") and not role.holds("manual", None) and not role.holds("folder", "statements")
    plain = package_scope.Role("y", __name__, "Y", lambda t, d: True, ("manual",))
    assert plain.holds("manual", None) and not plain.holds("manual", "statements")  # an invoice never in a statement package
