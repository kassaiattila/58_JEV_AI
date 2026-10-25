"""The logic pack registry (176, plan 170 L3).

Plain-language summary: the reconciliation package and the statement package are described once, in a registry, and the
shared code asks it instead of naming them. These tests check the registry's rules (a plain processing kind is no logic
package, every input role has a known source, a package without runs answers for its own approval), that a package of
an unknown kind is refused instead of being treated as an ordinary one, that a kind's delete guard runs only for its
own packages, and that the shared modules, the local service and the interface name no logic pack kind.

Synthetic packages only; no AI call, no network.
"""

from __future__ import annotations

import re
import pytest

from jav.app import logic_packs as lp, work, work_views
from jav.core import store
from jav.core.config import PROJECT_ROOT


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "l.sqlite"):
        yield tmp_path


@pytest.fixture
def probe(monkeypatch):
    """A registry with one made-up logic pack of runs (`probe`), apart from the registered ones."""
    calls: list[str] = []
    monkeypatch.setattr(lp, "_PACKS", dict(lp._PACKS))
    lp.register(lp.LogicPack(kind="probe", module=__name__, roles=(lp.InputRole("documents", "own_items", "made up"),),
                                delete_guard=lambda c, wp_id: calls.append(wp_id)))
    return calls


ROLE = (lp.InputRole("x", "own_items", "made up"),)


def test_the_logic_pack_and_its_roles() -> None:
    statements = lp.of("statements")  # 231 (C3a-2): the reconciliation's went (a reconciliation is a process pack's case)
    assert statements.has_runs is True
    assert [(r.name, r.source) for r in statements.roles] == [("statements", "own_items")]
    assert statements.rule is not None
    assert lp.kinds_without_runs() == ()  # 231 (A3d): no quote package; (C1c) no routing; (C3a-2) no reconciliation
    assert all(lp.of(kind) is None and lp.has_runs(kind) for kind in lp.DATA_KINDS)


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(lp.UnknownKind, match="load_all"):
        lp.of("offer")
    with pytest.raises(lp.UnknownKind):
        lp.has_runs("offer")


@pytest.mark.parametrize("make, message", [
    (lambda: lp.LogicPack(kind="folder", module="m", roles=ROLE), "plain processing kind"),
    (lambda: lp.LogicPack(kind="x", module="m", roles=()), "input role"),
    (lambda: lp.LogicPack(kind="x", module="m", roles=(lp.InputRole("x", "somewhere", "?"),)), "input role"),
    (lambda: lp.LogicPack(kind="x", module="m", roles=ROLE, has_runs=False), "without runs needs"),
    (lambda: lp.LogicPack(kind="x", module="m", roles=ROLE, has_runs=False, rule=object(), page=dict,
                             approved=bool, next_step=dict, list_next=dict, release_refusal=Exception), "no rule"),
])
def test_a_logic_pack_is_described_completely(make, message) -> None:
    with pytest.raises(ValueError, match=message):
        make()


def test_a_kind_is_registered_once(monkeypatch) -> None:
    monkeypatch.setattr(lp, "_PACKS", {})
    one = lp.LogicPack(kind="x", module="a", roles=ROLE)
    lp.register(one)
    lp.register(one)  # the same again adds nothing
    assert lp.packs() == [one]
    with pytest.raises(ValueError, match="registered already by a"):
        lp.register(lp.LogicPack(kind="x", module="b", roles=ROLE))


def test_a_kinds_delete_guard_runs_for_its_own_packages_only(db, probe) -> None:
    own = work.create_workpackage(name="probe", source_kind="probe", source_ref=None)
    plain = work.create_workpackage(name="plain", source_kind="manual", source_ref=None)
    work.delete_workpackage(plain["id"], actor="t")
    work.delete_workpackage(own["id"], actor="t")
    assert probe == [own["id"]]


def test_a_package_of_an_unknown_kind_is_neither_shown_nor_deleted(db) -> None:
    wp = work.create_workpackage(name="later", source_kind="offer", source_ref=None)
    with pytest.raises(lp.UnknownKind):
        work_views.workpackage_view(wp["id"])
    with pytest.raises(lp.UnknownKind):
        work.delete_workpackage(wp["id"], actor="t")
    assert work.get(wp["id"])["name"] == "later"  # nothing was deleted


