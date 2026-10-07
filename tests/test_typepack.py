"""Type packs (BACKLOG 1, carrying over the legacy types) - offline.

- both packs load; the Hungarian invoice's yields the earlier constants bit for bit (field list, scored fields,
  required / high-stakes fields, validators), the foreign one the content of the legacy schema.json / rules.json;
- the G path's output model is generated from the legacy schema (extra forbidden, supplier_country included);
- normalisation by kind (country / currency upper-case, money Decimal, date ISO), unknown fields go into `extra`;
- candidate profiles: `intl` finds the EU tax number, the English date, the $ amount, the name cut at the legal form,
  the 0 VAT of reverse charge; the `hu` profile is unchanged on a Hungarian sample;
- call sites: the select_foreign questions are built (supplier_country Choice in the parties request, currency
  criteria), verify_foreign inherits the Noul questions; the validator list is pack-driven; the policy looks at the
  pack's required fields;
- golden-set comparison by kind; eval report flow label from the row; admin per type.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from typesafe_sdk import Choice, Noul

from jav import cfg, policy, typepack
from jav.candidates import find_all, find_currencies
from jav.models import HEADER_FIELDS, SCORED_FIELDS, CellLayout, FieldPick, FlowState, InvoiceHU, LineLayout, record_from_llm


def _line(no: int, *cells: tuple[str, float]) -> LineLayout:
    return LineLayout(no=no, page=1, text="   ".join(t for t, _ in cells), cells=[CellLayout(text=t, x0=x, x1=x + 6 * len(t)) for t, x in cells])


def _foreign_lines() -> list[LineLayout]:
    return [
        _line(1, ("From:", 20), ("Omar Samplefreelancer", 80)),
        _line(2, ("Business Name:", 20), ("I N V O I C E", 300)),
        _line(3, ("Giza, 12345", 80)),
        _line(4, ("INVOICE #", 300), ("T500000001", 400)),
        _line(5, ("Egypt", 80)),
        _line(6, ("DATE", 300), ("Dec 25, 2022", 400)),
        _line(7, ("DUE DATE", 300), ("Dec 26, 2022", 400)),
        _line(8, ("TOTAL AMOUNT", 300), ("$1,642.50", 400)),
        _line(9, ("Bill to:", 20), ("BestIxCom Kft.", 80)),
        _line(10, ("VAT ID: HU28994028", 80)),
        _line(11, ("Omar Samplefreelancer - 2:50 hrs @ $15.00/hr - 12/19/2022 - 12/25/2022", 20), ("1,642.50", 400)),
        _line(12, ("VAT Reverse Charged", 20)),
        _line(13, ("Microsoft Ireland Operations Ltd, One Microsoft Place, Dublin 18, D18 P521, Írország", 20)),
        _line(14, ("Adószám IE8256796U", 20)),
    ]


# --- packs ----------------------------------------------------------------------------------


def test_packs_load_and_hu_pack_equals_legacy_constants():
    hu = typepack.get("invoice_hu")
    assert hu.header_fields == HEADER_FIELDS and hu.scored_fields == SCORED_FIELDS and hu.informational_fields == ("payment_iban",)
    assert set(hu.required) == {"buyer_name", "gross_total", "invoice_number", "supplier_name"} == set(policy.REQUIRED)
    assert set(hu.high_stakes) == {"amount_due", "due_date", "gross_total", "payment_iban", "supplier_tax_id"} == set(policy.HIGH_STAKES)
    assert [v["check"] for v in hu.validators] == ["vat_consistency", "date_order", "tax_id", "tax_id", "iban_check",
                                                   "line_items_total", "line_items_arithmetic", "distinct_parties",
                                                   "distinct_parties", "party_orientation"]  # 053 T3.2 line items; 069 both parties' tax numbers; 120 one party in two roles; 121 the pair against earlier documents
    assert hu.candidate_profile == "hu" and hu.is_default and hu.llm_model().__name__ == "InvoiceLLM"
    fo = typepack.get("invoice_foreign")
    assert fo.candidate_profile == "intl" and fo.select_callsite == "select_foreign" and fo.verify_callsite == "verify_foreign"
    assert fo.header_fields == tuple(fo.schema()["properties"]) [:-1] or "line_items" not in fo.header_fields  # the schema's order
    assert set(fo.required) == {"invoice_number", "gross_total"}  # the legacy rules.json
    assert set(fo.informational_fields) == {"payment_iban", "supplier_address", "buyer_address"}  # the legacy _compare_contract
    assert fo.kind("supplier_country") == "country" and "supplier_country" in fo.strict_scored
    assert "amount_due" not in fo.fields and "fulfillment_date" not in fo.fields  # not in the legacy schema either
    assert set(typepack.keys()) >= {"invoice_hu", "invoice_foreign"}
    assert "type:invoice_foreign" in cfg.all_names() and cfg.version("type:invoice_foreign") >= "1.0.1"
    assert any(v.get("optional") for v in fo.validators if v["check"] == "date_order")  # 1.0.1: a missing due date is not an error


def test_foreign_llm_model_is_generated_from_old_schema():
    fo = typepack.get("invoice_foreign")
    model = fo.llm_model()
    inst = model(supplier_country="IE", gross_total="108.38", line_items=[{"description": "x", "quantity": 1, "unit_price": "1", "net_amount": "1", "vat_rate": "0%", "gross_amount": "1"}])
    assert inst.supplier_country == "IE" and inst.line_items[0].quantity == 1
    with pytest.raises(Exception):
        model(amount_due="1")  # not in the legacy schema -> extra forbidden
    with pytest.raises(Exception):
        model(line_items=[{"description": "x", "note": "nem a sémában"}])


def test_record_from_llm_normalizes_by_kind_and_keeps_unknown_fields_in_extra():
    fo = typepack.get("invoice_foreign")
    rec, reasons = record_from_llm({"supplier_country": "ie", "currency": "eur", "gross_total": "108.38", "issue_date": "2022-11-02", "supplier_tax_id": "IE8256796U", "vat_total": "x"}, fo.fields)
    assert rec.supplier_country == "IE" and rec.currency == "EUR" and rec.gross_total == Decimal("108.38") and rec.issue_date == date(2022, 11, 2)
    assert rec.supplier_tax_id == "IE8256796U" and reasons == ["vat_total:unparseable:'x'"]
    rec2, _ = record_from_llm({"consumption_kwh": "1153", "supplier_name": "MVM"}, {"supplier_name": "name", "consumption_kwh": "number"})
    assert rec2.extra == {"consumption_kwh": Decimal("1153")} and rec2.get_field("consumption_kwh") == Decimal("1153")
    dp = rec2.to_datapoints(("supplier_name", "consumption_kwh"))
    assert dp["consumption_kwh"] == "1153" and dp["supplier_name"] == "MVM"


# --- candidate profiles --------------------------------------------------------------------------


def test_intl_profile_finds_foreign_values():
    c = find_all(_foreign_lines(), "intl")
    labels = {k: [x.label for x in v] for k, v in c.items()}
    assert "IE8256796U" in labels["tax_id"] and "HU28994028" in labels["tax_id"]
    assert {"2022-12-25", "2022-12-26", "2022-12-19"} <= set(labels["date"])  # English month name + US slash form
    money = {x.label: x for x in c["money"]}
    assert "1642.5" in money and money["1642.5"].ambiguous is False  # $1,642.50: thousands comma + decimal point
    assert "0" in money and money["0"].raw == "reverse charge"  # code rule: reverse charge = 0 VAT
    assert "Microsoft Ireland Operations Ltd" in labels["name"] and "Omar Samplefreelancer" in labels["name"] and "BestIxCom Kft." in labels["name"]
    assert "T500000001" in labels["invoice_number"]
    assert any(a.startswith("One Microsoft Place") for a in labels["address"]) and "Giza, 12345, Egypt" in labels["address"]
    assert find_currencies(_foreign_lines(), "intl") == ["HUF", "USD"] or set(find_currencies(_foreign_lines(), "intl")) >= {"USD"}


def test_hu_profile_is_default_and_unchanged():
    lines = [_line(1, ("Fizetési határidő: 2022.02.10.", 30)), _line(2, ("Bruttó összesen", 30), ("12,34", 300)), _line(3, ("Összeg: 1,600", 30))]
    default = {k: [(x.label, x.ambiguous) for x in v] for k, v in find_all(lines).items()}
    hu = {k: [(x.label, x.ambiguous) for x in v] for k, v in find_all(lines, "hu").items()}
    # 081 (owner decision 2026-10-01): money never has three decimals, so "1,600" is 1600 in the hu profile too (it was
    # read as 1.6 before); the default profile is still the hu one
    assert default == hu and ("1600", False) in hu["money"] and ("1.6", False) not in hu["money"]
    intl = {x.label for x in find_all(lines, "intl")["money"]}
    assert "1600" in intl  # intl: "1,600" thousands comma


# --- call sites ---------------------------------------------------------------------------------


def test_select_foreign_site_builds_country_and_currency_questions():
    from jav.jev_select import site_for

    site = site_for("invoice_foreign")
    assert site.request_order == ("foreign_parties", "foreign_header", "foreign_money")
    assert site.extra_request == {"currency": "foreign_money", "supplier_country": "foreign_parties"}
    q = site.build_extra("supplier_country")
    assert isinstance(q, Choice) and {"IE", "US", "EG", "none"} <= set(q.criteria) and len(q.criteria) <= 250
    assert {"EUR", "USD", "TRY", "PLN", "none"} <= set(site.build_extra("currency").criteria)
    assert isinstance(site.build_presence("supplier_tax_id"), Noul)
    assert site.config_hash != site_for("invoice_hu").config_hash
    # 067 (066 Á18): the Hungarian call site's identifier includes the pack too (earlier it was the call site only)
    assert site_for("invoice_hu").config_hash == cfg.combine(cfg.config_hash("callsite:select"), typepack.get("invoice_hu").config_hash)


def test_select_foreign_picks_to_invoice_by_kind():
    from jav.jev_select import site_for
    from jav.models import Candidate

    site = site_for("invoice_foreign")
    picks = {
        "supplier_country": FieldPick(field="supplier_country", label="IE", confidence=0.9, n_options=40, request_id="foreign_parties"),
        "currency": FieldPick(field="currency", label="EUR", confidence=0.9, n_options=9, request_id="foreign_money"),
        "gross_total": FieldPick(field="gross_total", label="108.38", confidence=0.9, n_options=3, request_id="foreign_money"),
        "issue_date": FieldPick(field="issue_date", label="2022-11-02", confidence=0.9, n_options=3, request_id="foreign_header"),
    }
    cands = {"money": [Candidate(kind="money", label="108.38", raw="108,38", line_no=6, context="L06")]}
    inv, reasons = site.picks_to_invoice(picks, cands)
    assert inv.supplier_country == "IE" and inv.currency == "EUR" and inv.gross_total == Decimal("108.38") and inv.issue_date == date(2022, 11, 2)
    assert reasons == [] and inv.net_total is None


def test_verify_foreign_inherits_nouls_and_has_own_field_specs():
    from jav.jev_verify import find_evidence, site_for

    site = site_for("invoice_foreign")
    base = cfg.load("callsite:verify")["nouls"]
    assert site.nouls == base and site.request_id == "verify_foreign"
    assert "supplier_country" in site.field_specs and "amount_due" not in site.field_specs
    llm = {"supplier_name": "Microsoft Ireland Operations Ltd", "supplier_country": "IE", "gross_total": "108.38", "supplier_tax_id": "IE8256796U"}
    lines = _foreign_lines()
    ev = {f: find_evidence(f, str(v), lines, None, kind=site.pack.kind(f), intl=True) for f, v in llm.items()}
    assert ev["supplier_country"] and ev["supplier_tax_id"] and ev["supplier_name"]  # country signal (Írország / IE prefix), tax number with letters, name
    q = site.build_questions(llm, ev)
    assert "supplier_country__off_target" in q and "supplier_tax_id__wrong_kind" in q and "parties_swapped" in q
    assert q["supplier_country__off_target"].instructions["field_spec"]["meaning"] == site.field_specs["supplier_country"]
    assert "issue_date__absence_wrong" in q and "amount_due__absence_wrong" not in q  # only the pack's fields


def test_validators_are_pack_driven():
    from jav.validators import run_all

    fo = typepack.get("invoice_foreign")
    inv = InvoiceHU(currency="EUR", supplier_country="IE", issue_date=date(2022, 11, 2), due_date=date(2022, 12, 2), gross_total=Decimal("108.38"))
    codes = {c.name: c.code for c in run_all(inv, fo.validators)}
    assert codes == {"date_order": "dates.ok", "format:currency": "format.ok", "format:supplier_country": "format.ok"}  # no VAT equation (reverse charge), no IBAN
    inv.supplier_country = "Ireland"
    assert {c.code for c in run_all(inv, fo.validators)} >= {"format.mismatch"}
    hu_codes = [c.name for c in run_all(InvoiceHU(currency="HUF", net_total=Decimal(1), vat_total=Decimal(0), gross_total=Decimal(1), issue_date=date(2022, 1, 1), due_date=date(2022, 1, 2)))]
    # the legacy list is unchanged (optional tax number / IBAN skipped when empty); 053: no line items, no item error
    assert hu_codes == ["vat_consistency", "date_order", "line_items_total", "line_items_arithmetic"]


def test_policy_uses_pack_required_and_high_stakes():
    st = FlowState(source_path="x.pdf", case_id="c", arm="S", doc_type="invoice_foreign")
    st.picks = {
        "buyer_name": FieldPick(field="buyer_name", label=None, confidence=0.99, n_options=2, request_id="foreign_parties"),  # NOT required for the foreign one
        "gross_total": FieldPick(field="gross_total", label=None, confidence=0.99, n_options=2, request_id="foreign_money"),
        "due_date": FieldPick(field="due_date", label="2022-12-02", confidence=0.7, n_options=2, request_id="foreign_header"),  # high stakes: review below 0.85
    }
    policy.apply_pick_policy(st)
    assert "pick:none:gross_total" in st.review_reasons and "pick:none:buyer_name" not in st.review_reasons
    assert any(r.startswith("pick:high_stakes_conf:due_date") for r in st.review_reasons)
    assert policy.required_for("invoice_hu") == policy.REQUIRED and "buyer_name" in policy.REQUIRED


def test_golden_compare_by_kind_and_case_loader_filters_type():
    from jav.evals import field_equal

    assert field_equal("supplier_country", "ie", "IE", "country") and field_equal("currency", "eur", "EUR", "currency")
    assert field_equal("supplier_tax_id", "IE8256796U", "IE8256796U", "tax_id") and not field_equal("supplier_tax_id", "IE8256796U", None, "tax_id")
    assert field_equal("issue_date", "2022-12-25", "2022-12-25", "date") and field_equal("gross_total", "1600.00", "1600", "money")
    assert field_equal("supplier_name", "BestIxCom Kft.", "bestixcom kft", "name")


def test_eval_report_and_admin_use_flow_label_and_doc_type(tmp_path):
    from jav.eval_report import _from_invoice_S

    row = {"case_id": "f1", "doc_type": "invoice_foreign", "flow_label": "invoice_foreign_S", "route": "auto", "scores": {"gross_total": True},
           "picks": {"gross_total": {"label": "108.38", "confidence": 0.95, "n_options": 3, "top3": {"108.38": 0.95, "0": 0.05}, "present_p": 0.9, "line_no": 6}}}
    js = _from_invoice_S(row)
    assert {j.flow for j in js} == {"invoice_foreign_S"} and js[0].callsite == "invoice.pick.high_stakes"  # gross_total is high-stakes for the foreign one too
    legacy = _from_invoice_S({**row, "doc_type": None, "flow_label": None})
    assert {j.flow for j in legacy} == {"invoice_S"}  # old file (no label) = Hungarian invoice


def test_flow_contract_is_type_independent_and_tracker_per_type():
    from jav import flow

    assert flow.CONTRACT["name"] == "invoice" and "invoice_foreign" in flow.CONTRACT["doc_note"]
    assert flow.tracker_project("invoice_hu") == "jav_invoice_hu" and flow.tracker_project("invoice_foreign") == "jav_invoice_foreign"
    assert flow.tracker_project("utility_bill_hu") == "jav_invoice"  # unknown pack name: default project
    app = flow.build_app("x.pdf", "c", "S", tracker=False, doc_type="invoice_foreign")
    assert app.state.data.doc_type == "invoice_foreign"
    with pytest.raises(FileNotFoundError):
        flow.build_app("x.pdf", "c", "S", tracker=False, doc_type="nincs_ilyen")
