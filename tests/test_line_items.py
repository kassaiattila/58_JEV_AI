"""Invoice line items (053 T3): itemised lists in the invoice and utility packs, item-level code checks, and the
pack's recommended path (automatic path). Offline, with synthetic data; no paid calls."""

from decimal import Decimal

import pytest

from jav import corrections, typepack, work
from jav.models import InvoiceHU, LineItem
from jav.runtime import worker
from jav.validators import line_items_arithmetic, line_items_total, run_checks

UTILITY = ("villamos_energia_szamla", "foldgaz_szamla", "viz_szamla", "vizmuvek_szamla", "csatorna_szamla", "mohu_szamla")


def _li(**kw) -> LineItem:
    return LineItem(**{k: Decimal(v) if k in ("quantity", "unit_price", "net_amount", "gross_amount", "vat_amount") and v is not None else v
                       for k, v in kw.items()})


def _inv(items, **totals) -> InvoiceHU:
    return InvoiceHU(currency=totals.pop("currency", "HUF"), line_items=items,
                     **{k: Decimal(v) for k, v in totals.items()})


# --- line-item total -------------------------------------------------------------------------------


def test_total_without_items_is_not_a_failure():
    r = line_items_total(_inv([], net_total="100", gross_total="127"))
    assert r.ok and r.code == "lines.none"


def test_total_matches_net_and_gross_within_tolerance():
    items = [_li(net_amount="100", gross_amount="127"), _li(net_amount="200", gross_amount="254")]
    r = line_items_total(_inv(items, net_total="301", gross_total="381"))  # a 1 Ft rounding difference is allowed
    assert r.ok and r.code == "lines.total_ok"


def test_total_mismatch_names_the_side_and_difference():
    items = [_li(net_amount="100", gross_amount="127"), _li(net_amount="200", gross_amount="254")]
    r = line_items_total(_inv(items, net_total="400", gross_total="381"))
    assert not r.ok and r.code == "lines.total_mismatch"
    assert "net" in r.detail and "-100" in r.detail


def test_total_uses_the_complete_side_when_the_other_is_partial():
    # the pattern of the long water lists: the per-row net is incomplete, the gross complete -> the gross total decides
    items = [_li(net_amount="100", gross_amount="127"), _li(net_amount=None, gross_amount="254")]
    r = line_items_total(_inv(items, net_total="300", gross_total="381"))
    assert r.ok and r.code == "lines.total_ok"


def test_total_incomplete_lists_the_rows_without_amount():
    items = [_li(net_amount="100"), _li(description="Alapdíj"), _li(net_amount="50")]
    r = line_items_total(_inv(items, net_total="300"))
    assert not r.ok and r.code == "lines.incomplete"
    assert "line 2" in r.detail


def test_total_without_header_total_is_not_checkable():
    r = line_items_total(_inv([_li(net_amount="100")]))
    assert r.ok and r.code == "lines.no_total"


def test_total_foreign_currency_tolerance():
    items = [_li(net_amount="10.00"), _li(net_amount="20.01")]
    assert line_items_total(_inv(items, currency="EUR", net_total="30.00")).ok
    assert not line_items_total(_inv(items, currency="EUR", net_total="30.10")).ok


# --- per-row arithmetic ------------------------------------------------------------------------------


def test_arithmetic_ok_and_rounding():
    items = [_li(quantity="312", unit_price="41.27", net_amount="12876", vat_rate="27%", gross_amount="16353")]
    r = line_items_arithmetic(_inv(items))
    assert r.ok and r.code == "lines.arithmetic_ok"


def test_arithmetic_marks_every_bad_row():
    items = [
        _li(quantity="2", unit_price="100", net_amount="200"),
        _li(quantity="3", unit_price="100", net_amount="250"),            # quantity × unit price is wrong
        _li(net_amount="1000", vat_rate="27", gross_amount="1500"),       # net + VAT is wrong
    ]
    r = line_items_arithmetic(_inv(items))
    assert not r.ok and r.code == "lines.arithmetic_mismatch"
    assert "line 2" in r.detail and "line 3" in r.detail and "line 1" not in r.detail


@pytest.mark.parametrize("rate", ["AHK", "TAM", None, "mentes"])
def test_arithmetic_skips_non_numeric_vat_rates(rate):
    r = line_items_arithmetic(_inv([_li(net_amount="1000", vat_rate=rate, gross_amount="1000")]))
    assert r.ok


def test_arithmetic_with_nothing_to_check():
    r = line_items_arithmetic(_inv([_li(description="Előző egyenleg", gross_amount="500")]))
    assert r.ok and r.code == "lines.not_checkable"


def test_run_checks_dispatches_line_checks():
    names = [r.name for r in run_checks(_inv([]), ({"check": "line_items_total"}, {"check": "line_items_arithmetic"}))]
    assert names == ["line_items_total", "line_items_arithmetic"]