# --- the shared code names no logic pack kind ---------------------------------------------------------------------------

SHARED = ("jav/app/work.py", "jav/app/work_views.py", "jav/app/package_release.py", "jav/app/datasets.py", "jav/runtime/worker.py")
# a comparison of a package's kind with a logic pack's kind ("reconcile", "statements")
NAMED = re.compile(r"source_kind[\"'\]]*\)?\s*(==|!=|in|not in)\s*\(?[\"'](reconcile|statements)[\"']")


@pytest.mark.parametrize("path", SHARED)
def test_the_shared_code_asks_the_registry(path: str) -> None:
    text = (PROJECT_ROOT / path).read_text(encoding="utf-8")
    assert not NAMED.search(text), f"{path} names a logic pack kind: {NAMED.search(text).group(0)}"


def test_the_workflows_ask_the_registry_for_a_packages_state() -> None:
    """The package-level questions (is the step done, what is its next step) go through the registry; the step kinds
    of `configs/workflows.json` (documents, emails, statements, reconcile) stay the workflow's own (plan 170 L5)."""
    text = (PROJECT_ROOT / "jav/app/workflows.py").read_text(encoding="utf-8")
    assert not NAMED.search(text)


def test_the_service_has_the_addresses_of_every_logic_pack_in_its_own_module() -> None:
    """185 (plan G-full-move T1a): each logic pack names its module (`LogicPack.service`); the service adds them first,
    in the order the packs are registered, then each domain's others."""
    import importlib

    from jav.service import api
    from jav.domains import DOMAINS

    own = [p.service for p in lp.packs()]
    # 231 (C1c): the email routing's addresses are its domain's (its logic pack went: a routing is a process pack's case)
    assert own == ["jav.domains.finance.api_statement_package"]  # (C3a-2): the reconciliation's are the domain's
    domains = [name for d in DOMAINS for name in importlib.import_module(d).SERVICE]
    # 191: quotes; 231 (A3d): the quote's own addresses (a case's page uses them) are the domain's since its logic pack went
    assert domains == ["jav.domains.finance.api_reconcile", "jav.domains.finance.api_parties", "jav.domains.finance.api_finance",
                       "jav.domains.email.api_mailbox",
                       "jav.domains.email.api_email_routing", "jav.domains.quotes.api_quote_package", "jav.domains.quotes.api_price_lists"]
    assert api.service_modules() == [*own, *domains]
    assert all(callable(importlib.import_module(name).routes) for name in api.service_modules())
    text = (PROJECT_ROOT / "jav/service/api.py").read_text(encoding="utf-8")
    assert not re.search(r"\breconcile_package\.|\bstatement_package\.|/reconcile|/statement-packages", text)
    # 185: nor a domain's other addresses (which modules it imports: `tests/test_dependency_direction.py`)
    assert not re.search(r"\"/mailbox|\"/parties|\"/statement-tables|/utility-cost\"|\"/bank-files|/attachments\"|"
                         r"/tasks/|/duplicates/|/statements/", text)

def test_the_interface_has_an_entry_for_every_logic_pack() -> None:
    text = (PROJECT_ROOT / "ui/src/logic/registry.tsx").read_text(encoding="utf-8")
    entries = set(re.findall(r"^  (\w+): \{$", text, re.MULTILINE))
    assert entries == {p.kind for p in lp.packs()}


@pytest.mark.parametrize("path", ["ui/src/views/WorkpackageDetail.tsx", "ui/src/views/WorkpackageActions.tsx",
                                  "ui/src/views/PackageItems.tsx"])
def test_the_interface_asks_its_registry(path: str) -> None:
    text = (PROJECT_ROOT / path).read_text(encoding="utf-8")
    assert not re.search(r"source_kind\s*===?\s*\"(reconcile|statements)\"", text)
    assert not re.search(r"case \"(reconcile|statements)\"", text)
