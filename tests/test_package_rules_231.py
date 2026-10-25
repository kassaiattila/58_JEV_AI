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


def test_a_package_of_a_logic_pack_keeps_its_kind_s_rule(db):
    from jav.domains.finance import statement_package

    wp = work.create_workpackage(name="Statements", source_kind=statement_package.KIND, source_ref=None, owner="t")["id"]
    assert work.package_rule(wp) is statement_package.RULE


def test_an_unknown_rule_name_is_refused():
    with pytest.raises(KeyError, match="no package rule named 'nothing'"):
        work.rule_named("nothing")


def test_registering_the_same_rule_again_adds_nothing_and_another_one_is_an_error():
    rule = work.rule_named("statements")
    work.register_rule("statements", rule)  # the same: nothing changes
    with pytest.raises(ValueError, match="registered already"):
        work.register_rule("statements", work.PackageRule())