# --- packs ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("key", ("invoice_hu", *UTILITY))
def test_packs_declare_line_items_from_their_schema(key):
    pack = typepack.get(key)
    assert pack.kind("line_items") == "list"
    assert "line_items" not in pack.header_fields and "line_items" not in pack.scored_fields  # golden scoring unchanged
    schema_cols = set(pack.schema()["properties"]["line_items"]["items"]["properties"])
    assert set(pack.list_fields["line_items"]) == schema_cols
    assert pack.list_fields["line_items"]["net_amount"] == "money"
    assert pack.list_fields["line_items"]["quantity"] == "number"
    checks = [v["check"] for v in pack.validators]
    assert "line_items_total" in checks
    assert ("line_items_arithmetic" in checks) == (key != "mohu_szamla")  # MOHU: the unit price means something else


def test_utility_packs_prefer_the_gpt_arm_and_invoice_keeps_code_arm():
    for key in UTILITY:
        assert typepack.get(key).default_arm == "G"
        assert worker.arm_for(key, "auto") == "G"
        assert worker.arm_for(key, "S") == "S"  # an explicit request wins
    assert worker.arm_for("invoice_hu", "auto") == "S"
    assert worker.arm_for("statement_cib", "auto") == "G"


def test_recipes_default_to_the_recommended_arm_with_budget():
    for rid in ("invoice-extraction", "document-processing"):
        r = work.recipe(rid)
        assert r["params"]["arm"]["default"] == "auto" and "auto" in r["params"]["arm"]["allowed"]
        assert work.item_budget(r, {"arm": "auto"})["openai"] > 0  # the G path fits too


def test_invoice_extraction_stage_resolves_auto_arm():
    r = work.recipe("invoice-extraction")
    [(flow, params)] = worker._stages(r, {"arm": "auto", "doc_type": "mohu_szamla"})
    assert flow == "invoice" and params["arm"] == "G"


# --- corrected data: marking the bad rows -------------------------------------------------------------


def test_effective_checks_mark_all_bad_rows():
    pack = typepack.get("csatorna_szamla")
    effective = {"currency": "HUF", "net_total": "450", "gross_total": "571", "line_items": [
        {"description": "Alapdíj", "quantity": 1, "unit_price": "100", "net_amount": "100", "vat_rate": "27%", "gross_amount": "127"},
        {"description": "Szennyvíz", "quantity": 5, "unit_price": "60", "net_amount": "350", "vat_rate": "27%", "gross_amount": "444"},
    ]}
    checks = {c["name"]: c for c in corrections.effective_checks(pack, effective)}
    assert checks["line_items_total"]["ok"]
    bad = checks["line_items_arithmetic"]
    assert not bad["ok"] and bad["rows"] == {"line_items": [2]}


def test_list_columns_follow_the_schema_order():
    cols = [c["name"] for c in corrections.list_columns(typepack.get("viz_szamla"), "line_items")]
    assert cols[:3] == ["description", "meter_serial", "period"]


# --- notice only: a failed check opens no to-do (053, owner's decision of 2026-09-28) -------------------


def test_advisory_check_is_marked_and_does_not_open_review():
    from jav import policy
    from jav.models import FlowState

    items = [_li(quantity="1", unit_price="592", net_amount="2572")]
    [adv] = run_checks(_inv(items), ({"check": "line_items_arithmetic", "review": False},))
    assert not adv.ok and adv.advisory
    [blocking] = run_checks(_inv(items), ({"check": "line_items_arithmetic"},))
    assert not blocking.advisory
    state = FlowState(source_path="x.pdf", case_id="c", arm="G", validation=[adv])
    policy.apply_validation_policy(state)
    assert not state.needs_review
    state.validation = [blocking]
    policy.apply_validation_policy(state)
    assert state.needs_review and state.review_reasons == ["validator:lines.arithmetic_mismatch"]


def test_water_statement_arithmetic_is_advisory_only():
    specs = {v["check"]: v for v in typepack.get("viz_szamla").validators}
    assert specs["line_items_arithmetic"].get("review") is False
    assert specs["line_items_total"].get("review", True) is True
    for key in ("vizmuvek_szamla", "csatorna_szamla", "villamos_energia_szamla", "foldgaz_szamla"):
        assert {v["check"]: v for v in typepack.get(key).validators}["line_items_arithmetic"].get("review", True) is True


def test_water_statement_header_vat_check_is_advisory_only():
    # 053, decision of 2026-09-28: the summary cover page has no net or VAT, so net + VAT = gross is only a notice
    specs = {v["check"]: v for v in typepack.get("viz_szamla").validators}
    assert specs["vat_consistency"].get("review") is False
    for key in ("vizmuvek_szamla", "csatorna_szamla", "villamos_energia_szamla", "foldgaz_szamla", "mohu_szamla", "invoice_hu"):
        assert {v["check"]: v for v in typepack.get(key).validators}["vat_consistency"].get("review", True) is True
