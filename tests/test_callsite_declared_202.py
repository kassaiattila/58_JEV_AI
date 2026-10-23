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

from jav.ai import jev_select, jev_verify
from jav.core import cfg
from jav.documents.layout import CellLayout, LineLayout
from jav.ai.typepack import get as get_pack

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


def test_a_type_without_an_s_path_gets_one_from_configuration_alone(monkeypatch, tmp_path):
    """After M2a a new type's S path needs no code: its type pack names an S call site, and the call site says its
    questions, its requests and their lines. Shown on the terms and conditions' pack with an invented call site and a
    stand-in JEV; whether such a path is good enough is a measurement on the type's golden set (M2c)."""
    from typesafe_sdk import Choice

    from jav.core import store
    from jav.ai.jev import JevAdapter
    from jav.ai.candidates import find_all
    from tests.test_select_presence import FakeClient

    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "t.sqlite")
    pack = get_pack("altalanos_szerzodesi_feltetelek").model_copy(update={"select_callsite": "select_terms_test", "arms": ("S", "G")})
    fields = {"seller_name": "name", "effective_date": "date"}
    site_config = {
        "glossary": "Terms and conditions glossary: hatályos = in force from.",
        "none_description": "the {what} is not among the options",
        "document": "General terms and conditions, selected lines (Lnn = line number)",
        "field_kind": dict(fields),
        "instructions": {f: f"Which option is the document's {f.replace('_', ' ')}?" for f in fields},
        "presence_template": "Is the {what} printed on the document?",
        "presence_what": {f: f.replace("_", " ") for f in fields},
        "extra_questions": {},
        "requests": {"issuer": {"fields": ["seller_name"], "kinds": ["name"], "extra_lines": {"top_fraction": 0.5}},
                     "validity": {"fields": ["effective_date"], "kinds": ["date"]}},
    }
    monkeypatch.setattr(cfg, "load", lambda name: site_config if name == "callsite:select_terms_test" else REAL_LOAD(name))
    lines = [LineLayout(no=i, page=1, text=t, cells=[CellLayout(text=t, x0=30, x1=300)]) for i, t in enumerate(
        ["Általános Szerződési Feltételek", "Példa Szolgáltató Kft.", "1. Hatály", "Hatályos: 2025.03.01-től"], 1)]
    client = FakeClient()  # it chooses each question's first option
    site = jev_select.SelectSite(pack)
    cands = find_all(lines, pack.candidate_profile, text_labels=pack.text_labels)
    picks, _calls = site.select_fields(JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0"), lines, cands, run_id="r")
    record, _reasons = site.picks_to_record(picks, cands, lines)
    assert [r["state"]["document"] for r in client.requests] == [site_config["document"]] * 2
    assert all(isinstance(r["questions"][f], Choice) for r, f in zip(client.requests, fields))
    assert str(record.get_field("effective_date")) == "2025-03-01"
    assert record.get_field("seller_name") == cands["name"][0].label
    assert "Példa Szolgáltató Kft." in {c.label for c in cands["name"]}
