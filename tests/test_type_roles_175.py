"""175 (plan 170 E3): the roles of the document types, read from the lists that name them (`jav/core/type_roles.py`).

A type's role (incoming or outgoing invoice, statement, utility, the checks that look at it) is written in several
settings files. The adapter reads them unchanged; these tests check that the lists agree with each other and with the
type packs, so that a new type left out of one list fails here instead of silently missing a check.
"""

from __future__ import annotations

import pytest

from jav.app import parties
from jav.ai import doc_types
from jav.core import cfg, type_roles
from jav.domains.email import email_rules
from jav.domains.finance import duplicates, reconcile, report_utility
from jav.ai.typepack import get as get_pack

PACKS = sorted(p.stem for p in (cfg.path_of("policy").parent / "types").glob("*.json"))


def _packs_with_broad_type(*broad: str) -> set[str]:
    return {p for p in PACKS if get_pack(p).parent in broad}


def test_each_role_reads_its_list_in_order() -> None:
    assert type_roles.types("incoming_invoice") == tuple(cfg.load("reconcile")["invoice_types"])
    assert type_roles.types("outgoing_invoice") == tuple(cfg.load("reconcile")["outgoing_types"])
    assert type_roles.types("statement") == tuple(cfg.load("reconcile")["statement_types"])
    assert type_roles.types("own_tax_check") == tuple(cfg.load("parties")["supplier_check"]["doc_types"])
    assert type_roles.types("utility") == tuple(cfg.load("reports")["utility_cost"]["utilities"])
    assert type_roles.types("hungarian_issuer") == tuple(cfg.load("policy")["detect_issuer"]["hungarian_types"])
    assert type_roles.types("email_extraction") == tuple(cfg.load("email")["m2_types"])
    for side in ("incoming", "outgoing"):
        assert type_roles.types(f"direction:{side}") == tuple(cfg.load("policy")["detect_detail"]["direction_sides"][side])
    for family, members in cfg.load("duplicates")["families"].items():
        assert type_roles.types(f"duplicate:{family}") == tuple(members)


def test_a_type_answers_its_roles_and_an_unknown_role_is_named() -> None:
    assert type_roles.roles("invoice_out") == ("outgoing_invoice", "direction:outgoing", "duplicate:invoice")
    assert type_roles.has("statement_table", "statement") and not type_roles.has(None, "statement")
    assert type_roles.duplicate_family("proforma_invoice") == "proforma" and type_roles.duplicate_family("statement_cib") is None
    assert type_roles.source("duplicate:invoice") == "duplicates.json families.invoice"
    with pytest.raises(type_roles.UnknownRole):
        type_roles.types("invoice")
    with pytest.raises(type_roles.UnknownRole):
        type_roles.types("duplicate:nothing")


def test_the_readers_ask_the_roles() -> None:
    """The code that used to read its own list gives the same answer through the adapter."""
    assert duplicates.family("vizmuvek_szamla") == "invoice" and duplicates.family("nav_receipt") is None
    assert parties.supplier_check_types() == frozenset(cfg.load("parties")["supplier_check"]["doc_types"])
    assert reconcile.handles("invoice_foreign") and reconcile.handles("statement_erste") and not reconcile.handles("invoice_out")
    assert report_utility.has_utility([{"doc_type": "foldgaz_szamla"}]) and not report_utility.has_utility([{"doc_type": None}])
    assert email_rules.M2_TYPES == frozenset(cfg.load("email")["m2_types"])


# --- the lists agree with each other and with the type packs -----------------------------------------------------------


def test_every_type_a_role_names_exists() -> None:
    known = set(PACKS) | set(doc_types.DOC_TYPE_KEYS)
    for role in type_roles.names():
        assert set(type_roles.types(role)) <= known, (role, type_roles.source(role))


def test_an_incoming_invoice_is_in_the_own_tax_check_and_one_duplicate_family() -> None:
    incoming, outgoing = set(type_roles.types("incoming_invoice")), set(type_roles.types("outgoing_invoice"))
    assert not incoming & outgoing
    assert set(type_roles.types("own_tax_check")) == incoming
    families = type_roles.duplicate_families()
    for t in incoming | outgoing:
        assert sum(t in members for members in families.values()) == 1, t
    assert {t for members in families.values() for t in members} == incoming | outgoing


def test_a_utility_pack_is_a_utility_and_an_incoming_invoice() -> None:
    utility = set(type_roles.types("utility"))
    assert utility <= set(type_roles.types("incoming_invoice"))
    assert _packs_with_broad_type("utility_bill_hu") == utility


def test_a_bank_statement_pack_is_a_statement() -> None:
    assert _packs_with_broad_type("bank_statement") == set(type_roles.types("statement"))


def test_an_invoice_pack_is_an_incoming_or_an_outgoing_invoice() -> None:
    invoices = set(type_roles.types("incoming_invoice")) | set(type_roles.types("outgoing_invoice"))
    assert _packs_with_broad_type("invoice_hu", "invoice_foreign", "proforma_invoice", "utility_bill_hu") == invoices


def test_a_direction_side_is_an_invoice_of_that_direction() -> None:
    assert set(type_roles.types("direction:incoming")) <= set(type_roles.types("incoming_invoice"))
    assert set(type_roles.types("direction:outgoing")) <= set(type_roles.types("outgoing_invoice"))
