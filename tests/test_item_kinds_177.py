"""177 (plan 170 E5): the item and source kind registry (`jav/app/item_kinds.py`).

What each kind of item and of package source means to the shared code is written once; the recipes, the workflows,
the logic pack registry and the labels agree with it; the email domain's rule after every item (a suspicious email's
attachments) and the mailbox package's page part are registered by the email domain, and asking for them before it
registered is an error. No calls.
"""

from __future__ import annotations

import pytest

from jav.app import item_kinds as ik, logic_packs, work_recipes, workflow_steps
from jav.core import cfg
from jav.domains.email import mailbox
from jav.domains import email as email_domain


def test_the_three_item_kinds_and_what_each_means():
    assert ik.names() == ("document", "email", "statement_table")
    doc, mail, table = (ik.of(k) for k in ik.names())
    assert (doc.copied, doc.record, doc.detected, doc.page_image, doc.attachments) == (True, True, True, True, False)
    assert (mail.copied, mail.record, mail.detected, mail.page_image, mail.attachments) == (False, False, False, False, True)
    assert (table.copied, table.record, table.detected, table.page_image, table.attachments) == (True, True, False, False, False)
    assert [k.plan_key for k in ik.ITEM_KINDS] == ["documents", "emails", "statement_tables"]
    assert [k.by_code for k in ik.ITEM_KINDS] == [False, False, True]


def test_an_unknown_item_kind_is_refused():
    with pytest.raises(ik.UnknownItemKind, match="unknown item kind: kep"):
        ik.of({"kind": "kep"})
    with pytest.raises(ik.UnknownItemKind):
        ik.of({"item_id": "x"})  # an item without a kind: every stored item has one
    with pytest.raises(ik.UnknownItemKind, match="unknown item kind: hang, kep"):
        ik.check(["kep", "document", "hang", "kep"])
    assert issubclass(ik.UnknownItemKind, ValueError)  # the service answers 422, as before


def test_every_recipe_routes_only_registered_item_kinds():
    for r in work_recipes.recipes():
        assert set(r.get("input_kinds") or []) <= set(ik.names()), r["id"]
        assert set(r.get("flows") or {}) <= set(ik.names()), r["id"]


def test_the_source_kinds_are_the_plain_processing_kinds():
    assert ik.source_names() == ("folder", "upload", "mailbox", "manual", "watch")
    assert logic_packs.DATA_KINDS == ik.source_names()
    assert {s.name for s in ik.SOURCE_KINDS if s.folder} == {"folder", "watch"}
    assert not set(ik.source_names()) & {p.kind for p in logic_packs.packs()}
    with pytest.raises(ik.UnknownSourceKind):
        ik.source("reconcile")  # a logic pack's kind is not a source kind


def test_a_workflow_step_takes_packages_of_known_kinds_only():
    known = set(ik.source_names()) | {p.kind for p in logic_packs.packs()}
    for step in workflow_steps.kinds():  # 181: the step kinds' registry (until then `workflows.PACKAGE_KINDS`)
        assert set(step.package_kinds) <= known


# a package of this kind is never made (plan 170, 9.4: the kind is listed, nothing creates it); its label waits
UNLABELLED = {"upload"}


def test_every_package_kind_has_a_label():
    labels = cfg.load("datasets")["labels"]["source_kind"]
    kinds = set(ik.source_names()) | {p.kind for p in logic_packs.packs()}
    assert kinds - UNLABELLED <= set(labels)


def test_the_email_domain_registers_its_rule_and_the_mailbox_page_part():
    # 180 (plan 170 E7): registered by the email domain module; the work stays in the mailbox module
    assert [(r.kind, r.name, r.module) for r in ik.rules()] == [("email", "suspicious_email_source", "jav.domains.email")]
    assert ik.rules()[0].after_item is mailbox.mark_suspicious_source
    assert ik.claimed_by("email") == ik.source_claimed_by("mailbox") == "jav.domains.email"  # 229 (MD1): claimed


def test_asking_before_the_email_domain_registered_is_an_error(monkeypatch):
    monkeypatch.setattr(ik, "_REGISTERED", set())
    with pytest.raises(ik.NotRegistered, match="jav.domains.email"):
        ik.rules()
    with pytest.raises(ik.NotRegistered):
        ik.page({"source_kind": "mailbox", "items": []})
    assert ik.page({"source_kind": "folder", "items": []}) == {}  # a source that adds nothing owes nothing


def test_a_rule_or_a_page_part_only_from_the_module_that_owes_it():
    rule = ik.ItemRule(kind="email", name="masik", module="jav.app.work", after_item=lambda run, item: False)
    with pytest.raises(ValueError, match="come from jav.domains.email"):
        ik.register_rule(rule)
    with pytest.raises(ValueError, match="comes from"):
        ik.register_page("folder", "jav.app.work", lambda wp: {})
    with pytest.raises(ValueError, match="registered already"):
        ik.register_rule(ik.ItemRule(kind="email", name="suspicious_email_source", module="jav.domains.email",
                                     after_item=lambda run, item: False))
    email_domain.register()  # the same registrations again add nothing (180: the email domain's, until then mailbox's)
    assert len(ik.rules()) == 1
