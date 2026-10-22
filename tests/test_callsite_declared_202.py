"""The JEV call sites declare what the code used to infer from a request's name (202, plan G-core-generalisation M2a).

Plain-language summary: the S path's call site used to decide from a request's name which lines go into it ("parties":
the top of the document, "money": the payment-method lines) and where an extra question belongs ("money"), and a call
site without its own document description or document-level questions got the Hungarian invoice's. Each call site now
says these itself, so a new type's call site is configuration only, and what a non-invoice type inherits from the
invoice is visible in the configuration. The requests sent to JEV are unchanged: the configuration states what the code
did before.

No AI call, no store.
"""

from __future__ import annotations

import copy

import pytest

from jav import cfg, jev_select, jev_verify
from jav.models import LineLayout
from jav.typepack import get as get_pack

SELECT_SITES = ("select", "select_foreign", "select_invoice_out", "select_utility")


@pytest.mark.parametrize("name", SELECT_SITES)
def test_every_select_site_declares_its_document_and_where_its_extra_questions_go(name):
    data = cfg.load(f"callsite:{name}")
    assert data["document"]
    assert {q["request"] for q in data["extra_questions"].values()} <= set(data["requests"])


def test_the_invoice_requests_declare_the_lines_they_took_by_name():
    requests = cfg.load("callsite:select")["requests"]
    assert requests["parties"]["extra_lines"] == {"top_fraction": 0.45}
    assert requests["money"]["payment_method_lines"] is True
    for name in SELECT_SITES:
        for rid, r in cfg.load(f"callsite:{name}")["requests"].items():
            assert r.get("payment_method_lines", False) is rid.endswith("money"), (name, rid)


def _lines(n: int) -> list[LineLayout]:
    texts = [f"line {i}" for i in range(n)]
    texts[n - 2] = "Fizetési mód: átutalás"
    return [LineLayout(no=i + 1, page=1, text=t) for i, t in enumerate(texts)]


REAL_LOAD = cfg.load


def _site(monkeypatch, change) -> jev_select.SelectSite:
    data = copy.deepcopy(REAL_LOAD("callsite:select"))
    change(data["requests"])
    monkeypatch.setattr(cfg, "load", lambda name: data if name == "callsite:select" else REAL_LOAD(name))
    return jev_select.SelectSite(get_pack("invoice_hu"))


def test_a_request_takes_only_the_lines_its_call_site_declares(monkeypatch):
    lines = _lines(20)

    def undeclared(requests):
        requests["parties"].pop("extra_lines")
        requests["money"].pop("payment_method_lines")

    site = _site(monkeypatch, undeclared)
    assert site._lines_for("parties", lines, {}) == set()
    assert site._lines_for("money", lines, {}) == set()

    def renamed(requests):
        requests["seller_block"] = requests.pop("parties")
        requests["totals"] = requests.pop("money")

    site = _site(monkeypatch, renamed)
    assert site._lines_for("seller_block", lines, {}) == set(range(9))  # the top 45% of 20 lines
    assert site._lines_for("totals", lines, {}) == {18}  # the payment-method line (index of "Fizetési mód")


def test_the_verify_site_declares_its_document_and_document_questions():
    data = cfg.load("callsite:verify")
    assert data["document"] == "Hungarian supplier invoice"
    assert data["document_nouls"] == ["parties_swapped", "line_items_missing_rows", "line_items_extra_rows"]
    assert not hasattr(jev_verify, "DOCUMENT_NOULS")


def test_a_non_invoice_type_inherits_the_invoice_document_questions_visibly():
    """What 189 found (every type is asked whether the parties are swapped and line items are missing) is now stated by
    `verify.json`, which every other verify call site inherits; changing it is a new request and a paid measurement."""
    site = jev_verify.site_for("altalanos_szerzodesi_feltetelek")
    assert "document_nouls" not in cfg.load("callsite:verify_altalanos_szerzodesi_feltetelek")
    assert site.document_nouls == ("parties_swapped", "line_items_missing_rows", "line_items_extra_rows")
