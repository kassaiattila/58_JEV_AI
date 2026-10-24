"""224 (plan G-process-core P3c): the shared rule file keeps the shared rules; a domain's rules live in its own file.

Plain-language summary: `configs/policy.json` keeps what every flow shares (the bands, the "none of these" label, the
OCR thresholds, the type details, a GPT field's confidence). The email flow's routes are in `configs/email.json`, read
by the email domain (`jav/domains/email/email_rules.py`); the duplicate search and the reconciliation's currency
bands and sure AI threshold in the finance domain's `configs/finance.json`, read by `jav/domains/finance/duplicates.py`
and `jav/domains/finance/reconcile.py`. So a change to one domain's rules no longer changes the fingerprint of another's
results, and the shared AI layer no longer imports the email domain. The values themselves did not change, and neither
did `configs/reconcile.json`, whose fingerprint a reconciliation's statement prints: an approved statement does not
read as changed.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from jav.core import cfg

JAV = Path(__file__).resolve().parents[1] / "jav"
SHARED = {"meta", "none_label", "ocr", "bands", "band_for", "detect_detail", "detect_issuer", "gpt_field_confidence"}


def _readers(name: str) -> set[str]:
    """The modules that load the config `name` by its name."""
    pattern = re.compile(r"""cfg\.load\(\s*["']""" + re.escape(name) + r"""["']\s*\)""")
    return {p.relative_to(JAV.parent).as_posix() for p in JAV.rglob("*.py")
            if "__pycache__" not in p.parts and pattern.search(p.read_text(encoding="utf-8"))}


def test_the_shared_rule_file_keeps_only_the_shared_rules():
    assert set(cfg.load("policy")) == SHARED


def test_the_email_routes_are_the_email_domains_with_their_values():
    from jav.domains.email import email_rules

    e = cfg.load("email")
    assert e["meta"]["version"] == "1.0.0"
    assert e["intent_route"]["szamlakuldes"] == "human:fetch_document" and e["intent_route"]["other"] == "human:inbox"
    assert (e["low_conf_route"], e["needs_ocr_route"], e["detect_route"], e["default_route"]) == (
        "human:low_confidence", "m2:needs_ocr", "m1:detect", "human:inbox")
    assert (e["jev_unavailable_route"], e["sent_route"]) == ("human:jev_unavailable", "archive:sent")
    assert e["signal_review"] == ["prompt_injection"] and e["signal_routes"] == {"prompt_injection": "human:suspicious"}
    assert email_rules.INTENT_ROUTE == e["intent_route"] and email_rules.CONFIG_HASH == cfg.config_hash("email")


def test_the_duplicate_rules_are_the_finance_domains_with_their_values():
    from jav.domains.finance import duplicates

    f = cfg.load("finance")
    assert f["meta"]["version"] == "1.0.0"
    d = f["duplicates"]
    assert list(d["families"]) == ["invoice", "proforma"] and d["families"]["proforma"] == ["proforma_invoice"]
    assert (d["number_field"], d["supplier_tax_field"], d["supplier_name_field"]) == (
        "invoice_number", "supplier_tax_id", "supplier_name")
    assert d["compared_fields"] == ["issue_date", "gross_total", "currency"]
    assert duplicates.config_hash() == cfg.config_hash("finance")


def test_the_reconciliations_bands_are_the_finance_domains_and_its_statement_is_unchanged():
    from jav.domains.finance import reconcile

    r = cfg.load("finance")["reconcile"]
    assert r["fx_tolerance"] == {"below": "0.02", "above": "0.05"} and r["ai_sure"] == {"min_jev_probability": 0.95}
    assert reconcile.fx_tolerance() == (Decimal("0.02"), Decimal("0.05"))
    assert reconcile.fx_bank_tolerance("fulfillment") == (Decimal("0.005"), Decimal("0.005"))
    assert reconcile.fx_bank_tolerance("booking") == (Decimal("0.02"), Decimal("0.02"))
    assert reconcile.ai_sure_probability() == 0.95
    # not in the reconciliation's own file: its fingerprint is printed on a statement (`tests/test_characterisation_176.py`
    # fixes an approval's fingerprint), so an approved statement does not read as changed
    assert not {"fx_tolerance", "fx_bank_tolerance", "ai_sure"} & set(cfg.load("reconcile"))


def test_each_domain_file_is_read_by_its_owner_and_the_type_roles_only():
    roles = "jav/core/type_roles.py"
    # 227 (plan R3c): the OCR module reads the shared file's `ocr` section, the OCR quality thresholds, for the rules
    # in the documents layer and for the decision rules alike
    assert _readers("policy") == {"jav/ai/policy.py", "jav/documents/ocr.py", roles}
    assert _readers("email") == {"jav/domains/email/email_rules.py", roles}
    assert _readers("finance") == {"jav/domains/finance/duplicates.py", "jav/domains/finance/reconcile.py", roles}


def test_the_shared_ai_layer_no_longer_holds_the_email_routes():
    from jav.ai import policy

    for name in ("email_next_flow", "email_sent_route", "email_signal_reasons", "email_signal_route", "INTENT_ROUTE",
                 "EMAIL_JEV_UNAVAILABLE_ROUTE", "EMAIL_SENT_ROUTE", "EMAIL_SIGNAL_REVIEW", "EMAIL_SIGNAL_ROUTES",
                 "M2_TYPES", "RECONCILE", "reconcile_fx_tolerance", "reconcile_fx_bank_tolerance"):
        assert not hasattr(policy, name), name
    source = (JAV / "ai" / "policy.py").read_text(encoding="utf-8")
    assert "jav.domains" not in source


def test_the_decision_points_name_the_files_they_read_now():
    from jav.app import registrations
    from jav.core import trace

    registrations.load_all()
    assert trace.point("email.intent").files == ("policy.json", "email.json")
    assert trace.point("email.next_flow").files == ("policy.json", "email.json")
    assert trace.point("finance.duplicate").files == ("finance.json", "fact_checks.json")
    help_ = cfg.load("rule_help")
    assert {"email.json", "finance.json"} <= set(help_["files"])
